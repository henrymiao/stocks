from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import CapitalSnapshot, ExtendedHoursSnapshot, FinancialsSnapshot, FundamentalSnapshot, InstrumentState, KLineBar, MarketSnapshot

# Income-statement field ids exposed by futuapi's get_financials_statements.py.
_FIELD_TOTAL_REVENUE = 5001
_FIELD_GROSS_PROFIT = 5010
_FIELD_NET_INCOME_PARENT = 5051
_FIELD_BASIC_EPS = 5054

Runner = Callable[[list[str]], str]

# A regular session's INTRADAY capital-flow series should run right up to the close. If the
# last point sits more than this far before the close on a session that has already ended, the
# feed froze mid-session and its cumulative reading is only a partial day — fall back to the
# full-day capital distribution instead. The observed freeze was hours wide, so the margin is
# generous enough never to trip on a feed that merely ends a minute or two early.
_STALE_INTRADAY_GAP = timedelta(minutes=30)


def _skill_dir_candidates(home: Path) -> tuple[Path, ...]:
    return tuple(home / root / "skills" / "futuapi" for root in (".codex", ".agents", ".claude"))


def _default_skill_dir(home: Path | None = None) -> Path:
    candidates = _skill_dir_candidates(home or Path.home())
    for candidate in candidates:
        if (candidate / "scripts" / "quote" / "get_snapshot.py").is_file():
            return candidate
    attempted = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(f"Futu skill installation not found. Tried:\n{attempted}")


def _market_close_hour(code: str) -> int:
    """Regular-session close hour in the instrument's local market timezone.

    US closes at 16:00 ET; A-shares close at 15:00 CST. HK truly closes at 16:00, but 15:00 is
    only used here as a *floor* for the staleness check (a feed running past it is never flagged),
    so the simpler split is safe.
    """
    return 16 if code.startswith("US.") else 15


def _market_tz(code: str) -> ZoneInfo:
    return ZoneInfo("America/New_York") if code.startswith("US.") else ZoneInfo("Asia/Shanghai")

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

