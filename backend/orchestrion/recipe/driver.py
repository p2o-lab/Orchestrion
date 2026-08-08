"""The production `StepDriver` — the engine's one door onto a real plant.

`recipe/engine.py` owns the orchestration semantics and holds no OPC UA code; this module
holds the OPC UA code and no semantics. Everything here is resolution and delegation:
given a `RecipeStep`, find its live connection and its parsed `Service`, then call the
primitives `opcua/control.py` already provides.

The sequences are not invented here — they are `POL_Step_Model_ISA88.md` §2 and §4, built in
units 2-4 and merely composed at this seam.
"""

from __future__ import annotations

import time

from orchestrion.mtp.model import Pea as PeaModel, Service
from orchestrion.opcua import control
from orchestrion.opcua.registry import PeaRegistry
from orchestrion.recipe.model import RecipeStep
from orchestrion.state.codes import Command, ServiceState


class StepBindingError(RuntimeError):
    """A step names a PEA/service/procedure this run cannot resolve.

    Raised rather than returned: the engine wraps `start`/`complete`/`reset` failures into a
    failed run (unit 6), so a mis-bound step fails loudly with its own message instead of
    hanging. The API validates the same references up front — this is the last line.
    """


class PlantStepDriver:
    """Binds recipe steps to a project's connected PEAs.

    Constructed per run from the parsed PEAs the API already has in hand, so the driver
    never re-parses AML and never touches the database.
    """

    READ_FAILURE_BUDGET = 10.0
    """How long `read_state` may keep failing for one step before the run is failed.

    Swallowing read errors **forever** is a silent hang: `_observe` reads "no reading" as
    "keep waiting", and step model §11 removed the global timeout that used to bound it.
    So there has to be a limit — but it must be **generously longer than the registry's
    health interval** (`_HEALTH_INTERVAL = 2 s`), because a dead PEA is the common cause
    and the health loop produces a far better message: *"lost connection to PEA n while
    step 's1' was running"* rather than *"could not read the state"*. Give it several
    chances to win the race, and only then fail on our own terms.

    A **duration**, not a count of ticks, so it stays meaningful if the engine's tick
    changes — a count coupled the budget to a number this module cannot see.
    """

    def __init__(self, registry: PeaRegistry, peas: dict[int, PeaModel]) -> None:
        self._registry = registry
        self._peas = peas
        self._read_failing_since: dict[str, float] = {}  # step id -> first failure (monotonic)

    # ── resolution ──────────────────────────────────────────────────────────────────

    def _service(self, step: RecipeStep) -> Service:
        pea = self._peas.get(step.pea_id)
        if pea is None:
            raise StepBindingError(f"step {step.id!r}: PEA {step.pea_id} is not in this project")
        for service in pea.services:
            if service.name == step.service:
                return service
        raise StepBindingError(
            f"step {step.id!r}: service {step.service!r} not on PEA {step.pea_id}"
        )

    def _connection(self, step: RecipeStep):
        conn = self._registry.connection(step.pea_id)
        if conn is None:
            raise StepBindingError(
                f"step {step.id!r}: PEA {step.pea_id} is not connected"
            )
        return conn

    # ── the four verbs ──────────────────────────────────────────────────────────────

    async def start(self, step: RecipeStep) -> None:
        """Pre-flight -> handshake + procedure + parameters -> Start -> await started.

        Exactly step model §2's opening, in order. `ensure_idle` is what makes a **reused**
        service safe: it `RESET`s a finished one and waits, so the `Start` that follows is
        not dropped into `COMPLETED` (`010` §2 — the defect this whole correction exists for).
        """
        conn, service = self._connection(step), self._service(step)
        await control.ensure_idle(conn, service)
        await control.start_service(conn, service, step.procedure_id, step.params)
        await control.await_started(conn, service)

    async def complete(self, step: RecipeStep) -> None:
        """[2658-4:2022] §6.2.3.2 — end a continuous procedure."""
        await control.command_service(
            self._connection(step), self._service(step), Command.COMPLETE
        )

    async def reset(self, step: RecipeStep) -> None:
        """[IEC 61512-1] Table B.2 — RESETTING always occurs between executions."""
        await control.command_service(
            self._connection(step), self._service(step), Command.RESET
        )

    # ── the two questions ───────────────────────────────────────────────────────────

    async def read_state(self, step: RecipeStep) -> ServiceState | None:
        """A **direct** read of `StateCur`, not the subscription snapshot.

        This is the freshness half of the latch (step model §5). The snapshot is a ~200 ms
        subscription cache; on a service the recipe *reuses*, it can still be holding the
        previous execution's `COMPLETED` when the engine first looks at the next step, and
        the engine would latch a termination that already happened. A direct read cannot.

        Cost: one OPC UA read per running step per engine tick. Bounded and small at recipe
        scale, and if it ever stops being so, this method is the only place that changes —
        the engine just awaits it.
        """
        conn = self._registry.connection(step.pea_id)
        if conn is None:
            return None  # disconnected — `is_connected` is what the engine acts on
        try:
            state = await conn.read_state(self._service(step))
        except StepBindingError:
            raise
        except Exception as exc:
            # A failure proves nothing on its own: a reconnecting session blips, and a
            # genuinely dead PEA is about to be caught by the registry's health loop, which
            # reports it far better than we can. Keep waiting until the budget is spent,
            # then fail on our own terms rather than hang for ever.
            since = self._read_failing_since.setdefault(step.id, time.monotonic())
            waited = time.monotonic() - since
            if waited >= self.READ_FAILURE_BUDGET:
                raise StepBindingError(
                    f"step {step.id!r}: could not read the state of {step.service!r} on "
                    f"PEA {step.pea_id} for {waited:.0f}s — last error: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            return None
        self._read_failing_since.pop(step.id, None)  # a good read clears the streak
        return state

    def is_self_completing(self, step: RecipeStep) -> bool:
        """[2658-4:2022] Table 36 #4b, straight off the parsed MTP."""
        service = self._service(step)
        for procedure in service.procedures:
            if procedure.procedure_id == step.procedure_id:
                return procedure.is_self_completing
        raise StepBindingError(
            f"step {step.id!r}: procedure {step.procedure_id} not on service {step.service!r}"
        )

    def is_connected(self, pea_id: int) -> bool:
        """The registry drops a PEA's entry as soon as its health check fails."""
        return self._registry.snapshot(pea_id) is not None

    # ── snapshot lookups for receptivities (pure, sync — `conditions.is_met`) ────────

    def state_of(self, pea_id: int, service: str) -> str | None:
        snapshot = self._registry.snapshot(pea_id)
        return snapshot.states.get(service) if snapshot else None

    def value_of(self, pea_id: int, value_name: str) -> float | None:
        snapshot = self._registry.snapshot(pea_id)
        if snapshot is None:
            return None
        raw = snapshot.values.get(value_name)
        return float(raw) if isinstance(raw, (int, float)) else None
