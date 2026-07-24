"""予約のJSON API。

画面（app/web）とは別に、JSONを返すエンドポイントをここに置く。
分けてあるのは、将来フロントを別のもの（Next.jsなど）に載せ替えるとき、
このAPIをそのまま叩けるようにしておくため。
どちらも app/services を呼ぶだけの薄い層にしてある。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.models import Gender, Reservation
from app.services import reservations as service

router = APIRouter(prefix="/api/reservations", tags=["reservations"])


class ReservationRead(BaseModel):
    """予約を返す形。

    名前と性別は利用者マスタが持っているので、そのままでは予約だけ返しても
    誰の予約か分からない。画面側で毎回マスタを引き直さなくて済むよう、
    ここで一緒に返す。
    """

    id: int
    user_master_id: int
    guest_name: str
    gender: Gender
    bed_id: str | None
    check_in: date
    check_out: date
    is_tentative: bool
    nights: int

    @classmethod
    def of(cls, reservation: Reservation) -> ReservationRead:
        return cls(
            id=reservation.id,  # type: ignore[arg-type]
            user_master_id=reservation.user_master_id,
            guest_name=reservation.guest_name,
            gender=reservation.gender,
            bed_id=reservation.bed_id,
            check_in=reservation.check_in,
            check_out=reservation.check_out,
            is_tentative=reservation.is_tentative,
            nights=reservation.nights,
        )


class ReservationCreate(BaseModel):
    user_master_id: int
    check_in: date
    check_out: date
    bed_id: str | None = None
    is_tentative: bool = False


class ReservationUpdate(BaseModel):
    user_master_id: int | None = None
    check_in: date | None = None
    check_out: date | None = None
    is_tentative: bool | None = None


class BedAssign(BaseModel):
    bed_id: str


def _handle(error: service.ValidationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@router.get("", response_model=list[ReservationRead])
def list_reservations(
    start: date,
    end: date,
    session: Session = Depends(get_session),
) -> list[ReservationRead]:
    return [ReservationRead.of(r) for r in service.list_in_period(session, start, end)]


@router.get("/unassigned", response_model=list[ReservationRead])
def list_unassigned(session: Session = Depends(get_session)) -> list[ReservationRead]:
    """部屋未定リスト。"""
    return [ReservationRead.of(r) for r in service.list_unassigned(session)]


@router.get("/{reservation_id}", response_model=ReservationRead)
def get_one(
    reservation_id: int,
    session: Session = Depends(get_session),
) -> ReservationRead:
    reservation = service.get_reservation(session, reservation_id)
    if reservation is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")
    return ReservationRead.of(reservation)


@router.post("", response_model=ReservationRead, status_code=201)
def create(
    payload: ReservationCreate,
    session: Session = Depends(get_session),
) -> ReservationRead:
    try:
        return ReservationRead.of(service.create_reservation(
            session,
            user_master_id=payload.user_master_id,
            check_in=payload.check_in,
            check_out=payload.check_out,
            bed_id=payload.bed_id,
            is_tentative=payload.is_tentative,
        ))
    except service.ValidationError as error:
        raise _handle(error) from error


@router.patch("/{reservation_id}", response_model=ReservationRead)
def update(
    reservation_id: int,
    payload: ReservationUpdate,
    session: Session = Depends(get_session),
) -> ReservationRead:
    try:
        return ReservationRead.of(service.update_reservation(
            session,
            reservation_id,
            user_master_id=payload.user_master_id,
            check_in=payload.check_in,
            check_out=payload.check_out,
            is_tentative=payload.is_tentative,
        ))
    except service.ValidationError as error:
        raise _handle(error) from error


@router.delete("/{reservation_id}", status_code=204)
def delete(reservation_id: int, session: Session = Depends(get_session)) -> None:
    try:
        service.delete_reservation(session, reservation_id)
    except service.ValidationError as error:
        raise _handle(error) from error


@router.post("/{reservation_id}/assign", response_model=ReservationRead)
def assign(
    reservation_id: int,
    payload: BedAssign,
    session: Session = Depends(get_session),
) -> ReservationRead:
    """部屋未定リストの予約に、部屋を割り当てる。"""
    try:
        return ReservationRead.of(
            service.assign_bed(session, reservation_id, payload.bed_id)
        )
    except service.ValidationError as error:
        raise _handle(error) from error


@router.post("/{reservation_id}/unassign", response_model=ReservationRead)
def unassign(
    reservation_id: int,
    session: Session = Depends(get_session),
) -> ReservationRead:
    """部屋の割り当てを外して、部屋未定リストに戻す。"""
    try:
        return ReservationRead.of(service.unassign_bed(session, reservation_id))
    except service.ValidationError as error:
        raise _handle(error) from error
