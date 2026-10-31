"""Parser for SAM 3.1 special-token output (dev.meta.ai/docs/sam/reading-segmentation).

Line:  <Nf>id<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|><|mask;...;data=H,W,<enc>payload|>,id<|box;...
Notes: frames may skip or be unordered; ids are sparse; the mask payload is base85 and can contain '|', '>', '!', '~',
       so records are split on the *next record start* (",<digits><|box;"), never on '|>'.
"""
from __future__ import annotations
import re
from .schemas import Detection

_FRAME_SPLIT = re.compile(r"(?=<\d+f>)")
_FRAME = re.compile(r"^<(\d+)f>")
_REC_SPLIT = re.compile(r",(?=\d+<\|box;)")
_REC = re.compile(r"^(\d+)<\|box;([^|]*)\|>(?:<\|mask;(.*)\|>)?$", re.S)


def _kv(s: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in s.split(";") if "=" in p)


def parse_wire(text: str) -> list[Detection]:
    out: list[Detection] = []
    for chunk in _FRAME_SPLIT.split(text.strip()):
        chunk = chunk.strip()
        m = _FRAME.match(chunk)
        if not m:
            continue
        frame = int(m.group(1))
        for rec in _REC_SPLIT.split(chunk[m.end():]):
            rm = _REC.match(rec.strip())
            if not rm:
                continue
            kv = _kv(rm.group(2))
            try:
                box = (int(kv["x1"]), int(kv["y1"]), int(kv["x2"]), int(kv["y2"]))
            except (KeyError, ValueError):
                continue
            out.append(Detection(
                frame=frame, obj_id=int(rm.group(1)), box=box,
                conf=float(kv["c"]) if "c" in kv else None,
                w=int(kv.get("w", 0)), h=int(kv.get("h", 0)), mask=rm.group(3),
            ))
    return out
