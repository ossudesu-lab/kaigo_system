"""帳票のCSV出力と、入浴日の手動調整API。

現場には紙で回す運用が残っているため、CSVで出せるようにする
（README「設計方針4」）。
"""

from __future__ import annotations

import csv
import io
import urllib.parse
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.services import bathing, reports
from app.services.reservations import ValidationError

router = APIRouter(prefix="/api/reports", tags=["reports"])

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


def _csv_response(rows: list[list[str]], filename: str) -> StreamingResponse:
    """CSVを返す。

    Excel が文字化けせずに開けるよう、UTF-8 の先頭に BOM を付ける。
    付けないと Windows の Excel は日本語をシフトJISとして読もうとして崩れる。
    """
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows(rows)
    buffer.seek(0)

    # HTTPヘッダーはラテン文字しか通らないので、日本語のファイル名はそのまま
    # 書けない。RFC 5987 の filename*= でUTF-8を百分率エンコードして渡す。
    # 古いブラウザ向けに、ASCIIだけの filename= も併記しておく。
    quoted = urllib.parse.quote(filename)
    disposition = f"attachment; filename=\"report.csv\"; filename*=UTF-8''{quoted}"

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


def _label(day: date) -> str:
    return f"{day.strftime('%Y/%m/%d')}（{WEEKDAY_LABELS[day.weekday()]}）"


@router.get("/bathing.csv")
def bathing_csv(
    day: date | None = None,
    span: str = "day",
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """入浴表のCSV。当日分と1週間分のどちらも出せる。"""
    target = day or date.today()

    if span == "week":
        sheets = reports.bathing_week(session, target)
        filename = f"入浴表_{target:%Y%m%d}_1週間.csv"
    else:
        sheets = [reports.bathing_sheet(session, target)]
        filename = f"入浴表_{target:%Y%m%d}.csv"

    rows: list[list[str]] = [["日付", "部屋", "名前", "入浴種別", "備考"]]
    for sheet in sheets:
        if not sheet.rows:
            # 入浴者がいない日も行を残す。抜けていると、その日を
            # 印刷し忘れたのか本当にいないのか判断できない。
            rows.append([_label(sheet.day), "", "（入浴者なし）", "", ""])
            continue
        for row in sheet.rows:
            attendee = row.attendee
            rows.append([
                _label(sheet.day),
                attendee.bed_id or "部屋未定",
                attendee.name,
                attendee.bathing_type or "",
                "仮予約" if attendee.is_tentative else "",
            ])

    return _csv_response(rows, filename)


@router.get("/ledger.csv")
def ledger_csv(
    day: date | None = None,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """当日台帳のCSV。

    仕様がCSV出力を求めているのは入浴表だけだが、台帳も紙で使う場面が
    あるので同じ形で出せるようにしてある。
    """
    target = day or date.today()
    attendees = reports.attendees_on(session, target)

    rows: list[list[str]] = [
        ["部屋", "名前", "疾患", "注意事項", "できる訓練", "備考"]
    ]
    for attendee in attendees:
        marks = []
        if attendee.is_checkin(target):
            marks.append("入所")
        if attendee.is_checkout(target):
            marks.append("退所")
        if attendee.is_tentative:
            marks.append("仮予約")

        rows.append([
            attendee.bed_id or "部屋未定",
            attendee.name,
            attendee.condition or "",
            attendee.notes or "",
            attendee.training or "",
            "/".join(marks),
        ])

    return _csv_response(rows, f"当日台帳_{target:%Y%m%d}.csv")


class BathingDaysUpdate(BaseModel):
    days: list[date]


@router.get("/bathing-days/{reservation_id}")
def get_bathing_days(
    reservation_id: int,
    session: Session = Depends(get_session),
) -> dict:
    from app.models import Reservation

    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")

    return {
        "reservation_id": reservation_id,
        "is_manual": reservation.bathing_is_manual,
        "days": [d.isoformat() for d in bathing.days_for(session, reservation)],
        "auto_days": [d.isoformat() for d in bathing.auto_days(reservation)],
        "expected_count": bathing.bath_count(reservation.nights),
    }


@router.put("/bathing-days/{reservation_id}")
def set_bathing_days(
    reservation_id: int,
    payload: BathingDaysUpdate,
    session: Session = Depends(get_session),
) -> dict:
    """入浴日を手動で決め直す。以降この予約は自動計算の対象から外れる。"""
    try:
        days = bathing.set_days(session, reservation_id, payload.days)
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {"reservation_id": reservation_id, "is_manual": True,
            "days": [d.isoformat() for d in days]}


@router.delete("/bathing-days/{reservation_id}")
def reset_bathing_days(
    reservation_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """手動の調整を捨てて、自動の候補に戻す。"""
    try:
        days = bathing.reset_days(session, reservation_id)
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {"reservation_id": reservation_id, "is_manual": False,
            "days": [d.isoformat() for d in days]}