# Pull the pre-market / after-hours columns the packaged get_snapshot.py does not expose
# (and which get_kline does not return as bars).
_EXTENDED_HOURS_SNIPPET = (
    "import sys,os,json;"
    "sys.path.insert(0, os.path.join({skill!r}, 'scripts'));"
    "from common import create_quote_context, safe_close;"
    "ctx=create_quote_context();"
    "ret,data=ctx.get_market_snapshot([{code!r}]);"
    "safe_close(ctx);"
    "r=data.iloc[0] if ret==0 and len(data) else None;"
    "g=lambda k:(None if r is None or str(r.get(k)) in ('nan','N/A','None') else float(r.get(k)));"
    "print(json.dumps({{'data':[{{'code':{code!r},'prev_close':g('prev_close_price'),"
    "'pre_price':g('pre_price'),'pre_change_rate':g('pre_change_rate'),'pre_volume':g('pre_volume'),"
    "'after_price':g('after_price'),'after_change_rate':g('after_change_rate'),'after_volume':g('after_volume')}}]}}"
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
    # Futu localizes this message, so accept the Chinese wording too: matching only
    # the English "support" turned every ETF analysis into a hard crash once OpenD
    # started answering in Chinese.
    return "etf" in text and ("support" in text or "不支持" in text)


class FutuFetcher:
    def __init__(
        self,
        python_bin: str | None = None,
        skill_dir: str | None = None,
        runner: Runner = _default_runner,
    ) -> None:
        self.python_bin = python_bin or os.environ.get("FUTU_PYTHON_BIN") or sys.executable
        self.skill_dir = Path(
            skill_dir
            or os.environ.get("FUTUAPI_SKILL_DIR")
            or _default_skill_dir()
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
        captured_at = _now_iso()
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
            timestamp=str(row.get("update_time") or captured_at),
            captured_at=captured_at,
        )

    def get_snapshots(self, codes: list[str]) -> list[MarketSnapshot]:
        """Batch snapshot. Futu accepts up to 400 codes per call; we chunk to stay safe.

        Tolerant of partial failures: Futu's get_market_snapshot rejects the *whole*
        batch if any single code lacks a market-data entitlement (e.g. CC.* crypto
        without a crypto quote card) or is unknown. When a batched call fails we retry
        the chunk code-by-code and keep whatever succeeds, so one bad code no longer
        sinks the entire backdrop/sector fetch — the dropped components just fall back
        to their neutral score downstream. Callers needing a hard guarantee for a
        single instrument use get_snapshot() (singular), which still raises.
        """
        snapshots: list[MarketSnapshot] = []
        for start in range(0, len(codes), 400):
            chunk = codes[start : start + 400]
            if chunk:
                snapshots.extend(self._snapshots_for_chunk(chunk))
        return snapshots

    def _snapshots_for_chunk(self, chunk: list[str]) -> list[MarketSnapshot]:
        command = [self.python_bin, self._script("quote", "get_snapshot.py"), *chunk, "--json"]
        try:
            payload = self._run_json(command)
        except (RuntimeError, subprocess.CalledProcessError):
            # The batch was rejected because at least one code is unentitled/unknown.
            # A single-code chunk that fails is simply dropped; a multi-code chunk is
            # retried per code so the good ones still come back.
            if len(chunk) == 1:
                return []
            salvaged: list[MarketSnapshot] = []
            for code in chunk:
                salvaged.extend(self._snapshots_for_chunk([code]))
            return salvaged
        parsed = (self._row_to_snapshot(row) for row in payload.get("data", []))
        return [snap for snap in parsed if snap is not None]

    @staticmethod
    def _row_to_snapshot(row: dict) -> MarketSnapshot | None:
        try:
            captured_at = _now_iso()
            return MarketSnapshot(
                code=row["code"],
                name=row.get("name", row["code"]),
                last_price=float(row["last_price"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                prev_close=float(row["prev_close"]),
                volume=int(row["volume"]),
                turnover=float(row["turnover"]),
                timestamp=str(row.get("update_time") or captured_at),
                captured_at=captured_at,
            )
        except (KeyError, ValueError, TypeError):
            return None

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

    def get_intraday_bars(
        self,
        code: str,
        *,
        num: int = 30,
        ktype: str = "5m",
    ) -> list[KLineBar]:
        """Fetch quote-only intraday bars for discovery confirmation.

        OpenD may include the currently forming final bar.  The discovery engine
        filters it against the evaluation timestamp before any state transition.
        """

        if ktype not in {"1m", "3m", "5m", "10m", "15m", "30m", "60m"}:
            raise ValueError(f"Unsupported intraday ktype: {ktype!r}")
        if num <= 0:
            raise ValueError("num must be positive")
        command = [
            self.python_bin,
            self._script("quote", "get_kline.py"),
            code,
            "--ktype",
            ktype,
            "--num",
            str(num),
            "--json",
        ]
        payload = self._run_json(command)
        return self._parse_bars(payload)

    def get_trading_days(self, market: str, *, start: str, end: str) -> list[str]:
        """Return OpenD's exchange-session dates for CN, HK, or US."""

        normalized = market.upper()
        if normalized not in {"CN", "HK", "US"}:
            raise ValueError(f"Unsupported trading-calendar market: {market!r}")
        command = [
            self.python_bin,
            self._script("quote", "get_trading_days.py"),
            normalized,
            "--start",
            start,
            "--end",
            end,
            "--json",
        ]
        payload = self._run_json(command)
        sessions: set[str] = set()
        for row in payload.get("data", []):
            if isinstance(row, str):
                value = row
            elif isinstance(row, dict):
                value = next(
                    (
                        str(row[key])
                        for key in ("time", "trade_date", "date")
                        if row.get(key)
                    ),
                    "",
                )
            else:
                continue
            try:
                sessions.add(datetime.fromisoformat(value).date().isoformat())
            except ValueError:
                continue
        return sorted(sessions)

    def get_market_states(self, codes: list[str]) -> dict[str, str]:
        """Return OpenD regular/closed state names without touching trade APIs."""

        if not codes:
            return {}
        command = [
            self.python_bin,
            self._script("quote", "get_market_state.py"),
            *codes,
            "--json",
        ]
        payload = self._run_json(command)
        return {
            str(row["code"]): str(row["market_state"]).upper()
            for row in payload.get("data", [])
            if row.get("code") and row.get("market_state")
        }

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
        """By-size net capital flow, robust to a frozen intraday feed.

        The INTRADAY capital-flow stream is normally the right source: its last point is the
        full-day cumulative total and the series lets us read intraday momentum. But that
        stream can freeze mid-session and keep returning a partial-day reading long after the
        close (e.g. stuck at 11:09 when queried at 23:07), which flips the by-size net flow to
        the wrong sign. When the feed looks stale — or is missing — we fall back to the
        full-day capital distribution, which is authoritative for the by-size totals.
        """
        command = [self.python_bin, self._script("quote", "get_capital_flow.py"), code, "--json"]
        payload = self._run_json(command)
        rows = payload.get("data", [])

        if rows and not self._intraday_feed_is_stale(code, rows):
            return self._capital_from_intraday(rows)

        # No trustworthy intraday reading (empty, or frozen mid-session on a finished day):
        # the full-day distribution gives the correct by-size net flow.
        distribution = self.get_capital_distribution(code)
        if distribution is not None:
            return distribution

        # Distribution unavailable too (e.g. instrument type unsupported) — use whatever
        # intraday we have rather than dropping the factor entirely; otherwise None.
        if rows:
            return self._capital_from_intraday(rows)
        return None

    @staticmethod
    def _capital_from_intraday(rows: list[dict]) -> CapitalSnapshot:
        """Build a snapshot from the INTRADAY cumulative flow series.

        The last point is the full-day total; comparing the second half of the series against
        the first half tells us whether money accelerated in or out, which denoises the read.
        """
        def _flow(row: dict, key: str) -> float:
            value = row.get(key, 0)
            if value in (None, "N/A"):
                return 0.0
            return float(value)

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
            source="intraday",
        )

    @staticmethod
    def _intraday_feed_is_stale(code: str, rows: list[dict], now: datetime | None = None) -> bool:
        """True when the intraday capital-flow feed froze before the close of a finished session.

        Heuristic: take the last point's timestamp; if the session for that day has already
        ended (now is at/after the market close) yet the last point sits well before that close,
        the feed stopped updating mid-session and its cumulative total is only a partial day.
        Timestamps that cannot be parsed (or a feed queried while the session is still live) are
        treated as not stale, so the normal intraday path is preserved.
        """
        last = rows[-1]
        # Use the bar's market time (capital_flow_item_time). last_valid_time is only the fetch
        # time — it is identical on every row and equals "now", so it can never reveal a feed
        # that stopped early.
        raw = last.get("capital_flow_item_time") or last.get("last_valid_time")
        if not raw:
            return False  # no timestamp to judge against → trust the feed
        try:
            last_dt = datetime.strptime(str(raw)[:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return False  # unparseable timestamp → trust the feed
        tz = _market_tz(code)
        last_dt = last_dt.replace(tzinfo=tz)
        close_dt = last_dt.replace(hour=_market_close_hour(code), minute=0, second=0, microsecond=0)
        now_market = now.astimezone(tz) if now is not None else datetime.now(tz)
        session_finished = now_market >= close_dt  # we're past that day's close → the full day should be in
        froze_early = (close_dt - last_dt) > _STALE_INTRADAY_GAP
        return session_finished and froze_early

    def get_capital_distribution(self, code: str) -> CapitalSnapshot | None:
        """Full-day capital distribution → by-size net flow (net = inflow − outflow per size).

        Authoritative for the full session regardless of the intraday feed's health, but it
        carries no time series, so intraday_trend is None. Tolerant of errors (e.g. the
        instrument type is unsupported by the interface): returns None rather than raising, so
        the capital factor simply scores neutral downstream.
        """
        command = [self.python_bin, self._script("quote", "get_capital_distribution.py"), code, "--json"]
        try:
            payload = self._run_json(command)
        except (RuntimeError, subprocess.CalledProcessError):
            return None

        def _val(key: str) -> float | None:
            value = payload.get(key)
            if value in (None, "N/A", ""):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        nets: dict[str, float] = {}
        for size in ("super", "big", "mid", "small"):
            inflow = _val(f"capital_in_{size}")
            outflow = _val(f"capital_out_{size}")
            if inflow is None and outflow is None:
                continue
            nets[size] = (inflow or 0.0) - (outflow or 0.0)
        if not nets:
            return None  # empty payload (e.g. {"data": {}}) → no usable distribution

        super_net = nets.get("super", 0.0)
        big_net = nets.get("big", 0.0)
        mid_net = nets.get("mid", 0.0)
        small_net = nets.get("small", 0.0)
        return CapitalSnapshot(
            net_inflow=super_net + big_net + mid_net + small_net,
            super_inflow=super_net,
            big_inflow=big_net,
            mid_inflow=mid_net,
            small_inflow=small_net,
            timestamp=str(payload.get("update_time") or _now_iso()),
            intraday_trend=None,
            source="distribution",
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
        None simply do not contribute to the quality sub-score. In practice analyze
        auto-fills them from get_financials() (latest income statement) unless the
        caller overrides with explicit flags.
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

    def get_extended_hours(self, code: str) -> ExtendedHoursSnapshot | None:
        """Pre-market and after-hours price/change for a US instrument.

        Read live from the Futu market snapshot's pre_*/after_* columns via an inline
        snippet — the packaged get_snapshot.py omits them, and get_kline returns no
        extended-hours bars. Fields are None outside the relevant session, or for
        markets without pre/post trading (e.g. A-shares).
        """
        snippet = _EXTENDED_HOURS_SNIPPET.format(skill=str(self.skill_dir), code=code)
        command = [self.python_bin, "-c", snippet]
        payload = self._run_json(command)
        rows = payload.get("data", [])
        if not rows:
            return None
        row = rows[0]
        return ExtendedHoursSnapshot(
            code=row.get("code", code),
            prev_close=row.get("prev_close"),
            pre_price=row.get("pre_price"),
            pre_change_rate=row.get("pre_change_rate"),
            pre_volume=row.get("pre_volume"),
            after_price=row.get("after_price"),
            after_change_rate=row.get("after_change_rate"),
            after_volume=row.get("after_volume"),
        )

    def get_financials(self, code: str) -> FinancialsSnapshot | None:
        """Quality metrics from the latest income statement (+ revenue breakdown).

        Reads futuapi's get_financials_statements.py for the most recent reported
        period and distills growth (revenue/EPS YoY) and profitability (gross/net
        margin) — the business-quality inputs that the market snapshot does not carry.
        Margins and growth are currency-independent ratios, so a CNY-reporting issue
        priced in HKD/USD needs no FX adjustment. Returns None when the statement feed
        is unavailable, so analyze simply falls back to valuation-only scoring.
        """
        try:
            payload = self._run_json(
                [self.python_bin, self._script("quote", "get_financials_statements.py"), code, "--json"]
            )
        except (RuntimeError, subprocess.CalledProcessError):
            return None
        reports = (payload.get("data") or {}).get("report_list") or []
        if not reports:
            return None
        latest = max(reports, key=lambda r: r.get("date_time", 0))
        items = {it.get("field_id"): it for it in latest.get("item_list", [])}

        def _data(field_id: int) -> float | None:
            item = items.get(field_id)
            value = item.get("data") if item else None
            return float(value) if value is not None else None

        def _yoy(field_id: int) -> float | None:
            item = items.get(field_id)
            value = item.get("yoy") if item else None
            return round(float(value), 1) if value is not None else None

        revenue = _data(_FIELD_TOTAL_REVENUE)

        def _margin(numerator: float | None) -> float | None:
            if numerator is None or not revenue:
                return None
            return round(numerator / revenue * 100, 1)

        return FinancialsSnapshot(
            code=code,
            period=latest.get("period_text"),
            revenue_growth=_yoy(_FIELD_TOTAL_REVENUE),
            eps_growth=_yoy(_FIELD_BASIC_EPS),
            gross_margin=_margin(_data(_FIELD_GROSS_PROFIT)),
            net_margin=_margin(_data(_FIELD_NET_INCOME_PARENT)),
            revenue_breakdown=self._revenue_breakdown(code),
        )

    def _revenue_breakdown(self, code: str, top: int = 4) -> list[tuple[str, float]]:
        """Top revenue segments as (name, percent). Best-effort: never fatal to analyze."""
        try:
            payload = self._run_json(
                [self.python_bin, self._script("quote", "get_financials_revenue_breakdown.py"), code, "--json"]
            )
        except (RuntimeError, subprocess.CalledProcessError):
            return []
        groups = (payload.get("data") or {}).get("breakdown_list") or []
        # type 1 is the by-business-segment split; fall back to whatever group exists.
        group = next((g for g in groups if g.get("type") == 1), groups[0] if groups else None)
        if not group:
            return []
        segments: list[tuple[str, float]] = []
        for item in group.get("item_list", [])[:top]:
            name, ratio = item.get("name"), item.get("ratio")
            if name and ratio is not None:
                segments.append((str(name), round(float(ratio), 1)))
        return segments

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
