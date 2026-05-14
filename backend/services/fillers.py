"""Identify filler words in a transcript built by the Whisper integration."""
import re
from typing import Iterable, List, Tuple

FILLER_TOKENS = {
    "um", "uh", "umm", "uhh", "erm", "er", "ah", "mm", "hmm",
    "like", "so", "you know", "i mean", "actually", "basically",
    "literally", "kinda", "sorta",
}

_clean = re.compile(r"[^a-z']+")


def _normalize(text: str) -> str:
    return _clean.sub("", (text or "").lower())


def find_fillers(transcript: dict) -> List[Tuple[int, int]]:
    """Return [(segment_idx, word_idx), ...] for each detected filler."""
    if not transcript or not transcript.get("segments"):
        return []

    hits: List[Tuple[int, int]] = []
    for si, seg in enumerate(transcript["segments"]):
        words = seg.get("words") or []
        for wi, w in enumerate(words):
            token = _normalize(w.get("text", ""))
            if token and token in FILLER_TOKENS:
                hits.append((si, wi))
    return hits


def words_to_ranges(
    transcript: dict,
    refs: Iterable[Tuple[int, int]],
    pad: float = 0.04,
) -> List[Tuple[float, float]]:
    """Map (segment_idx, word_idx) refs to [start, end] time ranges.

    Adds a tiny pad on each side to swallow the leading/trailing silence
    between words — keeps the splice tight.
    """
    segs = (transcript or {}).get("segments") or []
    ranges: List[Tuple[float, float]] = []
    for si, wi in refs:
        if si < 0 or si >= len(segs):
            continue
        words = segs[si].get("words") or []
        if wi < 0 or wi >= len(words):
            continue
        w = words[wi]
        try:
            start = float(w["start"]) - pad
            end = float(w["end"]) + pad
        except (KeyError, TypeError, ValueError):
            continue
        ranges.append((max(0.0, start), end))
    return ranges
