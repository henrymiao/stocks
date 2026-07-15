import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.models import CapitalSnapshot, KLineBar, MarketSnapshot
from tools.stock_skills.store import MarketStore, sync_daily_bars


def _bar(time: str, close: float) -> KLineBar:
    return KLineBar(time=time, open=close - 1, high=close + 1, low=close - 2, close=close, volume=1000, turnover=close * 1000)


def _snapshot(code: str, last: float, captured_at: str = "2026-07-10T10:00:00") -> MarketSnapshot:
    return MarketSnapshot(
        code=code,
        name=code,
        last_price=last,
        open=last - 1,
        high=last + 1,
        low=last - 2,
        prev_close=last - 0.5,
        volume=5000,
        turnover=last * 5000,
        timestamp="2026-07-10T10:00:00",
        captured_at=captured_at,
    )


class _FakeFetcher:
    def __init__(self, bars):
        self.bars = bars
        self.calls = 0

    def get_daily_bars(self, code, num=30):
        self.calls += 1
        return self.bars[-num:]


class MarketStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self._tmp.name) / "market.db")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_upsert_bars_is_idempotent_and_updates(self):
        bars = [_bar("2026-07-08", 100.0), _bar("2026-07-09", 102.0)]
        self.assertEqual(self.store.upsert_bars("US.COIN", "1d", bars), 2)
        self.assertEqual(self.store.upsert_bars("US.COIN", "1d", bars), 2)
        self.assertEqual(self.store.bar_count("US.COIN"), 2)

        revised = [_bar("2026-07-09", 103.5)]
        self.store.upsert_bars("US.COIN", "1d", revised)
        cached = self.store.get_bars("US.COIN")
        self.assertEqual(len(cached), 2)
        self.assertEqual(cached[-1].close, 103.5)

    def test_get_bars_orders_by_time_and_limits(self):
        self.store.upsert_bars("US.COIN", "1d", [_bar("2026-07-09", 2.0), _bar("2026-07-08", 1.0), _bar("2026-07-10", 3.0)])
        cached = self.store.get_bars("US.COIN", limit=2)
        self.assertEqual([bar.time for bar in cached], ["2026-07-09", "2026-07-10"])

    def test_bars_rejects_non_finite_values(self):
        with self.assertRaises(ValueError):
            self.store.upsert_bars("US.COIN", "1d", [_bar("2026-07-09", float("nan"))])

    def test_snapshot_and_capital_history_roundtrip(self):
        self.store.record_snapshot(_snapshot("US.COIN", 158.44))
        capital = CapitalSnapshot(
            net_inflow=-100.0, super_inflow=-50.0, big_inflow=-30.0,
            mid_inflow=-15.0, small_inflow=-5.0, timestamp="2026-07-10T10:00:00", source="distribution",
        )
        self.store.record_capital("US.COIN", capital)
        history = self.store.capital_history("US.COIN")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["super_net"], -50.0)
        self.assertEqual(history[0]["source"], "distribution")

    def test_alert_triggers_once_below(self):
        self.store.add_alert("US.COIN", "below", 150.0, "价值区上沿")
        self.store.add_alert("US.COIN", "below", 142.0, "中期底线")
        self.store.add_alert("US.COIN", "above", 180.0, "中期决策位")

        triggered = self.store.check_alerts({"US.COIN": _snapshot("US.COIN", 149.5)})
        self.assertEqual([alert["level"] for alert in triggered], [150.0])
        self.assertEqual(triggered[0]["triggered_price"], 149.5)

        # One-shot: the same level never fires again; deeper levels still armed.
        self.assertEqual(self.store.check_alerts({"US.COIN": _snapshot("US.COIN", 149.0)}), [])
        remaining = {alert["level"] for alert in self.store.active_alerts("US.COIN")}
        self.assertEqual(remaining, {142.0, 180.0})

    def test_alert_above_direction_and_missing_snapshot(self):
        self.store.add_alert("US.COIN", "above", 180.0)
        self.assertEqual(self.store.check_alerts({}), [])
        triggered = self.store.check_alerts({"US.COIN": _snapshot("US.COIN", 181.0)})
        self.assertEqual(len(triggered), 1)

    def test_alert_rejects_bad_direction_and_level(self):
        with self.assertRaises(ValueError):
            self.store.add_alert("US.COIN", "under", 150.0)
        with self.assertRaises(ValueError):
            self.store.add_alert("US.COIN", "below", float("inf"))

    def test_earnings_calendar_window(self):
        self.store.upsert_earnings("US.COIN", "2026-08-12", "盘后", "Q2财报(预计)")
        self.store.upsert_earnings("US.CRCL", "2026-09-30", "盘前", "太远")
        upcoming = self.store.upcoming_earnings(within_days=45, today="2026-07-10")
        self.assertEqual([row["code"] for row in upcoming], ["US.COIN"])
        self.assertEqual(upcoming[0]["days_until"], 33)
        # Past events never resurface.
        self.assertEqual(self.store.upcoming_earnings(within_days=365, today="2026-10-01"), [])

    def test_earnings_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            self.store.upsert_earnings("US.COIN", "Aug 12")

    def test_sync_daily_bars_writes_through(self):
        fetcher = _FakeFetcher([_bar("2026-07-08", 100.0), _bar("2026-07-09", 102.0)])
        bars = sync_daily_bars(self.store, fetcher, "US.COIN", num=2)
        self.assertEqual(len(bars), 2)
        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(self.store.bar_count("US.COIN"), 2)


if __name__ == "__main__":
    unittest.main()
