"""P3 robot bridge - SIMULATION ONLY + a safety-gated design. No hardware is connected;
SimAdapter is the implemented, tested path. Everything reaches a RobotAdapter ONLY through
SafetySupervisor.validate_*, which is the single choke-point the MCP tool surface (and
any model loop) must go through. Hardware adapter suggestions live in docs/ROBOT_BRIDGE.md
and are explicitly marked unverified.
"""
from .supervisor import SafetySupervisor, SimAdapter, Pose, Limits, SafetyVerdict
from .mcp_server import RobotTools
