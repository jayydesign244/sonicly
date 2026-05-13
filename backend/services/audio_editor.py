"""ffmpeg-backed audio editing: keep ranges, splice with a short crossfade."""
import asyncio
import os
import re
import shutil
import tempfile
from typing import List, Optional, Sequence, Tuple

CROSSFADE_SECONDS = 0.04  # 40ms — masks splice clicks without bleeding words

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


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")


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
