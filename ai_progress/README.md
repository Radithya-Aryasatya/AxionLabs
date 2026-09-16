# AI Progress Store

This folder persists the Sardine-Can AI solver's learning history and
best-known solutions **across** Streamlit restarts and refreshes.

## Contents

- **`config.json`** — User-toggled solver options (improve enabled, budget, etc.)
- **`history.jsonl`** — One JSON line per packing run (manifest hash, scores, timings)
- **`best_solutions/`** — Best placement list per manifest hash (`{hash}.json`)
- **`learned_weights.json`** — Heuristic strategy win/loss weights, keyed by manifest hash

## Git Policy

All runtime files above are **git-ignored** — only `.gitkeep` and a copy of
this `README.md` are tracked, so the folder structure survives a fresh clone.

## Lifecycle

1. On Streamlit startup, `memory.hydrate_session_state()` bulk-loads all
   persisted data into `st.session_state` caches (`ai_config`, `ai_history`,
   `ai_weights`).
2. When the user runs the Sardine-Can AI engine, each run is appended to
   `history.jsonl`. If it improves on the stored best, `best_solutions/`
   and `learned_weights.json` are updated atomically.
3. The improver reads `learned_weights.json` to prioritise which strategy
   variants to try first for a given manifest — this is how the AI "remembers"
   what worked before.
