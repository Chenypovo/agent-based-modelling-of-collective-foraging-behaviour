"""Central enforcement of the four paper-described role transitions."""

from __future__ import annotations

from dataclasses import dataclass

from .agents import Ant, Role

ALLOWED_TRANSITIONS: set[tuple[Role, Role]] = {
    (Role.FORAGER, Role.TRANSPORTER),
    (Role.FORAGER, Role.FOLLOWER),
    (Role.TRANSPORTER, Role.FOLLOWER),
    (Role.FOLLOWER, Role.TRANSPORTER),
}


@dataclass(frozen=True)
class TransitionRecord:
    time: int
    ant_id: int
    from_role: str
    to_role: str
    reason: str
    x: float
    y: float

    def to_dict(self) -> dict[str, int | float | str]:
        return {
            "time": self.time,
            "ant_id": self.ant_id,
            "from_role": self.from_role,
            "to_role": self.to_role,
            "reason": self.reason,
            "x": self.x,
            "y": self.y,
        }


def transition_role(
    ant: Ant, new_role: Role, *, reason: str, time: int
) -> TransitionRecord:
    old_role = ant.role
    if (old_role, new_role) not in ALLOWED_TRANSITIONS:
        raise ValueError(f"role transition {old_role.value} -> {new_role.value} is not allowed")
    ant.role = new_role
    return TransitionRecord(
        time=int(time),
        ant_id=ant.ant_id,
        from_role=old_role.value,
        to_role=new_role.value,
        reason=reason,
        x=float(ant.position[0]),
        y=float(ant.position[1]),
    )
