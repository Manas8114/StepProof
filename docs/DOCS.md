# StepProof — Docs index

Read in this order:

1. **`README.md`** (repo root) — what it is, quick start, v2 modes, disclosures, known limits.
2. **`docs/ARCHITECTURE.md`** — the two execution paths, component map, and the safety model.
3. **`docs/USAGE.md`** — how to set up and actually run it (UI modes, headless scripts, eval).
4. **`eval/RESULTS.md`** — the measured numbers: completion, safety, live agent, and the
   vision-self-heal experiment (an honest negative result).
5. **`SUBMISSION_CHECKLIST.md`** — v1 (A–D) + v2 (V–X) state, launch-video status, honesty rules.
6. **`AGENT_PROMPT.md`** / **`PRD.md`** — the originating specs (v2 master prompt supersedes where they conflict).

## Evidence artifacts (reproducible)
| File | What it is |
|---|---|
| `eval/results_v2.json` | completion + safety + condition matrix (offline B/C, live A when available) |
| `eval/live_agent_v2.json` | one live goal-only agent run (DONE, 4 actions, 13.0 s, gate on Submit) |
| `eval/live_agent_trace.json` | a dated full event trace of a live agent run |
| `eval/vision_heal_results.json` | the CUT vision-self-heal experiment (5/12, 41.7% < 70%) |
| `data/tour_runs/<date>.json` | dated, replayable guided-tour recordings |
| `brag-output/brag-plan.md` | the `/brag` launch-video plan + storyboard |
| `brag-output/share-copy.txt` | the launch-video share copy |
| `brag-output/brag.mp4` + `brag.jpg` | **the rendered launch video** (20 s) with its baked frame-0 poster |
| `brag-output/composition/` | the Hyperframes composition (re-render with `npx hyperframes check && npx hyperframes render`) |

## One-line project summary
StepProof v2 is a browser "procedure companion": **learn** a task by watching, **do** it with the
human in charge, and **verify** it with deterministic code — the model perceives, code decides.
Four UI modes (Monitor / Execute / Coach / Tour), sandboxed tiny browser, code-first safety
gates, an injection-resistant allowlist, voice, and a fully offline evaluation + showcase tour.
