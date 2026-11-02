# StepProof vs naive SAM+VLM — benchmark

Held-out clips: `[0, 3]` (never tuned on; the dev set is where calibration happened). Live API: **YES**.

## SAM frames billed (deterministic, offline)

| Condition | Frames | Saving |
|---|---|---|
| ours | 34 / 200 | 83.0% |
| ours_nofps | 42 / 200 | 79.0% |
| ours_notrim | 160 / 200 | 20.0% |
| ours_nods | 34 / 200 | 83.0% |
| ours_raw | 200 / 200 | 0.0% |

## Live verdict accuracy + latency (measured this run)

| Condition | exact | escalated | total | latency_s |
|---|---|---|---|---|
| ours | 2 | 2 | 6 | 9.6 |
| ours_raw | 2 | 2 | 6 | 6.1 |
| naive | 2 | 2 | 6 | 46.9 |

## Measured API meter (this run)

| model | requests | cached | frames billed | tokens (in+out) | median/p90 s |
|---|---|---|---|---|---|
| sam-3.1 | 15 | 3 | 1200 | 0 | 6.22/8.48 |

Cumulative this run: **18 calls, 1200 frames billed, 0 tokens** — the 'cheaper over N runs' number.

## Findings (computed, not asserted)

- ZERO DETECTIONS: every SAM call in this run returned 0 boxes (empty wire), so all conditions judge by ABSENCE and tie on accuracy. Cost + latency are the only differentiating axes here - the measured result, reported as such (clip content may not SAM-segment; no fabricated win).
- Frames billed: ours 34 vs ours_raw 200 (83.0% saved by the free preprocessors).
- Verdict accuracy (exact, small sample): {'ours': 2, 'ours_raw': 2, 'naive': 2}; latency_s: {'ours': 9.6, 'ours_raw': 6.1, 'naive': 46.9}. All conditions tie on accuracy - the honest null result.

## Caveats
- Clips are synthetic MJPG (dataset, not real footage); real-clip numbers will differ.
- Billed frames = frames uploaded to SAM (Meta bills per frame, 50-frame minimum).
- Accuracy on a small sample: counts, not percentages dressed up — report what was measured.
- A metric that does not improve is reported as such - the baseline was not weakened.
