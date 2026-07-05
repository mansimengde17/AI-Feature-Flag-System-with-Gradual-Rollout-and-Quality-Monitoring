"""Full lifecycle demo for the AI feature flag system.

Scenario: an email subject line generator gets two candidate upgrades.
1. A good prompt variant rolls out through every stage to 100 percent.
2. A bad prompt variant is caught by the quality monitor mid rollout and
   automatically rolled back before most users ever see it.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")

if os.path.exists("demo_flags.db"):
    os.remove("demo_flags.db")

from aiflags.schema import AIFlag, Variant
from aiflags.sdk import FlagClient
from aiflags.service import FlagService


def section(title: str) -> None:
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


def simulate_traffic(service, client, flag_name, users, outputs_per_user=2):
    served = {"baseline": 0, "experimental": 0}
    for user in users:
        decision = client.evaluate(flag_name, user_id=user)
        served[decision["variant"]] += 1
        for i in range(outputs_per_user):
            output = f"subject line for {user} draft {i}"
            service.score_async(flag_name, decision["variant"], output)
    return served


def run_rollout(service, client, flag_name):
    flag = service.get_flag(flag_name)
    users = [f"user-{i}" for i in range(400)]
    step = 0
    while flag.status == "rolling_out" and step < 12:
        step += 1
        served = simulate_traffic(service, client, flag_name, users)
        result = service.check_stage(flag_name)
        stats = service.monitor.comparison(flag_name)["experimental"]
        print(f"  step {step}: {flag.rollout_percentage}% traffic,"
              f" served exp={served['experimental']}"
              f" base={served['baseline']},"
              f" exp mean={stats['mean']} p10={stats['p10']}"
              f" -> {result.get('action', result.get('detail', ''))}:"
              f" {result.get('detail', '')}")
    print(f"  final status: {flag.status} at {flag.rollout_percentage}%")


def main() -> None:
    service = FlagService("demo_flags.db")
    client = FlagClient(service)

    section("Rollout 1: a good variant reaches 100 percent")
    service.create_flag(AIFlag(
        name="subject-gen-v2",
        description="richer subject line prompt with audience hints",
        baseline=Variant(name="baseline", prompt_version="v1-stable"),
        experimental=Variant(name="candidate", prompt_version="v2-good")))
    service.start_rollout("subject-gen-v2")
    run_rollout(service, client, "subject-gen-v2")

    section("Rollout 2: a bad variant is auto rolled back")
    service.create_flag(AIFlag(
        name="subject-gen-v3",
        description="aggressive shortening prompt, quality regressed",
        baseline=Variant(name="baseline", prompt_version="v2-good"),
        experimental=Variant(name="candidate", prompt_version="v3-bad")))
    service.start_rollout("subject-gen-v3")
    run_rollout(service, client, "subject-gen-v3")

    section("Alerts fired")
    for alert in service.alerts:
        print(f"  [{alert['flag']}] {alert['message']}")

    section("Consistent assignment check")
    first = client.evaluate("subject-gen-v2", user_id="user-7")
    second = client.evaluate("subject-gen-v2", user_id="user-7")
    print(f"  user-7 assigned to {first['variant']} both times:"
          f" {first['variant'] == second['variant']}")
    print("\nDemo complete. Start the API with:"
          " uvicorn aiflags.api:app --app-dir src")


if __name__ == "__main__":
    main()
