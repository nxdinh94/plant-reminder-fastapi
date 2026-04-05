from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version, soft_delete
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.plant import Plant
from app.models.user import User
from app.schemas.plant import PlantCreate, PlantResponse, PlantUpdate


router = APIRouter(prefix="/plants", tags=["plants"])


@router.get("", response_model=list[PlantResponse])
def list_plants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Plant]:
    return list(
        db.execute(
            select(Plant)
            .where(
                Plant.user_id == current_user.id,
                Plant.deleted_at.is_(None),
            )
            .order_by(Plant.updated_at.desc())
        ).scalars()
    )


@router.post("", response_model=PlantResponse, status_code=status.HTTP_201_CREATED)
def create_plant(
    payload: PlantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Plant:
    plant = Plant(user_id=current_user.id, **payload.model_dump())
    db.add(plant)
    db.commit()
    db.refresh(plant)
    return plant


@router.get("/{plant_id}", response_model=PlantResponse)
def get_plant(
    plant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Plant:
    plant = db.execute(
        select(Plant).where(
            Plant.id == plant_id,
            Plant.user_id == current_user.id,
            Plant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
    return plant


@router.patch("/{plant_id}", response_model=PlantResponse)
def update_plant(
    plant_id: str,
    payload: PlantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Plant:
    plant = db.execute(
        select(Plant).where(
            Plant.id == plant_id,
            Plant.user_id == current_user.id,
            Plant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(plant, key, value)
    bump_version(plant)
    db.add(plant)
    db.commit()
    db.refresh(plant)
    return plant


@router.delete("/{plant_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_plant(
    plant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    plant = db.execute(
        select(Plant).where(
            Plant.id == plant_id,
            Plant.user_id == current_user.id,
            Plant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
    soft_delete(plant)
    db.add(plant)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
