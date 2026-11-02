"""Mode C: From-demo / describe skill compiler CLI.
CLI: python -m stepproof.skill.from_demo --demo data/recordings/x.json [--out data/skills/<name>.artifact]
     python -m stepproof.skill.from_demo --describe "file an Acme office expense of $42" [--site http://...]

Models perceive, code decides:
Demo recording turns concrete operator actions into a signed Procedure.
Natural language describe turns prompts into a structured skeleton, explicitly labeled:
"unconfirmed until a verification run passes its checks."
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from ..proc import Procedure, Step, Locator
from ..artifact import sign_procedure, save_artifact
from ..audit import AuditSpine


def from_demo_file(demo_path: Path, out_path: Optional[Path] = None, name: str = "") -> Path:
    """Compile recorded demo JSON into a signed .artifact skill."""
    data = json.loads(demo_path.read_text(encoding="utf-8"))
    raw_steps = data.get("steps", [])
    goal = data.get("goal", f"Task from {demo_path.stem}")
    site = data.get("site", "")

    from ..learn.compile import compile_to_procedure
    proc, warnings = compile_to_procedure(raw_steps, goal, site)
    proc.provenance = {
        "compiler": "stepproof-skill-from-demo",
        "demo_source": str(demo_path),
        "ts": round(time.time(), 3),
    }
    sign_procedure(proc)

    skill_name = name or demo_path.stem
    dest = out_path or (Path("data/skills") / f"{skill_name}.artifact")
    dest.parent.mkdir(parents=True, exist_ok=True)
    save_artifact(proc, dest)

    # Append to audit spine
    spine = AuditSpine()
    spine.append(
        run_id=f"compile_demo_{skill_name}_{int(time.time())}",
        verdict="PASS",
        checks=[],
        steps=[{"step": s.id} for s in proc.steps],
        model_disclosure={"source": "from_demo", "warnings": warnings},
        cost={"kind": "compile_demo"},
    )
    return dest


def from_describe(prompt: str, site: str = "", out_path: Optional[Path] = None, name: str = "") -> Path:
    """Compile natural language description into an unconfirmed signed Procedure skeleton."""
    # Split prompt into simple clauses
    phrases = [p.strip() for p in prompt.replace("then", ",").replace("and", ",").split(",") if p.strip()]
    steps = []
    for i, p in enumerate(phrases, 1):
        action = "click"
        arg = {}
        locs = []
        low = p.lower()
        if any(k in low for k in ("type", "enter", "fill", "write")):
            action = "type"
            val = p.split()[-1] if len(p.split()) > 1 else "value"
            arg = {"text": val}
            locs = [Locator(kind="css", value=f"#input_{i}")]
        elif any(k in low for k in ("click", "press", "submit")):
            action = "click"
            locs = [Locator(kind="text", value=p)]
        else:
            action = "click"
            locs = [Locator(kind="css", value=f"#step_{i}")]

        steps.append(Step(
            id=f"s{i}",
            description=p,
            action=action,
            arg=arg,
            locators=locs,
            vision_concept=p,
        ))

    proc = Procedure(
        goal=prompt,
        site=site,
        steps=steps,
        source="describe_prompt",
        note="UNCONFIRMED: describe-path output is unconfirmed until a verification run passes its checks.",
    )
    proc.provenance = {
        "compiler": "stepproof-skill-from-describe",
        "status": "unconfirmed until a verification run passes its checks",
        "ts": round(time.time(), 3),
    }
    sign_procedure(proc)

    skill_name = name or f"described_{int(time.time())}"
    dest = out_path or (Path("data/skills") / f"{skill_name}.artifact")
    dest.parent.mkdir(parents=True, exist_ok=True)
    save_artifact(proc, dest)

    spine = AuditSpine()
    spine.append(
        run_id=f"compile_describe_{skill_name}_{int(time.time())}",
        verdict="PASS",
        checks=[],
        steps=[{"step": s.id} for s in proc.steps],
        model_disclosure={"source": "from_describe", "unconfirmed": True},
        cost={"kind": "compile_describe"},
    )
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="StepProof Mode C: Skill Compiler CLI")
    parser.add_argument("--demo", type=str, help="Path to demo recording JSON")
    parser.add_argument("--describe", type=str, help="Natural language description of procedure")
    parser.add_argument("--site", type=str, default="", help="Target site URL")
    parser.add_argument("--out", type=str, default="", help="Destination .artifact path")
    parser.add_argument("--name", type=str, default="", help="Skill name")

    args = parser.parse_args()
    out_p = Path(args.out) if args.out else None

    if args.demo:
        dp = Path(args.demo)
        if not dp.is_file():
            print(f"Error: Demo file not found: {dp}", file=sys.stderr)
            sys.exit(1)
        res = from_demo_file(dp, out_path=out_p, name=args.name)
        print(f"Compiled demo to signed artifact: {res}")
    elif args.describe:
        res = from_describe(args.describe, site=args.site, out_path=out_p, name=args.name)
        print(f"Compiled describe prompt to signed artifact: {res}")
        print("Note: Output is labeled 'unconfirmed until a verification run passes its checks.'")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

