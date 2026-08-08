import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from tools.stock_skills.cli import main as cli_main
from tools.stock_skills.discovery_engine import (
    MINIMUM_MEDIAN_TURNOVER,
    DiscoveryConfig,
    _initial_state,
    candidate_from_record,
    confirm_discoveries,
    discover_universe,
    review_discovery,
)
from tools.stock_skills.discovery_features import (
    FeatureValue,
    SectorFeatureContext,
    TrackFeatureSet,
    completed_daily_bars,
)
from tools.stock_skills.discovery_store import DiscoveryStore
from tools.stock_skills.discovery_runtime import (
    freeze_discovery_inputs,
    run_live_discovery,
    sector_confirmation_from_snapshots,
)
from tools.stock_skills.identity import SecurityIdentity
from tools.stock_skills.models import KLineBar, MarketSnapshot
from tools.stock_skills.point_in_time import EvidenceStamp, ModelRelease, PointInTimeInput, bind_shadow_pair
from tools.stock_skills.store import MarketStore
from tools.stock_skills.universe import (
    MarketUniverse,
    SectorUniverse,
    UniverseMember,
    load_universe,
    resolve_universe,
    universe_from_record,
)


def _bar(day, close, *, previous=None, volume=10_000_000, close_location=0.6):
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
            volume=34_000_000,
            turnover=2_958_000_000.0,
        )
    else:
        # High-volume decline that finishes near the low must not look like exhaustion.
        latest = KLineBar(
            time=day.isoformat(),
            open=82.0,
            high=87.0,
            low=77.5,
            close=78.0,
            volume=34_000_000,
            turnover=2_652_000_000.0,
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
                volume=40_000_000,
                turnover=3_920_000_000.0,
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
    def test_shadow_bindings_share_one_frozen_discovery_input(self):
        universe = _star_universe()
        identity = SecurityIdentity(
            "listing:SH.000688",
            "security:SH.000688",
            "SH.000688",
            "科创50",
            "CN",
            "ordinary-stock",
            "CNY",
            "2026-01-01T00:00:00+08:00",
        )
        snapshot = MarketSnapshot(
            "SH.000688",
            "科创50",
            87.0,
            82.0,
            88.0,
            77.5,
            82.0,
            3_400_000,
            295_800_000.0,
            "2026-07-20T15:15:00+08:00",
            "2026-07-20T15:15:02+08:00",
        )
        evidence = (
            EvidenceStamp(
                "snapshot",
                "available",
                "offline-fixture",
                snapshot.timestamp,
                None,
                snapshot.captured_at,
                "fixture:snapshot",
                "none",
            ),
        )

        with mock.patch.object(
            PointInTimeInput,
            "build_market_payload",
            wraps=PointInTimeInput.build_market_payload,
        ) as builder:
            package = freeze_discovery_inputs(
                universe=universe,
                identity=identity,
                identity_version="identity:test",
                as_of="2026-07-20T15:15:00+08:00",
                captured_at="2026-07-20T15:15:02+08:00",
                session_phase="after-close",
                snapshot=snapshot,
                daily_bars=_golden_bars()["SH.000688"],
                intraday_bars=[],
                daily_adjustment_basis="none",
                intraday_adjustment_basis="none",
                intraday_bar_interval="5m",
                evidence=evidence,
            )

        champion, challenger = bind_shadow_pair(
            package,
            ModelRelease("stock-analysis-v6", "logic-first-method-evidence-v6", "recommendation-v6"),
            ModelRelease(
                "stock-analysis-v7-shadow",
                "stock-analysis-v7-shadow-v1",
                "recommendation-v7-shadow-v1",
            ),
        )
        self.assertEqual(builder.call_count, 1)
        self.assertEqual(champion.input_package_id, challenger.input_package_id)
        self.assertEqual(champion.input_digest, challenger.input_digest)

    def test_configured_universes_are_valid_and_market_routed(self):
        expected_timezones = {
            "cn": "Asia/Shanghai",
            "hk": "Asia/Hong_Kong",
            "us": "America/New_York",
        }
        for market in ("cn", "hk", "us"):
            universe = load_universe(Path("data/universes") / f"{market}.json")
            self.assertEqual(universe.market, market.upper())
            self.assertTrue(universe.unique_codes())
            self.assertEqual(universe.timezone, expected_timezones[market])

    def test_v1_universe_remains_loadable_during_migration(self):
        payload = _star_universe().to_record()
        payload["schema_version"] = "opportunity-universe-v1"
        payload.pop("published_at", None)
        payload.pop("identity_registry_version", None)
        payload.pop("version_id", None)
        for sector in payload["sectors"]:
            for member in sector["members"]:
                member.pop("security_id", None)
                member.pop("member_from", None)
                member.pop("member_to", None)

        loaded = universe_from_record(payload, source="legacy-fixture")

        self.assertEqual(loaded.schema_version, "opportunity-universe-v1")
        self.assertEqual(loaded.effective_published_at, loaded.as_of)
        self.assertEqual(loaded.unique_codes(), _star_universe().unique_codes())

    def test_v2_membership_filters_future_and_ended_members(self):
        payload = _star_universe().to_record()
        payload.update(
            {
                "schema_version": "opportunity-universe-v2",
                "published_at": "2026-07-20T08:00:00+08:00",
                "identity_registry_version": "identity:test",
            }
        )
        payload.pop("version_id", None)
        members = payload["sectors"][0]["members"]
        for member in members:
            member["security_id"] = f"listing:{member['code']}"
            member["member_from"] = "2026-01-01T00:00:00+08:00"
        members[1]["member_to"] = "2026-07-19T23:59:59+08:00"
        members[2]["member_from"] = "2026-07-21T00:00:00+08:00"

        loaded = universe_from_record(payload)
        active = loaded.active_member_codes("2026-07-20T15:15:00+08:00")

        self.assertNotIn(members[1]["code"], active)
        self.assertNotIn(members[2]["code"], active)
        self.assertIn(members[3]["code"], active)

    def test_future_published_membership_is_rejected(self):
        payload = _star_universe().to_record()
        payload.update(
            {
                "schema_version": "opportunity-universe-v2",
                "published_at": "2026-07-21T08:00:00+08:00",
                "identity_registry_version": "identity:test",
            }
        )
        payload.pop("version_id", None)
        for member in payload["sectors"][0]["members"]:
            member["security_id"] = f"listing:{member['code']}"
            member["member_from"] = "2026-01-01T00:00:00+08:00"

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cn.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "published after"):
                resolve_universe(
                    "CN",
                    configured_path=path,
                    at="2026-07-20T15:15:00+08:00",
                )

    def test_universe_version_ignores_runtime_source_but_not_membership(self):
        payload = _star_universe().to_record()
        payload.pop("version_id", None)
        configured = universe_from_record(payload, source="configured")
        cached = universe_from_record(payload, source="cache")
        changed = json.loads(json.dumps(payload))
        changed["sectors"][0]["members"][0]["weight"] = 2.0

        self.assertEqual(configured.version_id, cached.version_id)
        self.assertNotEqual(
            configured.version_id,
            universe_from_record(changed).version_id,
        )

    def test_v2_persisted_version_mismatch_is_rejected(self):
        payload = _star_universe().to_record()
        payload.update(
            {
                "schema_version": "opportunity-universe-v2",
                "published_at": "2026-07-20T08:00:00+08:00",
                "identity_registry_version": "identity:test",
                "version_id": "universe:tampered",
            }
        )
        for member in payload["sectors"][0]["members"]:
            member["security_id"] = f"listing:{member['code']}"
            member["member_from"] = "2026-01-01T00:00:00+08:00"

        with self.assertRaisesRegex(ValueError, "version_id mismatch"):
            universe_from_record(payload)

    def test_future_cache_is_ignored_when_configured_membership_is_valid(self):
        configured = _star_universe().to_record()
        configured.pop("version_id", None)
        cached = json.loads(json.dumps(configured))
        cached.update(
            {
                "schema_version": "opportunity-universe-v2",
                "published_at": "2026-07-21T08:00:00+08:00",
                "identity_registry_version": "identity:test",
            }
        )
        for member in cached["sectors"][0]["members"]:
            member["security_id"] = f"listing:{member['code']}"
            member["member_from"] = "2026-01-01T00:00:00+08:00"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            configured_path = root / "configured.json"
            cache_path = root / "cache.json"
            configured_path.write_text(json.dumps(configured), encoding="utf-8")
            cache_path.write_text(json.dumps(cached), encoding="utf-8")

            resolved = resolve_universe(
                "CN",
                configured_path=configured_path,
                cache_path=cache_path,
                at="2026-07-20T15:15:00+08:00",
            )

        self.assertEqual(resolved.source, f"file:{configured_path}")

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
        leader_codes = [row["code"] for row in base["sector_opportunities"][0]["leaders"]]
        self.assertEqual(len(leader_codes), len(set(leader_codes)))
        for key in ("armed", "forming"):
            codes = [row["code"] for row in base[key]]
            self.assertEqual(len(codes), len(set(codes)))
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

        exchange_closed = confirm_discoveries(
            [candidate],
            intraday,
            {"star50": {"breadth": 0.75, "leader_breadth": 1.0, "coverage": 1.0}},
            evaluated_at="2026-07-21T09:56:00+08:00",
            market_states={candidate.code: "CLOSED"},
            analyzer=lambda row: {"entry_decision": "probe", "code": row.code},
        )
        self.assertEqual(exchange_closed["candidates"][0]["state"], "armed")

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

    def test_stale_five_minute_bar_cannot_trigger_later_in_session(self):
        report = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
        )
        candidate = candidate_from_record(
            next(
                row
                for row in report["armed"]
                if row["code"] == "SH.000688" and row["track"] == "oversold-reversal"
            )
        )
        bar = KLineBar(
            time="2026-07-21T09:50:00+08:00",
            open=candidate.trigger_level - 1,
            high=candidate.trigger_level + 2,
            low=candidate.structural_invalidation + 1,
            close=candidate.trigger_level + 1,
            volume=100_000,
            turnover=(candidate.trigger_level + 1) * 100_000,
        )
        result = confirm_discoveries(
            [candidate],
            {candidate.code: [bar]},
            {candidate.sector: {"breadth": 0.75, "leader_breadth": 1.0, "coverage": 1.0}},
            evaluated_at="2026-07-21T14:30:00+08:00",
        )
        self.assertEqual(result["candidates"][0]["state"], "armed")
        self.assertFalse(result["transitions"])

    def test_failed_deep_analysis_is_retried_while_triggered(self):
        report = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
        )
        candidate = candidate_from_record(
            next(
                row
                for row in report["armed"]
                if row["code"] == "SH.000688" and row["track"] == "oversold-reversal"
            )
        )
        bar = KLineBar(
            time="2026-07-21T09:50:00+08:00",
            open=candidate.trigger_level - 1,
            high=candidate.trigger_level + 2,
            low=candidate.structural_invalidation + 1,
            close=candidate.trigger_level + 1,
            volume=100_000,
            turnover=(candidate.trigger_level + 1) * 100_000,
        )
        evidence = {
            candidate.sector: {"breadth": 0.75, "leader_breadth": 1.0, "coverage": 1.0}
        }
        first = confirm_discoveries(
            [candidate],
            {candidate.code: [bar]},
            evidence,
            evaluated_at="2026-07-21T09:56:00+08:00",
            analyzer=lambda _: {
                "entry_decision": "defer",
                "error": "OpenD unavailable",
                "retryable": True,
            },
        )
        triggered = candidate_from_record(first["candidates"][0])
        calls = []
        second = confirm_discoveries(
            [triggered],
            {triggered.code: [bar]},
            evidence,
            evaluated_at="2026-07-21T10:01:00+08:00",
            analyzer=lambda row: calls.append(row.discovery_id)
            or {"entry_decision": "probe"},
        )
        updated = candidate_from_record(second["candidates"][0])
        self.assertEqual(calls, [triggered.discovery_id])
        self.assertEqual(updated.deep_analysis["entry_decision"], "probe")
        self.assertTrue(second["deep_analysis_handoffs"][0]["retry"])

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
                store.upsert(candidate)
                self.assertEqual(store.get(candidate.discovery_id), candidate)
                self.assertEqual(
                    len(store.transition_history(candidate.discovery_id)),
                    len(candidate.transition_history),
                )
                self.assertTrue(store.should_notify(candidate))
                self.assertFalse(store.should_notify(candidate))
                review = review_discovery(candidate, _series(recovery=True)[:10])
                store.save_review(review)
                self.assertEqual(len(store.reviews("CN")), 1)

    def test_latest_generation_wins_when_terminal_and_active_updates_tie(self):
        report = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
        )
        candidate = candidate_from_record(report["armed"][0])
        old = replace(
            candidate,
            discovery_id="old-generation",
            state="expired",
            score=90.0,
            updated_at="2026-07-24T15:15:00+08:00",
        )
        new = replace(
            candidate,
            discovery_id="new-generation",
            state="armed",
            score=70.0,
            first_seen_at="2026-07-24T15:15:00+08:00",
            updated_at="2026-07-24T15:15:00+08:00",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with DiscoveryStore(Path(tmpdir) / "discoveries.db") as store:
                store.upsert(old)
                store.upsert(new)
                latest = store.latest_by_key("CN")[(new.sector, new.code, new.track)]
                self.assertEqual(latest.discovery_id, "new-generation")

    def test_live_discovery_cannot_arm_from_stale_cache_when_opend_fails(self):
        class FailingFetcher:
            def get_snapshots(self, codes):
                raise RuntimeError("OpenD unavailable")

            def get_daily_bars(self, code, num=260):
                raise RuntimeError("OpenD unavailable")

            def get_capital(self, code):
                return None

            def get_trading_days(self, market, start, end):
                return ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24"]

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                MarketStore(Path(tmpdir) / "market.db") as market_store,
                DiscoveryStore(Path(tmpdir) / "discovery.db") as discovery_store,
            ):
                for code, bars in _golden_bars().items():
                    market_store.upsert_bars(code, "1d", bars)
                report = run_live_discovery(
                    _star_universe(),
                    evaluated_at="2026-07-24T15:15:00+08:00",
                    discovery_store=discovery_store,
                    market_store=market_store,
                    fetcher=FailingFetcher(),
                )
        self.assertFalse(report["armed"])
        self.assertTrue(report["data_failures"]["daily_bars"])
        self.assertTrue(report["stale_daily_codes"])

    def test_expiry_uses_supplied_exchange_sessions_not_weekdays(self):
        report = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at="2026-07-20T15:15:00+08:00",
            capital_improvement={code: 80.0 for code in _golden_bars() if code != "SH.000300"},
            trading_sessions=(
                "2026-07-20",
                "2026-07-21",
                "2026-07-22",
                # 2026-07-23 is an exchange holiday in this deterministic fixture.
                "2026-07-24",
                "2026-07-27",
            ),
        )
        self.assertEqual(report["armed"][0]["expires_at"][:10], "2026-07-24")

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


