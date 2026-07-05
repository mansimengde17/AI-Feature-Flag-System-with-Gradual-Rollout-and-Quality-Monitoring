# AI Feature Flag System with Gradual Rollout and Quality Monitoring

A feature flag platform built for AI features, where working is not a
boolean but a quality gradient. Flags roll out gradually through staged
percentages, quality is scored continuously against the baseline, and the
system rolls a bad variant back automatically before most users see it.

Live demo: https://mansimengde17.github.io/AI-Feature-Flag-System-with-Gradual-Rollout-and-Quality-Monitoring/

## Why this exists

Every engineering team uses feature flags. Almost none have adapted the
pattern for AI features. A traditional flag can tell you the new code path
did not crash. It cannot tell you the new prompt quietly made summaries
worse for 20 percent of users. This system closes that gap: each flag
carries a quality threshold and a rollback trigger, and the rollout only
advances when the evidence says the new variant is no worse than baseline.

## How it works

```
app --> SDK evaluate(flag, user) --> consistent hash bucket --> variant
                |                                               |
                +--> record_outcome (async, never blocks) ------+
                                    |
                      judge scoring -> rolling windows (mean, P10, trend)
                                    |
             stage gate: canary t test vs baseline  -> advance / pause
             rollback monitor: sustained P10 breach -> rollback to 0%
```

- `src/aiflags/schema.py` flag model: stages, quality threshold, rollback
  trigger, targeting rules, baseline and experimental variants
- `src/aiflags/engine.py` consistent hash assignment so raising the
  percentage only adds users and never reshuffles existing ones
- `src/aiflags/quality.py` async judge scoring, rolling windows, P10 and
  trend tracking, sustained breach detection with cooldown
- `src/aiflags/rollout.py` staged schedule, Welch t test canary gate,
  auto advance, pause, and rollback
- `src/aiflags/sdk.py` three line client integration with local caching
  and graceful degradation to baseline when the service is unreachable
- `src/aiflags/service.py` SQLite persistence, change log, alerting
- `src/aiflags/api.py` FastAPI management and evaluation endpoints

## Quick start

```bash
pip install -r requirements.txt
python demo.py                       # both rollout scenarios end to end
python -m unittest discover tests
uvicorn aiflags.api:app --app-dir src --port 8000
```

The demo shows a good prompt variant advancing 1% -> 5% -> 25% -> 50% ->
100%, then a deliberately degraded variant being caught by the quality
monitor and rolled back to 0 with an alert.

## SDK integration

```python
from aiflags.sdk import FlagClient

client = FlagClient(service)
decision = client.evaluate("subject-gen-v2", user_id=user.id)
output = generate(prompt_versions[decision["variant"]], user_input)
client.record_outcome("subject-gen-v2", decision["variant"], output)
```

Shadow mode runs the experimental variant on real traffic without showing
users the result, so catastrophic failures are caught at zero user impact.

## Docker

```bash
docker compose up --build
```
