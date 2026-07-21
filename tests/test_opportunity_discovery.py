import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from tools.stock_skills.cli import main as cli_main
from tools.stock_skills.discovery_engine import (
    candidate_from_record,
    confirm_discoveries,
    discover_universe,
    review_discovery,
)
from tools.stock_skills.discovery_features import completed_daily_bars
from tools.stock_skills.discovery_store import DiscoveryStore
from tools.stock_skills.discovery_runtime import sector_confirmation_from_snapshots
from tools.stock_skills.models import KLineBar, MarketSnapshot
from tools.stock_skills.universe import (
    MarketUniverse,
    SectorUniverse,
    UniverseMember,
    load_universe,
    resolve_universe,
)


def _bar(day, close, *, previous=None, volume=1_000_000, close_location=0.6):
    previous = close if previous is None else previous
    span = max(2.0, abs(close - previous) + 1.0)
    low = close - span * close_location
    high = low + span
    return KLineBar(
        time=day.isoformat(),
        open=previous,
        high=high,
        low=low,
        close=close,
        volume=volume,
        turnover=close * volume,
    )


def _series(*, recovery=True, future=False, leader=False):
    start = date(2026, 5, 22)
    bars = []
    previous = 120.0
    for index in range(59):
        close = 120.0 - index * 0.6
        bars.append(_bar(start + timedelta(days=index), close, previous=previous))
        previous = close
    day = date(2026, 7, 20)
    if recovery:
        # New low, very strong close location and positive close on a volume climax.
        latest = KLineBar(
            time=day.isoformat(),
            open=82.0,
            high=88.0,
            low=77.5,
            close=87.0 if not leader else 88.0,
            volume=3_400_000,
            turnover=295_800_000.0,
        )
    else:
        # High-volume decline that finishes near the low must not look like exhaustion.
        latest = KLineBar(
            time=day.isoformat(),
            open=82.0,
            high=87.0,
            low=77.5,
            close=78.0,
            volume=3_400_000,
            turnover=265_200_000.0,
        )
    bars.append(latest)
    if future:
        bars.append(
            KLineBar(
                time="2026-07-21",
                open=87.0,
                high=99.0,
                low=86.0,
                close=98.0,
                volume=4_000_000,
                turnover=392_000_000.0,
            )
        )
    return bars


def _benchmark():
    start = date(2026, 5, 22)
    bars = []
    previous = 100.0
    for index in range(60):
        close = 100.0 + index * 0.03
        bars.append(_bar(start + timedelta(days=index), close, previous=previous))
        previous = close
    return bars


def _star_universe():
    return MarketUniverse(
        market="CN",
        as_of="2026-07-20T15:15:00+08:00",
        source="golden-fixture",
        sectors=(
            SectorUniverse(
                key="star50",
                name="科创50",
                representative="SH.000688",
                benchmark="SH.000300",
                members=(
                    UniverseMember("SH.000688", "科创50", "etf"),
                    UniverseMember("SH.688981", "中芯国际", "leader"),
                    UniverseMember("SH.688256", "寒武纪", "leader"),
                    UniverseMember("SH.688012", "中微公司", "constituent"),
                    UniverseMember("SH.688008", "澜起科技", "constituent"),
                ),
            ),
        ),
    )


def _golden_bars(*, future=False, breadth=True):
    return {
        "SH.000300": _benchmark(),
        "SH.000688": _series(recovery=True, future=future),
        "SH.688981": _series(recovery=breadth, future=future, leader=True),
        "SH.688256": _series(recovery=breadth, future=future, leader=True),
        "SH.688012": _series(recovery=breadth, future=future),
        "SH.688008": _series(recovery=breadth, future=future),
    }


