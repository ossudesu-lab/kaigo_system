"""入浴回数と入浴日の候補（daily_reports_spec.md / README「入浴回数の設計」）。

- 入浴回数 = 泊数 ÷ 3 の切り上げ
- 最終回は退所日の前日に置き、残りは3日ずつさかのぼる
- 日帰りは設定（include_daytrip）しだいで1回か0回
- 人が調整した入浴日は自動計算より優先し、元に戻すこともできる
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from app.config import load_config
from app.models import Reservation
from app.services import bathing


def _stay(check_in: date, nights: int) -> Reservation:
    return Reservation(
        user_master_id=1,
        check_in=check_in,
        check_out=check_in + timedelta(days=nights),
    )


@pytest.mark.parametrize(
    "nights, expected",
    [(1, 1), (2, 1), (3, 1), (4, 2), (6, 2), (7, 3), (9, 3), (10, 4)],
)
def test_入浴回数は3泊ごとに1回の切り上げ(nights, expected):
    assert bathing.bath_count(nights) == expected


def test_日帰りは設定で1回にも0回にもできる(monkeypatch):
    config = load_config()
    assert bathing.bath_count(0) == 1  # 既定（include_daytrip = true）

    off = dataclasses.replace(
        config, bathing=dataclasses.replace(config.bathing, include_daytrip=False)
    )
    monkeypatch.setattr(bathing, "load_config", lambda: off)
    assert bathing.bath_count(0) == 0
    assert bathing.auto_days(_stay(date(2026, 7, 1), 0)) == []


def test_日帰りの入浴日はその日():
    assert bathing.auto_days(_stay(date(2026, 7, 1), 0)) == [date(2026, 7, 1)]


def test_1泊なら入所日に入浴():
    # 退所日の前日 = 入所日
    assert bathing.auto_days(_stay(date(2026, 7, 1), 1)) == [date(2026, 7, 1)]


def test_6泊なら2回で最終回は退所日の前日():
    # 7/1 入所 → 7/7 退所。最終回は 7/6、そこから3日さかのぼって 7/3
    assert bathing.auto_days(_stay(date(2026, 7, 1), 6)) == [
        date(2026, 7, 3),
        date(2026, 7, 6),
    ]


def test_月をまたぐ滞在でも退所日の前日に入る():
    # 7/30 入所 → 8/3 退所（4泊 = 2回）
    assert bathing.auto_days(_stay(date(2026, 7, 30), 4)) == [
        date(2026, 7, 30),
        date(2026, 8, 2),
    ]


@pytest.mark.parametrize("nights", range(1, 31))
def test_どの泊数でも候補は滞在中に収まり最終回は退所日の前日(nights):
    reservation = _stay(date(2026, 7, 1), nights)
    days = bathing.auto_days(reservation)

    assert len(days) == bathing.bath_count(nights)
    assert days[-1] == reservation.check_out - timedelta(days=1)
    assert all(reservation.check_in <= d < reservation.check_out for d in days)
    assert days == sorted(set(days))  # 同じ日に2回入れない


# --- ここから下はDBを使う（人が調整した入浴日） ---


def _saved_stay(session, check_in: date, nights: int) -> Reservation:
    from app.models import Gender
    from app.services import reservations as reservation_service
    from app.services import users as user_service

    user = user_service.create_user(session, name="佐藤 花子", gender=Gender.FEMALE)
    return reservation_service.create_reservation(
        session,
        user_master_id=user.id,
        check_in=check_in,
        check_out=check_in + timedelta(days=nights),
    )


def test_手で動かした入浴日が自動計算より優先される(session):
    reservation = _saved_stay(session, date(2026, 7, 1), 6)

    bathing.set_days(session, reservation.id, [date(2026, 7, 2), date(2026, 7, 5)])

    session.refresh(reservation)
    assert reservation.bathing_is_manual
    assert bathing.days_for(session, reservation) == [
        date(2026, 7, 2),
        date(2026, 7, 5),
    ]


def test_滞在期間の外の日は入浴日にできない(session):
    from app.services.reservations import ValidationError

    reservation = _saved_stay(session, date(2026, 7, 1), 3)

    with pytest.raises(ValidationError):
        bathing.set_days(session, reservation.id, [date(2026, 7, 10)])


def test_自動に戻すと候補の日に戻る(session):
    reservation = _saved_stay(session, date(2026, 7, 1), 6)
    bathing.set_days(session, reservation.id, [date(2026, 7, 2)])

    bathing.reset_days(session, reservation.id)

    session.refresh(reservation)
    assert not reservation.bathing_is_manual
    assert bathing.days_for(session, reservation) == [
        date(2026, 7, 3),
        date(2026, 7, 6),
    ]
