# Robot Bridge (P3) — Safety-Gated Robotic Procedure Execution

StepProof's robot bridge extends the same **models perceive, code decides** invariant to physical robotic manipulation. The `SafetySupervisor` enforces workspace bounds, speed/acceleration caps, heartbeat watchdogs, and approval gates identically to the browser safety gate — ensuring no model output can directly actuate hardware without code-level validation.

## What is implemented and tested

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
- **Modes:** Teach (record a program), Replay (validated queue), Sim (full simulation adapter).

## Live architecture

```
live camera -> fast local tracker (+ periodic SAM confirmation) -> event stream
             -> incremental RobotProgram (waypoint queue)
             -> Safety Supervisor (validate, rate-limit, workspace, speed, heartbeat,
                                    e-stop, approval)                    <-- THE ONLY GATE
             -> RobotAdapter: SimAdapter (implemented, tested)
                             | MockHardware (test double)
                             | HardwareAdapter (extensible interface)
MCP server exposes the supervised tools; any MCP client (incl. a model tool-loop) reaches
the robot ONLY through the supervisor.
```

The live path uses fast local tracking (colour/blob/ArUco or a small tracker) for the stream and SAM for periodic confirmation, with end-to-end latency measured and reported per waypoint.

## Hardware adapter support

Common primitives each adapter implements: a waypoint queue with lookahead, a
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

For each: the *interface* is `RobotAdapter` (`move`/`gripper`/`estop`); vendor-specific
adapters extend this interface for their target hardware.

## MCP transport (P3.4)

`robot/mcp_server.py::RobotTools` matches the official Python MCP SDK tool shape
(`robot_get_state`, `robot_plan_from_events`, `robot_validate_program`, `robot_move_to`,
`robot_gripper`, `robot_pause`, `robot_resume`, `robot_estop`). The SDK *transport* layer
is decoupled so the safety properties are testable offline
(`mcp` is importable; the supervisor tests never open a transport).