class OpportunityDiscoveryTests(unittest.TestCase):
    def test_configured_universes_are_valid_and_market_routed(self):
        for market in ("cn", "hk", "us"):
            universe = load_universe(Path("data/universes") / f"{market}.json")
            self.assertEqual(universe.market, market.upper())
            self.assertTrue(universe.unique_codes())
            self.assertIn("Shanghai" if market != "us" else "New_York", universe.timezone)

    def test_us_completed_bar_cutoff_observes_daylight_saving_time(self):
        summer_bar = _bar(date(2026, 7, 20), 100.0, previous=99.0)
        winter_bar = _bar(date(2026, 1, 20), 100.0, previous=99.0)
        self.assertFalse(
            completed_daily_bars(
                [summer_bar], evaluated_at="2026-07-20T19:30:00+00:00", market="US"
            )
        )
        self.assertTrue(
            completed_daily_bars(
                [summer_bar], evaluated_at="2026-07-20T20:30:00+00:00", market="US"
            )
        )
        self.assertFalse(
            completed_daily_bars(
                [winter_bar], evaluated_at="2026-01-20T20:30:00+00:00", market="US"
            )
        )
        self.assertTrue(
            completed_daily_bars(
                [winter_bar], evaluated_at="2026-01-20T21:30:00+00:00", market="US"
            )
        )

    def test_expired_membership_is_not_used_as_neutral_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cn.json"
            payload = _star_universe().to_record()
            payload["expires_at"] = "2026-07-19T23:59:59+08:00"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "expired"):
                resolve_universe(
                    "CN",
                    configured_path=path,
                    at="2026-07-20T15:15:00+08:00",
                )

    def test_golden_star50_replay_is_armed_without_lookahead(self):
        as_of = "2026-07-20T15:15:00+08:00"
        base = discover_universe(
            _star_universe(),
            _golden_bars(future=False),
            evaluated_at=as_of,
            capital_improvement={
                "SH.000688": 80.0,
                "SH.688981": 75.0,
                "SH.688256": 75.0,
                "SH.688012": 70.0,
                "SH.688008": 70.0,
            },
        )
        repeated = discover_universe(
            _star_universe(),
            _golden_bars(future=False),
            evaluated_at=as_of,
            capital_improvement={
                "SH.000688": 80.0,
                "SH.688981": 75.0,
                "SH.688256": 75.0,
                "SH.688012": 70.0,
                "SH.688008": 70.0,
            },
        )
        with_future = discover_universe(
            _star_universe(),
            _golden_bars(future=True),
            evaluated_at=as_of,
            capital_improvement={"SH.000688": 80.0},
        )

        candidate = next(
            row
            for row in base["candidates"]
            if row["code"] == "SH.000688" and row["track"] == "oversold-reversal"
        )
        future_candidate = next(
            row
            for row in with_future["candidates"]
            if row["code"] == "SH.000688" and row["track"] == "oversold-reversal"
        )
        self.assertEqual(candidate["state"], "armed")
        self.assertGreaterEqual(candidate["score"], 65.0)
        self.assertIn("breadth", candidate["evidence_clusters"])
        self.assertEqual(candidate["score"], future_candidate["score"])
        self.assertEqual(base, repeated)
        self.assertLessEqual(len(base["sector_opportunities"]), 5)
        self.assertLessEqual(len(base["armed"]), 10)
        self.assertLessEqual(len(base["forming"]), 5)
        self.assertIn("representative", base["sector_opportunities"][0])
        self.assertIn("leaders", base["sector_opportunities"][0])
        self.assertIsNone(base["entry_recommendation"])
        self.assertNotIn("enter", {row["state"] for row in base["candidates"]})

    def test_high_volume_decline_near_low_does_not_upgrade(self):
        bars = _golden_bars()
        bars["SH.000688"] = _series(recovery=False)
        report = discover_universe(
            _star_universe(),
            bars,
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={"SH.000688": 20.0},
        )
        candidates = [row for row in report["candidates"] if row["code"] == "SH.000688"]
        self.assertFalse(any(row["state"] == "armed" for row in candidates))

    def test_stabilizing_etf_with_worsening_breadth_is_at_most_forming(self):
        bars = _golden_bars(breadth=False)
        report = discover_universe(
            _star_universe(),
            bars,
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={"SH.000688": 90.0},
        )
        candidates = [row for row in report["candidates"] if row["code"] == "SH.000688"]
        self.assertFalse(any(row["state"] == "armed" for row in candidates))

    def test_one_leader_without_breadth_does_not_create_sector_opportunity(self):
        bars = _golden_bars(breadth=False)
        bars["SH.688981"] = _series(recovery=True, leader=True)
        report = discover_universe(
            _star_universe(),
            bars,
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={"SH.000688": 90.0, "SH.688981": 90.0},
        )
        self.assertFalse(any(row["state"] == "armed" for row in report["candidates"]))

    def test_low_coverage_caps_every_candidate_at_forming(self):
        bars = _golden_bars()
        del bars["SH.688256"]
        del bars["SH.688012"]
        report = discover_universe(
            _star_universe(),
            bars,
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={"SH.000688": 100.0},
        )
        self.assertTrue(report["disabled_sectors"])
        self.assertFalse(any(row["state"] == "armed" for row in report["candidates"]))

    def test_trigger_requires_price_breadth_and_leaders_then_hands_off(self):
        report = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
        )
        candidate = candidate_from_record(
            next(
                row
                for row in report["candidates"]
                if row["code"] == "SH.000688" and row["track"] == "oversold-reversal"
            )
        )
        trigger = candidate.trigger_level
        intraday = {
            "SH.000688": [
                KLineBar(
                    time="2026-07-21T09:50:00+08:00",
                    open=trigger - 1,
                    high=trigger + 2,
                    low=trigger - 2,
                    close=trigger + 1,
                    volume=100_000,
                    turnover=(trigger + 1) * 100_000,
                ),
                # A 09:55-start candle is still forming at 09:56.
                KLineBar(
                    time="2026-07-21T09:55:00+08:00",
                    open=trigger + 1,
                    high=trigger + 3,
                    low=trigger,
                    close=trigger + 2,
                    volume=10_000,
                    turnover=(trigger + 2) * 10_000,
                ),
            ]
        }
        still_forming = confirm_discoveries(
            [candidate],
            intraday,
            {"star50": {"breadth": 0.75, "leader_breadth": 1.0, "coverage": 1.0}},
            evaluated_at="2026-07-21T09:52:00+08:00",
            analyzer=lambda row: {"entry_decision": "probe", "code": row.code},
        )
        self.assertEqual(still_forming["candidates"][0]["state"], "armed")
        self.assertFalse(still_forming["deep_analysis_handoffs"])

        confirmed = confirm_discoveries(
            [candidate],
            intraday,
            {"star50": {"breadth": 0.75, "leader_breadth": 1.0, "coverage": 1.0}},
            evaluated_at="2026-07-21T09:56:00+08:00",
            analyzer=lambda row: {"entry_decision": "probe", "code": row.code},
        )
        updated = candidate_from_record(confirmed["candidates"][0])
        self.assertEqual(updated.state, "triggered")
        self.assertEqual(updated.deep_analysis["entry_decision"], "probe")
        self.assertTrue(confirmed["deep_analysis_handoffs"][0]["deep_analysis_invoked"])

    def test_material_capital_divergence_invalidates_armed_candidate(self):
        report = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
        )
        candidate = candidate_from_record(report["armed"][0])
        result = confirm_discoveries(
            [candidate],
            {
                candidate.code: [
                    KLineBar(
                        time="2026-07-21T09:50:00+08:00",
                        open=candidate.trigger_level - 1,
                        high=candidate.trigger_level + 2,
                        low=candidate.structural_invalidation + 1,
                        close=candidate.trigger_level + 1,
                        volume=100_000,
                        turnover=(candidate.trigger_level + 1) * 100_000,
                    )
                ]
            },
            {candidate.sector: {"breadth": 0.75, "leader_breadth": 1.0, "coverage": 1.0}},
            evaluated_at="2026-07-21T09:56:00+08:00",
            instrument_confirmation={candidate.code: {"capital_improvement": 10.0}},
        )
        self.assertEqual(result["candidates"][0]["state"], "invalidated")
        self.assertEqual(result["transitions"][0]["reason"], "material-capital-divergence")

    def test_after_close_hard_veto_clears_existing_armed_state(self):
        base = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
        )
        existing = candidate_from_record(
            next(
                row
                for row in base["armed"]
                if row["code"] == "SH.000688" and row["track"] == "oversold-reversal"
            )
        )
        bars = _golden_bars()
        bars["SH.000688"] = _series(recovery=False)
        refreshed = discover_universe(
            _star_universe(),
            bars,
            evaluated_at="2026-07-21T15:15:00+08:00",
            capital_improvement={"SH.000688": 10.0},
            existing={(existing.sector, existing.code, existing.track): existing},
        )
        same = next(
            row for row in refreshed["candidates"] if row["discovery_id"] == existing.discovery_id
        )
        self.assertEqual(same["state"], "invalidated")
        self.assertEqual(same["transition_history"][-1]["reason"], "hard-discovery-veto")

    def test_expired_setup_is_closed_before_a_new_discovery_id_is_created(self):
        base = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
        )
        existing = candidate_from_record(
            next(
                row
                for row in base["armed"]
                if row["code"] == "SH.000688" and row["track"] == "oversold-reversal"
            )
        )
        refreshed = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-24T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
            existing={(existing.sector, existing.code, existing.track): existing},
        )
        related = [
            row
            for row in refreshed["candidates"]
            if row["code"] == existing.code and row["track"] == existing.track
        ]
        self.assertEqual({row["state"] for row in related}, {"expired", "armed"})
        self.assertEqual(len({row["discovery_id"] for row in related}), 2)

    def test_stale_intraday_snapshots_cannot_confirm_sector_breadth(self):
        universe = _star_universe()

        def snapshot(code, timestamp):
            return MarketSnapshot(
                code=code,
                name=code,
                last_price=101.0,
                open=100.0,
                high=102.0,
                low=99.0,
                prev_close=100.0,
                volume=1_000_000,
                turnover=101_000_000.0,
                timestamp=timestamp,
                captured_at=timestamp,
            )

        snapshots = {
            member.code: snapshot(member.code, "2026-07-21T09:00:00+08:00")
            for member in universe.sectors[0].members
        }
        result = sector_confirmation_from_snapshots(
            universe,
            snapshots,
            evaluated_at="2026-07-21T10:00:00+08:00",
        )
        self.assertNotIn("star50", result)

    def test_discovery_store_deduplicates_notifications_and_roundtrips_reviews(self):
        report = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
        )
        candidate = candidate_from_record(report["armed"][0])
        with tempfile.TemporaryDirectory() as tmpdir:
            with DiscoveryStore(Path(tmpdir) / "discoveries.db") as store:
                store.upsert(candidate)
                self.assertEqual(store.get(candidate.discovery_id), candidate)
                self.assertTrue(store.should_notify(candidate))
                self.assertFalse(store.should_notify(candidate))
                review = review_discovery(candidate, _series(recovery=True)[:10])
                store.save_review(review)
                self.assertEqual(len(store.reviews("CN")), 1)

    def test_cli_discovers_confirms_and_reviews_offline_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_path = root / "fixture.json"
            db_path = root / "discoveries.db"
            discover_output = root / "discover.json"
            confirm_output = root / "confirm.json"
            review_output = root / "review.json"
            fixture = {
                "universe": _star_universe().to_record(),
                "bars": {
                    code: [asdict(bar) for bar in bars]
                    for code, bars in _golden_bars().items()
                },
                "capital_improvement": {
                    code: 80.0
                    for code in _golden_bars()
                    if code != "SH.000300"
                },
            }
            fixture_path.write_text(
                json.dumps(fixture, ensure_ascii=False), encoding="utf-8"
            )

            with redirect_stdout(io.StringIO()):
                result = cli_main(
                    [
                        "discover",
                        "--market",
                        "CN",
                        "--fixture",
                        str(fixture_path),
                        "--db",
                        str(db_path),
                        "--as-of",
                        "2026-07-20T15:15:00+08:00",
                        "--output",
                        str(discover_output),
                        "--no-notify",
                    ]
                )
            self.assertEqual(result, 0)
            discovered = json.loads(discover_output.read_text(encoding="utf-8"))
            armed = next(
                row
                for row in discovered["armed"]
                if row["code"] == "SH.000688"
                and row["track"] == "oversold-reversal"
            )
            self.assertIsNone(discovered["entry_recommendation"])

            trigger = armed["trigger_level"]
            fixture.update(
                {
                    "intraday_bars": {
                        "SH.000688": [
                            asdict(
                                KLineBar(
                                    time="2026-07-21T09:50:00+08:00",
                                    open=trigger - 1,
                                    high=trigger + 2,
                                    low=trigger - 2,
                                    close=trigger + 1,
                                    volume=100_000,
                                    turnover=(trigger + 1) * 100_000,
                                )
                            )
                        ]
                    },
                    "sector_confirmation": {
                        "star50": {
                            "breadth": 0.75,
                            "leader_breadth": 1.0,
                            "coverage": 1.0,
                        }
                    },
                    "future_bars": {
                        "SH.000688": [
                            asdict(
                                KLineBar(
                                    time="2026-07-22",
                                    open=trigger + 1,
                                    high=trigger + 5,
                                    low=trigger,
                                    close=trigger + 4,
                                    volume=1_000_000,
                                    turnover=(trigger + 4) * 1_000_000,
                                )
                            )
                        ]
                    },
                }
            )
            fixture_path.write_text(
                json.dumps(fixture, ensure_ascii=False), encoding="utf-8"
            )

            with redirect_stdout(io.StringIO()):
                result = cli_main(
                    [
                        "confirm-discoveries",
                        "--market",
                        "CN",
                        "--fixture",
                        str(fixture_path),
                        "--db",
                        str(db_path),
                        "--as-of",
                        "2026-07-21T09:56:00+08:00",
                        "--output",
                        str(confirm_output),
                        "--no-deep-analysis",
                    ]
                )
            self.assertEqual(result, 0)
            confirmed = json.loads(confirm_output.read_text(encoding="utf-8"))
            self.assertTrue(
                any(
                    row["code"] == "SH.000688" and row["state"] == "triggered"
                    for row in confirmed["candidates"]
                )
            )
            self.assertTrue(
                any(item["to"] == "triggered" for item in confirmed["notifications"])
            )

            with redirect_stdout(io.StringIO()):
                result = cli_main(
                    [
                        "review-discoveries",
                        "--market",
                        "CN",
                        "--fixture",
                        str(fixture_path),
                        "--db",
                        str(db_path),
                        "--output",
                        str(review_output),
                    ]
                )
            self.assertEqual(result, 0)
            reviewed = json.loads(review_output.read_text(encoding="utf-8"))
            self.assertGreaterEqual(reviewed["reviewed"], 1)


if __name__ == "__main__":
    unittest.main()
