"""Flag evaluation engine: consistent assignment and targeting rules."""

from __future__ import annotations

import hashlib

from .schema import AIFlag, EvaluationContext


def _bucket(flag_name: str, user_id: str) -> int:
    """Deterministic 0..99 bucket. The same user always lands in the same
    bucket for a given flag, so raising the percentage only adds users and
    never reshuffles existing ones."""
    digest = hashlib.sha256(f"{flag_name}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def evaluate(flag: AIFlag, context: EvaluationContext) -> dict:
    """Return which variant this request should be served and why."""
    def decision(variant: str, reason: str, shadow: bool = False) -> dict:
        return {"flag": flag.name, "variant": variant, "reason": reason,
                "shadow": shadow,
                "bucket": _bucket(flag.name, context.user_id)}

    if context.user_id in flag.targeting.blocklist:
        return decision("baseline", "user on blocklist")
    if context.user_id in flag.targeting.allowlist:
        return decision("experimental", "user on allowlist")

    if flag.status == "off" or flag.status == "rolled_back":
        return decision("baseline", f"flag status {flag.status}")
    if flag.status == "shadow":
        # Serve baseline to the user, but run the experimental variant
        # silently so quality can be measured with zero user impact.
        return decision("baseline", "shadow mode", shadow=True)
    if flag.status == "on":
        return decision("experimental", "fully rolled out")

    if flag.targeting.segments and \
            context.segment not in flag.targeting.segments:
        return decision("baseline",
                        f"segment {context.segment} not targeted")
    if flag.targeting.input_types and \
            context.input_type not in flag.targeting.input_types:
        return decision("baseline",
                        f"input type {context.input_type} not targeted")

    bucket = _bucket(flag.name, context.user_id)
    if bucket < flag.rollout_percentage:
        return decision("experimental",
                        f"bucket {bucket} < {flag.rollout_percentage}%")
    return decision("baseline",
                    f"bucket {bucket} >= {flag.rollout_percentage}%")
