import json
import unittest

from tools.stock_skills.futu_fetcher import FutuFetcher


class FakeRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        return json.dumps(
            {
                "data": [
                    {
                        "code": "SZ.002463",
                        "name": "沪电股份",
                        "last_price": 147.9,
                        "open": 146.0,
                        "high": 149.36,
                        "low": 142.81,
                        "prev_close": 146.55,
                        "volume": 83679015,
                        "turnover": 12271729868.41,
                    }
                ]
            },
            ensure_ascii=False,
        )


class FutuFetcherTests(unittest.TestCase):
    def test_snapshot_uses_existing_futu_script(self):
        runner = FakeRunner()
        fetcher = FutuFetcher(
            python_bin="/Users/shuren/.futu-venv/bin/python",
            skill_dir="/Users/shuren/.agents/skills/futuapi",
            runner=runner,
        )

        snapshot = fetcher.get_snapshot("SZ.002463")

        self.assertEqual(snapshot.code, "SZ.002463")
        self.assertEqual(snapshot.last_price, 147.9)
        self.assertIn("get_snapshot.py", runner.commands[0][1])


if __name__ == "__main__":
    unittest.main()
