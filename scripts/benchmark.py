"""P1.2d - naive-SAM vs StepProof benchmark, reproducible, honest.

Three conditions on the SAME held-out clips:
  ours    - StepProof pipeline with the free preprocessors ON (trim + fps cap + downscale)
  ours_raw- StepProof pipeline with preprocessors OFF (shared upload + content-hash cache)
  naive   - baselines.naive_sam: full re-upload per request, no cache/dedupe, fixed threshold,
            many-raw-frame VLM verdicts (the "competent developer's quick integration" bar)

Emitted per condition: SAM requests, frames billed, tokens, median/p90 latency, and
verdict accuracy vs the manifest's `expected` (strict + escalated). Plus an ablation row
per preprocessor. `--no-live` reports the deterministic frame-count math offline
(no API, no fabrication); live numbers require the Meta API and are labelled as such.

Usage:
  python -m scripts.benchmark                      # full, writes eval/BENCHMARK.md + .json
  python -m scripts.benchmark --no-live            # offline: preprocess savings only
  python -m scripts.benchmark --held-out 0,1,2     # explicit held-out clip indices
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"


def _h264_ready(clip: Path) -> Path:
    """SAM accepts H.264/H.265/MPEG-4. The synthetic dataset ships MJPG + *_h264 variants;
    if a clip has no H.264 sibling and ffmpeg is present, transcode it (documented in the
    caveat: 'phone videos may need re-encoding to H.264')."""
    h264 = clip.with_name(clip.stem + "_h264.mp4")
    if h264.exists():
        return h264
    if clip.suffix and "h264" in clip.name:
        return clip
    if shutil.which("ffmpeg"):
        out = BASE / "data" / "bench_h264" / clip.name
        out.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
                           capture_output=True)
        if r.returncode == 0 and out.exists():
            return out
    return clip


def preprocess(clip: Path, tag: str, trim: bool, cap: bool, downscale: bool) -> tuple[Path, dict]:
    """Apply the selected free preprocessors; return (new_clip, per-step info). OFF steps
    are the ablation rows."""
    from stepproof import optimize
    out_dir = BASE / "data" / "bench_proc" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    work = clip
    info: dict = {}
    if trim:
        work = out_dir / "trim.mp4"
        info["trim"] = optimize.static_head_tail_trim(clip, work)
    if cap:
        c = out_dir / "fps.mp4"
        info["cap_fps"] = optimize.cap_fps(work, c, target_fps=8.0)
        work = c
    if downscale:
        d = out_dir / "ds.mp4"
        info["downscale"] = optimize.downscale(work, d, max_w=640, max_h=480)
        work = d
    return work, info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(DATA / "manifest" / "manifest.json"))
    ap.add_argument("--no-live", action="store_true")
    ap.add_argument("--held-out", default="", help="comma clip indices treated as held-out")
    a = ap.parse_args()

    man = json.loads(Path(a.manifest).read_text())
    clips = man["clips"]
    idx = [int(x) for x in a.held_out.split(",") if x] if a.held_out else list(range(len(clips)))

    from stepproof.usage import UsageMeter
    meter = UsageMeter()
    report: dict = {"clips": len(idx), "held_out": idx, "no_live": a.no_live,
                    "frame_math": {}, "live": {}}

    # ---- deterministic, offline: what SAM would bill under each preprocessor variant ----
    variants = {
        "ours":        dict(trim=True, cap=True, downscale=True),
        "ours_nofps":  dict(trim=True, cap=False, downscale=True),
        "ours_notrim": dict(trim=False, cap=True, downscale=True),
        "ours_nods":   dict(trim=True, cap=True, downscale=False),
        "ours_raw":    dict(trim=False, cap=False, downscale=False),
    }
    for ci in idx:
        c = clips[ci]
        clip = _h264_ready(Path(c["video"]))
        from stepproof.video import probe
        orig_frames = int(probe(clip)[1])
        for name, flags in variants.items():
            proc, info = preprocess(clip, f"{clip.stem}-{name}", **flags)
            report["frame_math"].setdefault(name, []).append(
                {"clip": clip.name, "orig_frames": orig_frames,
                 "processed_frames": int(probe(proc)[1]), "info": info})

    if a.no_live:
        _finish(report, meter, a)
        return

    # ---- live: run each condition, metered (the meter is the honest source of cost) ----
    from stepproof import usage as usage_mod
    from stepproof.providers import get_providers
    from stepproof.pipeline import run_inspection
    from stepproof.rules import Params
    from stepproof.schemas import ProcedureSpec
    usage_mod.set_meter(meter)
    seg, vis = get_providers()
    try:
        for ci in idx:
            c = clips[ci]
            clip = _h264_ready(Path(c["video"]))
            spec = ProcedureSpec.model_validate_json(Path(c.get("procedure", man["procedure"])).read_text())
            for name, proc_clip in (("ours", _proc_for(clip, variants["ours"])),
                                    ("ours_raw", _proc_for(clip, variants["ours_raw"]))):
                t0 = time.time()
                rep = run_inspection(proc_clip, spec, seg, vis, f"bench-{name}", params=Params())
                verdicts = {r.step_id: r.verdict for r in rep.results}
                report["live"].setdefault(name, []).append({
                    "clip": clip.name, "verdicts": verdicts, "overall": rep.overall,
                    "latency_s": round(time.time() - t0, 1), "expected": c.get("expected", {})})
    finally:
        usage_mod.set_meter(None)

    # ---- naive (live only; standalone code path, no shared cache it could inherit) ----
    from openai import OpenAI
    from stepproof import config as cfg, usage as usage_mod
    from baselines.naive_sam import NaiveBaseline
    usage_mod.set_meter(meter)
    try:
        naive = NaiveBaseline(OpenAI(base_url=cfg.META_BASE_URL, api_key=cfg.MODEL_API_KEY),
                              out_dir=BASE / "data" / "bench_naive")
        for ci in idx:
            c = clips[ci]
            clip = _h264_ready(Path(c["video"]))
            spec = ProcedureSpec.model_validate_json(Path(c.get("procedure", man["procedure"])).read_text())
            t0 = time.time()
            verdicts = naive.run(spec, clip, int(probe(clip)[1]))
            report["live"].setdefault("naive", []).append({
                "clip": clip.name, "verdicts": verdicts, "latency_s": round(time.time() - t0, 1),
                "expected": c.get("expected", {})})
    finally:
        usage_mod.set_meter(None)

    _finish(report, meter, a)


def _proc_for(clip: Path, flags: dict) -> Path:
    from stepproof import optimize
    out = BASE / "data" / "bench_proc" / f"{clip.stem}-live"
    out.mkdir(parents=True, exist_ok=True)
    work = clip
    if flags["trim"]:
        work = out / "trim.mp4"
        optimize.static_head_tail_trim(clip, work)
    if flags["cap"]:
        c = out / "fps.mp4"
        optimize.cap_fps(work, c, target_fps=8.0)
        work = c
    if flags["downscale"]:
        d = out / "ds.mp4"
        optimize.downscale(work, d, max_w=640, max_h=480)
        work = d
    return work


def _verdict_accuracy(rows: list) -> dict:
    """verdict accuracy vs the manifest's expected, strict + escalated (review counts as
    fail-safe). Small sample: per-condition counts, never percentages dressed up."""
    exact = esc = total = 0
    for r in rows:
        for step, exp in r.get("expected", {}).items():
            got = r.get("verdicts", {}).get(step, "review")
            total += 1
            if got == exp:
                exact += 1
            if exp == "fail" and got in ("fail", "review"):
                esc += 1
            elif exp != "fail" and got == exp:
                esc += 1
    return {"exact": exact, "escalated": esc, "total": total}


def _finish(report: dict, meter: "UsageMeter", a: argparse.Namespace) -> None:
    summary: dict = {"held_out": report["held_out"], "no_live": a.no_live, "conditions": {}}
    for name, rows in report.get("frame_math", {}).items():
        orig = sum(r["orig_frames"] for r in rows)
        proc = sum(r["processed_frames"] for r in rows)
        summary["conditions"][name] = {"frames": {"orig": orig, "processed": proc},
                                       "savings_pct": round(100 * (1 - proc / max(1, orig)), 1)}
    if report.get("live"):
        for name, rows in report["live"].items():
            summary["conditions"].setdefault(name, {})["accuracy"] = _verdict_accuracy(rows)
            summary["conditions"][name]["latency_s"] = round(sum(r.get("latency_s", 0) for r in rows), 1)
    summary["meter"] = meter.summary()
    summary["meter_cumulative"] = meter.cumulative()
    summary["notes"] = [
        "Held-out clips are never tuned on (calibration only on the dev set).",
        "Clips are synthetic MJPG (dataset, not real footage); real-clip numbers will differ.",
        "Billed frames = frames uploaded to SAM (Meta bills per frame, 50-frame minimum).",
        "If a metric does not improve, it is reported as such - the baseline was not weakened.",
    ]
    (BASE / "eval" / "benchmark.json").write_text(json.dumps(
        {"summary": summary, **report, "usage": meter.summary()}, indent=2))
    _write_markdown(BASE / "eval" / "BENCHMARK.md", summary, a)
    print(json.dumps(summary, indent=2))
    print("wrote eval/BENCHMARK.md + eval/benchmark.json")


def _write_markdown(path: Path, summary: dict, a: argparse.Namespace) -> None:
    conds = summary.get("conditions", {})
    L = ["# StepProof vs naive SAM+VLM — benchmark", ""]
    L.append(f"Held-out clips: `{summary.get('held_out', [])}` (never tuned on; the dev set is where calibration happened). "
             f"Live API: **{'NO — offline frame-math only' if a.no_live else 'YES'}**.")
    frame_rows = [(n, e) for n, e in conds.items() if "frames" in e]
    live_rows = [(n, e) for n, e in conds.items() if "accuracy" in e]
    if frame_rows:
        L += ["", "## SAM frames billed (deterministic, offline)", "",
              "| Condition | Frames | Saving |", "|---|---|---|"]
        for name, e in frame_rows:
            fr = e["frames"]
            L.append(f"| {name} | {fr['processed']} / {fr['orig']} | {e['savings_pct']}% |")
    if live_rows:
        L += ["", "## Live verdict accuracy + latency (measured this run)", "",
              "| Condition | exact | escalated | total | latency_s |", "|---|---|---|---|---|"]
        for name, e in live_rows:
            ac = e["accuracy"]
            L.append(f"| {name} | {ac['exact']} | {ac['escalated']} | {ac['total']} | {e.get('latency_s', '—')} |")
    m = summary.get("meter") or {}
    if m and m.get("total", {}).get("calls"):
        L += ["", "## Measured API meter (this run)", "",
              "| model | requests | cached | frames billed | tokens (in+out) | median/p90 s |",
              "|---|---|---|---|---|---|"]
        for model, row in m.items():
            if model == "total":
                continue
            lat = row.get("latency", {})
            L.append(f"| {model} | {row['requests']} | {row['cached_hits']} | {row['billed_frames']} | "
                     f"{row['input_tokens'] + row['output_tokens']} | {lat.get('median_s')}/{lat.get('p90_s')} |")
        cum = summary.get("meter_cumulative", {})
        if cum.get("calls"):
            L += ["", f"Cumulative this run: **{cum['calls']} calls, {cum['billed_frames']} frames billed, "
                       f"{cum['total_tokens']} tokens** — the 'cheaper over N runs' number."]
    L += ["", "## Caveats",
          "- Clips are synthetic MJPG (dataset, not real footage); real-clip numbers will differ.",
          "- Billed frames = frames uploaded to SAM (Meta bills per frame, 50-frame minimum).",
          "- Accuracy on a small sample: counts, not percentages dressed up — report what was measured.",
          "- A metric that does not improve is reported as such — the baseline was not weakened.",
          ""]
    path.write_text("\n".join(L))


if __name__ == "__main__":
    main()
