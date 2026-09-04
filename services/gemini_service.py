"""
services/gemini_service.py
===========================
Gemini API multimodal service for spatial reasoning.

Consumes:
  - CCTV RGB frame
  - Depth Map (Depth Anything V2)
  - 3D Bin Packing Plan metadata/rendering
  - Manifest constraints (fragile flags, total expected volume)

LIVE vs SIMULATED — hard contract (no false successes):
  - When GEMINI_API_KEY is configured and the google-genai SDK is importable,
    every result comes from a REAL Gemini API call and carries
    status="SUCCESS", the exact `raw_response` text and the `model` used.
  - If the real request fails, the result carries status="FAILED" with the
    real error message and an EMPTY raw_response. It is NEVER replaced by a
    simulated analysis.
  - The deterministic simulation engine is used ONLY when no API key/SDK is
    available, and is always labelled status="SIMULATED". It must never be
    presented as live Gemini output.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from dataclasses import fields as dc_fields, MISSING
from typing import Dict, Any, Optional

# Keep third-party HTTP/SDK chatter quiet; our own GEMINI REQUEST/RESPONSE
# logs are the ones operators need to see.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

log = logging.getLogger("gemini_service")

# Result lifecycle status values (provenance contract)
STATUS_SUCCESS = "SUCCESS"      # real Gemini API returned content
STATUS_FAILED = "FAILED"        # real attempt made, error occurred (raw empty)
STATUS_SIMULATED = "SIMULATED"  # no API available -> deterministic fallback


@dataclass(init=False)
class GeminiAnalysisResult:
    """
    Result of a Gemini spatial-reasoning analysis.

    Provenance fields (filled honestly, always):
      status:        SUCCESS | FAILED | SIMULATED
      model:         exact Gemini model ID used for the request
      raw_response:  the EXACT text returned by Gemini ("" when none exists)
      error:         exception/error detail when status == FAILED
      extra:         any additional structured fields Gemini returned
    """

    anomaly_type: str = "NONE"
    severity: str = "NONE"
    confidence: float = 0.0
    analysis_paragraph: str = ""
    affected_items: list = field(default_factory=list)
    recommended_actions: list = field(default_factory=list)
    spatial_discrepancy_score: float = 0.0
    status: str = ""
    model: str = ""
    raw_response: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)

    def __init__(self, **kwargs):
        # Assign known fields; collect unknown kwargs into `extra` so that
        # additional Gemini output is preserved instead of crashing.
        leftover = dict(kwargs)
        for f in dc_fields(self):
            if f.name in leftover:
                setattr(self, f.name, leftover.pop(f.name))
            elif f.default_factory is not MISSING:
                setattr(self, f.name, f.default_factory())
            elif f.default is not MISSING:
                setattr(self, f.name, f.default)
        if leftover:
            self.extra.update(leftover)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'GeminiAnalysisResult':
        return cls(**data)

    @property
    def is_live_gemini(self) -> bool:
        """True ONLY when a real Gemini response was received."""
        return self.status == STATUS_SUCCESS and bool(self.raw_response)


class GeminiService:
    """
    Handles multimodal spatial reasoning by sending CCTV footage,
    depth maps, and 3D packing plan metadata to the Gemini API.

    Configuration (environment / .env):
      GEMINI_API_KEY   API key (required for live calls)
      GEMINI_MODEL     exact model ID to request — never silently swapped
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self._client = None
        self._initialized = False
        # Explicit, documented SIMULATION / FALLBACK mode: forces the labelled
        # deterministic engine even when a key exists. Results are ALWAYS
        # tagged status=SIMULATED and never presented as live Gemini output.
        self.simulation_mode = os.getenv(
            "GEMINI_SIMULATION", ""
        ).strip().lower() in ("1", "true", "yes", "on")

        # Explicit startup diagnostics (the key itself is NEVER logged).
        log.info("Gemini API configured: %s", "YES" if self.api_key else "NO")
        log.info("Gemini model: %s", self.model)
        if self.simulation_mode:
            log.info(
                "Gemini SIMULATION MODE enabled via GEMINI_SIMULATION — "
                "all results will be labelled SIMULATED, not live."
            )

        if self.api_key:
            self._init_client()

    def _init_client(self):
        """Initialize the Gemini API client (google-genai SDK)."""
        try:
            from google import genai
            from google.genai import types
            # Bound each attempt to 60s; transient 429/5xx conditions are
            # handled by the retry ladder in _generate(), so a stalled
            # request can never hang the pipeline indefinitely.
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=60000),
            )
            self._initialized = True
            log.info("Gemini client initialised (google-genai SDK).")
        except ImportError as e:
            self._initialized = False
            log.error(
                "google-genai SDK not importable — live Gemini disabled "
                "(install with: python -m pip install google-genai). %s", e
            )

    # --- PUBLIC API ---

    def analyze_loading(
        self,
        cctv_frame_path: str,
        depth_map_path: str,
        packing_plan: Dict[str, Any],
        manifest: Dict[str, Any],
        fleet_state: Dict[str, Any],
    ) -> GeminiAnalysisResult:
        """
        Main analysis method: sends multimodal input to the Gemini API
        for spatial reasoning and anomaly detection.

        NO silent fallback: if the real API call fails, the returned result
        has status="FAILED" plus the real error and an empty raw_response.
        The simulation engine only runs when no API key/SDK is available (or
        GEMINI_SIMULATION=1 is explicitly set), and is labelled
        status="SIMULATED".
        """
        if self._initialized and self._client and not self.simulation_mode:
            return self._call_gemini_api(
                cctv_frame_path, depth_map_path, packing_plan, manifest, fleet_state
            )
        result = self._simulate_analysis(
            cctv_frame_path, depth_map_path, packing_plan, manifest, fleet_state
        )
        result.status = STATUS_SIMULATED
        result.model = self.model
        result.extra["provenance"] = (
            "SIMULATION / FALLBACK — deterministic local rules, NOT live Gemini output"
        )
        return result

    def detect_departure_risk(
        self,
        cctv_frame_path: str,
        depth_map_path: str,
        previous_analysis: GeminiAnalysisResult,
        fleet_state: Dict[str, Any],
    ) -> GeminiAnalysisResult:
        """
        Analyzes whether the truck is attempting to depart with
        unresolved anomalies (Scenario 2: CRITICAL).
        """
        if self._initialized and self._client and not self.simulation_mode:
            return self._call_gemini_departure_api(
                cctv_frame_path, depth_map_path, previous_analysis, fleet_state
            )
        result = self._simulate_departure_detection(
            cctv_frame_path, depth_map_path, previous_analysis, fleet_state
        )
        result.status = STATUS_SIMULATED
        result.model = self.model
        result.extra["provenance"] = (
            "SIMULATION / FALLBACK — deterministic local rules, NOT live Gemini output"
        )
        return result

    def verify_raw(self, text: str) -> str:
        """
        Pure text -> Gemini -> raw text. Verification/debug path that proves
        genuine connectivity without any structured parsing in the way.
        Raises on failure so callers can display the real error.
        """
        log.info(
            "GEMINI REQUEST -> model=%s | prompt_chars=%d | text-only verification | request started",
            self.model, len(text),
        )
        try:
            raw = self._generate([text])
        except Exception as e:
            log.error(
                "GEMINI RESPONSE <- model=%s | Status: FAILED | request failed | %s: %s",
                self.model, type(e).__name__, e,
            )
            raise
        log.info(
            "GEMINI RESPONSE <- model=%s | Status: SUCCESS | response length: %d chars | request completed successfully",
            self.model, len(raw),
        )
        return raw

    # --- REAL GEMINI API PATH (google-genai SDK) ---

    def _load_image_part(self, path: str):
        """
        Load an image file as a google.genai Part. Returns None when the path
        is empty or the file is missing (never fabricates image data).
        """
        if not path:
            return None
        from google.genai import types
        if not os.path.isfile(path):
            log.warning("Image file not found, sending without it: %s", path)
            return None
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "bmp": "image/bmp"}.get(ext, "image/png")
        with open(path, "rb") as fh:
            data = fh.read()
        return types.Part.from_bytes(data=data, mime_type=mime)

    def _request_debug(self, parts) -> str:
        """Safe request summary for logs — never includes the API key."""
        desc = []
        for p in parts:
            if isinstance(p, str):
                desc.append(f"text({len(p)} chars)")
            else:
                inline = getattr(p, "inline_data", None)
                mime = getattr(inline, "mime_type", "?")
                size = len(getattr(inline, "data", b"") or b"")
                desc.append(f"{mime}({size} bytes)")
        return " | ".join(desc) if desc else "(empty request)"

    def _generate(self, parts, config=None) -> str:
        """
        Low-level REAL Gemini call via the google-genai SDK.
        Returns the exact text content returned by the model.
        Raises RuntimeError when the SDK is missing or the response has no text.
        """
        if not self._client:
            raise RuntimeError("Gemini client is not initialised (no API key?)")

        log.info("GEMINI REQUEST -> Model: %s | request started", self.model)
        log.info("GEMINI REQUEST -> Parts: %s", self._request_debug(parts))

        # Transient server-side failures (429/500/502/503 — rate limits and
        # "high demand" overloads) are retried with exponential backoff.
        # This is real error handling; failures are never masked.
        import time
        max_retries = 4
        attempt = 0
        while True:
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=parts, config=config
                )
                break
            except Exception as e:
                transient = self._is_transient_error(e)
                if transient and attempt < max_retries:
                    wait_s = 2.0 * (2 ** attempt)  # 2s, 4s, 8s, 16s
                    attempt += 1
                    log.warning(
                        "GEMINI REQUEST -> transient failure (attempt %d/%d), "
                        "retrying in %.0fs | %s: %.300s",
                        attempt, max_retries, wait_s, type(e).__name__, e,
                    )
                    time.sleep(wait_s)
                    continue
                log.error(
                    "GEMINI RESPONSE <- Model: %s | Status: FAILED | request failed | "
                    "%s: %s", self.model, type(e).__name__, e,
                )
                raise

        raw = getattr(response, "text", None)
        if not raw:
            # Surface finish/blocked reasons instead of pretending success.
            detail = ""
            try:
                cand = response.candidates[0]
                detail = f"finish_reason={cand.finish_reason}"
            except Exception:
                detail = "no candidates in response"
            log.error(
                "GEMINI RESPONSE <- Model: %s | Status: FAILED | empty response (%s)",
                self.model, detail,
            )
            raise RuntimeError(f"Gemini returned no text content ({detail})")

        log.info(
            "GEMINI RESPONSE <- Model: %s | Status: SUCCESS | response received | "
            "length: %d chars", self.model, len(raw),
        )
        return raw

    @staticmethod
    def _is_transient_error(e: Exception) -> bool:
        """
        True for retryable server-side conditions: rate limits and
        capacity overloads (HTTP 429/500/502/503, RESOURCE_EXHAUSTED,
        UNAVAILABLE). Non-transient errors (invalid key, malformed
        request) must fail fast and visibly.
        """
        code = getattr(e, "code", None) or getattr(e, "status_code", None)
        try:
            if int(code) in (429, 500, 502, 503):
                return True
        except (TypeError, ValueError):
            pass
        msg = str(e).upper()
        return any(sig in msg for sig in (
            "UNAVAILABLE", "RESOURCE_EXHAUSTED", "OVERLOADED",
            "RATE_LIMIT", "INTERNAL_ERROR", " 503", " 429", " 504",
            "HIGH DEMAND", "TRY AGAIN LATER", "DEADLINE_EXCEEDED",
        ))

    def _extract_json(self, text: str) -> Optional[dict]:
        """
        Tolerant JSON extraction: strips markdown fences and grabs the first
        balanced {...} block. Returns None when nothing parseable exists —
        the raw text is always preserved by the caller regardless.
        """
        cleaned = text.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if fence:
            cleaned = fence.group(1).strip()
        start = cleaned.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        return None
        return None

    def _finalize_success(self, raw: str) -> GeminiAnalysisResult:
        """
        Build a SUCCESS result from the raw Gemini text. The raw response is
        ALWAYS preserved verbatim in raw_response; structured fields are
        parsed best-effort so the rest of the app can act on them. A parse
        failure never discards the raw text.
        """
        parsed = self._extract_json(raw)
        if parsed is None:
            log.warning(
                "Gemini response was not parseable JSON — keeping raw text as "
                "the analysis paragraph (structured fields left at defaults)."
            )
            return GeminiAnalysisResult(
                analysis_paragraph=raw,
                status=STATUS_SUCCESS,
                model=self.model,
                raw_response=raw,
                extra={"parse_error": "response was not valid JSON"},
            )
        known = {"anomaly_type", "severity", "confidence", "analysis_paragraph",
                 "affected_items", "recommended_actions",
                 "spatial_discrepancy_score"}
        core = {k: parsed[k] for k in known if k in parsed}
        extra = {k: v for k, v in parsed.items() if k not in known}
        if not core.get("analysis_paragraph"):
            # Keep the model's voice even when it skipped the paragraph field.
            core["analysis_paragraph"] = raw
        return GeminiAnalysisResult(
            status=STATUS_SUCCESS,
            model=self.model,
            raw_response=raw,
            extra=extra,
            **core,
        )

    def _failed_result(self, exc: Exception) -> GeminiAnalysisResult:
        """FAILED result carrying the real error. raw stays EMPTY — no fake data."""
        return GeminiAnalysisResult(
            anomaly_type="OTHER",
            severity="NONE",
            confidence=0.0,
            analysis_paragraph="",
            status=STATUS_FAILED,
            model=self.model,
            raw_response="",
            error=f"{type(exc).__name__}: {exc}",
        )

    def _call_gemini_api(
        self, cctv_frame_path, depth_map_path, packing_plan, manifest, fleet_state
    ) -> GeminiAnalysisResult:
        """REAL Gemini multimodal analysis: CCTV + depth + plan metadata."""
        prompt = self._build_spatial_reasoning_prompt(packing_plan, manifest, fleet_state)
        parts = [prompt]
        cctv_part = self._load_image_part(cctv_frame_path)
        depth_part = self._load_image_part(depth_map_path)
        if cctv_part:
            parts.append(cctv_part)
        if depth_part:
            parts.append(depth_part)

        log.info(
            "GEMINI REQUEST\n  Model: %s\n  Text prompt length: %d chars\n"
            "  CCTV image: %s\n  Depth image: %s",
            self.model, len(prompt),
            "PRESENT" if cctv_part else "ABSENT",
            "PRESENT" if depth_part else "ABSENT",
        )
        try:
            raw = self._generate(parts)
        except Exception as e:
            return self._failed_result(e)
        log.info(
            "GEMINI RESPONSE\n  Model: %s\n  Status: SUCCESS\n  Response length: %d chars",
            self.model, len(raw),
        )
        return self._finalize_success(raw)

    def _call_gemini_departure_api(
        self, cctv_frame_path, depth_map_path, previous_analysis, fleet_state
    ) -> GeminiAnalysisResult:
        """REAL Gemini departure-risk analysis (Scenario 2)."""
        prompt = self._build_departure_prompt(previous_analysis, fleet_state)
        parts = [prompt]
        cctv_part = self._load_image_part(cctv_frame_path)
        depth_part = self._load_image_part(depth_map_path)
        if cctv_part:
            parts.append(cctv_part)
        if depth_part:
            parts.append(depth_part)

        log.info(
            "GEMINI REQUEST\n  Model: %s\n  Text prompt length: %d chars\n"
            "  CCTV image: %s\n  Depth image: %s\n  Request type: departure-risk",
            self.model, len(prompt),
            "PRESENT" if cctv_part else "ABSENT",
            "PRESENT" if depth_part else "ABSENT",
        )
        try:
            raw = self._generate(parts)
        except Exception as e:
            return self._failed_result(e)
        log.info(
            "GEMINI RESPONSE\n  Model: %s\n  Status: SUCCESS\n  Response length: %d chars",
            self.model, len(raw),
        )
        return self._finalize_success(raw)

    # --- PROMPT BUILDERS ---

    def _build_spatial_reasoning_prompt(
        self, packing_plan: Dict, manifest: Dict, fleet_state: Dict
    ) -> str:
        layout = packing_plan.get('layout', {})
        packed = layout.get('packed_items', [])
        manifest_summary = packing_plan.get('manifest_summary', [])
        fragile_items = [item['name'] for item in manifest_summary if item.get('fragile')]
        heavy_items = [p for p in packed if p.get('weight', 0) > 100]

        return f"""
You are an automated warehouse loading quality inspector AI.

TASK: Compare the live CCTV footage against the optimal 3D bin packing plan
      and identify spatial discrepancies, unstable stacking, safety risks, or misalignment between the images.

PACKING PLAN METADATA:
- Total items packed: {len(packed)}
- Fill percentage: {packing_plan.get('fill_percentage', 'N/A')}%
- Fragile items in manifest: {fragile_items if fragile_items else 'None'}
- Heavy items (>100kg): {[p['part_number'] for p in heavy_items] if heavy_items else 'None'}

MANIFEST SUMMARY:
{json.dumps(manifest_summary, indent=2, default=str)}

FLEET STATE:
- Loading in progress: {fleet_state.get('loading_in_progress', True)}
- Rear doors status: {'Open' if fleet_state.get('loading_in_progress', True) else 'Closing'}
- Dock engaged: {fleet_state.get('loading_in_progress', True)}

ANALYZE FOR:
1. Spatial misalignment - items not in planned positions
2. Unstable stacking - tilted items, structural voids, hollows
3. Weight distribution violations - heavy boxes stacked over fragile items
4. Layout discrepancy between plan and reality

OUTPUT STRICT JSON:
{{
  "anomaly_type": "MESSY_STACKING" | "NONE" | "OTHER",
  "severity": "WARNING" | "CRITICAL" | "NONE",
  "confidence": 0.0-1.0,
  "analysis_paragraph": "Detailed narrative explaining why the physical stack is unsafe...",
  "affected_items": ["list of item identifiers"],
  "recommended_actions": ["actionable steps"],
  "spatial_discrepancy_score": 0.0-1.0
}}
"""

    def _build_departure_prompt(
        self, previous: GeminiAnalysisResult, fleet_state: Dict
    ) -> str:
        return f"""
You are a warehouse departure safety inspector AI.

TASK: Determine if the truck is attempting to depart while carrying
      unresolved loading anomalies.

PREVIOUS ANALYSIS:
- Anomaly type: {previous.anomaly_type}
- Severity: {previous.severity}
- Confidence: {previous.confidence}

FLEET STATE:
- Doors closing: {fleet_state.get('doors_closing', False)}
- Truck moving: {fleet_state.get('truck_moving', False)}
- Loading in progress: {fleet_state.get('loading_in_progress', False)}

VISUAL CUES TO CHECK IN CCTV:
1. Rear doors closing or fully closed
2. Truck beginning to disengage from docking bay
3. Loading dock leveler retracting
4. Vehicle movement away from dock

OUTPUT STRICT JSON:
{{
  "anomaly_type": "UNRESOLVED_DEPARTURE_RISK" | "NONE",
  "severity": "CRITICAL" | "NONE",
  "confidence": 0.0-1.0,
  "analysis_paragraph": "Detailed warning about uncorrected anomaly during departure...",
  "affected_items": [],
  "recommended_actions": [],
  "spatial_discrepancy_score": 0.0-1.0
}}
"""

    # --- SIMULATION ENGINE (fallback when no API key) ---

    _SIM_LABEL = "[OFFLINE SIMULATION - NOT a live Gemini response] "

    def _simulate_analysis(
        self, cctv_frame_path, depth_map_path,
        packing_plan, manifest, fleet_state
    ) -> GeminiAnalysisResult:
        """
        Deterministic offline simulation, EXPLICITLY labelled so it can never
        be mistaken for a live Gemini response. Used only when no API key/SDK
        is available.
        """
        result = self._simulate_analysis_raw(
            cctv_frame_path, depth_map_path, packing_plan, manifest, fleet_state
        )
        result.analysis_paragraph = self._SIM_LABEL + result.analysis_paragraph
        result.status = STATUS_SIMULATED
        result.model = self.model
        result.extra["provenance"] = (
            "SIMULATION / FALLBACK — deterministic local rules, NOT live Gemini output"
        )
        return result

    def _simulate_analysis_raw(
        self, cctv_frame_path, depth_map_path,
        packing_plan, manifest, fleet_state
    ) -> GeminiAnalysisResult:
        """
        Simulates Gemini analysis based on deterministic rules derived from
        the fleet state and packing data. Produces realistic, reproducible
        results for demo purposes.
        """
        layout = packing_plan.get('layout', {})
        packed = layout.get('packed_items', [])
        manifest_summary = packing_plan.get('manifest_summary', [])
        fill_pct = packing_plan.get('fill_percentage', 0.0)

        has_fragile = any(item.get('fragile') for item in manifest_summary)
        loading_in_progress = fleet_state.get('loading_in_progress', True)

        # Check for heavy-over-fragile stacking
        heavy_items = [p for p in packed if p.get('weight', 0) > 100]
        fragile_items = [p for p in packed if p.get('fragile')]
        heavy_over_fragile = False

        if heavy_items and fragile_items:
            for heavy in heavy_items:
                for fragile in fragile_items:
                    hp = heavy.get('position', [0, 0, 0])
                    fp = fragile.get('position', [0, 0, 0])
                    if hp[1] > fp[1]:
                        heavy_over_fragile = True
                        break
                if heavy_over_fragile:
                    break

        # Compute simulated spatial discrepancy score
        discrepancy = 0.0
        if heavy_over_fragile:
            discrepancy += 0.35
        if fill_pct < 50:
            discrepancy += 0.25
        if heavy_items and len(heavy_items) > len(packed) * 0.3:
            discrepancy += 0.20
        discrepancy = min(1.0, discrepancy)

        if discrepancy >= 0.4 and loading_in_progress:
            return GeminiAnalysisResult(
                anomaly_type="MESSY_STACKING",
                severity="WARNING",
                confidence=round(0.75 + (discrepancy - 0.4) * 0.5, 2),
                analysis_paragraph=self._generate_messy_stacking_paragraph(
                    heavy_over_fragile, fill_pct, len(heavy_items), has_fragile
                ),
                affected_items=[p['part_number'] for p in heavy_items[:3]] +
                               [p['part_number'] for p in fragile_items[:2]],
                recommended_actions=[
                    "Redistribute heavy items to the bottom of the truck",
                    "Place fragile items on top, away from heavy boxes",
                    "Ensure stable stacking with no overhangs",
                    "Pause loading and re-inspect the current configuration",
                ],
                spatial_discrepancy_score=round(discrepancy, 3),
            )

        if discrepancy > 0.0:
            return GeminiAnalysisResult(
                anomaly_type="MESSY_STACKING",
                severity="WARNING",
                confidence=round(0.6 + discrepancy * 0.2, 2),
                analysis_paragraph=self._generate_mild_discrepancy_paragraph(
                    fill_pct, has_fragile, heavy_over_fragile
                ),
                affected_items=[],
                recommended_actions=[
                    "Monitor stacking pattern during continued loading",
                    "Proceed with caution",
                ],
                spatial_discrepancy_score=round(discrepancy, 3),
            )

        return GeminiAnalysisResult(
            anomaly_type="NONE",
            severity="NONE",
            confidence=0.95,
            analysis_paragraph=(
                "The live CCTV footage and depth map align well with the optimal "
                "3D bin packing plan. No significant spatial discrepancies detected. "
                "Stacking appears stable and efficient."
            ),
            affected_items=[],
            recommended_actions=[],
            spatial_discrepancy_score=0.0,
        )

    def _simulate_departure_raw(
        self,
        cctv_frame_path: str,
        depth_map_path: str,
        previous: GeminiAnalysisResult,
        fleet_state: Dict[str, Any],
    ) -> GeminiAnalysisResult:
        """
        Simulates departure risk detection.
        Scenario 2 triggers if there's an unresolved WARNING and departure cues
        are detected.
        """
        doors_closing = fleet_state.get('doors_closing', False)
        truck_moving = fleet_state.get('truck_moving', False)
        has_unresolved_warning = (
            previous.severity == "WARNING" and
            fleet_state.get('anomaly_unresolved', False)
        )

        if (doors_closing or truck_moving) and has_unresolved_warning:
            return GeminiAnalysisResult(
                anomaly_type="UNRESOLVED_DEPARTURE_RISK",
                severity="CRITICAL",
                confidence=0.92,
                analysis_paragraph=self._generate_departure_paragraph(
                    doors_closing, truck_moving, previous
                ),
                affected_items=previous.affected_items,
                recommended_actions=[
                    "BLOCK departure immediately",
                    "Require manager manual override",
                    "Re-inspect cargo before allowing departure",
                    "Document the incident in fleet log",
                ],
                spatial_discrepancy_score=previous.spatial_discrepancy_score,
            )

        return GeminiAnalysisResult(
            anomaly_type="NONE",
            severity="NONE",
            confidence=0.95,
            analysis_paragraph=(
                "No departure risk detected. The truck is not exhibiting "
                "departure cues, or all prior anomalies have been resolved."
            ),
            affected_items=[],
            recommended_actions=[],
            spatial_discrepancy_score=0.0,
        )

    def _simulate_departure_detection(
        self,
        cctv_frame_path: str,
        depth_map_path: str,
        previous: GeminiAnalysisResult,
        fleet_state: Dict[str, Any],
    ) -> GeminiAnalysisResult:
        """Offline departure-risk simulation, explicitly labelled (see above)."""
        result = self._simulate_departure_raw(
            cctv_frame_path, depth_map_path, previous, fleet_state
        )
        result.analysis_paragraph = self._SIM_LABEL + result.analysis_paragraph
        result.status = STATUS_SIMULATED
        result.model = self.model
        result.extra["provenance"] = (
            "SIMULATION / FALLBACK — deterministic local rules, NOT live Gemini output"
        )
        return result

    # --- PARAGRAPH GENERATORS ---

    def _generate_messy_stacking_paragraph(
        self, heavy_over_fragile, fill_pct, heavy_count, has_fragile
    ) -> str:
        parts = []
        parts.append(
            "The Gemini spatial analysis comparing the live CCTV feed against "
            "the 3D bin packing plan reveals significant discrepancies in the "
            "current load configuration."
        )

        if heavy_over_fragile:
            parts.append(
                f"Critically, {heavy_count} heavy cargo items are positioned "
                "above fragile items in a manner that violates structural safety "
                "protocols. The weight distribution shows heavy boxes stacked "
                "directly on top of fragile cargo, creating a high risk of "
                "crushing damage during transit."
            )

        if fill_pct < 50:
            parts.append(
                f"The volumetric fill rate is only {fill_pct:.1f}%, indicating "
                "that the truck is severely underfilled. This creates instability "
                "due to insufficient cargo-to-cargo contact and potential shifting."
            )

        parts.append(
            "Visual inspection of the depth map confirms spatial voids and "
            "tilted stacking patterns that deviate from the optimal layout. "
            "Recommended immediate actions include pausing the loading process, "
            "redistributing heavy items to the truck floor, and re-positioning "
            "fragile items on top with proper separation."
        )

        return " ".join(parts)

    def _generate_mild_discrepancy_paragraph(
        self, fill_pct, has_fragile, heavy_over_fragile
    ) -> str:
        base = (
            f"The live CCTV feed shows minor deviations from the 3D packing plan. "
            f"Fill rate is at {fill_pct:.1f}%. While not immediately hazardous, "
            "there are subtle stacking inefficiencies that warrant continued "
            "monitoring as loading progresses. "
        )
        if has_fragile:
            base += "Fragile item placement should be verified. "
        if heavy_over_fragile:
            base += "Heavy-over-fragile stacking detected — adjust positioning. "
        return base.strip()

    def _generate_departure_paragraph(
        self, doors_closing, truck_moving, previous
    ) -> str:
        cues = []
        if doors_closing:
            cues.append("rear doors are detected closing")
        if truck_moving:
            cues.append("vehicle movement away from the docking bay")
        cue_str = " and ".join(cues) if cues else "departure cues detected"

        return (
            f"CRITICAL: An unresolved loading anomaly (severity: {previous.severity}, "
            f"confidence: {previous.confidence:.0%}) remains uncorrected as the "
            f"system detects that the {cue_str}. The truck is attempting to depart "
            "with a messy, unstable, or severely underfilled cargo configuration.\n\n"
            "OPERATIONAL RISKS:\n"
            "1. Transit Collapse Hazard - unstable stacking may shift during transit.\n"
            "2. Severe Space Waste - inefficient packing increases costs.\n"
            "3. Safety Violation - heavy-over-fragile stacking creates liability.\n\n"
            "RECOMMENDED ACTION: Block departure until a qualified inspector "
            "re-evaluates the cargo configuration. Manager manual override required."
        )

    # NOTE: The former "REAL API CALLS" implementations of _call_gemini_api /
    # _call_gemini_departure_api defined here were removed. They crashed on
    # missing images, swallowed every exception with a bare `except Exception`
    # and silently returned _simulate_analysis() output — i.e. simulated data
    # presented as live Gemini results. The real implementations now live
    # directly above (see "--- REAL GEMINI API PATH ---"): they log the exact
    # request/response, preserve the raw model text, and return
    # status="FAILED" with the real error instead of ever faking success.