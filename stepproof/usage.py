"""Per-call API metering (UNIBOT P1.2b). Records what the system ACTUALLY did, so the
benchmark reports measured numbers, not estimates: model, request count, SAM frames
billed (Meta bills per frame with a 50-frame minimum - that's why trimming/downscaling
clips saves real money), input/output tokens (from the API's `usage` field when
present; SAM responses carry none, so we report 0 and say so), latency, and whether
the result came from the content-hash cache (0 network) or a live call.

Pure code: no model calls, no I/O beyond the optional JSONL sink.
"""
from __future__ import annotations
import json, time, statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class CallRecord:
    model: str
    kind: str                  # sam_video | sam_image | muse_state | muse_compile | muse_agent | ...
    ts: float
    latency_s: float
    frames_returned: int = 0   # SAM: distinct frames in the wire output
    billed_frames: int = 0     # SAM: frames BILLED (meta rule: per-frame, 50-frame minimum)
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False       # served from the content-hash cache -> no network, no billing


class UsageMeter:
    """Thread-safe per-run / per-process meter. Optional JSONL sink for persistence."""

    def __init__(self, sink: Optional[Path] = None) -> None:
        self.calls: list[CallRecord] = []
        self.sink = sink

    def record(self, model: str, kind: str, latency_s: float,
               frames_returned: int = 0, billed_frames: int = 0,
               input_tokens: int = 0, output_tokens: int = 0,
               cached: bool = False) -> CallRecord:
        rec = CallRecord(model=model, kind=kind, ts=time.time(), latency_s=round(latency_s, 3),
                         frames_returned=frames_returned, billed_frames=billed_frames,
                         input_tokens=input_tokens, output_tokens=output_tokens, cached=cached)
        self.calls.append(rec)
        if self.sink:
            self.sink.parent.mkdir(parents=True, exist_ok=True)
            with open(self.sink, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec)) + "\n")
        return rec

    # ---- aggregates (what the report/BENCHMARK.md emits) ----

    @staticmethod
    def latency_stats(latencies: list[float]) -> dict:
        if not latencies:
            return {"median_s": None, "p90_s": None}
        s = sorted(latencies)
        p90 = s[min(len(s) - 1, int(0.9 * len(s)))]
        return {"median_s": round(statistics.median(s), 2), "p90_s": round(p90, 2)}

    def summary(self) -> dict:
        out: dict = {}
        for c in self.calls:
            m = out.setdefault(c.model, {"requests": 0, "cached_hits": 0, "frames_returned": 0,
                                          "billed_frames": 0, "input_tokens": 0, "output_tokens": 0,
                                          "_lat": []})
            m["requests"] += 0 if c.cached else 1        # cached = no network request
            m["cached_hits"] += int(c.cached)
            m["frames_returned"] += c.frames_returned
            m["billed_frames"] += c.billed_frames
            m["input_tokens"] += c.input_tokens
            m["output_tokens"] += c.output_tokens
            if not c.cached:
                m["_lat"].append(c.latency_s)
        for m in out.values():
            lat = self.latency_stats(m.pop("_lat"))
            m["latency"] = lat
        out["total"] = {"calls": len(self.calls),
                        "network_requests": sum(1 for c in self.calls if not c.cached),
                        "billed_frames": sum(c.billed_frames for c in self.calls),
                        "tokens": sum(c.input_tokens + c.output_tokens for c in self.calls)}
        return out

    def cumulative(self) -> dict:
        """The 'cheaper over N runs' number: totals across every recorded call."""
        return {"calls": len(self.calls), "billed_frames": sum(c.billed_frames for c in self.calls),
                "total_tokens": sum(c.input_tokens + c.output_tokens for c in self.calls)}


# module-level active meter: providers record into it when set (benchmark.py / cost meter);
# when None (the default) every recording is a no-op - zero overhead, zero behavior change.
ACTIVE: Optional[UsageMeter] = None


def set_meter(m: Optional[UsageMeter]) -> None:
    global ACTIVE
    ACTIVE = m


def active() -> Optional[UsageMeter]:
    return ACTIVE
