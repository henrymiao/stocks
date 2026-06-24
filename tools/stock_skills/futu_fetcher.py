from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .models import CapitalSnapshot, FundamentalSnapshot, InstrumentState, KLineBar, MarketSnapshot

Runner = Callable[[list[str]], str]

# Inline snippet to pull valuation columns the packaged get_snapshot.py does not expose.
_FUNDAMENTAL_SNIPPET = (
    "import sys,os,json;"
    "sys.path.insert(0, os.path.join({skill!r}, 'scripts'));"
    "from common import create_quote_context, safe_close;"
    "ctx=create_quote_context();"
    "ret,data=ctx.get_market_snapshot([{code!r}]);"
    "safe_close(ctx);"
    "r=data.iloc[0] if ret==0 and len(data) else None;"
    "g=lambda k:(None if r is None or str(r.get(k)) in ('nan','N/A','None') else float(r.get(k)));"
    "print(json.dumps({{'data':[{{'code':{code!r},'pe_ttm':g('pe_ttm_ratio'),'pb':g('pb_ratio'),"
    "'eps':g('earning_per_share'),'dividend_ratio':g('dividend_ratio_ttm'),'market_val':g('total_market_val')}}]}}"
    " if r is not None else {{'data':[]}}))"
)


def _default_runner(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if lines:
        return lines[-1]
    return completed.stdout


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _is_unsupported_sector_error(exc: Exception) -> bool:
    """True when get_owner_plate failed because the code is an ETF.

    Futu's sector (所属板块) interface rejects ETFs with a "does not support ETFs
    type" message. We treat that as "no sector data" rather than a hard failure,
    so analyze falls back to the neutral sector score automatically — the same
    outcome as passing --no-sector. Any other error (e.g. OpenD down) still raises.
    """
    if isinstance(exc, subprocess.CalledProcessError):
        text = f"{exc.stdout or ''}{exc.stderr or ''}"
    else:
        text = str(exc)
    text = text.lower()
    return "etf" in text and "support" in text


class FutuFetcher:
    def __init__(
        self,
        python_bin: str | None = None,
        skill_dir: str | None = None,
        runner: Runner = _default_runner,
    ) -> None:
        self.python_bin = python_bin or os.environ.get("FUTU_PYTHON_BIN", "python3")
        self.skill_dir = Path(
            skill_dir
            or os.environ.get("FUTUAPI_SKILL_DIR", "/Users/allglitter/.codex/skills/futuapi")
        )
        self.runner = runner

    def _script(self, category: str, name: str) -> str:
        path = self.skill_dir / "scripts" / category / name
        if self.runner is _default_runner and not path.exists():
            raise FileNotFoundError(f"Futu script not found: {path}")
        return str(path)

    def _run_json(self, command: list[str]) -> dict:
        payload = json.loads(self.runner(command))
        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(f"Futu script error for {command[2:]}: {payload['error']}")
        return payload

    def get_snapshot(self, code: str) -> MarketSnapshot:
        command = [self.python_bin, self._script("quote", "get_snapshot.py"), code, "--json"]
        payload = self._run_json(command)
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
            timestamp=_now_iso(),
        )

    def get_snapshots(self, codes: list[str]) -> list[MarketSnapshot]:
        """Batch snapshot. Futu accepts up to 400 codes per call; we chunk to stay safe."""
        snapshots: list[MarketSnapshot] = []
        for start in range(0, len(codes), 400):
            chunk = codes[start : start + 400]
            if not chunk:
                continue
            command = [self.python_bin, self._script("quote", "get_snapshot.py"), *chunk, "--json"]
            payload = self._run_json(command)
            for row in payload.get("data", []):
                try:
                    snapshots.append(
                        MarketSnapshot(
                            code=row["code"],
                            name=row.get("name", row["code"]),
                            last_price=float(row["last_price"]),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            prev_close=float(row["prev_close"]),
                            volume=int(row["volume"]),
                            turnover=float(row["turnover"]),
                            timestamp=_now_iso(),
                        )
                    )
                except (KeyError, ValueError, TypeError):
                    continue
        return snapshots

    def get_owner_plates(self, code: str) -> list[dict]:
        command = [self.python_bin, self._script("quote", "get_owner_plate.py"), code, "--json"]
        try:
            payload = self._run_json(command)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            if _is_unsupported_sector_error(exc):
                return []  # ETF: no peer group, skip sector → neutral score downstream
            raise
        return payload.get("data", [])

    def pick_core_plate(self, code: str) -> dict | None:
        """Choose the most representative plate for an instrument.

        Prefer INDUSTRY plates, then CONCEPT, and skip noise plates like
        "High amplitude yesterday" that describe price behaviour rather than a real peer group.
        """
        plates = self.get_owner_plates(code)
        if not plates:
            return None
        noise = ("amplitude", "yesterday", "limit", "新股", "次新")

        def is_noise(name: str) -> bool:
            lowered = name.lower()
            return any(token.lower() in lowered for token in noise)

        for wanted in ("INDUSTRY", "CONCEPT"):
            for plate in plates:
                if plate.get("plate_type") == wanted and not is_noise(str(plate.get("plate_name", ""))):
                    return plate
        for plate in plates:
            if not is_noise(str(plate.get("plate_name", ""))):
                return plate
        return plates[0]

    def get_plate_constituent_changes(self, plate_code: str, limit: int = 30) -> list[float]:
        """Same-day percentage changes for the top constituents of a plate (for sector breadth)."""
        command = [
            self.python_bin,
            self._script("quote", "get_plate_stock.py"),
            plate_code,
            "--limit",
            str(limit),
            "--json",
        ]
        payload = self._run_json(command)
        codes = [row["code"] for row in payload.get("data", []) if row.get("code")]
        if not codes:
            return []
        changes: list[float] = []
        for snapshot in self.get_snapshots(codes):
            if snapshot.prev_close > 0:
                changes.append((snapshot.last_price - snapshot.prev_close) / snapshot.prev_close)
        return changes

    def get_index_snapshots(self, codes: list[str]) -> dict[str, MarketSnapshot]:
        return {snapshot.code: snapshot for snapshot in self.get_snapshots(codes)}

    def get_daily_bars(self, code: str, num: int = 30) -> list[KLineBar]:
        command = [
            self.python_bin,
            self._script("quote", "get_kline.py"),
            code,
            "--ktype",
            "1d",
            "--num",
            str(num),
            "--json",
        ]
        payload = self._run_json(command)
        return self._parse_bars(payload)

    def get_history_bars(self, code: str, start: str, end: str) -> list[KLineBar]:
        """Daily bars over [start, end] (YYYY-MM-DD), used to review past recommendations."""
        command = [
            self.python_bin,
            self._script("quote", "get_kline.py"),
            code,
            "--ktype",
            "1d",
            "--start",
            start,
            "--end",
            end,
            "--json",
        ]
        payload = self._run_json(command)
        return self._parse_bars(payload)

    @staticmethod
    def _parse_bars(payload: dict) -> list[KLineBar]:
        rows = payload.get("data", [])
        bars: list[KLineBar] = []
        for row in rows:
            bars.append(
                KLineBar(
                    time=str(row["time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                    turnover=float(row["turnover"]),
                )
            )
        return bars

    def get_capital(self, code: str) -> CapitalSnapshot | None:
        command = [self.python_bin, self._script("quote", "get_capital_flow.py"), code, "--json"]
        payload = self._run_json(command)
        rows = payload.get("data", [])
        if not rows:
            return None

        def _flow(row: dict, key: str) -> float:
            value = row.get(key, 0)
            if value in (None, "N/A"):
                return 0.0
            return float(value)

        # Futu returns the same-day intraday cumulative series. The last point is the
        # full-day total; comparing the second half against the first half tells us
        # whether money accelerated in or out, which denoises a single reading.
        last = rows[-1]
        intraday_trend: str | None = None
        if len(rows) >= 4:
            mid = len(rows) // 2
            first_half = _flow(rows[mid - 1], "in_flow")
            second_half = _flow(last, "in_flow") - first_half
            if second_half > abs(first_half) * 0.1:
                intraday_trend = "accelerating-in"
            elif second_half < -abs(first_half) * 0.1:
                intraday_trend = "accelerating-out"
            else:
                intraday_trend = "flat"

        return CapitalSnapshot(
            net_inflow=_flow(last, "in_flow"),
            super_inflow=_flow(last, "super_in_flow"),
            big_inflow=_flow(last, "big_in_flow"),
            mid_inflow=_flow(last, "mid_in_flow"),
            small_inflow=_flow(last, "sml_in_flow"),
            timestamp=str(last.get("last_valid_time") or last.get("capital_flow_item_time") or _now_iso()),
            intraday_trend=intraday_trend,
        )

    def get_fundamentals(
        self,
        code: str,
        eps_growth: float | None = None,
        revenue_growth: float | None = None,
        gross_margin: float | None = None,
        net_margin: float | None = None,
        roe: float | None = None,
    ) -> FundamentalSnapshot | None:
        """Valuation + business-quality snapshot.

        Valuation columns (PE-TTM, PB, EPS, dividend yield, market cap) are read live
        from the Futu market snapshot via an inline snippet (the packaged
        get_snapshot.py omits them). Growth/profitability inputs (`eps_growth`,
        `revenue_growth`, `gross_margin`, `net_margin`, `roe`, all YoY/percent) are not
        carried by the market snapshot, so they are supplied by the caller (CLI flags or
        a future financial-statement fetch) and passed straight through. Any left as
        None simply do not contribute to the quality sub-score.
        """
        snippet = _FUNDAMENTAL_SNIPPET.format(skill=str(self.skill_dir), code=code)
        command = [self.python_bin, "-c", snippet]
        payload = self._run_json(command)
        rows = payload.get("data", [])
        if not rows:
            return None
        row = rows[0]
        return FundamentalSnapshot(
            code=row.get("code", code),
            pe_ttm=row.get("pe_ttm"),
            pb=row.get("pb"),
            eps=row.get("eps"),
            dividend_ratio=row.get("dividend_ratio"),
            market_val=row.get("market_val"),
            eps_growth=eps_growth,
            revenue_growth=revenue_growth,
            gross_margin=gross_margin,
            net_margin=net_margin,
            roe=roe,
        )

    def build_state(
        self,
        code: str,
        num_bars: int = 30,
        user_context: dict | None = None,
    ) -> InstrumentState:
        snapshot = self.get_snapshot(code)
        bars = self.get_daily_bars(code, num=num_bars)
        capital = self.get_capital(code)
        return InstrumentState(
            snapshot=snapshot,
            daily_bars=bars,
            intraday_bars=[],
            capital=capital,
            user_context=user_context or {},
        )