class ArmingNeedsInstrumentEvidenceTests(unittest.TestCase):
    """A hot sector must not arm its members by itself.

    `breadth` is a required gate for arming, and `breadth` and `leaders` are both computed
    from the sector, so counting them toward the two-group minimum let the gate double as
    the evidence it was gating. On 2026-08-07 that armed 34 of 35 CN resources names and
    33 of 35 innovative-medicine names -- 57% of the universe -- while the price and flow
    groups were never consulted.
    """

    def _track(self, *, sector_score, instrument_score):
        """A track carried by its sector: name-level groups score below the 55 support line.

        With breadth and leader_sync at `sector_score` on 0.30 of the trend-buildup weight
        and every instrument feature at `instrument_score`, the total clears the 65 arming
        score while neither the price nor the flow group reaches 55.
        """

        features = {
            "breadth": FeatureValue(sector_score, "breadth", "", {}),
            "leader_sync": FeatureValue(sector_score, "leaders", "", {}),
            "relative_strength": FeatureValue(instrument_score, "price", "", {}),
            "pivot_distance": FeatureValue(instrument_score, "price", "", {}),
            "contraction": FeatureValue(instrument_score, "flow", "", {}),
            "volume_accumulation": FeatureValue(instrument_score, "flow", "", {}),
        }
        weights = {
            "relative_strength": 0.25,
            "breadth": 0.20,
            "volume_accumulation": 0.20,
            "contraction": 0.15,
            "pivot_distance": 0.10,
            "leader_sync": 0.10,
        }
        group_scores = {
            "breadth": float(sector_score),
            "leaders": float(sector_score),
            "price": float(instrument_score),
            "flow": float(instrument_score),
        }
        return TrackFeatureSet(
            track="trend-buildup",
            score=sum(weights[name] * value.score for name, value in features.items()),
            feature_coverage=1.0,
            supporting_groups=tuple(
                sorted(group for group, value in group_scores.items() if value >= 55.0)
            ),
            group_scores=group_scores,
            features=features,
            trigger_level=100.0,
            invalidation_level=90.0,
        )

    def _context(self):
        return SectorFeatureContext(
            coverage=1.0,
            breadth=1.0,
            previous_breadth=0.5,
            breadth_change=0.5,
            leader_breadth=1.0,
            leader_stabilization=100.0,
            synchronization=100.0,
        )

    def test_a_hot_sector_alone_cannot_arm_an_ordinary_instrument(self):
        track = self._track(sector_score=100.0, instrument_score=54.0)

        # The setup the old rule armed on: score over the line, breadth present, and the
        # two-group minimum met entirely by groups that every member of the sector shares.
        self.assertGreaterEqual(track.score, 65.0)
        self.assertEqual(track.supporting_groups, ("breadth", "leaders"))
        self.assertEqual(track.instrument_supporting_groups, ())

        self.assertEqual(
            _initial_state(track, self._context(), DiscoveryConfig()), "forming"
        )

    def test_the_same_instrument_arms_once_its_own_evidence_shows_up(self):
        # Identical sector, identical weights; only the instrument's own features move
        # across the support line. That is the only thing arming should turn on.
        track = self._track(sector_score=100.0, instrument_score=56.0)

        self.assertEqual(track.instrument_supporting_groups, ("flow", "price"))
        self.assertEqual(
            _initial_state(track, self._context(), DiscoveryConfig()), "armed"
        )


