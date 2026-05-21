"""ffmpeg-backed audio editing: keep ranges, splice with a short crossfade."""
import asyncio
import math
import os
import re
import shutil
import tempfile
from typing import List, Optional, Sequence, Tuple

CROSSFADE_SECONDS = 0.04  # 40ms — masks splice clicks without bleeding words

# Export format specs. Lossless WAV uses 24-bit PCM at 48kHz so further editing
# in a DAW doesn't lose headroom; MP3/M4A use bitrates high enough that even
# trained ears can't ABX them against the source.
FORMAT_SPECS = {
    "mp3": {
        "codec": "libmp3lame",
        "bitrate": "320k",
        "extra": [],
        "ext": "mp3",
        "content_type": "audio/mpeg",
    },
    "wav": {
        "codec": "pcm_s24le",
        "bitrate": None,
        "extra": ["-ar", "48000"],
        "ext": "wav",
        "content_type": "audio/wav",
    },
    "m4a": {
        "codec": "aac",
        "bitrate": "256k",
        "extra": [],
        "ext": "m4a",
        "content_type": "audio/mp4",
    },
}

_cached_ffmpeg: Optional[str] = None


def _ffmpeg_exe() -> Optional[str]:
    """Locate an ffmpeg binary — prefer system, fall back to imageio-ffmpeg."""
    global _cached_ffmpeg
    if _cached_ffmpeg is not None:
        return _cached_ffmpeg
    sys_path = shutil.which("ffmpeg")
    if sys_path:
        _cached_ffmpeg = sys_path
        return sys_path
    try:
        import imageio_ffmpeg
        _cached_ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        return _cached_ffmpeg
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return _ffmpeg_exe() is not None


def keep_ranges(deletes: Sequence[Tuple[float, float]], duration: float) -> List[Tuple[float, float]]:
    """Invert a list of deletion ranges into the ranges to keep."""
    if not deletes:
        return [(0.0, duration)] if duration > 0 else []

    merged: List[Tuple[float, float]] = []
    for start, end in sorted((max(0.0, s), max(0.0, e)) for s, e in deletes if e > s):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    keeps: List[Tuple[float, float]] = []
    cursor = 0.0
    for start, end in merged:
        if start > cursor:
            keeps.append((cursor, min(start, duration)))
        cursor = max(cursor, end)
    if cursor < duration:
        keeps.append((cursor, duration))
    return [(s, e) for s, e in keeps if e - s > 0.001]


