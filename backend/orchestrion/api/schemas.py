"""Wire formats for the workspace API — plain, serialisable views.

These decouple the HTTP surface from both the DB tables and the MTP domain model, so
neither leaks to the frontend. `pea_detail()` flattens a parsed `model.Pea` into what a
PEA's test/control view needs (services, procedures, control-node addresses).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from orchestrion.mtp import model


# ── requests ────────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class NameUpdate(BaseModel):
    name: str


# ── responses ───────────────────────────────────────────────────────────────────

class ProjectRead(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    pea_count: int


class PeaSummary(BaseModel):
    id: int
    project_id: int
    name: str
    aml_filename: str
    endpoint_url: str
    created_at: datetime


class PeaImported(PeaSummary):
    """The import response — a `PeaSummary` that may carry a non-blocking warning.

    Deliberately its own model rather than a field on `PeaSummary`: that one is also the
    list and rename response and is mirrored in `api/types.ts`, so a `warning` field there
    would be permanently `null` on every other use. This is the one response that can
    produce one.
    """

    warning: str | None = None
    """Something the operator should know about, on an import that nonetheless succeeded.

    Today the only case is a duplicate OPC UA endpoint within the project — see
    `api/peas.py::_endpoint_conflict`. **Never a reason to refuse the import**: the
    condition is recoverable (rename, repoint, delete) and the run path already fails
    loudly on the consequence, so blocking here would be stricter than the layer that
    actually matters.
    """


class NodeSchema(BaseModel):
    name: str
    namespace: str
    identifier: str
    identifier_type: str
    access: str


class ParameterSchema(BaseModel):
    name: str
    kind: str  # 'analog' | 'integer' | 'binary' | 'string' — picks the UI input


class ValueSchema(BaseModel):
    """A value's static descriptor — the shape the UI needs to render it.

    The live *number* arrives on the WebSocket keyed by `name`; this is everything
    else: what kind it is, which way it flows, and whether the operator may set it.
    """

    name: str
    kind: str          # 'analog' | 'integer' | 'binary' | 'string'
    direction: str     # 'in' (POL→PEA) | 'out' (PEA→POL)
    writable: bool     # in-values are set by the POL; out-values are display-only


class ProcedureSchema(BaseModel):
    name: str
    procedure_id: int
    is_self_completing: bool
    parameters: list[ParameterSchema]
    report_values: list[ValueSchema]      # [2658-4] #6 — live/read-only during EXECUTE
    process_values: list[ValueSchema]     # #7/#8 — in+out, tied to this procedure


class ServiceSchema(BaseModel):
    name: str
    procedures: list[ProcedureSchema]
    config_parameters: list[ValueSchema]  # #3 — service-level configuration inputs
    control_nodes: list[NodeSchema]


class PeaDetail(PeaSummary):
    """A PEA plus its parsed contents — the data the test/control view renders."""

    type_name: str
    mtp_version: str
    device_revision: str
    manufacturer_uri: str
    product_code: str
    services: list[ServiceSchema]
    process_values: list[ValueSchema]     # Table 42 — the PEA-wide ProcessValueSet


class ImportError(BaseModel):
    """Returned (HTTP 422) when an uploaded MTP fails to parse — for the UI to show."""

    error: str
    detail: str


# ── serialisers: parsed model.Pea -> schema ───────────────────────────────────────

def _service(service: model.Service) -> ServiceSchema:
    control_nodes = []
    if service.control is not None:
        control_nodes = [
            NodeSchema(
                name=name,
                namespace=node.namespace,
                identifier=node.identifier,
                identifier_type=node.identifier_type.name,
                access=node.access.name,
            )
            for name, node in sorted(service.control.nodes.items())
        ]
    return ServiceSchema(
        name=service.name,
        procedures=[_procedure(p) for p in service.procedures],
        config_parameters=[_value(v, "in", writable=True) for v in service.config_parameters],
        control_nodes=control_nodes,
    )


def _procedure(procedure: model.ServiceProcedure) -> ProcedureSchema:
    return ProcedureSchema(
        name=procedure.name,
        procedure_id=procedure.procedure_id,
        is_self_completing=procedure.is_self_completing,
        parameters=[
            ParameterSchema(name=par.name, kind=_value_kind(par.data.class_path))
            for par in procedure.parameters
        ],
        report_values=[_value(v, "out", writable=False) for v in procedure.report_values],
        process_values=[
            *[_value(v, "in", writable=True) for v in procedure.process_values_in],
            *[_value(v, "out", writable=False) for v in procedure.process_values_out],
        ],
    )


def _value(value: model.ValueObject, direction: str, *, writable: bool) -> ValueSchema:
    return ValueSchema(
        name=value.name,
        kind=_value_kind(value.data.class_path),
        direction=direction,
        writable=writable,
    )


def _value_kind(class_path: str) -> str:
    """Map a value DataAssembly's class to a UI kind, from the concrete leaf name.

    Covers every value element by its type prefix — AnaView/AnaServParam/
    AnaProcessValueIn → analog, DInt* → integer, Bin* → binary, String* → string.
    """
    leaf = class_path.rsplit("/", 1)[-1]
    if leaf.startswith("Ana"):
        return "analog"
    if leaf.startswith("DInt"):
        return "integer"
    if leaf.startswith("Bin"):
        return "binary"
    if leaf.startswith("String"):
        return "string"
    return "analog"


def pea_detail(summary: PeaSummary, parsed: model.Pea) -> PeaDetail:
    return PeaDetail(
        **summary.model_dump(),
        type_name=parsed.type_name,
        mtp_version=parsed.mtp_version,
        device_revision=parsed.device_revision,
        manufacturer_uri=parsed.manufacturer_uri,
        product_code=parsed.product_code,
        services=[_service(s) for s in parsed.services],
        process_values=[
            *[_value(v, "in", writable=True) for v in parsed.process_values_in],
            *[_value(v, "out", writable=False) for v in parsed.process_values_out],
        ],
    )
