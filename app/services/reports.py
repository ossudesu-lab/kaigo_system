"""当日帳票（当日台帳・入浴表）。

どちらも「その日いる利用者の一覧」という同じ元データから作る。
違うのは並べ方と出す項目だけなので、土台を1つにして2つの見せ方を出す
（daily_reports_spec.md の設計方針）。

新しく入力する情報はなく、予約データ × 利用者マスタの掛け合わせで出す。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session

from app.config import load_config
from app.models import Reservation
from app.services import bathing
from app.services import reservations as reservation_service


@dataclass
class Attendee:
    """その日いる利用者ひとり分。台帳にも入浴表にも、ここから必要な列を出す。"""

    reservation: Reservation
    bathing_days: list[date]

    @property
    def name(self) -> str:
        return self.reservation.user.name

    @property
    def bed_id(self) -> str | None:
        return self.reservation.bed_id

    @property
    def condition(self) -> str | None:
        return self.reservation.user.condition

    @property
    def notes(self) -> str | None:
        return self.reservation.user.notes

    @property
    def training(self) -> str | None:
        return self.reservation.user.training

    @property
    def bathing_type(self) -> str | None:
        return self.reservation.user.bathing_type

    @property
    def is_tentative(self) -> bool:
        return self.reservation.is_tentative

    def is_checkin(self, day: date) -> bool:
        return self.reservation.check_in == day

    def is_checkout(self, day: date) -> bool:
        return self.reservation.check_out == day

    def bathes_on(self, day: date) -> bool:
        return day in self.bathing_days

    @property
    def expected_baths(self) -> int:
        """ルール上、この滞在で入るはずの回数。"""
        return bathing.bath_count(self.reservation.nights)

    @property
    def is_bath_short(self) -> bool:
        """入浴日がルールの回数に足りていないか。

        手で調整したあとに日程が縮んで回数が減ることがある。減ったまま
        気づかないと入浴の抜けにつながるので、画面で分かるようにする。
        """
        return len(self.bathing_days) < self.expected_baths


def _bed_order(bed_id: str | None) -> tuple[int, int]:
    """並べ替え用の順番。

    部屋番号の文字列でそのまま並べると A10 が A2 より前に来てしまうので、
    config.toml に並べた順（＝現場の部屋の並び）をそのまま使う。

    部屋が未定の人は末尾に回す。ただし一覧から外すことはしない。
    台帳から漏れると現場で事故につながるため（daily_reports_spec.md）。
    """
    if bed_id is None:
        return (1, 0)

    config = load_config()
    for index, bed in enumerate(config.beds):
        if bed.id == bed_id:
            return (0, index)
    return (1, 0)


def attendees_on(session: Session, day: date) -> list[Attendee]:
    """その日いる利用者。部屋番号順、部屋未定は末尾。

    仮予約も含める。当日になっても仮のままの予約は、来るか来ないかを
    現場で確かめる必要があるので、伏せずに出したうえで印を付ける。
    """
    reservations = reservation_service.list_in_period(session, day, day)

    attendees = [
        Attendee(
            reservation=reservation,
            bathing_days=bathing.days_for(session, reservation),
        )
        for reservation in reservations
        if reservation.covers(day)
    ]

    attendees.sort(key=lambda a: _bed_order(a.bed_id))
    return attendees


# ---------------------------------------------------------------- 当日台帳


@dataclass
class LedgerBlock:
    """当日台帳の1ブロック（5列セット1つぶん）。"""

    rows: list[Attendee]


def ledger_blocks(attendees: list[Attendee]) -> list[LedgerBlock]:
    """台帳を、設定された数のブロックに分ける。

    一般的なショートステイの帳票では5列セットを横に複数ブロック並べることがある。
    紙面に収めるための都合で、人数や用紙によって変わるため設定で変えられるようにしている。

    左のブロックから順に埋める（上から下へ読んで、右のブロックへ移る）。
    """
    config = load_config()
    count = max(1, config.reports.ledger_blocks)

    # 端数は前のブロックに寄せる。最後のブロックだけ短くなる。
    per_block = -(-len(attendees) // count) if attendees else 0

    blocks: list[LedgerBlock] = []
    for i in range(count):
        start = i * per_block
        blocks.append(LedgerBlock(rows=attendees[start : start + per_block]))

    return blocks


# ---------------------------------------------------------------- 入浴表


@dataclass
class BathingRow:
    """入浴表の1行。"""

    day: date
    attendee: Attendee


@dataclass
class BathingSheet:
    """ある1日の入浴表。"""

    day: date
    rows: list[BathingRow]

    @property
    def count(self) -> int:
        return len(self.rows)


def bathing_sheet(session: Session, day: date) -> BathingSheet:
    """その日の入浴表。その日に入浴する人だけを並べる。"""
    rows = [
        BathingRow(day=day, attendee=attendee)
        for attendee in attendees_on(session, day)
        if attendee.bathes_on(day)
    ]
    return BathingSheet(day=day, rows=rows)


def bathing_week(session: Session, start: date) -> list[BathingSheet]:
    """start から7日分の入浴表。"""
    return [bathing_sheet(session, start + timedelta(days=i)) for i in range(7)]