async def _run(cmd: List[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    decoded = stderr.decode(errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exit {proc.returncode}: {decoded[-500:]}"
        )
    return decoded


def _ff() -> str:
    exe = _ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg not found")
    return exe


async def render_with_keeps(
    source_path: str,
    keeps: Sequence[Tuple[float, float]],
    out_path: str,
    crossfade: float = CROSSFADE_SECONDS,
) -> None:
    """Render `source_path` keeping only the given time ranges, joining them
    with a tiny crossfade so splice points aren't audible.
    """
    if not keeps:
        raise ValueError("No ranges to keep — would produce empty audio")

    parts = []
    for i, (start, end) in enumerate(keeps):
        parts.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[s{i}]"
        )

    if len(keeps) == 1:
        filter_complex = parts[0] + f";[s0]anull[out]"
    else:
        chain = parts[:]
        prev = "s0"
        for i in range(1, len(keeps)):
            cur = f"s{i}"
            out = f"m{i}" if i < len(keeps) - 1 else "out"
            chain.append(
                f"[{prev}][{cur}]acrossfade=d={crossfade}:c1=tri:c2=tri[{out}]"
            )
            prev = out
        filter_complex = ";".join(chain)

    cmd = [
        _ff(), "-y", "-i", source_path,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "128k",
        out_path,
    ]
    await _run(cmd)


async def render_with_ops(
    source_path: str,
    ops: Sequence[dict],
    out_path: str,
    crossfade: float = CROSSFADE_SECONDS,
) -> None:
    """Render an arbitrary sequence of keep + insert operations.

    Each op is one of:
      {"type": "keep",   "start": <s>, "end": <s>}    — atrim from source
      {"type": "insert", "path": "<file>"}            — splice this file in

    All inputs are loudness-normalised and joined with the standard
    crossfade so AI-generated inserts blend with surrounding audio.
    """
    if not ops:
        raise ValueError("No operations to render")

    inputs: List[str] = [source_path]
    insert_index: dict = {}  # op.id(path) → ffmpeg input index
    for op in ops:
        if op["type"] == "insert":
            if op["path"] not in insert_index:
                insert_index[op["path"]] = len(inputs)
                inputs.append(op["path"])

    # Per-op filter chain → labelled stream [n#].
    chain = []
    labels: List[str] = []
    for i, op in enumerate(ops):
        label = f"o{i}"
        labels.append(label)
        if op["type"] == "keep":
            chain.append(
                f"[0:a]atrim=start={op['start']:.3f}:end={op['end']:.3f},"
                f"asetpts=PTS-STARTPTS,"
                f"aresample=async=1:first_pts=0,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=44100[{label}]"
            )
        elif op["type"] == "insert":
            idx = insert_index[op["path"]]
            chain.append(
                f"[{idx}:a]asetpts=PTS-STARTPTS,"
                f"aresample=async=1:first_pts=0,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=44100[{label}]"
            )
        else:
            raise ValueError(f"Unknown op type: {op['type']}")

    if len(labels) == 1:
        chain.append(f"[{labels[0]}]anull[out]")
    else:
        prev = labels[0]
        for i in range(1, len(labels)):
            cur = labels[i]
            out_lbl = f"m{i}" if i < len(labels) - 1 else "out"
            chain.append(
                f"[{prev}][{cur}]acrossfade=d={crossfade}:c1=tri:c2=tri[{out_lbl}]"
            )
            prev = out_lbl

    filter_complex = ";".join(chain)

    cmd = [_ff(), "-y"]
    for inp in inputs:
        cmd.extend(["-i", inp])
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "128k",
        out_path,
    ])
    await _run(cmd)


async def transcode(source_path: str, out_path: str, fmt: str) -> None:
    """Re-encode `source_path` to the requested export format. No filter graph,
    no edits — just a straight codec swap so we don't degrade quality."""
    spec = FORMAT_SPECS.get(fmt)
    if not spec:
        raise ValueError(f"Unsupported export format: {fmt}")
    cmd = [_ff(), "-y", "-i", source_path, "-vn", "-c:a", spec["codec"]]
    if spec["bitrate"]:
        cmd.extend(["-b:a", spec["bitrate"]])
    cmd.extend(spec["extra"])
    cmd.append(out_path)
    await _run(cmd)


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")


# Whisper has a 25 MB per-request hard cap. We compress to mono 24 kbps Opus
# (speech-grade, indistinguishable to Whisper from higher bitrates) and only
# chunk when even compression isn't enough.
WHISPER_MAX_BYTES = 25 * 1024 * 1024
WHISPER_SIZE_BUDGET = 24 * 1024 * 1024  # 1 MB safety margin under the hard cap
WHISPER_CHUNK_SECONDS = 600  # 10 min — comfortably under the budget at 24 kbps


async def _compress_for_whisper(src: str, out: str) -> None:
    """Mono 24 kbps Opus. Speech-optimised, accepted natively by Whisper.

    Quality is identical to higher bitrates for transcription (Whisper
    downsamples to 16 kHz mono internally) but the file is 5-10x smaller.
    """
    cmd = [
        _ff(), "-y", "-i", src,
        "-vn", "-ac", "1",
        "-c:a", "libopus", "-b:a", "24k",
        "-application", "voip",
        out,
    ]
    await _run(cmd)


