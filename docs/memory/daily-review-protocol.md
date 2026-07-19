---
name: daily-review-protocol
description: "How to run the daily watchlist 复盘 cheaply — batch-scan into one table, report only deltas, don't re-derive per stock"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7e02d25f-dcfd-4dd6-94a8-75ae45eae779
---

The user wants daily 复盘 to cover the whole (now ~41-name) watchlist without burning tokens re-analysing each name in prose.

**How to apply — the cheap loop:**
0. **First, feed the evidence loop** (agreed 2026-07-18): run `python3 -m tools.stock_skills.cli review --window 5d` at the start of each 复盘 while OpenD is up. It is idempotent (skips already-reviewed code+timestamp+window triples) and fault-tolerant (one failed fetch no longer aborts the run), so running it every session is safe and usually cheap. Without this the journals go stale and backtest/evidence-optimize starve.
1. Run `python3 tools/stock_skills/scan_watchlist.py` (add `--tag defensive|robotics|index|cyclical…`, `--market HK|US|SH|SZ|CC`, or `--codes a,b,c` to scan a subset). It batch-runs the engine per code and prints ONE compact table (code / label / total / trend·capital·fundamental / price / stop). The heavy OpenD fetching stays inside that command, so only the small table returns.
2. **Report only deltas and triggers**, not full prose per stock: label/score changes vs last look, a gate breach, or price hitting a level stored in the plan docs. Silent names = "no change", skip them.
3. **Reference the stored theses/levels instead of re-deriving them**: `portfolio/allocation-plan-2026-07-03.md` (target weights, layers) and `xiaopeng/xiaopeng-midterm-holding-checklist.md` (小鹏 three gates + levels). Dated 复盘 notes live in `xiaopeng/`.

4. **End of session: run `sh tools/sync_memory_mirror.sh`** — mirrors the live memory into `docs/memory/` so the user's auto-commit+push backs it up off-machine (agreed 2026-07-18). Live memory stays the source of truth; the mirror is disaster recovery.

**Why:** re-fetching each name in conversational prose is the main token cost; a batch table + delta-only reporting covers more stocks for far fewer tokens. **Key data caveat:** capital/sector feeds blank out pre-open/holiday and can flip labels — prefer completed-session data and state the timestamp (see [[investment-horizon-before-tactics]]). Reconfirm live holdings before acting.
