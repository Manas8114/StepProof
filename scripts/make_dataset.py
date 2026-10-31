"""Build a deterministic, fully-offline StepProof dataset.

The Meta Model API is not reachable (401) in this environment and no labelled
footage exists to download, so instead of real clips we *generate* a synthetic
but self-consistent dataset:

* short H.264 MP4 clips where coloured parts appear/disappear on authored
  schedules, so a human watching the clip would see the intended scene;
* a per-clip sidecar ``<clip>.dets.json`` holding the ground-truth detections
  (concept -> present_frames/box/conf), the Muse-alone baseline verdicts and
  the per-step expected verdicts;
* two procedure specs and a unified manifest for the eval harness;
* ``data/stepproof_mock.json`` wiring the offline ``MockSam``/``MockMuse``.

Everything is deterministic (fixed seed) and needs no network. Run:

    python -m scripts.make_dataset            # writes into ./data
    python -m scripts.make_dataset --out DIR  # writes into DIR

The dataset is *synthetic*: it exercises the pipeline, rules, UI and eval
end to end offline, but its numbers must never be presented as measured model
performance. See the README "Known limits / dataset" note.
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
import cv2
import numpy as np

FPS = 10
N = 100  # 10 s

# concept -> BGR colour used when drawing the clip
COLORS = {
    "red connector": (60, 40, 200),
    "black cover": (40, 40, 40),
    "silver screw": (200, 200, 200),
    "blue clip": (230, 140, 40),
    "gold latch": (60, 190, 230),
}
BOXES = {  # concept -> (x1, y1, x2, y2) on a 320x240 frame
    "red connector": (30, 40, 110, 90),
    "black cover": (180, 40, 290, 110),
    "silver screw": (200, 150, 250, 190),
    "blue clip": (40, 140, 130, 200),
    "gold latch": (200, 130, 270, 200),
}
W, H = 320, 240


def _frames(a, b, step=1):
    return list(range(a, b + 1, step))


def draw_concept(frame, concept):
    x1, y1, x2, y2 = BOXES[concept]
    cv2.rectangle(frame, (x1, y1), (x2, y2), COLORS[concept], -1)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 2)
    cv2.putText(frame, concept, (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)


def write_clip(path: Path, presence: dict[str, list[int]], base_noise: int = 0):
    """Write an MJPG clip (H.264 requires a re-encode step; MJPG keeps this dependency-free)."""
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    rng = np.random.RandomState(base_noise % 2**31)  # deterministic texture per clip
    for f in range(N):
        frame = np.full((H, W, 3), 240, np.uint8)
        frame = (frame.astype(np.int16) + rng.randint(0, 12, frame.shape)).astype(np.uint8)  # tiny stable texture
        for concept, present in presence.items():
            if f in present:
                draw_concept(frame, concept)
        vw.write(frame)
    vw.release()


def sidecar(concepts: dict, baseline: dict, expected: dict, tags: list[str]) -> dict:
    """concepts: {concept: {present_frames, conf?, obj_ids?}} (box from BOXES, obj_ids default [0])."""
    return {
        "concepts": {c: {"present_frames": d["present_frames"], "box": BOXES[c],
                         "conf": d.get("conf", 0.9), "obj_ids": d.get("obj_ids", [0])} for c, d in concepts.items()},
        "baseline": baseline,
        "expected": expected,
        "tags": tags,
    }


def main(out: str = "data") -> None:
    root = Path(out)
    clips = root / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    (root / "procedures").mkdir(parents=True, exist_ok=True)
    (root / "manifest").mkdir(parents=True, exist_ok=True)

    # ---- procedure 1: board assembly ----
    p1 = {"name": "Board assembly", "steps": [
        {"id": "s1", "description": "Attach the red connector to the board", "concept": "red connector", "min_count": 1},
        {"id": "s2", "description": "Close the black cover", "concept": "black cover", "min_count": 1, "after": ["s1"]},
        {"id": "s3", "description": "Insert two silver screws", "concept": "silver screw", "min_count": 2, "after": ["s2"]},
    ]}
    (root / "procedures" / "board.json").write_text(json.dumps(p1, indent=2))

    # ---- procedure 2: fastening (second, unrelated domain) ----
    p2 = {"name": "Module fastening", "steps": [
        {"id": "s1", "description": "Snap the blue clip into place", "concept": "blue clip", "min_count": 1},
        {"id": "s2", "description": "Engage the gold latch", "concept": "gold latch", "min_count": 1, "after": ["s1"],
         "state_question": "Is the gold latch engaged?"},
    ]}
    (root / "procedures" / "fastening.json").write_text(json.dumps(p2, indent=2))

    manifest_clips = []

    def add(tag_file, proc, presence, expected, baseline, tags, obj_ids=None, confs=None):
        confs, obj_ids = confs or {}, obj_ids or {}
        concepts = {}
        for c, present in presence.items():
            d = {"present_frames": present}
            if c in confs:
                d["conf"] = confs[c]
            if c in obj_ids:
                d["obj_ids"] = obj_ids[c]
            concepts[c] = d
        sc = sidecar(concepts, baseline, expected, tags)
        write_clip(clips / tag_file, presence, base_noise=hash(tag_file) % 1000)
        (clips / tag_file.replace(".mp4", ".dets.json")).write_text(json.dumps(sc, indent=2))
        manifest_clips.append({"video": (clips / tag_file).as_posix(), "procedure": f"data/procedures/{proc}",
                               "expected": expected, "tags": tags})

    # procedure 1 clips
    add("p1_ok.mp4", "board.json",
        presence={"red connector": _frames(20, 99), "black cover": _frames(40, 99), "silver screw": _frames(60, 99)},
        expected={"s1": "pass", "s2": "pass", "s3": "pass"},
        baseline={"s1": "pass", "s2": "pass", "s3": "pass"},
        tags=["correct"], obj_ids={"silver screw": [1, 2]})
    add("p1_missing_connector.mp4", "board.json",
        presence={"red connector": [], "black cover": _frames(40, 99), "silver screw": _frames(60, 99)},
        expected={"s1": "fail", "s2": "review", "s3": "pass"},
        baseline={"s1": "fail", "s2": "uncertain", "s3": "pass"},
        tags=["missing_part"], obj_ids={"silver screw": [1, 2]})
    add("p1_wrong_order.mp4", "board.json",
        presence={"red connector": _frames(50, 99), "black cover": _frames(20, 99), "silver screw": _frames(60, 99)},
        expected={"s1": "pass", "s2": "fail", "s3": "pass"},
        baseline={"s1": "pass", "s2": "pass", "s3": "pass"},
        tags=["wrong_order"], obj_ids={"silver screw": [1, 2]})
    add("p1_low_conf.mp4", "board.json",
        presence={"red connector": _frames(20, 99), "black cover": [], "silver screw": []},
        expected={"s1": "review", "s2": "fail", "s3": "fail"},
        baseline={"s1": "uncertain", "s2": "fail", "s3": "fail"},
        tags=["ambiguous"], confs={"red connector": 0.55})

    # procedure 2 clips
    add("p2_ok.mp4", "fastening.json",
        presence={"blue clip": _frames(15, 99), "gold latch": _frames(35, 99)},
        expected={"s1": "pass", "s2": "pass"},
        baseline={"s1": "pass", "s2": "uncertain"},
        tags=["correct"])
    add("p2_missing_latch.mp4", "fastening.json",
        presence={"blue clip": _frames(15, 99), "gold latch": []},
        expected={"s1": "pass", "s2": "fail"},
        baseline={"s1": "pass", "s2": "fail"},
        tags=["missing_part"])
    add("p2_flicker.mp4", "fastening.json",
        presence={"blue clip": _frames(15, 99, 2), "gold latch": _frames(40, 99)},
        expected={"s1": "review", "s2": "review"},
        baseline={"s1": "uncertain", "s2": "pass"},
        tags=["ambiguous"])

    (root / "manifest" / "manifest.json").write_text(
        json.dumps({"procedure": "data/procedures/board.json", "clips": manifest_clips}, indent=2))

    mock_cfg = {
        "compile_table": {
            "Attach the red connector, close the cover, insert two screws": p1,
            "Snap the blue clip, then engage the gold latch": p2,
        },
        "state_table": {"Is the gold latch engaged?": {"answer": "yes", "confidence": 0.9, "rationale": "latch visibly seated"}},
    }
    (root / "stepproof_mock.json").write_text(json.dumps(mock_cfg, indent=2))

    n = len(manifest_clips)
    print(f"dataset written to {root}/ : {n} clips, 2 procedures, manifest + mock config.")
    print("clips:", ", ".join(c["video"].split('/')[-1] for c in manifest_clips))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    main(ap.parse_args().out)
