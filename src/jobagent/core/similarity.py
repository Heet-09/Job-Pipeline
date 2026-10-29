"""Light, offline text similarity (char-trigram cosine). Swappable for a sentence-transformer later."""
import math
import re
from collections import Counter
from typing import Callable

Embedder = Callable[[str], Counter]


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def trigram_embed(s: str) -> Counter:
    t = f"  {normalize_text(s)} "
    return Counter(t[i:i + 3] for i in range(len(t) - 2))


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def similarity(a: str, b: str, embed: Embedder = trigram_embed) -> float:
    return cosine(embed(a), embed(b))