async def prepare_for_whisper(src: str, work_dir: str) -> List[Tuple[str, float]]:
    """Produce Whisper-ready file(s) from a source audio path.

    Returns a list of ``(file_path, start_offset_seconds)``. Callers
    transcribe each piece and add ``start_offset_seconds`` to every word
    and segment timestamp before merging the results.

    Strategy:
      1. Always compress to mono 24 kbps Opus (small, lossless for speech).
      2. If still over the budget, fall back to splitting the source into
         ~10 min chunks at the same bitrate (segment muxer, accurate cuts).
    """
    compressed = os.path.join(work_dir, "for_whisper.ogg")
    await _compress_for_whisper(src, compressed)
    if os.path.getsize(compressed) <= WHISPER_SIZE_BUDGET:
        return [(compressed, 0.0)]

    # Compressed single file still too big → chunk. We re-encode to Opus
    # in the same pass since the segment muxer needs a re-encode anyway
    # to set fresh container metadata per chunk.
    os.remove(compressed)
    chunk_pattern = os.path.join(work_dir, "chunk_%03d.ogg")
    cmd = [
        _ff(), "-y", "-i", src,
        "-vn", "-ac", "1",
        "-c:a", "libopus", "-b:a", "24k",
        "-application", "voip",
        "-f", "segment",
        "-segment_time", str(WHISPER_CHUNK_SECONDS),
        "-reset_timestamps", "1",
        chunk_pattern,
    ]
    await _run(cmd)
    chunks = sorted(
        f for f in os.listdir(work_dir)
        if f.startswith("chunk_") and f.endswith(".ogg")
    )
    if not chunks:
        raise RuntimeError("ffmpeg produced no chunks")
    return [
        (os.path.join(work_dir, name), float(i * WHISPER_CHUNK_SECONDS))
        for i, name in enumerate(chunks)
    ]


async def apply_audio_filter(
    source_path: str, out_path: str, audio_filter: str
) -> None:
    """Apply a single ffmpeg -af filter chain to source_path → out_path (mp3 192k)."""
    cmd = [
        _ff(), "-y", "-i", source_path,
        "-af", audio_filter,
        "-c:a", "libmp3lame", "-b:a", "128k",
        out_path,
    ]
    await _run(cmd)


# Supported one-shot operations. Each maps to an ffmpeg -af filter chain.
# Operations that need params build the chain via build_operation_filter().
# Mirrors the operation catalogue in services/intent.py — keep both in sync.
SUPPORTED_OPERATIONS = {
    # Noise / cleanup
    "REMOVE_HUM",
    "REMOVE_WIND",
    "REMOVE_PLOSIVES",
    "REMOVE_SIBILANCE",
    "REMOVE_MOUTH_SOUNDS",
    "REMOVE_BREATHS",
    # EQ / tone
    "VOICE_WARMER",
    "VOICE_BRIGHTER",  # EQ-based (presence/treble boost), not pitch
    "VOICE_DEEPER",    # pitch shift down
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
}


def _pitch_filter(semitones: float) -> str:
    """Pitch-shift filter chain. Positive = brighter, negative = deeper.

    The asetrate+atempo trick only preserves duration when the asetrate
    base matches the input sample rate, so we first resample to 44.1 kHz
    and then apply the trick on that known baseline.
    """
    factor = 2 ** (semitones / 12.0)
    return (
        f"aresample=44100,"
        f"asetrate=44100*{factor:.6f},"
        f"aresample=44100,"
        f"atempo={1.0 / factor:.6f}"
    )


_INTENSITY_ALIASES = {
    "low": "low", "subtle": "low", "slight": "low", "gentle": "low", "a bit": "low",
    "medium": "medium", "default": "medium", "normal": "medium",
    "high": "high", "heavy": "high", "strong": "high", "aggressive": "high",
}


def _intensity(params: dict, default: str = "medium") -> str:
    raw = (params or {}).get("intensity")
    if raw is None:
        return default
    norm = _INTENSITY_ALIASES.get(str(raw).strip().lower())
    if norm is None:
        raise ValueError(f"intensity must be low|medium|high, got {raw!r}")
    return norm


def _eq(f: float, w: float, g: float, width_type: str = "o") -> str:
    """Compact wrapper for ffmpeg's equalizer filter — voice work uses
    octave bandwidth almost everywhere so that's the default."""
    return f"equalizer=f={f:g}:width_type={width_type}:width={w:g}:g={g:g}"


# -----------------------------------------------------------------------
# Filter chain builders. Each returns a comma-joined ffmpeg -af string.
# -----------------------------------------------------------------------


