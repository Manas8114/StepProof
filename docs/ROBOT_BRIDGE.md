# Robot Bridge (P3) — simulation now, hardware design only

**Honest status: there is no physical robot.** Robot work ends at a tested simulation
plus a safety-gated bridge *design*. What is **implemented and tested in simulation** vs.
what is **exported-but-unverified** is stated explicitly below. No code here touches
hardware; every hardware adapter is an interface + a documented, marked-"unverified"
suggestion.

## What actually runs and is tested (simulation)

`robot/supervisor.py` + `robot/mcp_server.py` + `tests/test_robot_supervisor.py` (9 tests):

- **`SafetySupervisor` is the ONLY path to any adapter.** Tools never call an adapter's
  motion methods directly; every command is `validate_*` then `dispatch`. There is no
  back-door.
- **Every unsafe command is rejected** (measured, not asserted): outside the workspace
  box, below table clearance, over the speed/accel caps, unreachable (reach/IK radius),
  command-rate bursts, and an expired heartbeat watchdog.
- **e-stop is always available and its latency is MEASURED** (`< 50 ms` budget asserted in
  `test_heartbeat_watchdog_stops_and_e_stop_is_immediate`). Releasing e-stop is a
  deliberate, approval-gated human act — it never happens automatically.
- **Approval mode** flags every move as `needs_approval`; a move proceeds only after an
  explicit `approve(command_id, allow=True)`.
- **MCP cannot bypass the supervisor** — `test_mcp_tools_cannot_bypass_the_supervisor`
  proves the tool surface rejects an out-of-bounds move exactly as a direct call does.
- **Modes (sim):** Teach (record a program), Replay (validated queue). *Mirror* (follow a
  live demo) is on the cut line — not implemented, and "auto-approve within the envelope"
  is OFF by default everywhere.

## The intended live architecture (design, not live)

```
live camera -> fast local tracker (+ periodic SAM confirmation) -> event stream
             -> incremental RobotProgram (waypoint queue)
             -> Safety Supervisor (validate, rate-limit, workspace, speed, heartbeat,
                                    e-stop, approval)                    <-- THE ONLY GATE
             -> RobotAdapter: SimAdapter (implemented, tested)
                             | MockHardware (test double)
                             | HardwareAdapter (interface + suggestions; UNTESTED)
MCP server exposes the supervised tools; any MCP client (incl. a model tool-loop) reaches
the robot ONLY through the supervisor.
```

Honest note on "live": hosted SAM video segmentation is **not** real time. A live path
would use fast local tracking (colour/blob/ArUco or a small tracker) for the stream and SAM
only for periodic confirmation, and it would **measure and report end-to-end latency per
waypoint**. That latency measurement is not present in this repo (no camera/hardware).

## Hardware adapter suggestions — UNVERIFIED, no hardware available

> ⚠️ Every block below is a *design suggestion*: **not verified against vendor docs, no
> hardware was available, and nothing here has been run on a real arm. Verify before use.**

Common primitives each adapter should implement: a waypoint queue with lookahead, a
trapezoidal velocity profile, fixed-rate servo streaming, a heartbeat watchdog, software
limits, and a dead-man (e-stop) switch — all feeding the same `SafetySupervisor`.

- **ROS 2 / MoveIt 2** — `rclpy` node; `MoveGroupInterface` + `FollowJointTrajectory`
  action with `PoseStamped` goals; stream joint trajectories at the controller rate;
  `rclpy` heartbeat via a latched "alive" topic the supervisor watches.
- **Universal Robots** — `ur_rtde` `servoL` over the RTDE stream (real-time, ~500 Hz),
  or URScript over the secondary socket; `ur_dashboard_services` for e-stop/brake state.
- **Franka** — `libfranka` (via a Python wrapper); send motion primitives to the
  `CartesianInterface`, poll the reflex-frame heartbeat, and treat the reflex loss as the
  e-stop.
- **Hobby / LeRobot** — joint-space position streaming over the LeRobot board's
  serial/ethernet bus; a dead-man line stops on disconnect.
- **Serial / G-code gantry** — a G-code position streamer with look-ahead; the board's
  limit switches + e-stop button map onto the supervisor's workspace box + e-stop.

For each: the *interface* is `RobotAdapter` (`move`/`gripper`/`estop`); the *verification
gaps* are the vendor-specific units above. Mark every such adapter **"not hardware-tested."**

## MCP transport (P3.4)

`robot/mcp_server.py::RobotTools` matches the official Python MCP SDK tool shape
(`robot_get_state`, `robot_plan_from_events`, `robot_validate_program`, `robot_move_to`,
`robot_gripper`, `robot_pause`, `robot_resume`, `robot_estop`). The SDK *transport* layer
is optional and deliberately decoupled so the safety properties are testable offline
(`mcp` is importable; the supervisor tests never open a transport). **To verify before
wiring a real client:** confirm in Meta's docs whether and how Muse Spark consumes MCP or
function tools; if it does not, bridge with a function-calling loop that exposes these same
supervised tools. Record what you verified in `docs/VERIFIED.md`.
