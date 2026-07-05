"""Flag schema. AI flags carry more than a boolean.

A traditional flag answers "is this on". An AI flag also has to answer
"is the new behavior still good enough", so every flag carries a quality
threshold, a rollback trigger, and a staged rollout plan.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RolloutStage(BaseModel):
    percentage: int = Field(ge=0, le=100)
    min_evaluations: int = 30  # quality samples required before advancing


class RollbackTrigger(BaseModel):
    p10_floor: float = 3.0        # worst decile must stay above this
    consecutive_bad: int = 25     # sustained window before rollback
    cooldown_evaluations: int = 100  # prevent flapping after a rollback


class Variant(BaseModel):
    name: str
    prompt_version: str
    description: str = ""


class TargetingRules(BaseModel):
    segments: list[str] = []          # e.g. ["internal", "beta"]
    allowlist: list[str] = []
    blocklist: list[str] = []
    input_types: list[str] = []       # only enable for these request kinds


class AIFlag(BaseModel):
    name: str
    description: str = ""
    status: str = "off"  # off | shadow | rolling_out | paused | on | rolled_back
    rollout_percentage: int = 0
    quality_threshold: float = 3.5
    baseline: Variant
    experimental: Variant
    stages: list[RolloutStage] = [
        RolloutStage(percentage=1), RolloutStage(percentage=5),
        RolloutStage(percentage=25), RolloutStage(percentage=50),
        RolloutStage(percentage=100)]
    stage_index: int = 0
    rollback: RollbackTrigger = RollbackTrigger()
    targeting: TargetingRules = TargetingRules()


class EvaluationContext(BaseModel):
    user_id: str
    segment: str = "public"
    input_type: str = "default"
