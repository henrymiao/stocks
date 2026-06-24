"""Backfill the recommendation/review journals from the existing 复盘 markdown files.

The repo already holds hand-written review notes per name (xiaopeng/, google/, 600584/,
002463/, 002625/, soxl-soxs/, circle/, MRVL/). This script turns each note into a
structured recommendation record, and — because every code has several dated notes —
also synthesises review outcomes *offline* by treating a later note's price as the
realised future price of an earlier call. That lets `backtest` produce a win rate
immediately, with no OpenD.

Caveats (printed in each record's source_refs so nothing is silently trusted):
  * entry_price is parsed from the note's "最新价/收盘价/收盘" line — best effort.
  * label is a keyword heuristic (these are reviews, not clean buy/sell calls).
  * invalidation_level is parsed from "风险位/防守/跌破/失效" when present, else None.
  * self-review uses close-only synthetic bars from the note prices, so MFE/MAE are
    approximate. Re-run the real `review` (with OpenD) for precise OHLC outcomes.

Usage:
    python3 -m tools.stock_skills.import_reviews                 # writes data/journal/*
    python3 -m tools.stock_skills.import_reviews --dry-run       # print, write nothing
    python3 -m tools.stock_skills.import_reviews --out-dir /tmp/j
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from .journal import append_record, read_records
from .models import KLineBar
from .review import evaluate_recommendation

# Folder → instrument code(s). Authoritative: filenames/titles are inconsistent, folders are not.
FOLDER_CODES: dict[str, list[str]] = {
    "002463": ["SZ.002463"],
    "002625": ["SZ.002625"],
    "600584": ["SH.600584"],
    "MRVL": ["US.MRVL"],
    "circle": ["US.CRCL"],
    "google": ["US.GOOGL"],
    "xiaopeng": ["HK.09868"],
    "soxl-soxs": ["US.SOXL", "US.SOXS"],
}

_DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_NUM = r"([0-9]{1,6}(?:\.[0-9]+)?)"

# Ordered, specific price patterns. We deliberately avoid loose fallbacks so a file we
# cannot read confidently is skipped rather than injected with a wrong number.
_PRICE_PATTERNS = [
    re.compile(r"最新价[^0-9\-]{0,6}" + _NUM),
    re.compile(r"收盘价[^0-9\-]{0,6}" + _NUM),
    re.compile(r"收盘[：:]\s*" + _NUM),
]

_INVALIDATION_PATTERNS = [
    re.compile(r"风险位[^0-9\-]{0,8}" + _NUM),
    re.compile(r"跌破\s*" + _NUM),
    re.compile(r"失效[^0-9\-]{0,8}" + _NUM),
    re.compile(r"防守[位区]?[^0-9\-]{0,8}" + _NUM),
]

_BEARISH_KW = ["减仓", "防守", "退出", "破位", "净流出", "走弱", "弱势", "止盈", "跌破", "降低试仓", "转弱", "回落"]
_BULLISH_KW = ["低吸", "补仓", "站上", "站稳", "转强", "突破确认", "持有", "拿底仓", "承接", "加仓", "修复成立"]


def parse_date(name: str) -> str | None:
    m = _DATE_RE.search(name)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _timestamp(date: str, code: str) -> str:
    if code.startswith("US."):
        return f"{date}T16:00:00-04:00"
    return f"{date}T15:00:00+08:00"


# Priority order for a "| label | number |" table row carrying the current price.
_PRICE_ROW_LABELS = ["最新价", "现价", "收盘价", "收盘"]


def _label_row_price(text: str, labels: list[str]) -> float | None:
    """Read the number from a table row whose first cell exactly equals a price label.

    Exact match avoids confusing 前收盘 / 盘前最新 with 收盘 / 最新价.
    """
    rows: list[list[str]] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    for label in labels:  # honour label priority regardless of row order
        for cells in rows:
            if len(cells) >= 2 and cells[0] == label:
                m = re.search(_NUM, cells[1])
                if m:
                    return float(m.group(1))
    return None


def parse_price(text: str, ticker_hint: str | None = None) -> float | None:
    """Best-effort current/closing price. For multi-instrument notes, restrict the
    search to the line/row that names the ticker (e.g. a SOXL table row)."""
    if ticker_hint:
        row = _ticker_row_price(text, ticker_hint)
        if row is not None:
            return row
    label_row = _label_row_price(text, _PRICE_ROW_LABELS)
    if label_row is not None:
        return label_row
    for pat in _PRICE_PATTERNS:
        m = pat.search(text)
        if m:
            return float(m.group(1))
    return None


def _ticker_row_price(text: str, ticker: str) -> float | None:
    """In a per-instrument markdown table, read the 收盘 column of the row for `ticker`.

    Falls back to the row's first numeric cell if no 收盘 header is found.
    """
    header_cols: list[str] | None = None
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if any("收盘" in c or "标的" in c or "开盘" in c for c in cells) and not cells[0].lstrip("-").isdigit():
            if any("收盘" in c for c in cells):
                header_cols = cells
            continue
        if cells and cells[0].upper().endswith(ticker.upper()):
            close_idx = None
            if header_cols:
                for i, c in enumerate(header_cols):
                    if c.strip() == "收盘":
                        close_idx = i
                        break
            nums = []
            for c in cells[1:]:
                m = re.fullmatch(_NUM, c)
                if m:
                    nums.append(float(m.group(1)))
            if close_idx is not None and close_idx - 1 < len(nums) and close_idx >= 1:
                # header includes the label column at index 0; data cells are cells[1:]
                try:
                    return float(re.fullmatch(_NUM, cells[close_idx]).group(1))  # type: ignore[union-attr]
                except (AttributeError, IndexError, ValueError):
                    pass
            if nums:
                return nums[len(nums) // 2] if len(nums) >= 4 else nums[-1]
    return None


def parse_invalidation(text: str) -> float | None:
    for pat in _INVALIDATION_PATTERNS:
        m = pat.search(text)
        if m:
            return float(m.group(1))
    return None


def parse_label(text: str) -> str:
    """Heuristic label from conclusion sentiment. Reviews are fuzzy, so we only split
    bullish vs bearish; ties default to 'hold' (a positive/observe stance)."""
    bear = sum(text.count(k) for k in _BEARISH_KW)
    bull = sum(text.count(k) for k in _BULLISH_KW)
    if bear > bull + 1:
        return "risk-reduce"
    if bear > bull:
        return "trim-on-strength"
    return "hold"


def parse_markdown(
    text: str,
    code: str,
    date: str,
    ticker_hint: str | None = None,
    parse_inval: bool = False,
) -> dict[str, Any] | None:
    price = parse_price(text, ticker_hint=ticker_hint)
    if price is None or price <= 0:
        return None
    label = parse_label(text)
    # Invalidation parsing is unreliable in prose (and cross-contaminates two-instrument
    # notes), so it is off by default: a None invalidation makes the review outcome a
    # clean final-return-vs-label decision. Opt in with --parse-invalidation.
    invalidation = parse_invalidation(text) if parse_inval else None
    return {
        "code": code,
        "name": code,
        "timestamp": _timestamp(date, code),
        "label": label,
        "entry_price": round(price, 4),
        "invalidation_level": invalidation,
        "support_levels": [],
        "resistance_levels": [],
        "total_score": None,
        "component_scores": {},
        "source_refs": [
            f"imported-from-md:{date}",
            "entry_price/label/invalidation are heuristic parses of a 复盘 note",
        ],
        "user_context": {"imported": True},
    }


def build_recommendations(root: Path, parse_inval: bool = False) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for folder, codes in FOLDER_CODES.items():
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            date = parse_date(path.name)
            if not date:
                continue
            text = path.read_text(encoding="utf-8")
            for code in codes:
                ticker_hint = code.split(".", 1)[1] if len(codes) > 1 else None
                rec = parse_markdown(text, code, date, ticker_hint=ticker_hint, parse_inval=parse_inval)
                if rec is not None:
                    rec["source_refs"].append(f"file:{folder}/{path.name}")
                    records.append(rec)
    return records


def self_review(records: list[dict[str, Any]], window: int = 5) -> list[dict[str, Any]]:
    """Synthesise review outcomes offline using each code's later-dated note prices.

    For every recommendation we collect the prices from strictly-later notes of the same
    code, turn them into close-only synthetic bars, and run the normal review evaluator.
    Calls with no later note (the most recent per code) are left for the live `review`.
    """
    by_code: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_code.setdefault(rec["code"], []).append(rec)

    reviews: list[dict[str, Any]] = []
    for code, recs in by_code.items():
        recs_sorted = sorted(recs, key=lambda r: r["timestamp"])
        for i, rec in enumerate(recs_sorted):
            future = recs_sorted[i + 1 : i + 1 + window]
            if not future:
                continue
            future_bars = [
                KLineBar(
                    time=str(f["timestamp"])[:10],
                    open=f["entry_price"],
                    high=f["entry_price"],
                    low=f["entry_price"],
                    close=f["entry_price"],
                    volume=0,
                    turnover=0.0,
                )
                for f in future
            ]
            outcome = evaluate_recommendation(
                rec,
                entry_price=float(rec["entry_price"]),
                future_bars=future_bars,
                review_window=f"md-{len(future_bars)}pt",
            )
            outcome["source_refs"] = ["self-review from later 复盘 note prices (close-only; approximate)"]
            reviews.append(outcome)
    return reviews


def _dedup_append(path: Path, records: list[dict[str, Any]], key_fields: tuple[str, ...]) -> int:
    existing = read_records(path) if path.exists() else []
    seen = {tuple(str(r.get(k)) for k in key_fields) for r in existing}
    written = 0
    for rec in records:
        key = tuple(str(rec.get(k)) for k in key_fields)
        if key in seen:
            continue
        append_record(path, rec)
        seen.add(key)
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill journals from existing 复盘 markdown")
    parser.add_argument("--root", default=".", help="Repository root containing the per-code folders (default: .)")
    parser.add_argument("--out-dir", default="data/journal", help="Output directory for the journals (default: data/journal)")
    parser.add_argument("--window", type=int, default=5, help="Max later notes to use as future points per call (default: 5)")
    parser.add_argument("--no-self-review", action="store_true", help="Only write recommendations; skip the offline review synthesis")
    parser.add_argument("--parse-invalidation", action="store_true", help="Also parse invalidation levels from prose (heuristic, noisy; off by default)")
    parser.add_argument("--dry-run", action="store_true", help="Print a summary and write nothing")
    args = parser.parse_args(argv)

    root = Path(args.root)
    recommendations = build_recommendations(root, parse_inval=args.parse_invalidation)
    reviews = [] if args.no_self_review else self_review(recommendations, window=args.window)

    print(f"Parsed {len(recommendations)} recommendation(s) and synthesised {len(reviews)} review(s).")
    by_code: dict[str, int] = {}
    for rec in recommendations:
        by_code[rec["code"]] = by_code.get(rec["code"], 0) + 1
    for code, count in sorted(by_code.items()):
        print(f"  {code}: {count} note(s)")

    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n_rec = _dedup_append(out / "recommendations.jsonl", recommendations, ("code", "timestamp"))
    n_rev = _dedup_append(out / "reviews.jsonl", reviews, ("code", "source_timestamp", "review_window"))
    print(f"Wrote {n_rec} new recommendation(s) → {out / 'recommendations.jsonl'}")
    print(f"Wrote {n_rev} new review(s) → {out / 'reviews.jsonl'}")
    print("Now run: python3 -m tools.stock_skills.cli backtest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
