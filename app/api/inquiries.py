"""問い合わせとCMマスタのJSON API。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.models import CareManager, Gender, Inquiry
from app.services import care_managers as cm_service
from app.services import inquiries as service
from app.services.reservations import ValidationError

router = APIRouter(tags=["inquiries"])


def _handle(error: ValidationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


# ---------------------------------------------------------------- CMマスタ


class CareManagerCreate(BaseModel):
    name: str
    office: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    notes: str | None = None


class CareManagerUpdate(BaseModel):
    name: str | None = None
    office: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    notes: str | None = None


@router.get("/api/care-managers", response_model=list[CareManager])
def list_care_managers(
    keyword: str | None = None,
    session: Session = Depends(get_session),
) -> list[CareManager]:
    return cm_service.list_care_managers(session, keyword=keyword)


@router.get("/api/care-managers/{care_manager_id}", response_model=CareManager)
def get_care_manager(
    care_manager_id: int,
    session: Session = Depends(get_session),
) -> CareManager:
    care_manager = cm_service.get_care_manager(session, care_manager_id)
    if care_manager is None:
        raise HTTPException(status_code=404, detail="CMが見つかりません")
    return care_manager


@router.post("/api/care-managers", response_model=CareManager, status_code=201)
def create_care_manager(
    payload: CareManagerCreate,
    session: Session = Depends(get_session),
) -> CareManager:
    try:
        return cm_service.create_care_manager(session, **payload.model_dump())
    except ValidationError as error:
        raise _handle(error) from error


@router.patch("/api/care-managers/{care_manager_id}", response_model=CareManager)
def update_care_manager(
    care_manager_id: int,
    payload: CareManagerUpdate,
    session: Session = Depends(get_session),
) -> CareManager:
    try:
        return cm_service.update_care_manager(
            session, care_manager_id, **payload.model_dump()
        )
    except ValidationError as error:
        raise _handle(error) from error


@router.delete("/api/care-managers/{care_manager_id}", status_code=204)
def delete_care_manager(
    care_manager_id: int,
    session: Session = Depends(get_session),
) -> None:
    try:
        cm_service.delete_care_manager(session, care_manager_id)
    except ValidationError as error:
        raise _handle(error) from error


# ---------------------------------------------------------------- 問い合わせ


class InquiryRead(BaseModel):
    """問い合わせを返す形。

    対象の利用者名はマスタ側にあることがあるので、解決した名前を一緒に返す。
    """

    id: int
    inquiry_date: date
    kind: str
    status: str
    care_manager_id: int | None
    user_master_id: int | None
    guest_name: str | None
    display_name: str
    desired_check_in: date | None
    desired_check_out: date | None
    memo: str | None
    reservation_id: int | None
    is_registered_user: bool

    @classmethod
    def of(cls, inquiry: Inquiry) -> InquiryRead:
        return cls(
            id=inquiry.id,  # type: ignore[arg-type]
            inquiry_date=inquiry.inquiry_date,
            kind=inquiry.kind,
            status=inquiry.status,
            care_manager_id=inquiry.care_manager_id,
            user_master_id=inquiry.user_master_id,
            guest_name=inquiry.guest_name,
            display_name=inquiry.display_name,
            desired_check_in=inquiry.desired_check_in,
            desired_check_out=inquiry.desired_check_out,
            memo=inquiry.memo,
            reservation_id=inquiry.reservation_id,
            is_registered_user=inquiry.is_registered_user,
        )


class InquiryCreate(BaseModel):
    inquiry_date: date
    kind: str
    status: str | None = None
    care_manager_id: int | None = None
    user_master_id: int | None = None
    guest_name: str | None = None
    desired_check_in: date | None = None
    desired_check_out: date | None = None
    memo: str | None = None


class InquiryUpdate(BaseModel):
    inquiry_date: date | None = None
    kind: str | None = None
    status: str | None = None
    care_manager_id: int | None = None
    user_master_id: int | None = None
    guest_name: str | None = None
    desired_check_in: date | None = None
    desired_check_out: date | None = None
    memo: str | None = None


class ConvertRequest(BaseModel):
    # 未指定なら、マスタ登録済みかどうかで自動的に決まる
    is_tentative: bool | None = None
    # マスタ未登録の方を変換するときだけ必要
    gender: Gender | None = None


@router.get("/api/inquiries", response_model=list[InquiryRead])
def list_inquiries(
    status: str | None = None,
    kind: str | None = None,
    care_manager_id: int | None = None,
    office: str | None = None,
    guest_keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    desired_from: date | None = None,
    desired_to: date | None = None,
    keyword: str | None = None,
    session: Session = Depends(get_session),
) -> list[InquiryRead]:
    rows = service.search_inquiries(
        session,
        status=status,
        kind=kind,
        care_manager_id=care_manager_id,
        office=office,
        guest_keyword=guest_keyword,
        date_from=date_from,
        date_to=date_to,
        desired_from=desired_from,
        desired_to=desired_to,
        keyword=keyword,
    )
    return [InquiryRead.of(row) for row in rows]


@router.get("/api/inquiries/{inquiry_id}", response_model=InquiryRead)
def get_inquiry(
    inquiry_id: int,
    session: Session = Depends(get_session),
) -> InquiryRead:
    inquiry = service.get_inquiry(session, inquiry_id)
    if inquiry is None:
        raise HTTPException(status_code=404, detail="問い合わせが見つかりません")
    return InquiryRead.of(inquiry)


@router.post("/api/inquiries", response_model=InquiryRead, status_code=201)
def create_inquiry(
    payload: InquiryCreate,
    session: Session = Depends(get_session),
) -> InquiryRead:
    try:
        return InquiryRead.of(service.create_inquiry(session, **payload.model_dump()))
    except ValidationError as error:
        raise _handle(error) from error


@router.patch("/api/inquiries/{inquiry_id}", response_model=InquiryRead)
def update_inquiry(
    inquiry_id: int,
    payload: InquiryUpdate,
    session: Session = Depends(get_session),
) -> InquiryRead:
    try:
        return InquiryRead.of(
            service.update_inquiry(session, inquiry_id, **payload.model_dump())
        )
    except ValidationError as error:
        raise _handle(error) from error


@router.delete("/api/inquiries/{inquiry_id}", status_code=204)
def delete_inquiry(
    inquiry_id: int,
    session: Session = Depends(get_session),
) -> None:
    try:
        service.delete_inquiry(session, inquiry_id)
    except ValidationError as error:
        raise _handle(error) from error


@router.post("/api/inquiries/{inquiry_id}/convert")
def convert(
    inquiry_id: int,
    payload: ConvertRequest,
    session: Session = Depends(get_session),
) -> dict:
    """問い合わせを予約データに変換する。"""
    try:
        reservation = service.convert_to_reservation(
            session,
            inquiry_id,
            is_tentative=payload.is_tentative,
            gender=payload.gender,
        )
    except ValidationError as error:
        raise _handle(error) from error

    return {
        "inquiry_id": inquiry_id,
        "reservation_id": reservation.id,
        "guest_name": reservation.guest_name,
        "check_in": reservation.check_in.isoformat(),
        "check_out": reservation.check_out.isoformat(),
        "is_tentative": reservation.is_tentative,
    }
