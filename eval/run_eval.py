"""Evaluation harness. Usage:
  python -m eval.run_eval --manifest eval/manifest.json --mode pipeline
  python -m eval.run_eval --manifest eval/manifest.json --mode baseline     (Muse Spark alone, 8 sampled frames)
Manifest: {"procedure": "eval/procedure.json", "clips": [{"video": "...", "expected": {"s1": "pass", "s2": "fail"}, "tags": ["missing_part"]}]}
Positive class = defect (expected 'fail'). Reports strict (pred fail) and escalated (pred fail or review) precision/recall.

Offline: STEPPROOF_PROVIDER=mock switches get_providers() to the deterministic dataset
providers (clips + sidecars from scripts.make_dataset, never for reported metrics);
PROVIDER_MODE=replay makes the real providers serve the disk cache without any network."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import cv2
from stepproof import config as cfg
from stepproof.pipeline import run_inspection
from stepproof.providers import get_providers
from stepproof.rules import Params
from stepproof.schemas import ProcedureSpec
from stepproof.video import probe, read_frame


def sample_frames(video: Path, out: Path, k: int = 8) -> list[Path]:
    _, n, _, _ = probe(video)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(k):
        idx = min(n - 1, int((i + 0.5) * n / k))
        p = out / f"{video.stem}_{i}.jpg"
        cv2.imwrite(str(p), read_frame(video, idx))
        paths.append(p)
    return paths


def prf(tp: int, fp: int, fn: int):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return p, r




def run_manifest(man: dict, mode: str, seg, vis, limit: int = 0, params: Params | None = None):
    spec_cache: dict[str, ProcedureSpec] = {}
    def spec_for(clip: dict) -> ProcedureSpec:
        p = clip.get("procedure", man["procedure"])
        return spec_cache.setdefault(p, ProcedureSpec.model_validate_json(Path(p).read_text()))
    rows, lat = [], []
    clips = man["clips"][: limit or None]
    for i, clip in enumerate(clips):
        spec = spec_for(clip)
        v = Path(clip["video"])
        t0 = time.time()
        if mode == "pipeline":
            rep = run_inspection(v, spec, seg, vis, f"eval-{i}", params=params or Params())
            pred = {r.step_id: r.verdict for r in rep.results}
        else:
            # sample frames next to the clip so offline (mock) sidecars can be found
            pred = vis.baseline_verdicts(spec, sample_frames(v, v.parent))
        lat.append(time.time() - t0)
        for sid, exp in clip["expected"].items():
            rows.append({"clip": v.name, "step": sid, "expected": exp, "pred": pred.get(sid, "review"), "tags": clip.get("tags", [])})
    def count(flag):
        tp = sum(1 for r in rows if r["expected"] == "fail" and flag(r["pred"]))
        fp = sum(1 for r in rows if r["expected"] != "fail" and flag(r["pred"]))
        fn = sum(1 for r in rows if r["expected"] == "fail" and not flag(r["pred"]))
        return tp, fp, fn
    summary = {"mode": mode, "clips": len(clips), "step_checks": len(rows), "models": {"segmentation": seg.name, "reasoning": vis.name},
               "params": vars(params or Params()),
               "avg_latency_s": round(sum(lat) / max(1, len(lat)), 1),
               "review_rate": round(sum(r["pred"] == "review" for r in rows) / max(1, len(rows)), 3)}
    for label, flag in (("strict", lambda p: p == "fail"), ("escalated", lambda p: p in ("fail", "review"))):
        tp, fp, fn = count(flag)
        p, r = prf(tp, fp, fn)
        summary[label] = {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r}
    out = Path("eval") / f"results_{mode}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    return summary, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--mode", choices=["pipeline", "baseline"], default="pipeline")
    ap.add_argument("--limit", type=int, default=0)
    p = ap.add_argument_group("calibration (tune on dev clips only)")
    p.add_argument("--min-conf", type=float, default=None)
    p.add_argument("--review-conf", type=float, default=None)
    p.add_argument("--stable-frames", type=int, default=None)
    a = ap.parse_args()
    man = json.loads(Path(a.manifest).read_text())
    kw = {k: v for k, v in (("min_conf", a.min_conf), ("review_conf", a.review_conf), ("stable_frames", a.stable_frames)) if v is not None}
    params = Params(**kw) if kw else None
    seg, vis = get_providers()
    summary, _ = run_manifest(man, a.mode, seg, vis, limit=a.limit, params=params)
    print(json.dumps(summary, indent=2))
    print("wrote", f"eval/results_{a.mode}.json")


if __name__ == "__main__":
    main()
