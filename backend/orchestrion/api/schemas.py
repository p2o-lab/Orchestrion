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


class NodeSchema(BaseModel):
    name: str
    namespace: str
    identifier: str
    identifier_type: str
    access: str


class ProcedureSchema(BaseModel):
    name: str
    procedure_id: int
    is_self_completing: bool


class ServiceSchema(BaseModel):
    name: str
    procedures: list[ProcedureSchema]
    control_nodes: list[NodeSchema]


class PeaDetail(PeaSummary):
    """A PEA plus its parsed contents — the data the test/control view renders."""

    type_name: str
    mtp_version: str
    device_revision: str
    manufacturer_uri: str
    product_code: str
    services: list[ServiceSchema]


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
        procedures=[
            ProcedureSchema(
                name=p.name,
                procedure_id=p.procedure_id,
                is_self_completing=p.is_self_completing,
            )
            for p in service.procedures
        ],
        control_nodes=control_nodes,
    )


def pea_detail(summary: PeaSummary, parsed: model.Pea) -> PeaDetail:
    return PeaDetail(
        **summary.model_dump(),
        type_name=parsed.type_name,
        mtp_version=parsed.mtp_version,
        device_revision=parsed.device_revision,
        manufacturer_uri=parsed.manufacturer_uri,
        product_code=parsed.product_code,
        services=[_service(s) for s in parsed.services],
    )
