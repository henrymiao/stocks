import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.positions import (
    Portfolio,
    Position,
    load_portfolio,
    portfolio_from_record,
)


def _book(**overrides):
    values = dict(
        as_of="2026-08-03T22:30:00+08:00",
        base_currency="CNY",
        fx_rates={"CNY": 1.0, "USD": 7.0, "HKD": 0.9},
        cash={"CNY": 1_000_000.0},
        positions=(
            Position("US.GOOGL", 100, 290.0, "USD", "ai-compute", current_stop=300.0),
            Position("HK.00700", 700, 402.0, "HKD", "china-internet", current_stop=450.0),
            Position("SH.600584", 100, 61.0, "CNY", "semiconductor", current_stop=56.0),
        ),
    )
    values.update(overrides)
    return Portfolio(**values)


class PortfolioHeatTests(unittest.TestCase):
    def test_heat_is_weight_times_loss_to_stop_against_nav(self):
        book = _book()
        heat = book.heat({"US.GOOGL": 350.0, "HK.00700": 490.0, "SH.600584": 61.0})

        # 100*350*7 = 245,000 | 700*490*0.9 = 308,700 | 100*61 = 6,100
        self.assertEqual(heat.equity_value, 559_800.0)
        self.assertEqual(heat.cash_value, 1_000_000.0)
        self.assertEqual(heat.nav, 1_559_800.0)
        # risk: 100*(350-300)*7 = 35,000 | 700*(490-450)*0.9 = 25,200 | 100*(61-56) = 500
        self.assertEqual(heat.portfolio_open_risk_pct, round(60_700 / 1_559_800 * 100, 4))
        self.assertEqual(
            heat.theme_open_risk_pct["ai-compute"], round(35_000 / 1_559_800 * 100, 4)
        )
        self.assertTrue(heat.complete)

    def test_cash_is_part_of_nav_so_limits_are_not_overstated(self):
        priced = {"US.GOOGL": 350.0, "HK.00700": 490.0, "SH.600584": 61.0}
        with_cash = _book().heat(priced)
        without_cash = _book(cash={}).heat(priced)

        self.assertLess(
            with_cash.position_weight_pct["US.GOOGL"],
            without_cash.position_weight_pct["US.GOOGL"],
        )
        self.assertLess(
            with_cash.portfolio_open_risk_pct, without_cash.portfolio_open_risk_pct
        )

    def test_missing_price_or_stop_is_reported_never_treated_as_zero_risk(self):
        heat = _book().heat({"US.GOOGL": 350.0, "HK.00700": 490.0})
        self.assertEqual(heat.missing_prices, ("SH.600584",))
        self.assertFalse(heat.complete)

        no_stop = _book(
            positions=(Position("US.GOOGL", 100, 290.0, "USD", "ai-compute"),)
        ).heat({"US.GOOGL": 350.0})
        self.assertEqual(no_stop.missing_stops, ("US.GOOGL",))
        self.assertEqual(no_stop.portfolio_open_risk_pct, 0.0)
        self.assertFalse(no_stop.complete)

    def test_stop_above_price_contributes_no_open_risk(self):
        book = _book(
            positions=(Position("US.GOOGL", 100, 290.0, "USD", "ai-compute", current_stop=400.0),),
            cash={},
        )
        self.assertEqual(book.heat({"US.GOOGL": 350.0}).portfolio_open_risk_pct, 0.0)

    def test_contract_rejects_duplicates_unknown_fx_and_bad_rows(self):
        with self.assertRaisesRegex(ValueError, "duplicate position codes"):
            _book(
                positions=(
                    Position("US.GOOGL", 10, 1.0, "USD", "a"),
                    Position("US.GOOGL", 10, 1.0, "USD", "a"),
                )
            )
        with self.assertRaisesRegex(ValueError, "Missing FX rate"):
            _book(fx_rates={"CNY": 1.0})
        with self.assertRaisesRegex(ValueError, "share count must be positive"):
            Position("US.GOOGL", 0, 1.0, "USD", "a")
        with self.assertRaisesRegex(ValueError, "requires an explicit theme"):
            Position("US.GOOGL", 1, 1.0, "USD", "")
        with self.assertRaisesRegex(ValueError, "Unsupported market prefix"):
            Position("XX.GOOGL", 1, 1.0, "USD", "a")

    def test_configured_book_loads_and_prices_the_real_positions(self):
        book = load_portfolio("data/portfolio/positions.json")
        self.assertEqual(book.schema_version, "portfolio-positions-v1")
        self.assertGreaterEqual(len(book.positions), 10)
        self.assertEqual(book.theme_of("US.SOXL"), "semiconductor")
        self.assertTrue(all(p.current_stop is not None for p in book.positions))

    def test_roundtrip_from_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.json"
            payload = {
                "schema_version": "portfolio-positions-v1",
                "as_of": "2026-08-03T22:30:00+08:00",
                "base_currency": "CNY",
                "fx_rates": {"CNY": 1.0, "USD": 7.0},
                "cash": {"CNY": 100.0},
                "positions": [
                    {
                        "code": "US.GOOGL",
                        "shares": 10,
                        "cost_basis": 290.0,
                        "currency": "USD",
                        "theme": "ai-compute",
                        "current_stop": 250.0,
                    }
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(load_portfolio(path), portfolio_from_record(payload))


if __name__ == "__main__":
    unittest.main()
