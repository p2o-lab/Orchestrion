"""PEA import + CRUD, scoped to a project.

Import is the gate: an uploaded `.aml` is parsed and validated *before* it is stored,
so a bad file is rejected (HTTP 422 with the parser's message for the UI to highlight)
and never becomes a row. Every stored PEA is therefore known-parseable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from orchestrion.api.mtp_import import parse_aml
from orchestrion.api.schemas import NameUpdate, PeaDetail, PeaSummary, pea_detail
from orchestrion.db.engine import get_session
from orchestrion.db.models import Pea, Project
from orchestrion.mtp.caex import MtpError

router = APIRouter(tags=["peas"])


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
    response_model=PeaSummary,
    status_code=201,
    responses={422: {"description": "the uploaded MTP failed to parse"}},
)
async def import_pea(
    project_id: int,
    name: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> PeaSummary:
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

    pea = Pea(
        project_id=project_id,
        name=name,
        aml_filename=filename,
        aml_content=content.decode("utf-8", errors="replace"),
        endpoint_url=parsed.endpoints[0].url if parsed.endpoints else "",
    )
    session.add(pea)
    session.commit()
    session.refresh(pea)
    return _summary(pea)


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
