import os
import sys
import unittest

sys.path.insert(0, "src")

from aiflags.engine import _bucket, evaluate
from aiflags.quality import QualityMonitor, judge_score
from aiflags.schema import AIFlag, EvaluationContext, Variant
from aiflags.service import FlagService

DB = "test_flags.db"


def make_flag(**overrides) -> AIFlag:
    defaults = dict(
        name="test-flag",
        baseline=Variant(name="base", prompt_version="v1-stable"),
        experimental=Variant(name="exp", prompt_version="v2-good"))
    defaults.update(overrides)
    return AIFlag(**defaults)


class EngineTests(unittest.TestCase):
    def test_consistent_assignment(self):
        flag = make_flag(status="rolling_out", rollout_percentage=50)
        ctx = EvaluationContext(user_id="user-1")
        results = {evaluate(flag, ctx)["variant"] for _ in range(20)}
        self.assertEqual(len(results), 1)

    def test_rollout_percentage_monotonic(self):
        """Users in the experiment at 10 percent stay in it at 50."""
        flag = make_flag(status="rolling_out", rollout_percentage=10)
        in_at_10 = {u for u in (f"u{i}" for i in range(300))
                    if evaluate(flag, EvaluationContext(
                        user_id=u))["variant"] == "experimental"}
        flag.rollout_percentage = 50
        in_at_50 = {u for u in (f"u{i}" for i in range(300))
                    if evaluate(flag, EvaluationContext(
                        user_id=u))["variant"] == "experimental"}
        self.assertTrue(in_at_10.issubset(in_at_50))

    def test_shadow_mode_serves_baseline(self):
        flag = make_flag(status="shadow")
        result = evaluate(flag, EvaluationContext(user_id="u1"))
        self.assertEqual(result["variant"], "baseline")
        self.assertTrue(result["shadow"])

    def test_blocklist_wins(self):
        flag = make_flag(status="on")
        flag.targeting.blocklist = ["vip-user"]
        result = evaluate(flag, EvaluationContext(user_id="vip-user"))
        self.assertEqual(result["variant"], "baseline")


class QualityTests(unittest.TestCase):
    def test_bad_prompt_scores_lower(self):
        good = [judge_score("v2-good", f"output {i}") for i in range(50)]
        bad = [judge_score("v3-bad", f"output {i}") for i in range(50)]
        self.assertGreater(sum(good) / 50, sum(bad) / 50 + 1.0)

    def test_rollback_signal_after_streak(self):
        monitor = QualityMonitor()
        signal = {}
        for i in range(30):
            signal = monitor.record("f", "experimental", 1.5,
                                    p10_floor=3.0, consecutive_bad=25)
        self.assertTrue(signal["rollback"])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        if os.path.exists(DB):
            os.remove(DB)
        self.service = FlagService(DB)

    def test_auto_rollback_during_rollout(self):
        self.service.create_flag(make_flag(
            name="bad-rollout",
            experimental=Variant(name="exp", prompt_version="v3-bad")))
        self.service.start_rollout("bad-rollout")
        for i in range(60):
            self.service.score_async("bad-rollout", "experimental",
                                     f"output {i}")
        flag = self.service.get_flag("bad-rollout")
        self.assertEqual(flag.status, "rolled_back")
        self.assertEqual(flag.rollout_percentage, 0)
        self.assertTrue(self.service.alerts)

    def test_good_rollout_advances(self):
        self.service.create_flag(make_flag(name="good-rollout"))
        self.service.start_rollout("good-rollout")
        for i in range(40):
            self.service.score_async("good-rollout", "experimental",
                                     f"output {i}")
            self.service.score_async("good-rollout", "baseline",
                                     f"base output {i}")
        result = self.service.check_stage("good-rollout")
        self.assertEqual(result["action"], "advance")


if __name__ == "__main__":
    unittest.main()
