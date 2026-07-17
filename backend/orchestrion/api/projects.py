"""Project CRUD — a workspace of modular plants."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from orchestrion.api.schemas import NameUpdate, ProjectCreate, ProjectRead
from orchestrion.db.engine import get_session
from orchestrion.db.models import Project

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _read(project: Project) -> ProjectRead:
    return ProjectRead(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        pea_count=len(project.peas),
    )


def _get_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return project


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)) -> ProjectRead:
    project = Project(name=body.name)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read(project)


@router.get("", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectRead]:
    projects = session.exec(select(Project).order_by(Project.created_at)).all()
    return [_read(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, session: Session = Depends(get_session)) -> ProjectRead:
    return _read(_get_or_404(session, project_id))


@router.patch("/{project_id}", response_model=ProjectRead)
def rename_project(
    project_id: int, body: NameUpdate, session: Session = Depends(get_session)
) -> ProjectRead:
    project = _get_or_404(session, project_id)
    project.name = body.name
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read(project)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> None:
    project = _get_or_404(session, project_id)
    session.delete(project)          # cascades to its PEAs (models.Project.peas)
    session.commit()
