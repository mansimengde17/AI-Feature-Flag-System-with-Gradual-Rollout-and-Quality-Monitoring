"""Flag service: storage, change log, and the async quality queue."""

from __future__ import annotations

import json
import sqlite3
import time

from .quality import QualityMonitor, judge_score
from .rollout import RolloutController
from .schema import AIFlag


class FlagService:
    def __init__(self, db_path: str = "flags.db"):
        self.db = sqlite3.connect(db_path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS flags (
            name TEXT PRIMARY KEY, config TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS changelog (
            id INTEGER PRIMARY KEY AUTOINCREMENT, flag TEXT, actor TEXT,
            action TEXT, detail TEXT, at REAL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, flag TEXT, variant TEXT,
            score REAL, at REAL)""")
        self.monitor = QualityMonitor()
        self.controller = RolloutController(self.monitor)
        self.alerts: list[dict] = []
        self._flags: dict[str, AIFlag] = {}
        for name, config in self.db.execute("SELECT name, config FROM flags"):
            self._flags[name] = AIFlag(**json.loads(config))

    def _persist(self, flag: AIFlag) -> None:
        self.db.execute("INSERT OR REPLACE INTO flags VALUES (?, ?)",
                        (flag.name, flag.model_dump_json()))
        self.db.commit()

    def _audit(self, flag: str, actor: str, action: str, detail: str) -> None:
        self.db.execute(
            "INSERT INTO changelog (flag, actor, action, detail, at)"
            " VALUES (?, ?, ?, ?, ?)",
            (flag, actor, action, detail, time.time()))
        self.db.commit()

    def create_flag(self, flag: AIFlag, actor: str = "system") -> AIFlag:
        self._flags[flag.name] = flag
        self._persist(flag)
        self._audit(flag.name, actor, "create", flag.description)
        return flag

    def get_flag(self, name: str) -> AIFlag:
        return self._flags[name]

    def list_flags(self) -> list[AIFlag]:
        return list(self._flags.values())

    def start_rollout(self, name: str, actor: str = "system") -> dict:
        event = self.controller.start(self._flags[name])
        self._persist(self._flags[name])
        self._audit(name, actor, "start_rollout", event["detail"])
        return event

    def pause(self, name: str, actor: str = "system") -> dict:
        flag = self._flags[name]
        flag.status = "paused"
        self._persist(flag)
        self._audit(name, actor, "pause", "manually paused")
        return {"flag": name, "status": "paused"}

    def rollback(self, name: str, actor: str = "system",
                 reason: str = "manual rollback") -> dict:
        event = self.controller.rollback(self._flags[name], reason)
        self._persist(self._flags[name])
        self._audit(name, actor, "rollback", reason)
        self._alert(name, f"ROLLBACK: {reason}")
        return event

    def _alert(self, flag: str, message: str) -> None:
        # Slack webhook stand in; the alert payload matches what the
        # webhook sender posts in a live deployment.
        self.alerts.append({"flag": flag, "message": message,
                            "at": time.time()})

    def score_async(self, flag_name: str, variant: str, output: str) -> dict:
        """Queued after every AI gated response. Never blocks the caller."""
        flag = self._flags[flag_name]
        version = (flag.experimental.prompt_version if variant ==
                   "experimental" else flag.baseline.prompt_version)
        score = judge_score(version, output)
        self.db.execute(
            "INSERT INTO scores (flag, variant, score, at) VALUES (?,?,?,?)",
            (flag_name, variant, score, time.time()))
        signal = self.monitor.record(
            flag_name, variant, score, flag.rollback.p10_floor,
            flag.rollback.consecutive_bad)
        if signal["rollback"] and flag.status == "rolling_out":
            self.rollback(flag_name, actor="quality-monitor",
                          reason=f"sustained quality drop, {signal['bad_streak']}"
                                 f" consecutive scores below"
                                 f" {flag.rollback.p10_floor}")
        return {"score": score, **signal}

    def check_stage(self, name: str) -> dict:
        result = self.controller.check_and_advance(self._flags[name])
        if result.get("action") == "rollback":
            self._audit(name, "canary-gate", "rollback", result["detail"])
            self._alert(name, f"ROLLBACK: {result['detail']}")
        self._persist(self._flags[name])
        return result

    def analytics(self, name: str) -> dict:
        flag = self._flags[name]
        return {"flag": flag.model_dump(),
                "quality": self.monitor.comparison(name),
                "events": [e for e in self.controller.events
                           if e["flag"] == name],
                "alerts": [a for a in self.alerts if a["flag"] == name]}