class LiquidityFloorTests(unittest.TestCase):
    """An untradable listing is not an opportunity, whatever its setup looks like.

    A hard veto says the setup is bad; this says the name cannot be bought. On 2026-08-07
    the top-scoring HK candidate was a shell turning over under HK$100m, and 36 of the 65
    armed HK candidates were below that floor.
    """

    def _thin_bars(self):
        bars = _golden_bars()
        bars["SH.688012"] = [
            replace(bar, volume=bar.volume // 5_000, turnover=bar.turnover / 5_000.0)
            for bar in bars["SH.688012"]
        ]
        return bars

    def test_a_name_below_the_floor_never_becomes_a_candidate(self):
        as_of = "2026-07-20T15:15:00+08:00"
        report = discover_universe(
            _star_universe(),
            self._thin_bars(),
            evaluated_at=as_of,
            capital_improvement={},
        )
        codes = {row["code"] for row in report["candidates"]}
        self.assertNotIn("SH.688012", codes)
        self.assertIn(
            "SH.688012",
            {row["code"] for row in report["liquidity_floor"]["excluded"]},
        )
        self.assertEqual(
            report["liquidity_floor"]["minimum_median_turnover"],
            MINIMUM_MEDIAN_TURNOVER["CN"],
        )
        # The liquid members are untouched, so the floor is not disabling the sector.
        self.assertTrue(codes)

    def test_an_active_candidate_that_dries_up_is_retired_with_its_reason(self):
        as_of = "2026-07-20T15:15:00+08:00"
        first = discover_universe(
            _star_universe(),
            _golden_bars(),
            evaluated_at=as_of,
            capital_improvement={"SH.688012": 70.0},
        )
        active = {
            (row["sector"], row["code"], row["track"]): candidate_from_record(row)
            for row in first["candidates"]
            if row["code"] == "SH.688012" and row["state"] in {"forming", "armed"}
        }
        self.assertTrue(active, "fixture must produce an active candidate to retire")

        later = discover_universe(
            _star_universe(),
            self._thin_bars(),
            evaluated_at="2026-07-21T15:15:00+08:00",
            existing=active,
            capital_improvement={},
        )
        retired = [row for row in later["candidates"] if row["code"] == "SH.688012"]
        self.assertEqual(len(retired), len(active))
        for row in retired:
            self.assertEqual(row["state"], "invalidated")
            self.assertEqual(
                row["transition_history"][-1]["reason"], "below-liquidity-floor"
            )

    def test_a_thin_tape_does_not_exclude_the_sector_etf(self):
        # SH.000688 is the star50 representative. A fund is quoted against its basket, so
        # its own turnover is not the constraint, and excluding it would remove the safest
        # way to act on the sector it represents.
        as_of = "2026-07-20T15:15:00+08:00"
        bars = _golden_bars()
        bars["SH.000688"] = [
            replace(bar, volume=bar.volume // 5_000, turnover=bar.turnover / 5_000.0)
            for bar in bars["SH.000688"]
        ]
        report = discover_universe(
            _star_universe(), bars, evaluated_at=as_of, capital_improvement={}
        )
        self.assertEqual(report["liquidity_floor"]["excluded"], [])
        self.assertIn(
            "SH.000688", {row["code"] for row in report["candidates"]}
        )

    def test_bars_without_turnover_are_not_treated_as_illiquid(self):
        as_of = "2026-07-20T15:15:00+08:00"
        bars = _golden_bars()
        bars["SH.688012"] = [replace(bar, turnover=0.0) for bar in bars["SH.688012"]]
        report = discover_universe(
            _star_universe(), bars, evaluated_at=as_of, capital_improvement={}
        )
        self.assertEqual(report["liquidity_floor"]["excluded"], [])


if __name__ == "__main__":
    unittest.main()
