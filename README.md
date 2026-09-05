# AxionLabs — 3D Bin Packing Fleet Monitor

Streamlit app for 3D truck-loading optimisation with **real Google Gemini
spatial-reasoning analysis** of loading docks (CCTV frame + depth map +
packing plan), an executive fleet dashboard, and anomaly alerting.

## Gemini API configuration

Credentials come from the environment (or a gitignored `.env` file at the
repo root). The key is never hard-coded and never logged.

```dotenv
GEMINI_API_KEY=<your key>
GEMINI_MODEL=gemini-3.5-flash-lite   # exact model ID used for every request
```

On service start-up the app logs:

```
Gemini API configured: YES
Gemini model: gemini-3.5-flash-lite
```

Per request it logs `GEMINI REQUEST` (model, parts, prompt/image sizes) and
`GEMINI RESPONSE` (status, response length, error details on failure).
Transient API failures (429/5xx, capacity overloads) are retried with
exponential backoff; permanent failures fail fast and visibly.

## Provenance contract (no false successes)

Every Gemini analysis result carries a `status`, the `model` used, the exact
`raw_response` text and, on failure, the real `error`:

| status      | meaning                                                        | UI chip        |
|-------------|----------------------------------------------------------------|----------------|
| `SUCCESS`   | real Gemini API reply received (`raw_response` = model output) | LIVE GEMINI    |
| `FAILED`    | request attempted and failed — shown with the real error, raw response stays **empty**, never replaced by simulated data | GEMINI FAILED |
| `SIMULATED` | deterministic local rules (no API key, or mock/demo fleets) — never presented as Gemini output | SIMULATED |

The **Gemini AI Interpretative Audit** panel always shows:

- `GEMINI STATUS: SUCCESS | FAILED | SIMULATED`
- `MODEL USED: <exact model ID>`
- **RAW GEMINI RESPONSE** — the exact, verbatim model output (even when it is
  not clean JSON)
- the real exception/error when a request failed

Structured fields are parsed from the model's reply, but the raw response is
always preserved alongside them.

## Running

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Verification scripts

```powershell
# 1. Pure connectivity proof: text -> Gemini -> raw model text (exit 0 = success)
python verify_gemini.py

# 2. Full-suite tests: logic/provenance tests, end-to-end UI flow (Streamlit
#    AppTest), and a LIVE real-API round-trip through the app pipeline
python test_smoke.py

# 3. Web-UI proof: renders the real app and drives "Run Gemini Spatial Analysis"
#    Pass 1: invalid key  -> UI must show GEMINI STATUS: FAILED (no fake content)
#    Pass 2: real key     -> UI must show GEMINI STATUS: SUCCESS + raw output
python verify_gemini_ui.py

# 4. Virtual rear-CCTV renderer: renders the 3D packing plan from a fixed
#    rear-mounted virtual camera (same code path for Dock 1 live + mock
#    docks); proves determinism (byte-identical PNGs), the rear/elevated
#    pose, the red rear-door strip reference and graceful fallbacks.
#    Artifacts land in assets/virtual_cctv/ for inspection.
python verify_virtual_cctv.py

# 5. Task 4 validation matrix: pure-logic + Streamlit AppTest coverage for
#    the centralized multi-dock scanning workflow (SCAN ALL DOCKS),
#    per-dock CCTV replacement, Dock 1 pre/post-render behavior, Docks 2-4
#    with predetermined twins, per-dock Gemini failure isolation, and
#    the no-staged-anomalies guarantee.
#    NOTE: git ignores test* by default — run directly with `python test_task4_scan_all.py`.
python test_task4_scan_all.py
```

## Task 4 — Centralized Multi-Dock Scanning

The Executive Control Tower now supports a centralized scanning workflow:

### Workflow

1. Operator opens the Executive Dashboard.
2. All four docks are visible, each with its current CCTV image.
3. Operator can **Change CCTV Image** for ANY dock (or multiple docks):
   - preset gallery picker + file uploader
   - updates only the dock's current CCTV input
   - does NOT trigger Gemini
4. Operator presses **SCAN ALL DOCKS**.
5. The system analyzes the current CCTV state of all four docks.
6. Per-dock results flow back to the dashboard; operator can drill in.

### Architecture

**Per-dock CCTV replacement** (`services/cctv_manager.py`)
- Single canonical store: `Fleet.cctv_frame_path` (unchanged).
- `set_dock_cctv(dock_number, path)` → updates the linked fleet, records the
  choice in `st.session_state['cctv_selections']`, stamps
  `DockState.cctv_updated_at`, and does NOT trigger analysis.
- `apply_cctv_selections()` re-applies choices after seeding (seeding would
  otherwise overwrite them with deterministic placeholders).
- `render_cctv_change_control(dock_number)` → reusable widget block
  (selectbox + file uploader in an expander).

**Scan orchestration** (`services/scan_orchestrator.py`)
- `run_scan_all_docks()` processes all four docks sequentially (quota-conscious),
  each in full isolation. A failed Gemini request for one dock NEVER blocks
  the others.
- Each dock's scan: resolve context → CCTV pre-guard (no API call when
  CCTV missing) → `analyze_with_fallback(fleet, virtual_cctv_path=twin)`
  → persist result (success or honest failure) → anomaly/notification.
- `SCAN_ALL_RETRIES` env-tunable per-dock retry budget for honest failures.

**Gemini input structure** (`services/gemini_service.py`)
- PRIMARY: actual CCTV image.
- SECONDARY: virtual digital-twin rear-camera render (when available).
- Request parts are ordered `[prompt, ACTUAL CCTV, VIRTUAL TWIN (if any), depth]`.
- Dock 1 before worker render: no twin → CCTV-only analysis.
- Dock 1 after worker render: worker layout present → twin rendered as
  secondary context.
- Docks 2-4: predetermined mock layout → twin available from the start.
- The prompt was rewritten so CCTV is the primary reasoning target and the
  digital twin is explicitly secondary comparison context.

**Hash-idempotent seeding** (`services/mock_fleet_factory.py`)
- `seed_mock_docks()` is now hash-idempotent: a dock is re-seeded only when
  its JSON layout file's content-hash changed. This preserves operator CCTV
  selections and scan results across ordinary Streamlit reruns while keeping
  the "edit the JSON → see it on next rerun" feature.
- `reseed_mock_docks()` clears the hash cache to force a full reset
  (between rehearsals).