def _filter_remove_hum(hz: int) -> str:
    """Notch the mains fundamental + its first three harmonics. 50 Hz for
    most of the world, 60 Hz for North America."""
    if hz not in (50, 60):
        raise ValueError("hz must be 50 or 60")
    base = hz
    return ",".join([
        f"equalizer=f={base}:width_type=q:width=1:g=-20",
        f"equalizer=f={base*2}:width_type=q:width=1:g=-15",
        f"equalizer=f={base*3}:width_type=q:width=1:g=-10",
        f"equalizer=f={base*4}:width_type=q:width=1:g=-8",
    ])


def _filter_remove_wind() -> str:
    return ",".join([
        "highpass=f=150:width_type=q:width=0.5",
        _eq(80, 2, -10),
    ])


def _filter_remove_plosives() -> str:
    return ",".join([
        "highpass=f=120:width_type=q:width=0.7",
        _eq(80, 2, -6),
    ])


def _filter_remove_sibilance(intensity: str) -> str:
    if intensity == "low":
        return _eq(8000, 1, -3)
    if intensity == "high":
        return ",".join([
            "equalizer=f=7000:width_type=o:width=1.5:g=-7",
            "equalizer=f=9000:width_type=o:width=1.5:g=-6",
        ])
    # medium
    return ",".join([
        "equalizer=f=7500:width_type=q:width=2:g=-5",
        "equalizer=f=9000:width_type=q:width=2:g=-4",
    ])


def _filter_remove_mouth_sounds() -> str:
    return ",".join([
        "afftdn=nr=15:nf=-30",
        "equalizer=f=3000:width_type=q:width=3:g=-3",
    ])


def _filter_voice_warmer(intensity: str) -> str:
    if intensity == "low":
        return ",".join([_eq(200, 1.5, 2), _eq(120, 2, 1)])
    if intensity == "high":
        return ",".join([
            _eq(200, 1.5, 4), _eq(120, 2, 3), _eq(80, 2, 2),
            _eq(400, 1.5, -2), _eq(3000, 1, -1),
        ])
    # medium
    return ",".join([_eq(200, 1.5, 3), _eq(120, 2, 2), _eq(400, 1.5, -1)])


def _filter_voice_brighter(intensity: str) -> str:
    """EQ-based brightening per the new spec (was pitch shift previously)."""
    if intensity == "low":
        return ",".join([_eq(5000, 1.5, 2), _eq(8000, 2, 1)])
    if intensity == "high":
        return ",".join([
            _eq(5000, 1.5, 4), _eq(8000, 2, 3),
            _eq(12000, 2, 2), _eq(200, 1.5, -2),
        ])
    # medium
    return ",".join([_eq(5000, 1.5, 3), _eq(8000, 2, 2), _eq(200, 1.5, -1)])


def _filter_fix_muddy() -> str:
    return ",".join([_eq(300, 1.5, -4), _eq(500, 1, -3), _eq(4000, 1.5, 3), _eq(200, 1, -2)])


def _filter_fix_tinny() -> str:
    return ",".join([
        _eq(3000, 1.5, -4), _eq(2000, 1, -3), _eq(5000, 1, -2),
        _eq(150, 2, 3), _eq(200, 2, 2),
    ])


def _filter_fix_boxy() -> str:
    return ",".join([
        "equalizer=f=400:width_type=q:width=2:g=-5",
        "equalizer=f=300:width_type=q:width=2:g=-3",
        "equalizer=f=500:width_type=q:width=2:g=-3",
    ])


def _filter_fix_nasal() -> str:
    return ",".join([
        "equalizer=f=1000:width_type=q:width=2:g=-4",
        "equalizer=f=1500:width_type=q:width=2:g=-3",
        _eq(200, 1.5, 2),
    ])


def _filter_add_presence() -> str:
    return ",".join([_eq(2000, 1.5, 3), _eq(3500, 1.5, 2), _eq(5000, 1, 2)])


def _filter_add_air() -> str:
    return ",".join([_eq(10000, 2, 3), _eq(12000, 2, 2), _eq(8000, 2, 1)])


def _filter_reduce_air() -> str:
    return ",".join([_eq(10000, 2, -4), _eq(8000, 1.5, -2)])


