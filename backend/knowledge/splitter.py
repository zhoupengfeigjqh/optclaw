"""Chinese-optimized text splitter (no langchain dependency)."""

import re

from .config import get_chunk_size, get_overlap_size

_SEPARATORS = [
    r"\n\n",
    r"\n",
    r"。(?!\s*[）\)\]】])",
    r"！(?!\s*[）\)\]】])",
    r"？(?!\s*[）\)\]】])",
    r"；(?!\s*[）\)\]】])",
    r"，(?!\s*[）\)\]】])",
    r"\s{2,}",
]


def _split_on_separators(text: str, separators: list[str]) -> list[str]:
    """Recursively split text by separators."""
    if not separators:
        return [text]
    sep = separators[0]
    remaining = separators[1:]
    parts = re.split(f"({sep})", text)
    chunks = []
    for i, part in enumerate(parts):
        if not part:
            continue
        if re.fullmatch(sep, part):
            continue
        chunks.extend(_split_on_separators(part, remaining))
    return chunks if chunks else [text]


def _merge_splits(splits: list[str], chunk_size: int, overlap: int) -> list[str]:
    """Merge small splits into chunks of target size."""
    if not splits:
        return []
    chunks = []
    current = ""
    for split in splits:
        if len(current) + len(split) <= chunk_size:
            current += split
        else:
            if current:
                chunks.append(current)
            # Calculate overlap: keep tail of previous chunk
            if overlap > 0 and chunks:
                current = current[-overlap:] + split if len(current) >= overlap else split
            else:
                current = split
            # If single split exceeds chunk_size, force append
            if len(current) > chunk_size:
                chunks.append(current)
                current = ""
    if current:
        chunks.append(current)

    # If no chunks produced, use splits directly
    if not chunks and splits:
        return [splits[0]] if len(splits[0]) <= chunk_size else [
            splits[0][i:i+chunk_size] for i in range(0, len(splits[0]), chunk_size)
        ]
    return chunks


def split_text(text: str, chunk_size: int | None = None, overlap_size: int | None = None) -> list[str]:
    """Split text into chunks using Chinese-aware separators."""
    cs = chunk_size or get_chunk_size()
    ov = overlap_size or get_overlap_size()
    splits = _split_on_separators(text, _SEPARATORS)
    return _merge_splits(splits, cs, ov)
