"""利用者マスタのJSON API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.models import Gender, UserMaster
from app.services import users as service
from app.services.reservations import ValidationError

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    name: str
    gender: Gender
    kana: str | None = None
    condition: str | None = None
    notes: str | None = None
    training: str | None = None
    bathing_type: str | None = None
    fixed_bed_id: str | None = None
    cm_name: str | None = None
    cm_office: str | None = None
    cm_phone: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    gender: Gender | None = None
    kana: str | None = None
    condition: str | None = None
    notes: str | None = None
    training: str | None = None
    bathing_type: str | None = None
    fixed_bed_id: str | None = None
    cm_name: str | None = None
    cm_office: str | None = None
    cm_phone: str | None = None


def _handle(error: ValidationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@router.get("", response_model=list[UserMaster])
def list_users(
    keyword: str | None = None,
    session: Session = Depends(get_session),
) -> list[UserMaster]:
    return service.list_users(session, keyword=keyword)


@router.get("/{user_id}", response_model=UserMaster)
def get_one(user_id: int, session: Session = Depends(get_session)) -> UserMaster:
    user = service.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="利用者が見つかりません")
    return user


@router.post("", response_model=UserMaster, status_code=201)
def create(
    payload: UserCreate,
    session: Session = Depends(get_session),
) -> UserMaster:
    try:
        return service.create_user(session, **payload.model_dump())
    except ValidationError as error:
        raise _handle(error) from error


@router.patch("/{user_id}", response_model=UserMaster)
def update(
    user_id: int,
    payload: UserUpdate,
    session: Session = Depends(get_session),
) -> UserMaster:
    try:
        return service.update_user(session, user_id, **payload.model_dump())
    except ValidationError as error:
        raise _handle(error) from error


@router.delete("/{user_id}", status_code=204)
def delete(user_id: int, session: Session = Depends(get_session)) -> None:
    try:
        service.delete_user(session, user_id)
    except ValidationError as error:
        raise _handle(error) from error
