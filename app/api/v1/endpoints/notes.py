from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version, soft_delete
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.note import Note
from app.models.plant import Plant
from app.models.user import User
from app.schemas.note import NoteCreate, NoteResponse, NoteUpdate


router = APIRouter(prefix="/notes", tags=["notes"])


def _ensure_plant_owner(db: Session, plant_id: str, user_id: str) -> None:
    plant = db.execute(
        select(Plant).where(
            Plant.id == plant_id,
            Plant.user_id == user_id,
            Plant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")


@router.get("", response_model=list[NoteResponse])
def list_notes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Note]:
    return list(
        db.execute(
            select(Note)
            .where(
                Note.user_id == current_user.id,
                Note.deleted_at.is_(None),
            )
            .order_by(Note.entry_date.desc(), Note.updated_at.desc())
        ).scalars()
    )


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(
    payload: NoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Note:
    _ensure_plant_owner(db, payload.plant_id, current_user.id)
    entity = Note(user_id=current_user.id, **payload.model_dump())
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.patch("/{note_id}", response_model=NoteResponse)
def update_note(
    note_id: str,
    payload: NoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Note:
    entity = db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.user_id == current_user.id,
            Note.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    bump_version(entity)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_note(
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    entity = db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.user_id == current_user.id,
            Note.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    soft_delete(entity)
    db.add(entity)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
