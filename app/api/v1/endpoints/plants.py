from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version, soft_delete
from app.core.config import settings
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.plant import Plant
from app.models.user import User
from app.schemas.plant import PlantCreate, PlantResponse, PlantUpdate


router = APIRouter(prefix="/plants", tags=["plants"])


def _path_to_url(image_path: str | None) -> str | None:
    if not image_path:
        return None
    if image_path.startswith("http"):
        return image_path
    normalized = image_path.replace("\\", "/")
    upload_dir_str = str(settings.upload_dir_path).replace("\\", "/")
    if normalized.startswith(upload_dir_str):
        relative = normalized[len(upload_dir_str):].lstrip("/")
        return f"/uploads/{relative}"
    if "/uploads/" in normalized:
        idx = normalized.index("/uploads/")
        return normalized[idx:]
    return f"/uploads/{normalized.rsplit('/', 1)[-1]}"


def _plant_to_response(plant: Plant) -> PlantResponse:
    data = {
        "id": plant.id,
        "user_id": plant.user_id,
        "name": plant.name,
        "species": plant.species,
        "potted_date": plant.potted_date,
        "image_path": _path_to_url(plant.image_path),
        "note": plant.note,
        "is_paused": plant.is_paused,
        "created_at": plant.created_at,
        "updated_at": plant.updated_at,
        "deleted_at": plant.deleted_at,
        "version": plant.version,
        "overview": plant.overview,
        "water": plant.water,
        "sunlight": plant.sunlight,
        "fertilizer": plant.fertilizer,
        "propagating": plant.propagating,
        "varieties": plant.varieties,
        "humidity": plant.humidity,
        "temperature": plant.temperature,
        "soil": plant.soil,
        "running": plant.running,
        "potting_and_repotting": plant.potting_and_repotting,
        "pests_and_diseases": plant.pests_and_diseases,
        "toxicity": plant.toxicity,
        "propagation": plant.propagation,
    }
    return PlantResponse(**data)


@router.get("", response_model=list[PlantResponse])
def list_plants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PlantResponse]:
    plants = list(
        db.execute(
            select(Plant)
            .where(
                Plant.user_id == current_user.id,
                Plant.deleted_at.is_(None),
            )
            .order_by(Plant.updated_at.desc())
        ).scalars()
    )
    return [_plant_to_response(p) for p in plants]


@router.post("", response_model=PlantResponse, status_code=status.HTTP_201_CREATED)
def create_plant(
    payload: PlantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlantResponse:
    plant = Plant(user_id=current_user.id, **payload.model_dump())
    db.add(plant)
    db.commit()
    db.refresh(plant)
    return _plant_to_response(plant)


@router.get("/{plant_id}", response_model=PlantResponse)
def get_plant(
    plant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlantResponse:
    plant = db.execute(
        select(Plant).where(
            Plant.id == plant_id,
            Plant.user_id == current_user.id,
            Plant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
    return _plant_to_response(plant)


@router.patch("/{plant_id}", response_model=PlantResponse)
def update_plant(
    plant_id: str,
    payload: PlantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlantResponse:
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
    return _plant_to_response(plant)


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
    db.delete(plant)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
