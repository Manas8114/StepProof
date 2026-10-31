"""Evaluation harness. Usage:
  python -m eval.run_eval --manifest eval/manifest.json --mode pipeline
  python -m eval.run_eval --manifest eval/manifest.json --mode baseline     (Muse Spark alone, 8 sampled frames)
Manifest: {"procedure": "eval/procedure.json", "clips": [{"video": "...", "expected": {"s1": "pass", "s2": "fail"}, "tags": ["missing_part"]}]}
Positive class = defect (expected 'fail'). Reports strict (pred fail) and escalated (pred fail or review) precision/recall."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import cv2
from stepproof import config as cfg
from stepproof.pipeline import run_inspection
from stepproof.providers import get_providers
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--mode", choices=["pipeline", "baseline"], default="pipeline")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    man = json.loads(Path(a.manifest).read_text())
    spec = ProcedureSpec.model_validate_json(Path(man["procedure"]).read_text())
    seg, vis = get_providers()
    rows, lat = [], []
    clips = man["clips"][: a.limit or None]
    for i, clip in enumerate(clips):
        v = Path(clip["video"])
        t0 = time.time()
        if a.mode == "pipeline":
            rep = run_inspection(v, spec, seg, vis, f"eval-{i}")
            pred = {r.step_id: r.verdict for r in rep.results}
        else:
            pred = vis.baseline_verdicts(spec, sample_frames(v, cfg.DATA_DIR / "eval_frames"))
        lat.append(time.time() - t0)
        for sid, exp in clip["expected"].items():
            rows.append({"clip": v.name, "step": sid, "expected": exp, "pred": pred.get(sid, "review"), "tags": clip.get("tags", [])})
    def count(flag):
        tp = sum(1 for r in rows if r["expected"] == "fail" and flag(r["pred"]))
        fp = sum(1 for r in rows if r["expected"] != "fail" and flag(r["pred"]))
        fn = sum(1 for r in rows if r["expected"] == "fail" and not flag(r["pred"]))
        return tp, fp, fn
    summary = {"mode": a.mode, "clips": len(clips), "step_checks": len(rows), "models": {"segmentation": seg.name, "reasoning": vis.name},
               "avg_latency_s": round(sum(lat) / max(1, len(lat)), 1),
               "review_rate": round(sum(r["pred"] == "review" for r in rows) / max(1, len(rows)), 3)}
    for label, flag in (("strict", lambda p: p == "fail"), ("escalated", lambda p: p in ("fail", "review"))):
        tp, fp, fn = count(flag)
        p, r = prf(tp, fp, fn)
        summary[label] = {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r}
    out = Path("eval") / f"results_{a.mode}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
