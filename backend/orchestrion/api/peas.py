"""PEA import + CRUD, scoped to a project.

Import is the gate: an uploaded `.aml` is parsed and validated *before* it is stored,
so a bad file is rejected (HTTP 422 with the parser's message for the UI to highlight)
and never becomes a row. Every stored PEA is therefore known-parseable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from orchestrion.api.mtp_import import parse_aml
from orchestrion.api.schemas import (
    NameUpdate,
    PeaDetail,
    PeaImported,
    PeaSummary,
    pea_detail,
)
from orchestrion.db.engine import get_session
from orchestrion.db.models import Pea, Project
from orchestrion.mtp.caex import MtpError

router = APIRouter(tags=["peas"])


def _normalise_endpoint(url: str) -> str:
    """The form two endpoints are compared in — case-folded, no trailing slash.

    **Deliberately not clever.** This will not see through `opc.tcp://localhost:48050`
    versus `opc.tcp://127.0.0.1:48050`, which are the same server spelled two ways.
    Catching that means resolving hostnames inside a request handler — a network call that
    can also be wrong (DNS moves, and this repo already has scars from `localhost`
    resolving to `::1` while the service sat on IPv4). Exact-string is
    right for the case that actually occurs: a plant where only the port differs.
    """
    return url.strip().rstrip("/").casefold()


def _endpoint_conflict(
    session: Session, project_id: int, endpoint_url: str
) -> str | None:
    """Another PEA in **this project** already on this endpoint, as a warning, or None.

    Compared on the **whole endpoint URL**, not the port: `opc.tcp://192.168.1.5:4840` and
    `opc.tcp://192.168.1.9:4840` are two different modules that merely share a port number,
    and flagging those would be wrong. For a VirtualPEA plant the two are equivalent, since
    everything is on `127.0.0.1` and only the port varies.

    Scoped to the project because that is where the damage would occur: a recipe binds its
    steps to PEAs within one project. The same physical module legitimately appears in two
    plant configurations.
    """
    if not endpoint_url:
        return None
    target = _normalise_endpoint(endpoint_url)
    clash = [
        row.name
        for row in session.exec(select(Pea).where(Pea.project_id == project_id)).all()
        if _normalise_endpoint(row.endpoint_url) == target
    ]
    if not clash:
        return None
    return (
        f"{', '.join(sorted(clash))} already use{'s' if len(clash) == 1 else ''} "
        f"{endpoint_url} in this project — both will talk to the same server. "
        "Point one at a different endpoint, or remove it."
    )


def _summary(pea: Pea) -> PeaSummary:
    return PeaSummary(
        id=pea.id,
        project_id=pea.project_id,
        name=pea.name,
        aml_filename=pea.aml_filename,
        endpoint_url=pea.endpoint_url,
        created_at=pea.created_at,
    )


def _pea_or_404(session: Session, pea_id: int) -> Pea:
    pea = session.get(Pea, pea_id)
    if pea is None:
        raise HTTPException(status_code=404, detail=f"PEA {pea_id} not found")
    return pea


@router.post(
    "/api/projects/{project_id}/peas",
    response_model=PeaImported,
    status_code=201,
    responses={422: {"description": "the uploaded MTP failed to parse"}},
)
async def import_pea(
    project_id: int,
    name: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> PeaImported:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")

    content = await file.read()
    filename = file.filename or "upload.aml"
    try:
        parsed = parse_aml(content, filename)
    except MtpError as exc:
        # 422: the file is well-formed HTTP but semantically not a valid MTP. The
        # message names the violated rule/clause — the UI shows it inline.
        raise HTTPException(
            status_code=422,
            detail={"error": type(exc).__name__, "detail": str(exc)},
        ) from exc

    endpoint_url = parsed.endpoints[0].url if parsed.endpoints else ""
    # Computed BEFORE the row is added, or the new PEA would find itself.
    warning = _endpoint_conflict(session, project_id, endpoint_url)

    pea = Pea(
        project_id=project_id,
        name=name,
        aml_filename=filename,
        aml_content=content.decode("utf-8", errors="replace"),
        endpoint_url=endpoint_url,
    )
    session.add(pea)
    session.commit()
    session.refresh(pea)
    return PeaImported(**_summary(pea).model_dump(), warning=warning)


@router.get("/api/projects/{project_id}/peas", response_model=list[PeaSummary])
def list_peas(project_id: int, session: Session = Depends(get_session)) -> list[PeaSummary]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    peas = session.exec(
        select(Pea).where(Pea.project_id == project_id).order_by(Pea.created_at)
    ).all()
    return [_summary(p) for p in peas]


@router.get("/api/peas/{pea_id}", response_model=PeaDetail)
def get_pea(pea_id: int, session: Session = Depends(get_session)) -> PeaDetail:
    pea = _pea_or_404(session, pea_id)
    # Re-derive the parsed model from the stored .aml (single source of truth).
    parsed = parse_aml(pea.aml_content.encode("utf-8"), pea.aml_filename)
    return pea_detail(_summary(pea), parsed)


@router.patch("/api/peas/{pea_id}", response_model=PeaSummary)
def rename_pea(
    pea_id: int, body: NameUpdate, session: Session = Depends(get_session)
) -> PeaSummary:
    pea = _pea_or_404(session, pea_id)
    pea.name = body.name
    session.add(pea)
    session.commit()
    session.refresh(pea)
    return _summary(pea)


@router.delete("/api/peas/{pea_id}", status_code=204)
def delete_pea(pea_id: int, session: Session = Depends(get_session)) -> None:
    session.delete(_pea_or_404(session, pea_id))
    session.commit()