def _filter_add_bass(intensity: str) -> str:
    if intensity == "low":
        return _eq(100, 2, 3)
    if intensity == "high":
        return ",".join([
            _eq(100, 2, 5), _eq(80, 2, 4), _eq(60, 2, 3),
            "bass=g=5:f=100:width_type=s:width=0.5",
        ])
    return ",".join([_eq(100, 2, 4), _eq(60, 2, 3)])


def _filter_reduce_bass() -> str:
    return ",".join([
        _eq(100, 2, -4), _eq(150, 2, -3),
        "highpass=f=80:width_type=q:width=0.5",
    ])


def _filter_voice_podcast() -> str:
    return ",".join([
        "highpass=f=80:width_type=q:width=0.7",
        _eq(200, 1.5, 2),
        _eq(400, 1, -2),
        _eq(3000, 1.5, 2),
        _eq(8000, 2, 1),
        "acompressor=threshold=-18dB:ratio=3:attack=10:release=100:makeup=2",
        "loudnorm=I=-16:LRA=11:TP=-1.5",
    ])


def _filter_voice_radio() -> str:
    return ",".join([
        "highpass=f=100:width_type=q:width=0.7",
        _eq(200, 1.5, 3),
        _eq(400, 1, -3),
        _eq(2500, 1.5, 3),
        _eq(8000, 2, 2),
        "acompressor=threshold=-20dB:ratio=4:attack=5:release=80:makeup=3",
        "alimiter=level_in=1:level_out=0.9:limit=0.9:attack=5:release=50",
        "loudnorm=I=-16:LRA=7:TP=-1.5",
    ])


_LOUDNESS_TARGETS = {
    "podcast":   ("loudnorm=I=-16:LRA=11:TP=-1.5", -16),
    "youtube":   ("loudnorm=I=-14:LRA=11:TP=-1.5", -14),
    "streaming": ("loudnorm=I=-14:LRA=11:TP=-1.5", -14),
    "broadcast": ("loudnorm=I=-23:LRA=7:TP=-2.0",  -23),
}


def _filter_compress(intensity: str) -> str:
    if intensity == "low":
        return "acompressor=threshold=-20dB:ratio=2:attack=20:release=200:makeup=1:knee=8"
    if intensity == "high":
        return "acompressor=threshold=-15dB:ratio=5:attack=5:release=80:makeup=4:knee=3"
    return "acompressor=threshold=-18dB:ratio=3:attack=10:release=100:makeup=2:knee=5"


def _filter_gate(intensity: str) -> str:
    if intensity == "low":
        return "agate=threshold=0.01:attack=80:release=500:ratio=2:knee=8"
    if intensity == "high":
        return "agate=threshold=0.04:attack=20:release=200:ratio=8:knee=2"
    return "agate=threshold=0.02:attack=50:release=300:ratio=4:knee=5"


def _filter_limiter() -> str:
    return "alimiter=level_in=1:level_out=0.9:limit=0.9:attack=5:release=50:asc=1"


