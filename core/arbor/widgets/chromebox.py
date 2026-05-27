"""
Chromebox Widget - controlled ChromeOS host inspection.

Runs inside the single-process Arbor Core and calls the lab repository's
scripts/chromeboxctl helper. Read commands execute directly; restore-ssh is
confirmation-gated through the widget write path.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Query

from .base import ConfirmIntent, Widget


def _now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


class ChromeboxWidget(Widget):
    id = "chromebox"
    name = "Chromebox"
    icon = "monitor-cog"

    commands = {
        "status": {"args": ["status"], "timeout": 10},
        "health": {"args": ["health"], "timeout": 15},
        "snapshot": {"args": ["snapshot"], "timeout": 60},
        "network": {"args": ["network"], "timeout": 15},
        "storage": {"args": ["storage"], "timeout": 15},
        "hardware": {"args": ["hardware"], "timeout": 20},
        "devmode": {"args": ["devmode"], "timeout": 10},
        "vm": {"args": ["vm"], "timeout": 15},
    }
    recovery = {"args": ["restore-ssh"], "timeout": 30}

    def __init__(self) -> None:
        self.chromebox_ctl = os.getenv("CHROMEBOX_CTL", "../../../chromebox-boxy-rev3-lab/scripts/chromeboxctl")
        self.chromebox_host = os.getenv("CHROMEBOX_HOST", "chromebox")
        self.ssh_timeout = os.getenv("CHROMEBOX_SSH_CONNECT_TIMEOUT", "8")
        super().__init__()

    def init_db(self) -> None:
        with self.get_db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS command_runs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    command     TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    returncode  INTEGER,
                    summary     TEXT DEFAULT '',
                    ran_at      TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_time ON command_runs(ran_at DESC);
            """)

    def _ctl_path(self) -> Path:
        return Path(self.chromebox_ctl)

    def _run(self, command: str, recovery: bool = False) -> dict[str, Any]:
        spec = self.recovery if recovery else self.commands[command]
        ctl = self._ctl_path()
        if not ctl.is_file():
            return {
                "status": "error",
                "command": command,
                "error": f"chromeboxctl not found at {ctl}",
                "raw": "",
                "stderr": "",
                "summary": {},
                "ran_at": _now(),
            }

        env = os.environ.copy()
        env["CHROMEBOX_HOST"] = self.chromebox_host
        env["CHROMEBOX_SSH_CONNECT_TIMEOUT"] = self.ssh_timeout

        try:
            completed = subprocess.run(
                ["bash", str(ctl), *spec["args"]],
                capture_output=True,
                text=True,
                timeout=spec["timeout"],
                env=env,
                check=False,
            )
            raw = completed.stdout
            result = {
                "status": "ok" if completed.returncode == 0 else "error",
                "command": command,
                "returncode": completed.returncode,
                "raw": raw,
                "stderr": completed.stderr,
                "summary": self._parse_summary(command, raw),
                "ran_at": _now(),
            }
        except subprocess.TimeoutExpired:
            result = {
                "status": "error",
                "command": command,
                "returncode": None,
                "raw": "",
                "stderr": "",
                "error": f"{command} timed out after {spec['timeout']}s",
                "summary": {},
                "ran_at": _now(),
            }

        self._record_run(result)
        return result

    def _record_run(self, result: dict[str, Any]) -> None:
        with self.get_db() as conn:
            conn.execute(
                "INSERT INTO command_runs (command, status, returncode, summary, ran_at) VALUES (?,?,?,?,?)",
                (
                    result.get("command", ""),
                    result.get("status", "unknown"),
                    result.get("returncode"),
                    str(result.get("summary", {})),
                    result.get("ran_at", _now()),
                ),
            )

    def _parse_summary(self, command: str, raw: str) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        if command in {"health", "snapshot"}:
            match = re.search(r"Summary:\s*PASS=(\d+)\s+WARN=(\d+)\s+FAIL=(\d+)", raw)
            if match:
                summary["pass"] = int(match.group(1))
                summary["warn"] = int(match.group(2))
                summary["fail"] = int(match.group(3))
                summary["state"] = "fail" if summary["fail"] else ("warn" if summary["warn"] else "ok")
        if command in {"vm", "snapshot"}:
            summary["crostini_seen"] = bool(re.search(r"crosvm|termina|penguin|vmtap", raw, re.IGNORECASE))
        if command in {"devmode", "snapshot"}:
            summary["developer_mode_seen"] = bool(re.search(r"devsw_(boot|cur)\s*=\s*1|devmode\s+enabled", raw))
        return summary

    def _recent_runs(self, limit: int = 10) -> list[dict]:
        with self.get_db() as conn:
            rows = conn.execute(
                "SELECT command, status, returncode, summary, ran_at FROM command_runs ORDER BY ran_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def handle_read(self, intent: str, params: dict) -> dict:
        if intent == "recent":
            return {"runs": self._recent_runs(int(params.get("limit", 10)))}
        if intent in self.commands:
            return self._run(intent)
        return self.get_state()

    def prepare_write(self, intent: str, params: dict) -> ConfirmIntent:
        if intent == "restore-ssh":
            return ConfirmIntent(
                widget_id=self.id,
                action="restore-ssh",
                summary="Restore ChromeOS host SSH listener and firewall rule",
                detail={"requires": "confirm=restore-ssh", **params},
            )
        return super().prepare_write(intent, params)

    def execute_write(self, intent: str, params: dict) -> dict:
        if intent != "restore-ssh":
            return {"error": f"unknown intent: {intent}"}
        if params.get("confirm") != "restore-ssh":
            return {"status": "rejected", "error": "confirm must exactly equal restore-ssh"}
        return self._run("restore-ssh", recovery=True)

    def get_state(self) -> dict:
        return {
            "chromebox_ctl": self.chromebox_ctl,
            "chromebox_ctl_exists": self._ctl_path().is_file(),
            "chromebox_host": self.chromebox_host,
            "recent_runs": self._recent_runs(5),
        }

    def _register_routes(self) -> None:
        r = self.router

        @r.get("/state")
        def state():
            return self.get_state()

        @r.get("/runs")
        def runs(limit: int = Query(10)):
            return {"runs": self._recent_runs(limit)}

        @r.get("/{command}")
        def run_read(command: str):
            if command not in self.commands:
                return {"error": f"unknown command: {command}", "allowed": sorted(self.commands)}
            return self._run(command)

        @r.post("/restore-ssh")
        def restore_ssh(body: dict):
            return self.execute_write("restore-ssh", body)
