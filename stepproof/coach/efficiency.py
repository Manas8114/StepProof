"""Deterministic efficiency detectors. Pure code over run metrics (never the model) -
the model only phrases the resulting suggestion (coach.voice / agent.model.suggest).
Each detector returns {"what", "why", "expected_saving", "risk"} where it matches.
A saving is only ever reported when the detector measured it."""
from __future__ import annotations
import json
from collections import Counter


def _tool_of(a) -> str:
    """Actions arrive two ways: full step dicts {"tool","args",...} (agent loop metrics)
    or bare tool-name strings (executor healed-step metrics, tour snapshots). Normalize."""
    return a.get("tool", "") if isinstance(a, dict) else str(a)


def _url_of(a) -> object:
    if not isinstance(a, dict) or _tool_of(a) != "goto":
        return None
    args = a.get("args")
    if isinstance(args, dict) and "url" in args:
        return args["url"]
    return a.get("url")



def run_detectors(metrics: dict, human_demo: dict | None = None) -> list[dict]:
    out: list[dict] = []
    actions = metrics.get("actions", [])
    n = len(actions)
    if not n:
        return out

    # 1. repeated identical action (same tool+args back to back)
    for i in range(1, n):
        a, b = actions[i - 1], actions[i]
        if a == b:
            label = json.dumps(b) if isinstance(b, dict) else b
            out.append(_msg("repeated action", f"{label} issued twice in a row (step {i})",
                           "1 step", "low", "drop the duplicate"))
            break

    # 2. redundant navigation: same URL visited more than once (needs dict actions with args)
    urls = [u for u in (_url_of(a) for a in actions) if u is not None]
    if len(urls) > 1:
        c = Counter(json.dumps(u, sort_keys=True) for u in urls)
        dup = [v for v in c.values() if v > 1]
        if dup:
            out.append(_msg("redundant navigation", f"same page opened {max(dup)}x",
                           f"{sum(dup) - 1} step", "low", "skip the repeated goto"))

    # 3. avoidable wait: consecutive wait actions
    waits = sum(1 for a in actions if _tool_of(a) == "wait")
    if waits > 2:
        out.append(_msg("avoidable wait", f"{waits} wait steps", "1-2 steps", "low", "merge or drop waits"))

    # 4. backtrack: revisiting a page/state (goto then goto-back)
    for i in range(2, len(urls)):
        if urls[i] == urls[i - 2]:
            out.append(_msg("backtrack", "page revisited after moving on", "1-2 steps", "medium",
                           "fix the step that forced the return"))
            break

    # 5. more steps than the human demo
    if human_demo is not None:
        hd = human_demo.get("steps", 0)
        if n > hd:
            saving = n - hd
            out.append(_msg("steps above human baseline",
                           f"{n} steps vs human {hd}", f"{saving} steps", "medium",
                           "apply an accepted suggestion and re-verify success"))
        elif n < hd and metrics.get("result", {}).get("success"):
            out.append(_msg("faster than human", f"{n} steps vs human {hd}",
                           f"{hd - n} steps", "low", "keep this path"))
    return out[:6]  # bounded; most-detects first


def compare_runs(agent: dict, human_demo: dict | None) -> dict:
    """The compare view payload: agent vs human on steps + time. Human demo may be None."""
    return {
        "agent": {"steps": agent.get("steps", 0), "wall_s": agent.get("wall_s"),
                  "model_calls": agent.get("model_calls"), "success": bool(agent.get("result", {}).get("success"))},
        "human": {"steps": human_demo.get("steps") if human_demo else None,
                  "wall_s": human_demo.get("wall_s") if human_demo else None,
                  "takeovers": human_demo.get("takeovers") if human_demo else None},
        "agent_beat_human": bool(human_demo and agent.get("steps", 1) <= human_demo.get("steps", float("inf"))),
    }


def _msg(what: str, why: str, expected_saving: str, risk: str, apply_hint: str) -> dict:
    return {"what": what, "why": why, "expected_saving": expected_saving, "risk": risk, "apply": apply_hint}


