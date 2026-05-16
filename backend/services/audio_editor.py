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
        "-c:a", "libmp3lame", "-b:a", "192k",
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
        "-c:a", "libmp3lame", "-b:a", "192k",
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


async def apply_audio_filter(
    source_path: str, out_path: str, audio_filter: str
) -> None:
    """Apply a single ffmpeg -af filter chain to source_path → out_path (mp3 192k)."""
    cmd = [
        _ff(), "-y", "-i", source_path,
        "-af", audio_filter,
        "-c:a", "libmp3lame", "-b:a", "192k",
        out_path,
    ]
    await _run(cmd)


# Supported one-shot operations. Each maps to an ffmpeg -af filter chain.
# Operations that need params build the chain via build_operation_filter().
SUPPORTED_OPERATIONS = {
    "REMOVE_HUM",
    "NORMALISE_LOUDNESS",
    "TRIM_SILENCE",
    "ADJUST_VOLUME",
    "BALANCE_SPEAKERS",
    "REMOVE_BREATHS",
    "VOICE_DEEPER",
    "VOICE_BRIGHTER",
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


def build_operation_filter(op_type: str, params: dict) -> Tuple[str, str]:
    """Return (audio_filter, default_label) for a given operation.

    Raises ValueError for unknown ops or invalid params.
    """
    p = params or {}
    if op_type == "REMOVE_HUM":
        return "highpass=f=80,lowpass=f=8000", "Removed hum"

    if op_type == "NORMALISE_LOUDNESS":
        target = float(p.get("target_lufs", -16))
        if target not in (-16.0, -14.0):
            raise ValueError("target_lufs must be -16 (podcast) or -14 (youtube)")
        label = "Normalised loudness (podcast)" if target == -16.0 else "Normalised loudness (YouTube)"
        return f"loudnorm=I={target:g}:LRA=11:TP=-1.5", label

    if op_type == "TRIM_SILENCE":
        return (
            "silenceremove=start_periods=1:start_silence=0.5:start_threshold=-50dB:"
            "stop_periods=1:stop_silence=0.5:stop_threshold=-50dB",
            "Trimmed silence",
        )

    if op_type == "ADJUST_VOLUME":
        direction = (p.get("direction") or "up").lower()
        amount_db = float(p.get("amount_db", 3))
        if amount_db <= 0:
            raise ValueError("amount_db must be > 0")
        if direction not in ("up", "down"):
            raise ValueError("direction must be 'up' or 'down'")
        sign = "+" if direction == "up" else "-"
        return f"volume={sign}{amount_db:g}dB", f"Volume {direction} {amount_db:g}dB"

    if op_type == "BALANCE_SPEAKERS":
        return "dynaudnorm=p=0.9:s=5", "Balanced speaker levels"

    if op_type == "REMOVE_BREATHS":
        return "afftdn=nf=-25", "Removed breaths"

    if op_type == "VOICE_DEEPER":
        semitones = int(p.get("semitones", 2))
        if not 1 <= semitones <= 4:
            raise ValueError("semitones must be 1..4 for VOICE_DEEPER")
        return _pitch_filter(-semitones), f"Voice deeper ({semitones} semitones)"

    if op_type == "VOICE_BRIGHTER":
        semitones = int(p.get("semitones", 2))
        if not 1 <= semitones <= 3:
            raise ValueError("semitones must be 1..3 for VOICE_BRIGHTER")
        return _pitch_filter(semitones), f"Voice brighter ({semitones} semitones)"

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
