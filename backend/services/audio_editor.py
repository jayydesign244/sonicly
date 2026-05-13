"""ffmpeg-backed audio editing: keep ranges, splice with a short crossfade."""
import asyncio
import os
import shutil
import tempfile
from typing import List, Sequence, Tuple

CROSSFADE_SECONDS = 0.04  # 40ms — masks splice clicks without bleeding words


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


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


async def _run(cmd: List[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exit {proc.returncode}: {stderr.decode(errors='replace')[-500:]}"
        )


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

    # Build a filtergraph that trims N segments and concatenates them with
    # acrossfade between each consecutive pair.
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
        "ffmpeg", "-y", "-i", source_path,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        out_path,
    ]
    await _run(cmd)


async def probe_duration(path: str) -> float:
    """Return audio duration in seconds via ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return 0.0
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0
