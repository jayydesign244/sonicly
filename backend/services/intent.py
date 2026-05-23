"""GPT-driven intent parser for the editor chat.

Returns a list of operations (possibly empty) plus a reply. The chat
handler executes the operations in canonical order on a single working
file and creates one new AudioVersion at the end.

Design goals (per the product spec):
  - Recognise INTENT, not exact keywords. "yaar meri awaaz achi nahi lag
    rahi" maps to VOICE_WARMER just like "warmer voice".
  - Handle any language. The model autodetects and replies in the same
    language the user wrote in.
  - Handle vague/emotional prompts. "this is terrible" → FULL_CLEANUP.
    "not happy with my voice" → ONE clarifying question with 2-3
    suggested actions the user can pick from.
  - Handle combined prompts in a single sentence by emitting MULTIPLE
    operations in one response.
  - Pull intensity from natural language ("tiny bit" → low, "much much"
    → high, default → medium).

Returning structured JSON keeps the assistant honest — it cannot claim
to have edited something unless this parser produced concrete ops.
"""
import json
from typing import List, Optional

from openai import AsyncOpenAI

INTENT_MODEL = "gpt-4o-mini"

OPERATION_TYPES = (
    # Noise / cleanup
    "NOISE_REMOVAL",
    "REMOVE_REVERB",
    "REMOVE_HUM",
    "REMOVE_WIND",
    "REMOVE_PLOSIVES",
    "REMOVE_SIBILANCE",
    "REMOVE_MOUTH_SOUNDS",
    "REMOVE_BREATHS",
    "REMOVE_FILLERS",
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
    # Presets / pipelines
    "VOICE_PODCAST",
    "VOICE_RADIO",
    "VOICE_AUTHORITATIVE",
    "FULL_CLEANUP",
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


SYSTEM_PROMPT = """You are the intent layer of an AI audio editor. Convert
the user's request (in ANY language) into a list of structured operations
the backend will execute. Return STRICT JSON in exactly this shape:

{
  "operations": [ <0 or more ops, see below> ],
  "reply": "<one short sentence in the user's own language>",
  "suggestions": null   OR   ["short option 1", "short option 2", "short option 3"]
}

Each op in "operations" is ONE of:
  { "kind": "apply_operation", "type": "<OPERATION_TYPE>", "params": { ... } }
  { "kind": "delete_range",    "start_seconds": <number>, "end_seconds": <number> }

==================================================================
CORE PRINCIPLES
==================================================================
1. UNDERSTAND INTENT — not exact words. A user describing a problem
   ("sounds like a bathroom") maps to the right fix (REMOVE_REVERB)
   even if they never use the keyword.
2. ANY LANGUAGE — detect the user's language and reply in EXACTLY THE
   SAME LANGUAGE AND SCRIPT the user wrote in. Do NOT translate.
   ✅ English in  → English out.        ("My voice has no energy" → English reply)
   ✅ Devanagari Hindi in → Devanagari out.   ("मेरी आवाज़..." → Devanagari)
   ✅ Romanised Hindi / Hinglish in → Romanised out (NOT Devanagari).
   ✅ German in → German out. Spanish in → Spanish out.
   ❌ NEVER reply in Hindi/Devanagari when the user wrote in English.
   ❌ NEVER switch scripts mid-conversation.
   When you describe what you're doing, match register: a casual English
   user gets a casual English reply, not a stiff translation.
3. MULTIPLE OPS IN ONE SENTENCE — split "remove noise AND make voice
   deeper AND cut the ums" into three operations in one response.
4. NEVER show technical terms (FFmpeg, ElevenLabs, dB, LUFS, semitones)
   in the reply. Plain language only.
5. NEVER say "I can't do that" — if it's in the catalogue, the backend
   executes it.
6. EMOTIONAL / VAGUE COMPLAINTS = FULL_CLEANUP. When the user voices
   dissatisfaction without naming a specific issue ("this is terrible",
   "make it better", "i hate how i sound", "fix everything", "make it
   nice"), emit a single FULL_CLEANUP op. Only fall back to a chat
   clarification when the user is genuinely asking a question or the
   request is open-ended in a way FULL_CLEANUP can't resolve.
7. ACT — DO NOT JUST TRANSLATE OR ACKNOWLEDGE. If the user describes a
   PROBLEM with their audio ("I say um too much", "meri awaaz mein um uh
   hai", "ich sage zu viel ähm"), that IS a request to fix it. Emit the
   matching operation. Replying "I say um too much" without operations
   is wrong. Always interpret a stated problem as a request for the fix.

==================================================================
INTENSITY FROM NATURAL LANGUAGE
==================================================================
For ops that take {"intensity": "low"|"medium"|"high"}:
  low      ← "slightly", "a bit", "a little", "subtle", "gently",
              "tiny bit", "थोड़ा" (Hindi), "leicht" (German),
              "un peu" (French), "un poco" (Spanish)
  medium   ← default (no modifier)
  high     ← "a lot", "much", "very", "heavily", "really", "much much",
              "completely", "बहुत" / "बहुत ज्यादा" (Hindi), "sehr / ganz
              viel" (German), "beaucoup" (French), "mucho" (Spanish)

VOICE_DEEPER takes {"semitones": 1..4}:
  1 = slightly,  2 = default,  3 = much,  4 = very/much much.

ADJUST_VOLUME takes {"direction": "up"|"down", "amount_db": positive number}:
  default amount_db is 3. "much louder" → 6. "tiny bit quieter" → 2.

==================================================================
EXAMPLE INTENT MAPPINGS (read for the SHAPE, not as a fixed table)
==================================================================
"yaar meri awaaz achi nahi lag rahi"         → VOICE_WARMER  (medium)
"it sounds like i recorded in a bathroom"    → REMOVE_REVERB
"mere video mein bahut shor hai"             → NOISE_REMOVAL (Hindi: a lot of noise)
"meine bohot zyada um uh bola"               → REMOVE_FILLERS (Hindi/Eng mix)
"der ton klingt dumpf"                       → FIX_MUDDY  (German: sounds dull/muddy)
"my voice has no energy"                     → VOICE_BRIGHTER
"sounds like i'm talking in a box"           → FIX_BOXY
"i hate how i sound"                         → FULL_CLEANUP
"make me sound like a pro"                   → VOICE_PODCAST
"the levels are all over the place"          → COMPRESS_DYNAMICS
"this is terrible"                           → FULL_CLEANUP
"make it better"                             → FULL_CLEANUP
"just a tiny bit warmer"                     → VOICE_WARMER (intensity=low)
"make it much much deeper"                   → VOICE_DEEPER (semitones=4)
"slightly less echo"                         → REMOVE_REVERB (intensity=low)
"remove noise and deeper voice and cut ums"  → 3 ops in one response
"मेरी आवाज़ गहरी करो"                          → VOICE_DEEPER
"sound like a news anchor"                   → VOICE_AUTHORITATIVE
"too many pauses, tighten it"                → TRIM_SILENCE
"too much bass, sounds boomy"                → REDUCE_BASS
"electric hum in background"                 → REMOVE_HUM
"windy outside recording"                    → REMOVE_WIND
"the S's are sharp and harsh"                → REMOVE_SIBILANCE
"i'm popping the mic with my P's"            → REMOVE_PLOSIVES
"mouth clicks between words"                 → REMOVE_MOUTH_SOUNDS
"audible breathing"                          → REMOVE_BREATHS
"hiss only when I'm not talking"             → NOISE_GATE
"clipping spots in the audio"                → LIMIT_PEAKS
"normalize for spotify"                      → NORMALISE_LOUDNESS (target=streaming)
"podcast standard volume"                    → NORMALISE_LOUDNESS (target=podcast)
"remove from 0:16 to 1:22"                   → delete_range  (start=16, end=82)
"first 30 seconds"                           → delete_range  (start=0, end=30)
"yes apply" (after assistant proposed an edit) → re-emit that edit

==================================================================
WHEN TO ASK A QUESTION
==================================================================
If the user's intent is genuinely unclear (e.g. "not happy with my
voice" — could be tone, pitch, noise, levels), emit an EMPTY operations
list AND set "suggestions" to an array of 2-3 SHORT, plain-language
options the user can click. Example:

  user: "not happy with my voice"
  →
  {
    "operations": [],
    "reply": "Tell me what's bothering you — should it sound warmer, more confident, or just clearer?",
    "suggestions": ["Make voice warmer", "Sound more confident", "Just clean it up"]
  }

ONE question, MAX 3 suggestions, no technical terms. If the intent is
genuinely clear, do NOT ask — just emit operations and let the backend
run.

==================================================================
FULL OPERATION CATALOGUE & PARAMS
==================================================================
— NOISE / CLEANUP —
  NOISE_REMOVAL        — background noise of any kind
                          (no params)
  REMOVE_REVERB        — room echo, bathroom/cave sound
                          (no params)
  REMOVE_HUM           — electrical 50/60 Hz buzzing
                          params: {"hz": 50|60}  default 50.  US → 60.
  REMOVE_WIND          — outdoor wind in mic
                          (no params)
  REMOVE_PLOSIVES      — popping P/B sounds
                          (no params)
  REMOVE_SIBILANCE     — harsh S sounds, de-essing
                          params: {"intensity"}
  REMOVE_MOUTH_SOUNDS  — mouth clicks, lip smacks
                          (no params)
  REMOVE_BREATHS       — audible breathing
                          (no params)
  REMOVE_FILLERS       — anything that means "cut the filler/hesitation
                          words". Trigger words/phrases: "um", "uh",
                          "like", "you know", "ums and uhs", "filler
                          words", "hesitations", "verbal tics",
                          "matlab", "yaani", "ähm", "euh", "este".
                          ALSO trigger when the user says they used too
                          many of these — e.g. "bohot zyada um uh bola",
                          "ich sage zu viel ähm", "i say um too much".
                          (no params — backend uses the transcript)

— EQ / TONE —
  VOICE_WARMER         params: {"intensity"}
  VOICE_BRIGHTER       params: {"intensity"}   (EQ presence, not pitch)
  VOICE_DEEPER         params: {"semitones": 1..4}   default 2
  FIX_MUDDY            (no params)
  FIX_TINNY            (no params)
  FIX_BOXY             (no params)
  FIX_NASAL            (no params)
  ADD_PRESENCE         (no params)
  ADD_AIR              (no params)
  REDUCE_AIR           (no params)
  ADD_BASS             params: {"intensity"}
  REDUCE_BASS          (no params)

— PRESETS / PIPELINES —
  VOICE_PODCAST        — clean modern podcast sound
  VOICE_RADIO          — broadcast radio sound
  VOICE_AUTHORITATIVE  — news-anchor / commanding voice
  FULL_CLEANUP         — when the user is unhappy and just wants it
                          fixed (use for vague "make it better",
                          "this is terrible", "fix everything")

— DYNAMICS / VOLUME —
  NORMALISE_LOUDNESS   params: {"target": "podcast"|"youtube"|"streaming"|"broadcast"}
                          default "podcast" (-16 LUFS)
  ADJUST_VOLUME        params: {"direction": "up"|"down", "amount_db": positive number}
  COMPRESS_DYNAMICS    params: {"intensity"}
  NOISE_GATE           params: {"intensity"}
  LIMIT_PEAKS          (no params)
  BALANCE_SPEAKERS     (no params)

— CONTENT —
  TRIM_SILENCE         — remove dead air / shorten long pauses
                          (no params)
  delete_range         — cut a specific time window
                          { "start_seconds": number, "end_seconds": number }
                          Convert MM:SS to seconds. end > start.

==================================================================
FOLLOW-UP TURNS
==================================================================
If the latest user message is a confirmation ("yes", "apply",
"do it", "haan kar do", "ja mach es") and the previous assistant
message proposed a concrete edit, RE-EMIT that edit as operations.
Do NOT apologise."""


class IntentError(RuntimeError):
    pass


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# Few-shot examples — proven more reliable than prose for JSON-mode parsing.
# Pair each "user" with a canonical "assistant" JSON response. The model
# imitates the pattern instead of drifting (e.g. answering in the wrong
# language or describing the problem instead of acting on it).
FEW_SHOT_EXAMPLES: List[dict] = [
    # English problem statement → action, English reply
    {"role": "user", "content": "i say um too much"},
    {"role": "assistant", "content": json.dumps({
        "operations": [{"kind": "apply_operation", "type": "REMOVE_FILLERS", "params": {}}],
        "reply": "Cutting the ums and uhs now.",
        "suggestions": None,
    })},
    # German problem statement → action, German reply
    {"role": "user", "content": "ich sage zu viel ähm"},
    {"role": "assistant", "content": json.dumps({
        "operations": [{"kind": "apply_operation", "type": "REMOVE_FILLERS", "params": {}}],
        "reply": "Ich entferne die Füllwörter.",
        "suggestions": None,
    })},
    # Hinglish problem statement → action, Hinglish (romanised) reply
    {"role": "user", "content": "yaar meri awaaz achi nahi lag rahi"},
    {"role": "assistant", "content": json.dumps({
        "operations": [{"kind": "apply_operation", "type": "VOICE_WARMER", "params": {"intensity": "medium"}}],
        "reply": "Tumhari awaaz thodi warm kar deta hoon.",
        "suggestions": None,
    })},
    # English emotional complaint → FULL_CLEANUP, English reply
    {"role": "user", "content": "i hate how i sound"},
    {"role": "assistant", "content": json.dumps({
        "operations": [{"kind": "apply_operation", "type": "FULL_CLEANUP", "params": {}}],
        "reply": "Running a full cleanup pass on your audio.",
        "suggestions": None,
    })},
    # Combined multi-op, English in → English out
    {"role": "user", "content": "remove noise and make my voice deeper and cut the ums"},
    {"role": "assistant", "content": json.dumps({
        "operations": [
            {"kind": "apply_operation", "type": "NOISE_REMOVAL", "params": {}},
            {"kind": "apply_operation", "type": "VOICE_DEEPER", "params": {"semitones": 2}},
            {"kind": "apply_operation", "type": "REMOVE_FILLERS", "params": {}},
        ],
        "reply": "Removing background noise, deepening your voice, and cutting the ums.",
        "suggestions": None,
    })},
    # Genuinely vague → suggestions
    {"role": "user", "content": "not happy with my voice"},
    {"role": "assistant", "content": json.dumps({
        "operations": [],
        "reply": "Tell me what's bothering you — should it sound warmer, more confident, or clearer?",
        "suggestions": ["Make voice warmer", "Sound more confident", "Just clean it up"],
    })},
]


async def extract_intent(
    client: AsyncOpenAI,
    user_message: str,
    history: Optional[List[dict]] = None,
    model: str = INTENT_MODEL,
) -> dict:
    """Classify a user message into an action plan.

    Returns a dict:
      {
        "operations": [ {"kind": "apply_operation"|"delete_range", ...}, ... ],
        "reply": str,
        "suggestions": list[str] | None,
      }

    `history` carries the conversation BEFORE the current message so
    follow-ups like "yes apply" can be resolved against a previous
    proposal.
    """
    messages: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(FEW_SHOT_EXAMPLES)
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
    """Validate the model output and drop anything malformed. We always
    return a well-shaped dict so callers can rely on the keys."""
    reply = (data.get("reply") or "").strip() or "Okay."

    raw_ops = data.get("operations")
    if not isinstance(raw_ops, list):
        raw_ops = []

    ops: List[dict] = []
    for op in raw_ops:
        if not isinstance(op, dict):
            continue
        kind = op.get("kind")
        if kind == "delete_range":
            start, end = op.get("start_seconds"), op.get("end_seconds")
            if not _is_number(start) or not _is_number(end):
                continue
            if float(end) <= float(start) or float(start) < 0:
                continue
            ops.append({
                "kind": "delete_range",
                "start_seconds": float(start),
                "end_seconds": float(end),
            })
        elif kind == "apply_operation":
            op_type = (op.get("type") or "").upper()
            if op_type not in OPERATION_TYPES:
                continue
            params = op.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            ops.append({
                "kind": "apply_operation",
                "type": op_type,
                "params": params,
            })

    # Suggestions only make sense when we have nothing to execute.
    suggestions = data.get("suggestions")
    if not isinstance(suggestions, list):
        suggestions = None
    else:
        suggestions = [str(s).strip() for s in suggestions if str(s).strip()]
        suggestions = suggestions[:3] if suggestions else None
    if ops:
        suggestions = None

    return {
        "operations": ops,
        "reply": reply,
        "suggestions": suggestions,
    }
