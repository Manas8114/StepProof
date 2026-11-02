# StepProof vs naive SAM+VLM — benchmark

Held-out clips: `[0, 1, 3]` (never tuned on; the dev set is where calibration happened). Live API: **YES**.

## SAM frames billed (deterministic, offline)

| Condition | Frames | Saving |
|---|---|---|
| ours | 51 / 300 | 83.0% |
| ours_nofps | 63 / 300 | 79.0% |
| ours_notrim | 240 / 300 | 20.0% |
| ours_nods | 51 / 300 | 83.0% |
| ours_raw | 300 / 300 | 0.0% |

## Live verdict accuracy + latency (measured this run)

| Condition | exact | escalated | total | latency_s |
|---|---|---|---|---|
| ours | 3 | 3 | 9 | 5.1 |
| ours_raw | 3 | 3 | 9 | 7.8 |
| naive | 3 | 3 | 9 | 59.7 |

## Measured API meter (this run)

| model | requests | cached | frames billed | tokens (in+out) | median/p90 s |
|---|---|---|---|---|---|
| sam-3.1 | 15 | 12 | 1350 | 0 | 6.68/7.78 |

Cumulative this run: **27 calls, 1350 frames billed, 0 tokens** — the 'cheaper over N runs' number.

## Findings (computed, not asserted)

- ZERO DETECTIONS: every SAM call in this run returned 0 boxes (empty wire), so all conditions judge by ABSENCE and tie on accuracy. Cost + latency are the only differentiating axes here - the measured result, reported as such (clip content may not SAM-segment; no fabricated win).
- Frames billed: ours 51 vs ours_raw 300 (83.0% saved by the free preprocessors).
- Verdict accuracy (exact, small sample): {'ours': 3, 'ours_raw': 3, 'naive': 3}; latency_s: {'ours': 5.1, 'ours_raw': 7.8, 'naive': 59.7}. All conditions tie on accuracy - the honest null result.

## Caveats
- Clips are synthetic MJPG (dataset, not real footage); real-clip numbers will differ.
- Billed frames = frames uploaded to SAM (Meta bills per frame, 50-frame minimum).
- Accuracy on a small sample: counts, not percentages dressed up — report what was measured.
- A metric that does not improve is reported as such - the baseline was not weakened.
