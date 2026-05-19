"""GPT-driven intent parser for the editor chat.

Classifies each user message into one of:
  - delete_range     — cut a specific time window from the audio
  - apply_operation  — run a Phase-A FFmpeg primitive (pitch, loudness, etc.)
  - chat             — everything else (questions, small talk, follow-ups
                       that need clarification)

Returning structured JSON keeps the assistant honest — it cannot claim to
have edited something unless this parser produced a concrete action.
"""
import json
from typing import List, Optional

from openai import AsyncOpenAI

INTENT_MODEL = "gpt-4o-mini"

SUPPORTED_ACTIONS = ("delete_range", "apply_operation", "chat")

# Mirrors audio_editor.SUPPORTED_OPERATIONS — keep in sync if you add ops.
OPERATION_TYPES = (
    "REMOVE_HUM",
    "NORMALISE_LOUDNESS",
    "TRIM_SILENCE",
    "ADJUST_VOLUME",
    "BALANCE_SPEAKERS",
    "REMOVE_BREATHS",
    "VOICE_DEEPER",
    "VOICE_BRIGHTER",
)

SYSTEM_PROMPT = """You parse user requests for an AI audio editor and return STRICT JSON.

Pick ONE of these actions per message:

  1. "delete_range"      — user names a specific time window to cut.
  2. "apply_operation"   — user asks for a one-shot effect like deeper voice,
                           louder, remove hum, normalise loudness, etc.
  3. "chat"              — anything else: questions, small talk, ambiguous
                           edit requests that need clarification.

Return EXACTLY this JSON shape (always all fields, use null when unused):
{
  "action": "delete_range" | "apply_operation" | "chat",
  "start_seconds": <number or null>,
  "end_seconds":   <number or null>,
  "operation": {
    "type":   "<one of the operation types below, or null>",
    "params": { ... }
  } or null,
  "reply": "<one short confident sentence in the user's language>"
}

------------------------------------------------------------------
Rules for action="delete_range"
------------------------------------------------------------------
Use ONLY when the user names a specific clock time or duration window to
remove. Convert times to TOTAL SECONDS as numbers:
  "1:22"  -> 82       "0:16"  -> 16
  "1 minute 30" -> 90
  "first 20 seconds" -> start_seconds=0, end_seconds=20
end_seconds must be > start_seconds.
Set "operation" to null.
Reply briefly confirms what you'll remove. Do NOT claim it's done.

------------------------------------------------------------------
Rules for action="apply_operation"
------------------------------------------------------------------
The "type" field MUST be one of:
  REMOVE_HUM, NORMALISE_LOUDNESS, TRIM_SILENCE, ADJUST_VOLUME,
  BALANCE_SPEAKERS, REMOVE_BREATHS, VOICE_DEEPER, VOICE_BRIGHTER

Mapping cheatsheet (case-insensitive matching on the user's text):

  VOICE_DEEPER  — "deeper voice", "lower my voice", "more bass in my voice"
    params: {"semitones": 1..4}   default 2.  "much deeper" -> 3 or 4.
  VOICE_BRIGHTER — "brighter", "higher pitch", "lighter voice"
    params: {"semitones": 1..3}   default 2.
  REMOVE_HUM   — "remove hum", "kill the buzz", "clean electrical noise"
    params: {} (none)
  NORMALISE_LOUDNESS — "normalize loudness", "level it", "match podcast volume"
    params: {"target_lufs": -16 | -14}   default -16 (podcast). YouTube/video -> -14.
  TRIM_SILENCE — "trim silence", "remove dead air from start and end"
    params: {} (none)
  ADJUST_VOLUME — "make it louder", "quieter", "raise volume 3 dB"
    params: {"direction": "up"|"down", "amount_db": <positive number>}
    Defaults: direction=up, amount_db=3.
  BALANCE_SPEAKERS — "balance speakers", "even out the volume between speakers"
    params: {} (none)
  REMOVE_BREATHS — "remove breaths", "cut breath sounds"
    params: {} (none)

The reply briefly confirms what you'll apply, including any non-default
parameter you chose. Example: "Dropping your voice by 3 semitones."
Never say "I can't do that from chat" — you CAN, this is the API.

------------------------------------------------------------------
Rules for action="chat"
------------------------------------------------------------------
Use when:
  - The user is asking a question or chatting.
  - The user wants an edit but the target is unclear ("remove the boring
    part"). In that case, ask one short clarifying question.
  - The user is following up on a previous unfinished edit ("yes apply",
    "do it now"). Look at the chat history: if the previous assistant
    message proposed an edit, EMIT THAT EDIT AS A STRUCTURED ACTION
    (delete_range or apply_operation) — do NOT use action="chat" to
    apologise. Only fall back to chat if you genuinely can't tell what
    to apply.
Set start_seconds, end_seconds, and operation to null.

Never invent timestamps. Never claim limitations that don't exist."""


class IntentError(RuntimeError):
    pass


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


async def extract_intent(
    client: AsyncOpenAI,
    user_message: str,
    history: Optional[List[dict]] = None,
    model: str = INTENT_MODEL,
) -> dict:
    """Classify a user message, optionally with prior chat turns for context.

    `history` is a list of {"role": "user"|"assistant", "content": str} from
    the conversation BEFORE the current user_message. Used so the parser
    can resolve follow-ups like "yes apply" against what was just offered.
    """
    messages: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Keep history short — last 6 turns is plenty for follow-up disambiguation.
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_message})

    completion = await client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntentError(f"Model returned non-JSON: {raw[:200]}") from exc

    return _normalise(data)


def _normalise(data: dict) -> dict:
    """Validate and clean the model's output. Coerces malformed responses to
    a safe "chat" action so we never execute a half-specified edit."""
    action = data.get("action")
    reply = (data.get("reply") or "").strip() or "Okay."

    chat_fallback = {
        "action": "chat",
        "start_seconds": None,
        "end_seconds": None,
        "operation": None,
        "reply": reply,
    }

    if action not in SUPPORTED_ACTIONS:
        return chat_fallback

    if action == "delete_range":
        start, end = data.get("start_seconds"), data.get("end_seconds")
        if not _is_number(start) or not _is_number(end):
            return {
                **chat_fallback,
                "reply": "I need a clear time range — start and end in seconds or MM:SS, please.",
            }
        if float(end) <= float(start) or float(start) < 0:
            return {
                **chat_fallback,
                "reply": "That range doesn't look right — end should be after start.",
            }
        return {
            "action": "delete_range",
            "start_seconds": float(start),
            "end_seconds": float(end),
            "operation": None,
            "reply": reply,
        }

    if action == "apply_operation":
        op = data.get("operation") or {}
        op_type = (op.get("type") or "").upper()
        if op_type not in OPERATION_TYPES:
            return {
                **chat_fallback,
                "reply": "I'm not sure which effect to apply — could you rephrase?",
            }
        params = op.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        return {
            "action": "apply_operation",
            "start_seconds": None,
            "end_seconds": None,
            "operation": {"type": op_type, "params": params},
            "reply": reply,
        }

    return chat_fallback
