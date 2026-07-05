"""Staged rollout automation with canary analysis and auto rollback."""

from __future__ import annotations

import math
import statistics
import time

from .quality import QualityMonitor
from .schema import AIFlag


def welch_t_test(a: list[float], b: list[float]) -> dict:
    """Two sample Welch t test with a normal approximation p value.
    Used as the canary gate: the rollout only advances when the
    experimental variant is statistically no worse than baseline."""
    if len(a) < 5 or len(b) < 5:
        return {"p_value": 1.0, "significant": False, "delta": 0.0}
    mean_a, mean_b = statistics.mean(a), statistics.mean(b)
    var_a = statistics.variance(a) if len(a) > 1 else 0.0001
    var_b = statistics.variance(b) if len(b) > 1 else 0.0001
    se = math.sqrt(var_a / len(a) + var_b / len(b)) or 1e-9
    t = (mean_b - mean_a) / se
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return {"p_value": round(p, 4), "significant": p < 0.05,
            "delta": round(mean_b - mean_a, 3), "t": round(t, 3)}


class RolloutController:
    """Advances, pauses, or rolls back flags based on quality evidence."""

    def __init__(self, monitor: QualityMonitor):
        self.monitor = monitor
        self.events: list[dict] = []

    def _log(self, flag: AIFlag, action: str, detail: str) -> dict:
        event = {"flag": flag.name, "action": action, "detail": detail,
                 "percentage": flag.rollout_percentage, "at": time.time()}
        self.events.append(event)
        return event

    def start(self, flag: AIFlag) -> dict:
        flag.status = "rolling_out"
        flag.stage_index = 0
        flag.rollout_percentage = flag.stages[0].percentage
        return self._log(flag, "start",
                         f"rollout started at {flag.rollout_percentage}%")

    def rollback(self, flag: AIFlag, reason: str) -> dict:
        flag.status = "rolled_back"
        flag.rollout_percentage = 0
        self.monitor.start_cooldown(flag.name,
                                    flag.rollback.cooldown_evaluations)
        return self._log(flag, "rollback", reason)

    def check_and_advance(self, flag: AIFlag) -> dict:
        """Called at stage boundaries. Applies the canary gate."""
        if flag.status != "rolling_out":
            return {"action": "none", "detail": f"status {flag.status}"}
        comparison = self.monitor.comparison(flag.name)
        exp = comparison["experimental"]
        stage = flag.stages[flag.stage_index]
        if exp["count"] < stage.min_evaluations:
            return {"action": "wait",
                    "detail": f"{exp['count']}/{stage.min_evaluations}"
                              " evaluations collected"}
        if exp["p10"] < flag.rollback.p10_floor and exp["count"] >= 10:
            return self.rollback(
                flag, f"P10 quality {exp['p10']} below floor"
                      f" {flag.rollback.p10_floor}")
        baseline_scores = list(
            self.monitor._window(flag.name, "baseline").scores)
        exp_scores = list(
            self.monitor._window(flag.name, "experimental").scores)
        test = welch_t_test(baseline_scores, exp_scores)
        if test["significant"] and test["delta"] < 0:
            flag.status = "paused"
            return self._log(
                flag, "pause",
                f"experimental significantly worse (delta {test['delta']},"
                f" p {test['p_value']})")
        if flag.stage_index + 1 < len(flag.stages):
            flag.stage_index += 1
            flag.rollout_percentage = flag.stages[flag.stage_index].percentage
            return self._log(
                flag, "advance",
                f"quality holds (mean {exp['mean']}, p10 {exp['p10']});"
                f" advancing to {flag.rollout_percentage}%")
        flag.status = "on"
        flag.rollout_percentage = 100
        return self._log(flag, "complete", "rollout reached 100%")
