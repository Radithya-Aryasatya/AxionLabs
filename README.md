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
```

