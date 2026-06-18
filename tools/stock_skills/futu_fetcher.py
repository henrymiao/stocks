from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .models import MarketSnapshot

Runner = Callable[[list[str]], str]


def _default_runner(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if lines:
        return lines[-1]
    return completed.stdout


class FutuFetcher:
    def __init__(
        self,
        python_bin: str = "/Users/shuren/.futu-venv/bin/python",
        skill_dir: str = "/Users/shuren/.agents/skills/futuapi",
        runner: Runner = _default_runner,
    ) -> None:
        self.python_bin = python_bin
        self.skill_dir = Path(skill_dir)
        self.runner = runner

    def _script(self, category: str, name: str) -> str:
        path = self.skill_dir / "scripts" / category / name
        if not path.exists():
            raise FileNotFoundError(f"Futu script not found: {path}")
        return str(path)

    def get_snapshot(self, code: str) -> MarketSnapshot:
        command = [self.python_bin, self._script("quote", "get_snapshot.py"), code, "--json"]
        payload = json.loads(self.runner(command))
        rows = payload.get("data", [])
        if not rows:
            raise ValueError(f"No snapshot returned for {code}")
        row = rows[0]
        return MarketSnapshot(
            code=row["code"],
            name=row.get("name", code),
            last_price=float(row["last_price"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            prev_close=float(row["prev_close"]),
            volume=int(row["volume"]),
            turnover=float(row["turnover"]),
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
