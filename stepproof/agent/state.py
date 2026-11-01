"""Explicit agent state machine with allowed transitions. `pause` is honoured at the next
action boundary (the loop checks before every action); takeover and the kill switch can be
entered from any RUNNING-ish state."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    PAUSED_HUMAN = "PAUSED_HUMAN"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DONE = "DONE"
    ERROR = "ERROR"


# allowed transitions: from -> {to, ...}. Kept explicit so illegal jumps raise.
_ALLOWED: dict[str, set[str]] = {
    State.IDLE: {State.PLANNING, State.ERROR},
    State.PLANNING: {State.RUNNING, State.PAUSED_HUMAN, State.ERROR, State.DONE},
    State.RUNNING: {State.RUNNING, State.PAUSED_HUMAN, State.AWAITING_APPROVAL,
                    State.DONE, State.ERROR},
    State.PAUSED_HUMAN: {State.RUNNING, State.DONE, State.ERROR},
    State.AWAITING_APPROVAL: {State.RUNNING, State.PAUSED_HUMAN, State.ERROR, State.DONE},
    State.DONE: {State.IDLE, State.PLANNING},
    State.ERROR: {State.IDLE, State.PLANNING},
}


class IllegalTransition(Exception):
    pass


@dataclass
class StateMachine:
    state: State = State.IDLE

    def transition(self, to: State, reason: str = "") -> State:
        to = State(to)
        if to not in _ALLOWED[self.state]:
            raise IllegalTransition(f"illegal transition {self.state.value} -> {to.value} ({reason})")
        self.state = to
        return to

    def can(self, to: State) -> bool:
        return State(to) in _ALLOWED[self.state]

    @property
    def is_running(self) -> bool:
        return self.state in (State.RUNNING, State.PLANNING)
