"""FastAPI surface for the AI feature flag service."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .engine import evaluate
from .schema import AIFlag, EvaluationContext
from .service import FlagService

app = FastAPI(title="AI Feature Flags", version="1.0.0")
service = FlagService()


class EvaluateRequest(BaseModel):
    user_id: str
    segment: str = "public"
    input_type: str = "default"


class ScoreRequest(BaseModel):
    variant: str
    output: str


@app.post("/v1/flags")
def create_flag(flag: AIFlag):
    return service.create_flag(flag, actor="api").model_dump()


@app.get("/v1/flags")
def list_flags():
    return [f.model_dump() for f in service.list_flags()]


@app.post("/v1/flags/{name}/evaluate")
def evaluate_flag(name: str, request: EvaluateRequest):
    try:
        flag = service.get_flag(name)
    except KeyError:
        raise HTTPException(404, f"unknown flag {name}")
    return evaluate(flag, EvaluationContext(**request.model_dump()))


@app.post("/v1/flags/{name}/score")
def score(name: str, request: ScoreRequest):
    return service.score_async(name, request.variant, request.output)


@app.post("/v1/flags/{name}/rollout")
def start_rollout(name: str):
    return service.start_rollout(name, actor="api")


@app.post("/v1/flags/{name}/check-stage")
def check_stage(name: str):
    return service.check_stage(name)


@app.post("/v1/flags/{name}/pause")
def pause(name: str):
    return service.pause(name, actor="api")


@app.post("/v1/flags/{name}/rollback")
def rollback(name: str):
    return service.rollback(name, actor="api")


@app.get("/v1/flags/{name}/analytics")
def analytics(name: str):
    return service.analytics(name)


@app.get("/v1/alerts")
def alerts():
    return service.alerts[-50:]
