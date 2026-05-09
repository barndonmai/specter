"""
Voyage embeddings — `voyage-law-2` is trained for legal text. Use that.

Built-in protections so we never blow Voyage's free-tier 3 RPM cap:

1. Lazy client init   — env vars are read at call time, not import time.
2. Token-bucket throttle — caller-side rate limit, default 3 RPM. Set
   VOYAGE_RPM=300 once you've added a payment method.
3. Query cache       — repeated queries (very common during demos and
   eval re-runs) hit memory, not the API.
4. Retry on 429      — exponential backoff with jitter, up to 3 tries.

All call sites (load_chroma, /search, /ask, eval) go through this.
"""
from __future__ import annotations
import hashlib
import os
import random
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from typing import Sequence
import voyageai


# ---------- config (env-driven so we never have to edit code at the demo) ----------

def _model() -> str:
    return os.getenv("VOYAGE_MODEL", "voyage-law-2")


def _rpm() -> int:
    """Requests per minute we allow. Free tier = 3. Paid = 300+."""
    try:
        return max(1, int(os.getenv("VOYAGE_RPM", "3")))
    except ValueError:
        return 3


def _cache_size() -> int:
    return max(0, int(os.getenv("VOYAGE_CACHE_SIZE", "4096")))


# ---------- lazy client ----------

@lru_cache(maxsize=1)
def _client() -> voyageai.Client:
    return voyageai.Client()  # picks up VOYAGE_API_KEY from env


# ---------- token-bucket rate limiter ----------

class _RateLimiter:
    """Simple thread-safe minute-window limiter. Blocks until a slot is free."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[float] = []  # timestamps of recent calls

    def acquire(self) -> None:
        rpm = _rpm()
        while True:
            with self._lock:
                now = time.monotonic()
                # Drop entries older than 60s
                self._calls = [t for t in self._calls if now - t < 60.0]
                if len(self._calls) < rpm:
                    self._calls.append(now)
                    return
                # Otherwise: wait until the oldest call ages out
                wait = 60.0 - (now - self._calls[0]) + 0.05
            time.sleep(max(0.0, wait))


_limiter = _RateLimiter()


# ---------- in-memory cache (LRU, keyed by sha256 of text + input_type) ----------

class _LRU:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._d: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, k: str) -> list[float] | None:
        with self._lock:
            v = self._d.get(k)
            if v is not None:
                self._d.move_to_end(k)
            return v

    def put(self, k: str, v: list[float]) -> None:
        if self.capacity <= 0:
            return
        with self._lock:
            self._d[k] = v
            self._d.move_to_end(k)
            while len(self._d) > self.capacity:
                self._d.popitem(last=False)


_cache = _LRU(_cache_size())


def _key(text: str, input_type: str) -> str:
    h = hashlib.sha256(f"{_model()}|{input_type}|{text}".encode("utf-8")).hexdigest()
    return h


# ---------- public API ----------

def embed(texts: Sequence[str], input_type: str = "document") -> list[list[float]]:
    """input_type: 'document' for indexing, 'query' for search-time."""
    if not texts:
        return []

    # 1. Cache lookup. Anything not cached goes in `to_fetch`.
    out: list[list[float] | None] = [None] * len(texts)
    to_fetch_idx: list[int] = []
    to_fetch_text: list[str] = []
    for i, t in enumerate(texts):
        v = _cache.get(_key(t, input_type))
        if v is not None:
            out[i] = v
        else:
            to_fetch_idx.append(i)
            to_fetch_text.append(t)

    # 2. Fetch only the misses, batched into a single Voyage call (Voyage
    #    accepts up to 128 strings per request, well within our budget).
    if to_fetch_text:
        embeddings = _call_voyage(to_fetch_text, input_type)
        for idx, vec, text in zip(to_fetch_idx, embeddings, to_fetch_text):
            _cache.put(_key(text, input_type), vec)
            out[idx] = vec

    # mypy: at this point everything is filled
    return [v for v in out if v is not None]


def _call_voyage(texts: list[str], input_type: str) -> list[list[float]]:
    """Rate-limited + retrying single Voyage embed call."""
    last_err: Exception | None = None
    for attempt in range(3):
        _limiter.acquire()
        try:
            res = _client().embed(texts, model=_model(), input_type=input_type)
            return res.embeddings
        except Exception as e:  # voyageai.error.RateLimitError, transient errors, etc.
            last_err = e
            msg = str(e).lower()
            is_rate = "rate" in msg or "429" in msg
            if not is_rate and attempt == 2:
                raise
            # Exponential backoff with jitter.
            sleep = (2 ** attempt) * 5.0 + random.uniform(0, 2.0)
            time.sleep(sleep)
    assert last_err is not None
    raise last_err


def cache_stats() -> dict[str, int]:
    return {"size": len(_cache._d), "capacity": _cache.capacity, "rpm": _rpm()}
