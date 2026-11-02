"""Naive SAM+VLM baseline (UNIBOT P1.2a). The bar our pipeline is benchmarked against.

Everything here is intentionally the thing a competent developer writes QUICKLY -
not a weakened strawman:
  * uploads the FULL clip at native fps + resolution on EVERY SAM request (no shared
    upload, no content-hash cache, no dedupe - so re-using a concept re-uploads),
  * one SAM request per concept PER STEP occurrence (no cross-step dedupe),
  * counts objects per frame with a single fixed confidence threshold (no calibration,
    no geometry / region rejection, no temporal smoothing),
  * judges each state step with a VLM prompt fed MANY raw frames.
The only shared code is the deterministic verdict math (count-in-range + ordering),
which every approach must use (ground rule: models perceive, code decides).
"""
from .naive_sam import NaiveBaseline, naive_segment, naive_count, naive_vlm_verdicts
