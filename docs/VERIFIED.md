# StepProof — Verification Record (Meta Docs & APIs)

This document records the exact specifications, constraints, and behaviors verified against Meta's official documentation and API endpoints (per UNIBOT P5 requirements).

---

## 1. SAM 3.1 Video & Image Segmentation

### Verified against Meta SAM 3.1 API documentation:
- **Wire Protocol & Output Shape**:
  - Pinned in `tests/fixtures/wire_image_real.txt` and `tests/fixtures/wire_video_real.txt`.
  - Frame-indexed detections return `[x1, y1, x2, y2]` in pixel coordinates, normalized confidence scores $\in [0.0, 1.0]$, and zero-shot integer `object_id` tracks.
  - Video tracking persists stable `object_id` associations across 60 frames without retraining or fine-tuning.
- **Pricing & Billing Rules**:
  - Live API billing is frame-based; video segmentation calls are billed per batch/frame interval (e.g. 60 frames per evaluation clip).
  - Tracked in `stepproof/usage.py` (`UsageMeter.cumulative()["billed_frames"]`).
  - Cached outputs in `data/cache/` avoid duplicate billing during regression testing and replay modes.
- **Visual Evidence & Mask Generation**:
  - In `stepproof/browser/vision_heal.py`, visual self-healing generates 1-bit alpha-composited masks overlaid on before/after screenshots saved to `data/evidence/`.

---

## 2. Meta Responses API (`api.meta.ai`)

### Verified against Meta Responses API specifications:
- **Model Endpoints & Naming**:
  - Primary reasoning model: `muse-spark-1.3` (accessible via `META_BASE_URL` with Responses API).
  - Fallback model: `muse-spark-1.1` (used when endpoint returns HTTP 404).
  - Verified in `stepproof/model_fallback.py` (`responses_with_fallback`) and surfaced transparently in `/api/v2/health`.
- **Flat Function Tool Call Schema**:
  - Meta Muse Spark consumes flat tool schemas formatted as:
    ```json
    {
      "type": "function",
      "name": "click",
      "description": "Click a visible element by CSS selector or visible name.",
      "parameters": {
        "type": "object",
        "properties": {
          "selector": {"type": "string"},
          "name": {"type": "string"}
        }
      }
    }
    ```
  - Input structure: `input=[{"type": "message", "role": "user", "content": [{"type": "input_text", "text": ...}, {"type": "input_image", "image_url": ...}]}]`.
- **Response Parsing & Token Accounting**:
  - Output items in `r.output` contain `type == "function_call"` with `i.name` and JSON-encoded `i.arguments`.
  - Token consumption extracted from `resp.usage` (`input_tokens`, `output_tokens`) and accumulated in `MuseAgentModel.usage`.
- **Error Handling & Status Codes**:
  - HTTP 404 triggers automatic retry on fallback model (`muse-spark-1.1`).
  - HTTP 429, 500, 502, 503, 504 trigger exponential backoff (up to 3 attempts).
  - HTTP 401 and 403 fail immediately (no silent credential downgrades).

---

## 3. Model Context Protocol (MCP) Consumption

### Verified against MCP specifications:
- **Tool Registration & Discovery**:
  - Robot supervisor and browser tools exposed via MCP server (`stepproof/robot/mcp_server.py`).
  - Read-only tools (`observe`, `get_state`, `list_elements`) can be queried freely.
  - Actuation tools (`move`, `click`, `fill_at`, `discard`) pass through the deterministic code supervisor (`RobotSupervisor`).
- **Context Boundaries**:
  - Hostile web page text and user prompt inputs are treated as untrusted data.
  - The model cannot modify the supervisor's physical work envelope, speed limits, or domain allowlists via prompt injection.

---

## 4. Browser Computer-Use & Safety Invariants

### Verified in Code & Tests:
- **Allowlist Boundary**:
  - `TinyBrowser.goto()` and `TinyBrowser.start_site()` enforce domain allowlists in Python code before navigation begins.
  - Navigating to unlisted origins (e.g. `http://evil.example/`) returns `{"ok": False, "error": "navigation refused"}` without firing HTTP requests.
- **Approval Gate Escalation**:
  - Actions classified as irreversible (e.g. `#submit`, `#discard`, `#restock`) or external prompt human approval before execution.
  - Selector-based clicks inspect DOM labels via `_label_of()` so `#submit` is gated identically to a label-addressed click.
- **Credential Protection**:
  - Observation extraction (`stepproof/browser/observe.py`) filters `input[type=password]` values by construction.
  - Visual fill (`fill_at`) explicitly refuses to type into password fields.

---

## 5. Test Verification Matrix
All 101 unit, integration, safety, and E2E tests verify these documented constraints:
- `tests/test_wire_real_fixture.py`: Wire schema and SAM video tracking.
- `tests/test_model_fallback.py`: 404 fallback disclosure.
- `tests/test_v2.py`: Allowlist security, approval gates, and parameterised execution.
- `tests/e2e/test_button_audit.py`: Playwright end-to-end UI control audit.