def build_operation_filter(op_type: str, params: dict) -> Tuple[str, str]:
    """Return (audio_filter, default_label) for a given operation.

    Raises ValueError for unknown ops or invalid params.
    """
    p = params or {}

    # ---- Noise / cleanup --------------------------------------------------
    if op_type == "REMOVE_HUM":
        hz = int(p.get("hz", 50))
        return _filter_remove_hum(hz), f"Removed hum ({hz} Hz)"
    if op_type == "REMOVE_WIND":
        return _filter_remove_wind(), "Removed wind noise"
    if op_type == "REMOVE_PLOSIVES":
        return _filter_remove_plosives(), "Removed plosives"
    if op_type == "REMOVE_SIBILANCE":
        intensity = _intensity(p)
        return _filter_remove_sibilance(intensity), f"De-essed ({intensity})"
    if op_type == "REMOVE_MOUTH_SOUNDS":
        return _filter_remove_mouth_sounds(), "Removed mouth sounds"
    if op_type == "REMOVE_BREATHS":
        return "afftdn=nf=-25", "Removed breaths"

    # ---- EQ / tone --------------------------------------------------------
    if op_type == "VOICE_WARMER":
        intensity = _intensity(p)
        return _filter_voice_warmer(intensity), f"Warmer voice ({intensity})"
    if op_type == "VOICE_BRIGHTER":
        intensity = _intensity(p)
        return _filter_voice_brighter(intensity), f"Brighter voice ({intensity})"
    if op_type == "VOICE_DEEPER":
        semitones = int(p.get("semitones", 2))
        if not 1 <= semitones <= 4:
            raise ValueError("semitones must be 1..4 for VOICE_DEEPER")
        return _pitch_filter(-semitones), f"Voice deeper ({semitones} semitones)"
    if op_type == "FIX_MUDDY":
        return _filter_fix_muddy(), "Fixed muddiness"
    if op_type == "FIX_TINNY":
        return _filter_fix_tinny(), "Fixed tinny sound"
    if op_type == "FIX_BOXY":
        return _filter_fix_boxy(), "Fixed boxy resonance"
    if op_type == "FIX_NASAL":
        return _filter_fix_nasal(), "Reduced nasal tone"
    if op_type == "ADD_PRESENCE":
        return _filter_add_presence(), "Added presence"
    if op_type == "ADD_AIR":
        return _filter_add_air(), "Added air"
    if op_type == "REDUCE_AIR":
        return _filter_reduce_air(), "Reduced high-end air"
    if op_type == "ADD_BASS":
        intensity = _intensity(p)
        return _filter_add_bass(intensity), f"Added bass ({intensity})"
    if op_type == "REDUCE_BASS":
        return _filter_reduce_bass(), "Reduced bass"

    # ---- Presets ----------------------------------------------------------
    if op_type == "VOICE_PODCAST":
        return _filter_voice_podcast(), "Podcast preset"
    if op_type == "VOICE_RADIO":
        return _filter_voice_radio(), "Radio preset"

    # ---- Dynamics ---------------------------------------------------------
    if op_type == "NORMALISE_LOUDNESS":
        # Accept either target string ("podcast") or legacy target_lufs number.
        target = p.get("target")
        if target is None and "target_lufs" in p:
            lufs = float(p["target_lufs"])
            target = {-16: "podcast", -14: "youtube", -23: "broadcast"}.get(lufs)
        target = (target or "podcast").lower()
        spec = _LOUDNESS_TARGETS.get(target)
        if not spec:
            raise ValueError("target must be podcast|youtube|streaming|broadcast")
        chain, lufs = spec
        return chain, f"Normalised loudness ({target}, {lufs} LUFS)"
    if op_type == "ADJUST_VOLUME":
        direction = (p.get("direction") or "up").lower()
        amount_db = float(p.get("amount_db", 3))
        if amount_db <= 0:
            raise ValueError("amount_db must be > 0")
        if direction not in ("up", "down"):
            raise ValueError("direction must be 'up' or 'down'")
        sign = "+" if direction == "up" else "-"
        return f"volume={sign}{amount_db:g}dB", f"Volume {direction} {amount_db:g}dB"
    if op_type == "COMPRESS_DYNAMICS":
        intensity = _intensity(p)
        return _filter_compress(intensity), f"Compressed dynamics ({intensity})"
    if op_type == "NOISE_GATE":
        intensity = _intensity(p)
        return _filter_gate(intensity), f"Noise gated ({intensity})"
    if op_type == "LIMIT_PEAKS":
        return _filter_limiter(), "Limited peaks"
    if op_type == "BALANCE_SPEAKERS":
        return "dynaudnorm=p=0.9:s=5", "Balanced speaker levels"

    # ---- Content ----------------------------------------------------------
    if op_type == "TRIM_SILENCE":
        return (
            "silenceremove=start_periods=1:start_silence=0.5:start_threshold=-50dB:"
            "stop_periods=1:stop_silence=0.5:stop_threshold=-50dB",
            "Trimmed silence",
        )

    raise ValueError(f"Unknown operation: {op_type}")


async def probe_duration(path: str) -> float:
    """Return audio duration in seconds.

    We use ffmpeg with -i and parse its stderr for the Duration line,
    so we don't depend on ffprobe being on PATH (imageio-ffmpeg ships
    only ffmpeg).
    """
    exe = _ffmpeg_exe()
    if not exe:
        return 0.0
    proc = await asyncio.create_subprocess_exec(
        exe, "-hide_banner", "-i", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    m = _DUR_RE.search(stderr.decode(errors="replace"))
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)
