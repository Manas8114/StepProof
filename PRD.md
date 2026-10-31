# StepProof: Product Requirements Document

**Hackathon:** Meta Global AI Developer Hackathon. Submission due **Nov 4, 9:00 PM ET** (= Nov 5, 7:30 AM IST). Internal cutoff: submit by **Nov 4, 2:00 PM ET**.
**Themes targeted:** "Push the Frontier" (manufacturing, scientific experiments, physical systems) and "Build for Your World".
**Models:** SAM 3.1 (segmentation and tracking) and Muse Spark 1.3 (reasoning) on Meta Model API.

## 1. One-line pitch
Describe any manual procedure in one sentence; StepProof compiles it into a checkable spec, watches the video with SAM 3.1, and returns an evidence-backed pass / fail / needs-review report. **No training data per part or task.**

## 2. Problem
Verifying that a manual procedure was done correctly (assembly, lab protocol, kit packing, repair) either relies on a human watching or on vision systems that need a labelled dataset and an engineer for every new part. Both are slow to set up and hard to audit.

## 3. Differentiator (why this can win)
1. **Zero-shot setup.** Open-vocabulary concept segmentation (SAM 3.1) plus a language model that compiles plain English into rules. A new inspection takes minutes, not a dataset.
2. **Honest reliability.** Models perceive; deterministic code decides. Uncertain cases are escalated, never guessed. We publish measured precision/recall, including failures.
3. **Generality shown, not claimed.** The demo runs the *same code* on two unrelated procedures (hardware assembly and a second domain) with no retraining.
4. **Ablation.** We report Muse Spark alone (sampled frames) vs the full pipeline on the same clips.

## 4. Users and jobs
- **Quality or process engineer:** "Prove this step happened, in this order, with evidence."
- **Lab or workshop lead:** "Check protocol compliance from a recording."
- **Judge (primary audience for the demo):** see it work on an unseen clip in about 90 seconds.

## 5. Scope
**In (MVP, must ship):** FR-1 to FR-9 below.
**Stretch (only after MVP is green):** PDF/HTML export, live camera, mask overlays (P1), multi-station dashboard.
**Out:** autonomous robots, auth/multi-tenant, audio, fine-tuning, cloud deployment beyond a single machine.

## 6. Functional requirements
| ID | Requirement | Acceptance test |
|---|---|---|
| FR-1 | Compile plain-English text to a `ProcedureSpec` (steps, `concept`, counts, `after`, optional `state_question`) with schema-constrained output and server-side sanitising | Spec for the demo sentences validates; list-style or negated concepts are reduced and warned |
| FR-2 | Upload a clip (MP4/MOV H.264/H.265) and run an inspection asynchronously with progress and clear errors | Inspection reaches `done` or `error` with a readable reason |
| FR-3 | One SAM 3.1 request per distinct concept, in parallel; wire output parsed per frame with confidences and stable object ids | `tests/test_wire.py` passes; zero matches treated as a normal result |
| FR-4 | Deterministic rules: count range stable over N frames, still true at end (unless `persist=false`), ordering via `after`, low confidence or flicker means `review` | `tests/test_rules.py` passes |
| FR-5 | Optional state checks (Muse Spark, schema-constrained yes/no/uncertain) run only on steps that need them, on a cropped evidence frame | `uncertain` or low confidence escalates to `review` |
| FR-6 | Report: per-step verdict, reasons, first-satisfied timestamp, evidence images with boxes, model names used | Every non-pass verdict has at least one human-readable reason |
| FR-7 | Web UI: compile, edit-view steps, save, upload, live overlay on video, per-step swimlane timeline (click to seek), evidence cards, reviewer confirm pass/fail | Manual walkthrough in under 2 minutes |
| FR-8 | Replay mode: disk cache of raw SAM text and Muse JSON so the demo is reproducible and credits are not burned twice | `PROVIDER_MODE=replay` runs the demo with no network |
| FR-9 | Evaluation harness: per-step precision/recall (strict and escalated), review rate, latency; `pipeline` and `baseline` modes | `python -m eval.run_eval` writes `eval/results_*.json` |

