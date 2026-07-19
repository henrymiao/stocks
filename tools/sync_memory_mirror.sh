#!/bin/sh
# Mirror Claude's session memory into the repo so the auto-committer backs it up.
# Source of truth is the live memory directory; docs/memory/ is a read-only copy —
# edits made in docs/memory/ are overwritten on the next sync and never reach sessions.
set -eu
SRC="$HOME/.claude/projects/-Users-allglitter-codes-stocks/memory"
DST="$(cd "$(dirname "$0")/.." && pwd)/docs/memory"
mkdir -p "$DST"
cp "$SRC"/*.md "$DST"/
echo "memory mirror synced: $(ls "$SRC"/*.md | wc -l | tr -d ' ') files -> docs/memory/"
