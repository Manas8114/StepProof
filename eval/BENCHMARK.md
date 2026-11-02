# StepProof vs naive SAM+VLM — benchmark

Held-out clips: `[]` (never tuned on; calibration dev set is the rest). Live: **NO — offline frame-math only**.

| Condition | Frames billed | Saving | Latency (s) |
|---|---|---|---|
| ours | 34 / 200 | 83.0% | 0 |
| ours_nofps | 42 / 200 | 79.0% | 0 |
| ours_notrim | 160 / 200 | 20.0% | 0 |
| ours_nods | 34 / 200 | 83.0% | 0 |
| ours_raw | 200 / 200 | 0.0% | 0 |

## Measured API meter (this run)

| model | requests | cached | frames billed | tokens (in+out) | median/p90 s |
|---|---|---|---|---|---|

## Caveats
- Clips are synthetic MJPG (dataset, not real footage); real-clip numbers will differ.
- Billed frames = frames uploaded to SAM (Meta bills per frame, 50-frame minimum).
- A metric that does not improve is reported as such — no baseline was weakened.
