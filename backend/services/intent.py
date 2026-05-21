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
    # Noise / cleanup
    "REMOVE_HUM",
    "REMOVE_WIND",
    "REMOVE_PLOSIVES",
    "REMOVE_SIBILANCE",
    "REMOVE_MOUTH_SOUNDS",
    "REMOVE_BREATHS",
    # EQ / tone
    "VOICE_WARMER",
    "VOICE_BRIGHTER",
    "VOICE_DEEPER",
    "FIX_MUDDY",
    "FIX_TINNY",
    "FIX_BOXY",
    "FIX_NASAL",
    "ADD_PRESENCE",
    "ADD_AIR",
    "REDUCE_AIR",
    "ADD_BASS",
    "REDUCE_BASS",
    # Presets
    "VOICE_PODCAST",
    "VOICE_RADIO",
    # Dynamics
    "NORMALISE_LOUDNESS",
    "ADJUST_VOLUME",
    "COMPRESS_DYNAMICS",
    "NOISE_GATE",
    "LIMIT_PEAKS",
    "BALANCE_SPEAKERS",
    # Content
    "TRIM_SILENCE",
)

SYSTEM_PROMPT = """You parse user requests for an AI audio editor and return STRICT JSON.

Pick ONE of these actions per message:

  1. "delete_range"      — user names a specific time window to cut.
  2. "apply_operation"   — user asks for any effect/cleanup/EQ/dynamics.
  3. "chat"              — questions, small talk, or ambiguous requests
                           that need clarification.

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

You CAN execute every operation listed below. NEVER say "I can't do that
from chat" or "use the button" — the backend executes structured
operations and the UI updates automatically. Always reply in the same
language the user used.

INTENSITY RULE (whenever an op accepts {intensity}):
  "slightly", "a bit", "little", "subtle"  -> "low"
  no modifier                              -> "medium"  (the default)
  "a lot", "very", "heavily", "really"     -> "high"

==================================================================
delete_range
==================================================================
Use ONLY when the user names a specific clock time or duration:
  "1:22"               -> 82 seconds
  "1 minute 30"        -> 90
  "first 20 seconds"   -> start_seconds=0, end_seconds=20
  "remove 0:16 to 1:22" -> start=16, end=82
end_seconds must be > start_seconds. Set "operation" to null.

==================================================================
apply_operation — full catalogue
==================================================================
Pick the most specific match. When several fit, prefer the named issue
(e.g. "sounds muddy" -> FIX_MUDDY, not generic NOISE_REMOVAL).

— NOISE & CLEANUP —
  REMOVE_HUM           — "electrical hum", "buzzing", "50/60 Hz hum",
                          "power line noise"
    params: {"hz": 50|60}   default 50 (rest of world). US/Canada -> 60.
  REMOVE_WIND          — "wind noise", "recorded outside", "wind in mic",
                          "low rumble from wind"
    params: {} (none)
  REMOVE_PLOSIVES      — "popping P/B sounds", "mic pops", "plosives",
                          "too close to mic"
    params: {} (none)
  REMOVE_SIBILANCE     — "too much S sounds", "harsh S", "sibilance",
                          "sharp S sounds", "de-ess"
    params: {"intensity": "low"|"medium"|"high"}   default medium.
  REMOVE_MOUTH_SOUNDS  — "mouth clicks", "lip smacking", "wet mouth
                          sounds", "swallowing sounds"
    params: {} (none)
  REMOVE_BREATHS       — "remove breathing", "audible breaths between
                          sentences"
    params: {} (none)

— EQ / TONE —
  VOICE_WARMER         — "warmer voice", "add warmth", "voice sounds
                          cold/thin", "fuller/richer sound", "गर्म आवाज़",
                          "गરમ અવાજ" (Hindi/Gujarati: warm voice)
    params: {"intensity": "low"|"medium"|"high"}   default medium.
  VOICE_BRIGHTER       — "brighter voice", "more energy", "voice sounds
                          dull". This is EQ presence boost (NOT pitch).
    params: {"intensity": "low"|"medium"|"high"}   default medium.
  VOICE_DEEPER         — "deeper voice", "lower pitch", "more masculine
                          sound", "आवाज़ गहरी करो"
    params: {"semitones": 1..4}   default 2.  "much deeper" -> 3 or 4.
  FIX_MUDDY            — "sounds muddy", "muffled", "unclear",
                          "talking through pillow"
    params: {} (none)
  FIX_TINNY            — "sounds tinny", "too much treble", "phone-call
                          sound", "metallic"
    params: {} (none)
  FIX_BOXY             — "sounds boxy", "hollow", "talking in a box",
                          "cardboard sound"
    params: {} (none)
  FIX_NASAL            — "sounds nasal", "twangy", "pinched",
                          "talking through nose"
    params: {} (none)
  ADD_PRESENCE         — "more presence", "voice needs to cut through",
                          "more upfront", "more intelligibility"
    params: {} (none)
  ADD_AIR              — "more air", "more openness", "high-end
                          sparkle", "sounds stuffy"
    params: {} (none)
  REDUCE_AIR           — "too much air", "too much high end", "hissy",
                          "reduce treble"
    params: {} (none)
  ADD_BASS             — "more bass", "more low end", "bass boost"
    params: {"intensity": "low"|"medium"|"high"}   default medium.
  REDUCE_BASS          — "too much bass", "too boomy", "reduce bass",
                          "proximity effect"
    params: {} (none)

— PRESETS (multi-step EQ + dynamics chains) —
  VOICE_PODCAST        — "podcast ready", "podcast quality", "clean
                          podcast sound"
    params: {} (none)
  VOICE_RADIO          — "radio quality", "radio host sound", "FM/AM
                          radio voice", "broadcast quality"
    params: {} (none)

— DYNAMICS / VOLUME —
  NORMALISE_LOUDNESS   — "normalize volume", "balance loudness",
                          "podcast volume", "Apple/Spotify standard"
    params: {"target": "podcast"|"youtube"|"streaming"|"broadcast"}
    default "podcast" (-16 LUFS). YouTube/streaming -> -14 LUFS.
    Broadcast (EBU R128) -> -23 LUFS.
  ADJUST_VOLUME        — "make it louder", "quieter", "raise by 3 dB"
    params: {"direction": "up"|"down", "amount_db": <positive number>}
    Defaults direction=up, amount_db=3.
  COMPRESS_DYNAMICS    — "uneven volume", "level jumps around", "compress
                          my voice", "smooth out the volume"
    params: {"intensity": "low"|"medium"|"high"}   default medium.
  NOISE_GATE           — "noise between sentences", "hiss between words",
                          "silence the gaps"
    params: {"intensity": "low"|"medium"|"high"}   default medium.
  LIMIT_PEAKS          — "clipping", "distortion", "limit peaks",
                          "prevent clipping"
    params: {} (none)
  BALANCE_SPEAKERS     — "balance speakers", "even out volume between
                          speakers"
    params: {} (none)

— CONTENT —
  TRIM_SILENCE         — "trim silence", "remove dead air", "shorten
                          long pauses"
    params: {} (none)

==================================================================
chat (fallback)
==================================================================
Use when:
  - The user is asking a question or chatting (not requesting an edit).
  - Edit request is genuinely ambiguous ("clean it up" could be many
    things — ask one short clarifying question).
  - The user confirms a previous proposal ("yes apply", "do it now"):
    look at chat history. If the assistant just proposed a concrete
    edit, re-emit it as a structured action (delete_range or
    apply_operation). Only use chat if you truly cannot tell what to
    apply.

For chat: set start_seconds, end_seconds, and operation to null.
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
