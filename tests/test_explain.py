import unittest

from tools.stock_skills.explain import explain_recommendation


def _record(**overrides):
    record = {
        "code": "US.GOOGL",
        "name": "谷歌-A",
        "entry_price": 377.65,
        "label": "trim-on-strength",
        "horizon": "core",
        "data_quality": {"session_phase": "after-close"},
        "strategy_assessment": {
            "horizon": "core",
            "setup_score": 68.17,
            "entry_decision": "probe",
            "position_decision": "hold",
            "suggested_allocation_pct": 4.02,
            "factor_clusters": {
                "thesis": 72.0,
                "market_behavior": 49.93,
                "environment": 68.56,
                "risk_fit": 72.0,
            },
            "gates_failed": [],
            "gates_missing": ["event-window"],
        },
        "exit_plan": {
            "structural_invalidation": 363.35,
            "initial_stop": 349.49,
            "risk_per_share": 28.16,
            "targets": [{"name": "tp1", "price": 448.05, "r_multiple": 2.5, "fraction": 0.15}],
            "time_stop": {"sessions": 120, "progress_r": 0.5, "action": "full-exit"},
        },
    }
    record.update(overrides)
    return record


class ExplainTests(unittest.TestCase):
    def test_the_two_questions_are_labelled_as_different_questions(self):
        text = explain_recommendation(_record(), cost_basis=290.0, shares=170)

        # The confusion this module exists to remove: an entry decision read as advice
        # about a position already held.
        self.assertIn("已有仓位：强势时可减一部分", text)
        self.assertIn("持仓动作：继续持有", text)
        self.assertIn("要不要新建/加仓：仅小额试探", text)
        self.assertIn("与已有持仓无关", text)

    def test_position_context_comes_from_the_book_not_the_record(self):
        with_book = explain_recommendation(_record(), cost_basis=290.0, shares=170)
        self.assertIn("持仓 170 股 @290.00", with_book)
        self.assertIn("+30.2%", with_book)
        self.assertIn("3.11R", with_book)  # (377.65-290)/28.16

        without_book = explain_recommendation(_record())
        self.assertNotIn("持仓", without_book.splitlines()[1])
        self.assertNotIn("R  当前进展", without_book)

    def test_failed_gates_are_split_by_whether_a_lower_price_can_fix_them(self):
        text = explain_recommendation(
            _record(
                strategy_assessment={
                    **_record()["strategy_assessment"],
                    "gates_failed": ["resistance-room", "trend-regime"],
                }
            )
        )
        self.assertIn("失守（价格解决不了）：趋势方向", text)
        self.assertIn("失守（等更低的价格即可）：阻力空间", text)

    def test_method_restrictions_and_provisional_sessions_are_surfaced(self):
        text = explain_recommendation(
            _record(
                data_quality={"session_phase": "intraday"},
                method_assessment={
                    "restrictions": [{"code": "swing-stage-4", "effect": "reject-new-risk"}]
                },
            )
        )
        self.assertIn("读数为临时值", text)
        self.assertIn("swing-stage-4", text)

    def test_it_renders_a_bare_record_without_a_plan_or_position(self):
        text = explain_recommendation(
            {
                "code": "US.X",
                "name": "X",
                "strategy_assessment": {"setup_score": 50.0, "entry_decision": "watch"},
            }
        )
        self.assertIn("US.X", text)
        self.assertIn("观察", text)


if __name__ == "__main__":
    unittest.main()
