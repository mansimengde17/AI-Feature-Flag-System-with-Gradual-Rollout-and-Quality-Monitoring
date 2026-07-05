"""Quality monitoring: judge scoring, rolling windows, trend analysis.

Every response served under a flag is scored asynchronously so quality
measurement never adds latency to the user facing path. Scores flow into
rolling windows per variant, and the rollback monitor watches the worst
decile rather than the mean, because AI features usually fail in the tail
first.
"""

from __future__ import annotations

import hashlib
import statistics
from collections import deque
from dataclasses import dataclass, field


def judge_score(prompt_version: str, output: str) -> float:
    """LLM as judge stand in: deterministic 1..5 score.

    Prompt versions tagged 'bad' produce a visibly degraded distribution,
    which is what the demo uses to show automatic rollback. With an API key
    this function is where a real judge model call goes.
    """
    seed = int(hashlib.sha256(output.encode()).hexdigest()[:8], 16)
    base = 3.9 + (seed % 100) / 100  # 3.9 .. 4.9
    if "bad" in prompt_version:
        base -= 2.1
    return round(max(1.0, min(5.0, base)), 2)


@dataclass
class QualityWindow:
    size: int = 100
    scores: deque = field(default_factory=lambda: deque(maxlen=100))

    def add(self, score: float) -> None:
        self.scores.append(score)

    def stats(self) -> dict:
        if not self.scores:
            return {"count": 0, "mean": 0.0, "stdev": 0.0, "p10": 0.0,
                    "trend": "no data"}
        values = list(self.scores)
        ordered = sorted(values)
        p10 = ordered[max(0, int(0.1 * len(ordered)) - 1)] \
            if len(ordered) >= 10 else ordered[0]
        half = len(values) // 2
        trend = "stable"
        if half >= 10:
            older, newer = values[:half], values[half:]
            delta = statistics.mean(newer) - statistics.mean(older)
            trend = "improving" if delta > 0.15 else \
                "degrading" if delta < -0.15 else "stable"
        return {"count": len(values),
                "mean": round(statistics.mean(values), 3),
                "stdev": round(statistics.pstdev(values), 3),
                "p10": round(p10, 2), "trend": trend}


class QualityMonitor:
    """Tracks baseline vs experimental quality and fires rollback signals."""

    def __init__(self):
        self.windows: dict[tuple[str, str], QualityWindow] = {}
        self.bad_streak: dict[str, int] = {}
        self.cooldown: dict[str, int] = {}

    def _window(self, flag: str, variant: str) -> QualityWindow:
        return self.windows.setdefault((flag, variant), QualityWindow())

    def record(self, flag_name: str, variant: str, score: float,
               p10_floor: float, consecutive_bad: int) -> dict:
        self._window(flag_name, variant).add(score)
        if self.cooldown.get(flag_name, 0) > 0:
            self.cooldown[flag_name] -= 1
        if variant != "experimental":
            return {"rollback": False}
        if score < p10_floor:
            self.bad_streak[flag_name] = self.bad_streak.get(flag_name, 0) + 1
        else:
            self.bad_streak[flag_name] = 0
        should_rollback = (self.bad_streak.get(flag_name, 0)
                           >= consecutive_bad
                           and self.cooldown.get(flag_name, 0) == 0)
        return {"rollback": should_rollback,
                "bad_streak": self.bad_streak.get(flag_name, 0)}

    def start_cooldown(self, flag_name: str, evaluations: int) -> None:
        self.cooldown[flag_name] = evaluations
        self.bad_streak[flag_name] = 0

    def comparison(self, flag_name: str) -> dict:
        return {"baseline":
                    self._window(flag_name, "baseline").stats(),
                "experimental":
                    self._window(flag_name, "experimental").stats()}
