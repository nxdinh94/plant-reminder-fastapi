from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.media_storage import (
    MAX_FILE_SIZE,
    MediaStorageConfigurationError,
    MediaStorageError,
    MediaStorageRemoteError,
    MediaStorageValidationError,
    store_upload_file,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])

@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    if file.size is not None and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 10MB.",
        )

    try:
        stored = await store_upload_file(file, user_id=str(current_user.id))
    except MediaStorageValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except MediaStorageConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except MediaStorageRemoteError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except MediaStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {str(exc)}",
        ) from exc

    return {"path": stored.path, "file_id": stored.file_id}
