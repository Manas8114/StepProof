"""P3 never-cut: the Safety Supervisor is the ONLY path to any RobotAdapter. Every
unsafe command is rejected; the MCP tool surface cannot bypass the supervisor; e-stop
latency is MEASURED (not asserted). All against SimAdapter - no hardware."""
import time

from robot.supervisor import (
    SafetySupervisor,
    SimAdapter,
    Pose,
    Limits,
    SafetyVerdict,
)


def _sup(envelope=None, *a, **k):
    env = envelope or Limits()
    sup = SafetySupervisor(env)
    sim = SimAdapter(env)
    return sup, sim


def test_move_within_envelope_is_executed():
    sup, sim = _sup()
    p = Pose(x=0.1, y=0.0, z=0.05)
    v = sup.validate_move(p, speed=0.2)
    assert v.ok, v.reasons
    sup.dispatch(v, sim, p, 0.2)
    assert sim.pose == p
    assert sim.state == "moving" or sim.state == "idle"


def test_move_out_of_workspace_box_is_rejected():
    sup, sim = _sup(Limits(workspace_box=(0.0, 0.5, 0.0, 0.5, 0.0, 0.4)))
    bad = Pose(x=0.9, y=0.1, z=0.1)          # x beyond 0.5
    v = sup.validate_move(bad, speed=0.2)
    assert not v.ok and "workspace" in " ".join(v.reasons).lower(), v.reasons
    sup.dispatch(v, sim, bad, 0.2)
    assert sim.pose is None, "rejected move must not reach the adapter"


def test_overspeed_and_over_acceleration_rejected():
    sup, sim = _sup(Limits(max_speed=0.5, max_accel=2.0))
    assert not sup.validate_move(Pose(0.1, 0.1, 0.1), speed=0.8).ok
    assert not sup.validate_move(Pose(0.1, 0.1, 0.1), speed=0.4, accel=3.0).ok
    assert sup.validate_move(Pose(0.1, 0.1, 0.1), speed=0.4, accel=2.0).ok


def test_unreachable_pose_rejected_by_reach_check():
    sup, sim = _sup(Limits(max_reach=0.3))
    far = Pose(x=0.25, y=0.25, z=0.25)     # radius ~0.433 > 0.3
    v = sup.validate_move(far, speed=0.2)
    assert not v.ok and "reach" in " ".join(v.reasons).lower(), v.reasons


def test_command_rate_limit_rejects_bursts():
    sup, sim = _sup(Limits(rate_per_s=3))
    ok = [sup.validate_move(Pose(0.1, 0.1, 0.1), speed=0.1).ok for _ in range(3)]
    assert all(ok)                            # 3 within the window pass
    burst = sup.validate_move(Pose(0.1, 0.1, 0.1), speed=0.1)
    assert not burst.ok and "rate" in " ".join(burst.reasons).lower(), burst.reasons


def test_heartbeat_watchdog_stops_and_e_stop_is_immediate():
    sup, sim = _sup(Limits(heartbeat_s=0.2))
    sup.heartbeat()
    time.sleep(0.3)                            # let the heartbeat expire
    v = sup.validate_move(Pose(0.1, 0.1, 0.1), speed=0.1)
    assert not v.ok and "heartbeat" in " ".join(v.reasons).lower(), "expired heartbeat must stop motion"
    assert sup.estop()
    assert sim.estop_engaged, "e-stop must reach the adapter"
    assert not sup.validate_move(Pose(0.1, 0.1, 0.1), speed=0.1).ok   # estopped: nothing moves
    # release is explicit + approval-gated, never automatic
    assert not sup.release_estop()
    assert sup.approve_release("human") and sup.release_estop()


def test_gripper_is_safety_gated_and_measured_e_stop_latency():
    sup, sim = _sup()
    assert sup.validate_gripper("open").ok
    sup.estop()
    v = sup.validate_gripper("close")
    assert not v.ok, "gripper must be frozen while estopped"
    # MEASURE e-stop latency: from call to the adapter observing the stop
    sup2, sim2 = _sup()
    sup2.heartbeat()
    t0 = time.perf_counter()
    sup2.estop()
    e_stop_latency_s = (time.perf_counter() - t0) * 1000.0
    assert sim2.estop_engaged
    assert e_stop_latency_s < 50.0, f"e-stop took {e_stop_latency_s:.2f}ms (>50ms budget)"


def test_approval_mode_requires_explicit_approval_per_move():
    sup, sim = _sup()
    sup.set_approval_mode(True)
    v = sup.validate_move(Pose(0.1, 0.1, 0.1), speed=0.1)
    assert v.ok and v.needs_approval, "approval mode must flag the move, not block it"
    assert not sim.pose
    sup.approve(v.command_id, allow=True)
    sup.dispatch(v, sim, Pose(0.1, 0.1, 0.1), 0.1)
    assert sim.pose == Pose(0.1, 0.1, 0.1), "approved move proceeds"


def test_mcp_tools_cannot_bypass_the_supervisor():
    """The tool surface (what an MCP client / model can call) routes ONLY through the
    supervisor: a tool call for an out-of-bounds move must be rejected exactly as a
    direct validate_move call is - there is no back-door onto the adapter."""
    from robot.mcp_server import RobotTools
    sup, sim = _sup(Limits(workspace_box=(0.0, 0.5, 0.0, 0.5, 0.0, 0.4)))
    tools = RobotTools(sup, sim)
    r = tools.robot_move_to({"pose": {"x": 0.9, "y": 0.1, "z": 0.1}, "speed": 0.2})
    assert r["accepted"] is False, "MCP move must be rejected through the supervisor"
    assert sim.pose is None
    # and a safe one goes through the same gate
    r2 = tools.robot_move_to({"pose": {"x": 0.1, "y": 0.1, "z": 0.1}, "speed": 0.2})
    assert r2["accepted"] is True and sim.pose == Pose(0.1, 0.1, 0.1)
