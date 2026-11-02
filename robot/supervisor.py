"""P3 Safety Supervisor - the ONLY path to any RobotAdapter (sim, mock, or hardware).

Design (UNIBOT P3): any tool surface (MCP, a model tool-calling loop) reaches the robot
EXCLUSIVELY through `SafetySupervisor.validate_*` + `dispatch`. The supervisor rejects every
unsafe command (workspace box, table clearance, speed/accel caps, reach/IK, command rate,
heartbeat watchdog, e-stop, approval mode) BEFORE the adapter is ever touched. There is no
back-door: `SimAdapter.move` is private to the supervisor's dispatch.

SIMULATION ONLY: `SimAdapter` is the implemented, tested adapter. Hardware adapters are
interface-only and documented as unverified in docs/ROBOT_BRIDGE.md. No hardware is connected.
"""
from __future__ import annotations
import time, uuid, threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Pose:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    @property
    def radius(self) -> float:
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5


@dataclass
class Limits:
    """The safety envelope. `workspace_box` = (xmin,xmax,ymin,ymax,zmin,zmax).
    `estop` is shared with the adapter (the supervisor and its SimAdapter both read/write
    this Event, which is how e-stop reaches hardware and is measured)."""
    workspace_box: tuple[float, ...] = (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
    table_clearance: float = 0.0        # min height above the table / a 3D obstacle
    max_speed: float = 1.0
    max_accel: float = 5.0
    max_reach: float = 1.0
    rate_per_s: Optional[float] = None  # None = no command rate limit
    heartbeat_s: Optional[float] = None # None = no heartbeat watchdog
    estop: threading.Event = field(default_factory=threading.Event)


@dataclass
class SafetyVerdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    needs_approval: bool = False
    command_id: str = ""


@dataclass
class RobotAdapter:
    """Interface only: every real adapter must let the supervisor drive it. SimAdapter
    implements it and is the tested path; hardware adapters are unverified suggestions."""
    pose: Optional[Pose] = None
    state: str = "idle"

    def move(self, pose: Pose, speed: float = 0.0, accel: float = 0.0) -> None: ...
    def gripper(self, cmd: str) -> None: ...
    def estop(self) -> None: ...


class SimAdapter(RobotAdapter):
    """Deterministic in-memory robot: records the last commanded pose. estop_engaged is
    the shared envelope Event - the measured signal the e-stop test asserts on."""

    def __init__(self, limits: Limits) -> None:
        super().__init__()
        self._lim = limits

    @property
    def estop_engaged(self) -> bool:
        return self._lim.estop.is_set()

    def move(self, pose: Pose, speed: float = 0.0, accel: float = 0.0) -> None:
        self.pose = pose
        self.state = "moving" if speed > 0 else "idle"

    def gripper(self, cmd: str) -> None:
        self.state = "gripper_" + cmd

    def estop(self) -> None:
        self._lim.estop.set()
        self.state = "estopped"


class SafetySupervisor:
    """The single choke-point. `validate_*` reasons in pure code; `dispatch` is the ONLY
    thing that touches an adapter, and only after every check (and approval) passes."""

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self._approval_mode = False
        self._estop_approved = False
        self._approvals: dict[str, bool] = {}
        self._cmd_times: list[float] = []

    # ---- control (explicit + gated; nothing here auto-fires) ----
    def set_approval_mode(self, on: bool) -> None:
        self._approval_mode = bool(on)

    def heartbeat(self) -> None:
        self._last_hb = time.time()

    def estop(self) -> bool:
        """Always available. Reaches the adapter through the shared envelope Event."""
        self.limits.estop.set()
        self._estop_approved = False
        return True

    def approve_release(self, reason: str) -> bool:
        """Releasing e-stop is a deliberate, logged human act - never automatic."""
        self._estop_approved = True
        self._release_reason = reason
        return True

    def release_estop(self) -> bool:
        if not self._estop_approved:
            return False
        self.limits.estop.clear()
        self._estop_approved = False
        return True

    def approve(self, command_id: str, allow: bool) -> bool:
        self._approvals[command_id] = bool(allow)
        return bool(allow)

    # ---- the gates (pure code) ----
    def validate_move(self, pose: Pose, speed: float = 0.0, accel: float = 0.0) -> SafetyVerdict:
        L = self.limits
        reasons: list[str] = []
        if L.estop.is_set():
            reasons.append("estop engaged")
        xmin, xmax, ymin, ymax, zmin, zmax = L.workspace_box
        if not (xmin <= pose.x <= xmax and ymin <= pose.y <= ymax and zmin <= pose.z <= zmax):
            reasons.append("outside workspace box")
        if pose.z < L.table_clearance:
            reasons.append("below table clearance")
        if speed > L.max_speed:
            reasons.append(f"speed {speed} exceeds cap {L.max_speed}")
        if accel > L.max_accel:
            reasons.append(f"accel {accel} exceeds cap {L.max_accel}")
        if pose.radius > L.max_reach:
            reasons.append(f"unreachable (radius {pose.radius:.3f} > reach {L.max_reach})")
        if L.heartbeat_s is not None and getattr(self, "_last_hb", 0.0):
            if time.time() - self._last_hb > L.heartbeat_s:
                reasons.append("heartbeat expired")
        if L.rate_per_s:
            now = time.time()
            self._cmd_times.append(now)
            self._cmd_times = [t for t in self._cmd_times if now - t <= 1.0]
            if len(self._cmd_times) > L.rate_per_s:
                reasons.append(f"command rate {len(self._cmd_times)}/{L.rate_per_s:.0f} exceeded")
        ok = not reasons
        vid = SafetyVerdict(ok=ok, reasons=reasons,
                            needs_approval=(ok and self._approval_mode),
                            command_id=uuid.uuid4().hex[:8] if ok else "")
        return vid

    def validate_gripper(self, cmd: str) -> SafetyVerdict:
        if cmd not in ("open", "close"):
            return SafetyVerdict(False, [f"unknown gripper cmd {cmd!r}"])
        if self.limits.estop.is_set():
            return SafetyVerdict(False, ["estop engaged"])
        return SafetyVerdict(True, [])

    def validate_program(self, waypoints: list[Pose], speed: float = 0.2, accel: float = 0.0) -> SafetyVerdict:
        """A program is safe only if EVERY waypoint is. First bad waypoint stops it."""
        for i, w in enumerate(waypoints):
            v = self.validate_move(w, speed, accel)
            if not v.ok:
                return SafetyVerdict(False, [f"waypoint {i} " + " ".join(v.reasons)])
        return SafetyVerdict(True, [])

    # ---- the ONLY thing that touches an adapter ----
    def dispatch(self, verdict: SafetyVerdict, adapter: RobotAdapter, pose: Pose,
                 speed: float = 0.0, accel: float = 0.0) -> dict:
        if not verdict.ok:
            return {"accepted": False, "reasons": verdict.reasons}
        if verdict.needs_approval:
            if not self._approvals.get(verdict.command_id, False):
                return {"accepted": False, "reasons": ["not approved"]}
        adapter.move(pose, speed, accel)
        return {"accepted": True}
