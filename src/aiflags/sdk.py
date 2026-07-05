"""Drop in client SDK.

Integration is three lines:

    from aiflags.sdk import FlagClient
    client = FlagClient(service)
    variant = client.evaluate("summarizer-v2", user_id="u-42")

The client caches flag configurations locally and degrades gracefully to
the baseline variant if the flag service is unreachable.
"""

from __future__ import annotations

import time

from .engine import evaluate
from .schema import EvaluationContext


class FlagClient:
    def __init__(self, service, cache_ttl_seconds: float = 10.0):
        self._service = service
        self._cache: dict[str, tuple[float, object]] = {}
        self._ttl = cache_ttl_seconds

    def _flag(self, name: str):
        cached = self._cache.get(name)
        if cached and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        try:
            flag = self._service.get_flag(name)
            self._cache[name] = (time.monotonic(), flag)
            return flag
        except Exception:
            # Service unreachable: use stale cache, else force baseline.
            if cached:
                return cached[1]
            return None

    def evaluate(self, flag_name: str, user_id: str,
                 segment: str = "public", input_type: str = "default") -> dict:
        flag = self._flag(flag_name)
        if flag is None:
            return {"flag": flag_name, "variant": "baseline",
                    "reason": "flag service unreachable, safe default",
                    "shadow": False, "bucket": -1}
        return evaluate(flag, EvaluationContext(
            user_id=user_id, segment=segment, input_type=input_type))

    def record_outcome(self, flag_name: str, variant: str,
                       output: str) -> None:
        try:
            self._service.score_async(flag_name, variant, output)
        except Exception:
            pass  # quality recording must never break the app