## 7. Non-functional requirements
- Processing time per 20-30 s clip: target under 90 s with 3-4 concepts (measure and report; do not promise).
- Secrets only via `.env`; never logged or committed.
- Every external call has timeout, bounded retry (429/5xx/network only; never retry 400/401/403/404) and a clear surfaced error.
- Model substitution (e.g. gateway for Muse Spark) must be visible in the UI (`/api/health`, report `models`) and the README.

## 8. Architecture
```
Clip -> OpenCV probe -> SAM 3.1 (1 request per concept, parallel, cached)
     -> wire parser -> per-concept detections -> deterministic rules engine
     -> (only if needed) Muse Spark state check on cropped evidence frame
     -> Report (verdicts, reasons, evidence) -> SQLite -> FastAPI -> static UI
Natural language -> Muse Spark (JSON schema) -> sanitise -> ProcedureSpec
```
Provider interfaces (`SegmentationProvider`, `VisionProvider`) isolate every model call. The rules engine takes plain data and never calls a model.

## 9. Rule semantics (authoritative)
- `ok[f]` is true when the confident-detection count for the step's concept is in `[min_count, max_count]`.
- **Satisfied** = `ok` holds for `stable_frames` consecutive frames; first such frame is the step's time.
- `fail`: never `ok`; or not `ok` for most of the final `tail_frac` of the video when `persist=true`; or happened before a prerequisite; or state check answered `no`.
- `review`: flicker (ok but never stable), confidence below `review_conf`, simultaneous with prerequisite, prerequisite never satisfied, state `uncertain` or low confidence.
- Overall = worst step verdict. Human review can override a `review` step only.

## 10. SAM 3.1 constraints that shape the design (verified in Meta docs)
Concept prompt must be one short concrete noun phrase; lists, commands, negation and spatial phrases are unreliable; one concept per request; video tracks at most 16 objects per frame; video is billed per frame (min 50); MP4/MOV with H.264/H.265/MPEG-4 only. Therefore: choose large, distinct, colour-coded parts; express "missing" as a count of 0 satisfied; express order through timestamps, not prompts.

## 11. Evaluation plan
- 2 procedures x about 10 clips each (target 20 total; do not claim more than you filmed).
- Clip types: correct, missing part, wrong order, wrong placement, ambiguous/occluded.
- Report per step: strict and escalated precision/recall, review rate, average latency; pipeline vs Muse-alone baseline. Publish failures with a one-line cause.
- Do not tune thresholds on the clips you report; hold out at least 6 clips.

## 12. Demo script (90 s)
1. (10 s) Type the procedure sentence; click Compile; steps appear.
2. (25 s) Upload a clip with a deliberately missing part; overlay tracks parts; swimlanes fill.
3. (20 s) Report: failed step with timestamp, evidence frame and reason.
4. (15 s) Upload a second clip in a different domain, new sentence, no code change.
5. (20 s) Evaluation slide: baseline vs pipeline numbers, plus one honest failure.

## 13. Risks and mitigations
| Risk | Mitigation |
|---|---|
| Account cannot reach a model | `scripts.smoke_test` first, tonight; ask on hackathon Discord; gateway fallback for Muse Spark only, disclosed |
| SAM misses small parts | Large, colour-distinct parts; fixed camera; confidence and review escalation |
| Credits or rate limits | Disk cache, bounded concurrency, short clips |
| Scope creep | MVP list in section 5; stretch only when tests and eval are green |
| Phone video rotation or codec | Re-encode: `ffmpeg -i in.mov -c:v libx264 -movflags +faststart out.mp4` |

## 14. Milestones (ET)
- **Oct 31 (tonight):** smoke test green, SAM checkpoint request (optional), read Official Rules, film clips.
- **Nov 1:** image to SAM to rules working end to end on real clips; API access proven.
- **Nov 2:** video tracking pipeline, compiler, second domain, UI wired.
- **Nov 3:** evaluation and baseline run, fix top failure modes, record demo.
- **Nov 4:** README, architecture diagram, submission assets; **submit by 2:00 PM ET.**

## 15. Submission checklist
Official Rules read; track chosen per rules; public repo with README and `.env.example`; demo video; evaluation results with failures; model/provider disclosure; links verified in a logged-out browser.
