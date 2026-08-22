"""Typed contracts between the layers.

These are the only shapes that cross a layer boundary. Every one is validated
*at the boundary*, so a malformed plan never reaches the translator and a model
that returns an out-of-range value is re-asked rather than silently coerced.

The validators are deliberately verbose: their messages are fed straight back to
the agent as the repair prompt, so "room R-04 target_area_m2=0.0 must be > 0" is
worth more than a stack trace.

No LLM ever sees a coordinate here. `ArchitectPlan` carries areas, categories and
adjacencies; turning those into metres is `recognition.translate`'s job, and that
separation is what stops a model inventing a plausible-looking wall position.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_BRIEF = "designbrief/v1"
SCHEMA_PLAN = "architectplan/v1"

# Categories the downstream model/rules already understand (recognition.model).
CATEGORIES = (
    "bedroom", "living", "kitchen", "bathroom", "office", "meeting",
    "lab", "hall", "utility", "stair", "roof", "other",
)
HABITABLE = ("bedroom", "living", "kitchen", "office")
ACCESS_TIERS = ("none", "din18040_2", "din18040_2_R")


class ContractError(ValueError):
    """Raised when an artifact crossing a layer boundary is malformed.

    The message is the repair instruction. Keep it specific and actionable.
    """


def _req(d: dict, key: str, kind: type, where: str) -> Any:
    if key not in d:
        raise ContractError(f"{where}: missing required field '{key}'")
    v = d[key]
    if not isinstance(v, kind):
        raise ContractError(
            f"{where}: '{key}' must be {kind.__name__}, got {type(v).__name__} ({v!r})"
        )
    return v


# --------------------------------------------------------------------------
# DesignBrief — SoT-1, written by L1 (the interview)
# --------------------------------------------------------------------------

@dataclass
class RoomRequest:
    category: str
    count: int = 1
    min_area_m2: float | None = None
    label: str | None = None

    def validate(self, where: str) -> None:
        if self.category not in CATEGORIES:
            raise ContractError(
                f"{where}: category '{self.category}' is not one of {list(CATEGORIES)}"
            )
        if self.count < 1:
            raise ContractError(f"{where}: count must be >= 1, got {self.count}")
        if self.min_area_m2 is not None and self.min_area_m2 <= 0:
            raise ContractError(f"{where}: min_area_m2 must be > 0, got {self.min_area_m2}")


@dataclass
class Assumption:
    """A value the system inferred rather than being told.

    Every inferred value must appear here. There is no third category: a value is
    either confirmed by the client or declared as an assumption. This is the
    honesty surface -- the silent default is the failure mode we are designing out.
    """
    slot: str
    value: Any
    basis: str
    confidence: str = "medium"
    confirmed: bool = False


@dataclass
class DesignBrief:
    project: str
    bundesland: str = "BY"
    building_class: str = "detached_house"
    plot_width_m: float = 18.0
    plot_depth_m: float = 24.0
    dwelling_count: int = 1
    storey_count: int = 1
    storey_height_m: float = 2.50
    occupants: int = 4
    rooms: list[RoomRequest] = field(default_factory=list)
    accessibility_tier: str = "none"
    assumptions: list[Assumption] = field(default_factory=list)
    notes: str = ""
    schema: str = SCHEMA_BRIEF

    # -- derived -----------------------------------------------------------

    def resolve_accessibility(self) -> None:
        """BayBO Art. 48 (1): above two dwellings, one storey must be barrier-free.

        Derived, never asked directly -- and recorded as an assumption so the
        client can see the rule that forced it.
        """
        if self.dwelling_count > 2 and self.accessibility_tier == "none":
            self.accessibility_tier = "din18040_2"
            self.assumptions.append(Assumption(
                slot="accessibility_tier",
                value="din18040_2",
                basis="BayBO Art. 48 (1): more than 2 dwellings requires one storey barrier-free",
                confidence="high",
            ))

    def validate(self) -> DesignBrief:
        w = "DesignBrief"
        if not self.project.strip():
            raise ContractError(f"{w}: 'project' must not be empty")
        if self.accessibility_tier not in ACCESS_TIERS:
            raise ContractError(
                f"{w}: accessibility_tier '{self.accessibility_tier}' not in {list(ACCESS_TIERS)}"
            )
        if self.dwelling_count < 1:
            raise ContractError(f"{w}: dwelling_count must be >= 1, got {self.dwelling_count}")
        if self.storey_count != 1:
            # v1 constraint, stated loudly rather than failing mysteriously later.
            raise ContractError(
                f"{w}: storey_count must be 1 in v1 (multi-storey is not implemented); got {self.storey_count}"
            )
        if self.storey_height_m < 2.40:
            raise ContractError(
                f"{w}: storey_height_m {self.storey_height_m} is below the BayBO Art. 45 (1) "
                "minimum clear height of 2.40 m"
            )
        if not self.rooms:
            raise ContractError(f"{w}: at least one room is required")
        for i, r in enumerate(self.rooms):
            r.validate(f"{w}.rooms[{i}]")
        if self.plot_width_m <= 0 or self.plot_depth_m <= 0:
            raise ContractError(f"{w}: plot dimensions must be > 0")
        return self

    # -- io ----------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> DesignBrief:
        rooms = [RoomRequest(**r) for r in d.get("rooms", [])]
        assumptions = [Assumption(**a) for a in d.get("assumptions", [])]
        known = {f for f in cls.__dataclass_fields__}
        kw = {k: v for k, v in d.items() if k in known and k not in ("rooms", "assumptions")}
        return cls(rooms=rooms, assumptions=assumptions, **kw)

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    @classmethod
    def read(cls, path: str | Path) -> DesignBrief:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# --------------------------------------------------------------------------
# ArchitectPlan -- written by L2 (the architect), read by L3 (the translator)
# --------------------------------------------------------------------------

@dataclass
class RoomSpec:
    id: str
    category: str
    label: str
    target_area_m2: float
    exterior_wall: bool = True

    def validate(self, where: str) -> None:
        if not self.id.strip():
            raise ContractError(f"{where}: room 'id' must not be empty")
        if self.category not in CATEGORIES:
            raise ContractError(
                f"{where}: category '{self.category}' is not one of {list(CATEGORIES)}"
            )
        if self.target_area_m2 <= 0:
            raise ContractError(
                f"{where}: room {self.id} target_area_m2 must be > 0, got {self.target_area_m2}"
            )


@dataclass
class Adjacency:
    a: str
    b: str
    via: str = "door"   # door | open

    def validate(self, where: str, ids: set[str]) -> None:
        for side in (self.a, self.b):
            if side not in ids:
                raise ContractError(f"{where}: adjacency references unknown room '{side}'")
        if self.a == self.b:
            raise ContractError(f"{where}: room '{self.a}' cannot be adjacent to itself")
        if self.via not in ("door", "open"):
            raise ContractError(f"{where}: 'via' must be 'door' or 'open', got '{self.via}'")


@dataclass
class Envelope:
    width_m: float
    depth_m: float
    external_wall_m: float = 0.30
    internal_wall_m: float = 0.15

    @property
    def area_m2(self) -> float:
        return self.width_m * self.depth_m

    def validate(self, where: str) -> None:
        if self.width_m <= 0 or self.depth_m <= 0:
            raise ContractError(f"{where}: envelope dimensions must be > 0")
        if self.external_wall_m <= 0 or self.internal_wall_m <= 0:
            raise ContractError(f"{where}: wall thicknesses must be > 0")


@dataclass
class ArchitectPlan:
    """Relationships and areas. Deliberately no coordinates -- see module docstring."""
    project: str
    envelope: Envelope
    rooms: list[RoomSpec]
    adjacency: list[Adjacency] = field(default_factory=list)
    storey_name: str = "Erdgeschoss"
    storey_height_m: float = 2.50
    circulation_id: str | None = None
    glazing_ratio: float = 0.125          # BayBO Art. 45 (2) = 1/8
    accessibility_tier: str = "none"
    rationale: str = ""
    todo_agent: list[str] = field(default_factory=list)
    schema: str = SCHEMA_PLAN

    # -- validation --------------------------------------------------------

    def validate(self) -> ArchitectPlan:
        w = "ArchitectPlan"
        self.envelope.validate(f"{w}.envelope")
        if not self.rooms:
            raise ContractError(f"{w}: at least one room is required")

        ids: set[str] = set()
        for i, r in enumerate(self.rooms):
            r.validate(f"{w}.rooms[{i}]")
            if r.id in ids:
                raise ContractError(f"{w}: duplicate room id '{r.id}'")
            ids.add(r.id)

        for i, a in enumerate(self.adjacency):
            a.validate(f"{w}.adjacency[{i}]", ids)

        # Areas must physically fit, allowing for walls. Checked *before* geometry
        # exists, so an impossible plan costs one cheap call instead of a full
        # geometry round-trip.
        wanted = sum(r.target_area_m2 for r in self.rooms)
        usable = self.usable_area_m2()
        if wanted > usable + 1e-6:
            raise ContractError(
                f"{w}: rooms need {wanted:.1f} m2 but the envelope only offers "
                f"{usable:.1f} m2 of usable floor after wall thickness. "
                f"Reduce room areas or enlarge the envelope "
                f"({self.envelope.width_m} x {self.envelope.depth_m} m)."
            )

        if self.circulation_id is not None and self.circulation_id not in ids:
            raise ContractError(f"{w}: circulation_id '{self.circulation_id}' is not a known room")

        if not 0 < self.glazing_ratio < 1:
            raise ContractError(f"{w}: glazing_ratio must be between 0 and 1, got {self.glazing_ratio}")

        if len(self.rooms) > 1 and self.adjacency:
            self._assert_connected(ids)
        return self

    def _assert_connected(self, ids: set[str]) -> None:
        """Every room must be reachable. A disconnected plan is a bug, not a style."""
        graph: dict[str, set[str]] = {i: set() for i in ids}
        for a in self.adjacency:
            graph[a.a].add(a.b)
            graph[a.b].add(a.a)
        start = next(iter(ids))
        seen, stack = {start}, [start]
        while stack:
            for nxt in graph[stack.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if seen != ids:
            missing = sorted(ids - seen)
            raise ContractError(
                f"ArchitectPlan: rooms {missing} are not reachable from the rest of the plan. "
                "Add an adjacency connecting them (usually to the circulation room)."
            )

    # -- derived -----------------------------------------------------------

    def usable_area_m2(self) -> float:
        """Envelope area minus the external wall band and an allowance for partitions."""
        e = self.envelope
        inner_w = e.width_m - e.external_wall_m
        inner_d = e.depth_m - e.external_wall_m
        gross = max(inner_w, 0.0) * max(inner_d, 0.0)
        # Partition allowance: roughly one internal wall per room boundary.
        partitions = max(len(self.rooms) - 1, 0) * e.internal_wall_m * max(inner_w, inner_d)
        return max(gross - partitions, 0.0)

    def room(self, room_id: str) -> RoomSpec:
        for r in self.rooms:
            if r.id == room_id:
                return r
        raise ContractError(f"ArchitectPlan: no room with id '{room_id}'")

    # -- io ----------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ArchitectPlan:
        env = Envelope(**d["envelope"]) if isinstance(d.get("envelope"), dict) else d["envelope"]
        rooms = [RoomSpec(**r) for r in d.get("rooms", [])]
        adj = [Adjacency(**a) for a in d.get("adjacency", [])]
        known = {f for f in cls.__dataclass_fields__}
        kw = {k: v for k, v in d.items()
              if k in known and k not in ("envelope", "rooms", "adjacency")}
        return cls(envelope=env, rooms=rooms, adjacency=adj, **kw)

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    @classmethod
    def read(cls, path: str | Path) -> ArchitectPlan:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_plan(raw: str | dict) -> ArchitectPlan:
    """Parse and validate whatever an agent returned. Never trust it unchecked."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ContractError(f"ArchitectPlan: response is not valid JSON ({e})") from e
    if not isinstance(raw, dict):
        raise ContractError(f"ArchitectPlan: expected a JSON object, got {type(raw).__name__}")
    return ArchitectPlan.from_dict(raw).validate()
