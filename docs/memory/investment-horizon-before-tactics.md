---
name: investment-horizon-before-tactics
description: "Establish the user's holding horizon (short vs mid-term) and leverage before giving stop-loss/tactical advice; they trade unleveraged and mid-term"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7e02d25f-dcfd-4dd6-94a8-75ae45eae779
---

The user pushed back that I defaulted to short-term tight stops (e.g. a −3% technical stop at 48.82 on 小鹏/HK.09868) while they were actually a mid-term, unleveraged holder. I had mirrored their pocket/tactical questions (chased shares, asked about 补仓, intraday, tail rallies) instead of first fixing the frame.

**Why:** Without leverage there is no forced liquidation / margin call, so an unleveraged mid-term holder can sit through normal drawdowns and should use thesis-based stops + a WIDE price backstop, not tight technical stops. Tight stops are a short-term / leveraged-trade construct. Applying them to an unleveraged mid-term core position shakes the holder out before the thesis can play out.

**How to apply:** At the start of a position/analysis, ask (or confirm) the holding horizon and whether leveraged, then match the risk framework: mid-term core → validate on quarterly earnings/fundamentals + wide price backstop; short-term sleeve → tight technical stop. A clean pattern that worked: split one position into a large mid-term **core** (rides through, wide/thesis stop) + a small short-term **波段 sleeve** (tight stop, trades the swings) — see [[xiaopeng-position]]. Also: most retail net profit comes from mid-term holding of winners (captures the trend, avoids overtrading cost/error drag); don't push short-term trading as "higher profit" unless the user has a real edge.
