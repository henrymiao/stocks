import unittest

from tools.stock_skills.import_reviews import (
    parse_label,
    parse_markdown,
    parse_price,
    self_review,
)

SOXL_TABLE = (
    "| 标的 | 开盘 | 最高 | 最低 | 收盘 | 昨收 | 单日表现 |\n"
    "| SOXL | 230.85 | 233.69 | 181.81 | 182.54 | 262.70 | -30.51% |\n"
    "| SOXS | 5.855 | 6.85 | 5.79 | 6.84 | 5.20 | +31.54% |\n"
)


class ImportReviewTests(unittest.TestCase):
    def test_price_from_label_table_row(self):
        self.assertEqual(parse_price("| 最新价 | 368.53 |"), 368.53)

    def test_price_exact_match_prefers_close_over_prev_close(self):
        text = "| 前收盘 | 82.53 |\n| 收盘 | 81.10 |\n"
        self.assertEqual(parse_price(text), 81.10)

    def test_price_from_prose(self):
        self.assertEqual(parse_price("沪电股份今日收盘价为 137.00 元"), 137.0)
        self.assertEqual(parse_price("截至 2026-06-10 收盘：37.05 元"), 37.05)

    def test_price_per_ticker_in_multi_instrument_table(self):
        self.assertEqual(parse_price(SOXL_TABLE, ticker_hint="SOXL"), 182.54)
        self.assertEqual(parse_price(SOXL_TABLE, ticker_hint="SOXS"), 6.84)

    def test_label_heuristic(self):
        self.assertEqual(parse_label("继续走弱，跌破防守位，建议减仓防守"), "risk-reduce")
        self.assertEqual(parse_label("站上压力位，放量突破确认，可低吸持有"), "hold")

    def test_parse_markdown_defaults_invalidation_none(self):
        text = "| 收盘价 | 70.30 元 |\n若跌破 69.7 则走弱"
        rec = parse_markdown(text, "SH.600584", "2026-06-08")
        self.assertEqual(rec["entry_price"], 70.30)
        self.assertIsNone(rec["invalidation_level"])
        self.assertTrue(rec["user_context"]["imported"])

    def test_parse_markdown_opt_in_invalidation(self):
        text = "| 收盘价 | 70.30 元 |\n若跌破 69.7 则走弱"
        rec = parse_markdown(text, "SH.600584", "2026-06-08", parse_inval=True)
        self.assertEqual(rec["invalidation_level"], 69.7)

    def test_unparseable_price_returns_none(self):
        self.assertIsNone(parse_markdown("没有任何价格的纯文字", "X.NONE", "2026-06-08"))

    def test_self_review_uses_later_note_as_future_price(self):
        recs = [
            {"code": "X", "timestamp": "2026-06-08T15:00:00+08:00", "label": "hold", "entry_price": 100.0, "invalidation_level": None},
            {"code": "X", "timestamp": "2026-06-09T15:00:00+08:00", "label": "hold", "entry_price": 90.0, "invalidation_level": None},
        ]
        reviews = self_review(recs, window=5)

        self.assertEqual(len(reviews), 1)  # only the earlier call has a future note
        self.assertFalse(reviews[0]["directional_success"])  # bullish call, price fell 10%
        self.assertAlmostEqual(reviews[0]["final_return_pct"], -10.0, places=2)


if __name__ == "__main__":
    unittest.main()
