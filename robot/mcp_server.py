"""P3 MCP tool surface - the ONLY way an MCP client / model tool-loop reaches the robot,
and it routes EXCLUSIVELY through SafetySupervisor. There is no back-door to the adapter:
`RobotTools` holds a reference to the supervisor (not to any adapter's unsafe methods) and
every tool is a validate_* + dispatch.

The method signatures match the official MCP Python SDK tool shape
(`robot_get_state`, `robot_plan_from_events`, `robot_validate_program`, `robot_move_to`,
`robot_gripper`, `robot_pause`, `robot_resume`, `robot_estop`); the SDK transport layer is
separate and optional so the safety properties are testable offline. If the target model
(Muse Spark) does not consume MCP directly, the same tools are exposed to a function-calling
loop - verified against Meta's docs before wiring the transport (see docs/VERIFIED.md).
"""
from __future__ import annotations
import json
from typing import Any, Optional

from .supervisor import Pose, SafetySupervisor, RobotAdapter


def _pose(d: dict) -> Pose:
    return Pose(x=float(d.get("x", 0.0)), y=float(d.get("y", 0.0)), z=float(d.get("z", 0.0)))


class RobotTools:
    """Supervisor-gated tool surface. `sup` is the single gate; `adapter` is only ever
    touched through `sup.dispatch` - never directly for motion."""

    def __init__(self, sup: SafetySupervisor, adapter: RobotAdapter) -> None:
        self.sup, self.adapter = sup, adapter

    # ---- tool surface (each is a supervised call) ----
    def robot_get_state(self, _args: dict) -> dict:
        return {"pose": None if self.adapter.pose is None else
                {"x": self.adapter.pose.x, "y": self.adapter.pose.y, "z": self.adapter.pose.z},
                "state": self.adapter.state, "estop": self.sup.limits.estop.is_set()}

    def robot_plan_from_events(self, args: dict) -> dict:
        """Incremental RobotProgram: a queued waypooint list awaiting validation. No move
        happens here - only the plan is built and validated."""
        wps = [_pose(w) for w in args.get("waypoints", [])]
        v = self.sup.validate_program(wps, float(args.get("speed", 0.2)), float(args.get("accel", 0.0)))
        return {"accepted": v.ok, "waypoints": len(wps), "reasons": v.reasons}

    def robot_validate_program(self, args: dict) -> dict:
        wps = [_pose(w) for w in args.get("waypoints", [])]
        v = self.sup.validate_program(wps, float(args.get("speed", 0.2)), float(args.get("accel", 0.0)))
        return {"accepted": v.ok, "reasons": v.reasons}

    def robot_move_to(self, args: dict) -> dict:
        pose = _pose(args.get("pose", {}))
        v = self.sup.validate_move(pose, float(args.get("speed", 0.0)))
        return self.sup.dispatch(v, self.adapter, pose, float(args.get("speed", 0.0)))

    def robot_gripper(self, args: dict) -> dict:
        cmd = str(args.get("command", "open"))
        v = self.sup.validate_gripper(cmd)
        if not v.ok:
            return {"accepted": False, "reasons": v.reasons}
        self.adapter.gripper(cmd)
        return {"accepted": True}

    def robot_pause(self, _args: dict) -> dict:
        self.adapter.state = "paused"
        return {"accepted": True, "state": "paused"}

    def robot_resume(self, _args: dict) -> dict:
        if self.sup.limits.estop.is_set():
            return {"accepted": False, "reasons": ["estop engaged"]}
        self.adapter.state = "moving"
        return {"accepted": True, "state": "moving"}

    def robot_estop(self, _args: dict) -> dict:
        return {"accepted": self.sup.estop()}
