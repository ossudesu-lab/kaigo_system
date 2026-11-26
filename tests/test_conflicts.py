"""部屋の重複検知（reservation_spec.md / README「設計方針3」）。

- 同じ部屋で泊まりが重なれば重複
- 退所日に次の人が入所する「入れ替わり」は重複にしない
- 部屋未定の予約は重複の対象外
- 重複していても予約は受け付ける（止めない）
"""

from __future__ import annotations

from datetime import date

from app.config import load_config
from app.models import Gender
from app.services import grid as grid_service
from app.services import reservations as reservation_service
from app.services import users as user_service


def _bed(index: int = 0) -> str:
    return load_config().beds[index].id


def _book(session, check_in: date, check_out: date, bed_id: str | None):
    user = user_service.create_user(session, name="佐藤 花子", gender=Gender.FEMALE)
    return reservation_service.create_reservation(
        session,
        user_master_id=user.id,
        check_in=check_in,
        check_out=check_out,
        bed_id=bed_id,
    )


def test_泊まりが重なれば重複として受け付ける(session):
    a = _book(session, date(2026, 7, 1), date(2026, 7, 5), _bed())
    # 同じ部屋に重ねて入れても、エラーにせず登録はできる
    b = _book(session, date(2026, 7, 3), date(2026, 7, 7), _bed())

    assert reservation_service.find_conflicts([a, b]) == {a.id, b.id}


def test_退所日に次の人が入るのは重複ではない(session):
    a = _book(session, date(2026, 7, 1), date(2026, 7, 5), _bed())
    b = _book(session, date(2026, 7, 5), date(2026, 7, 8), _bed())

    assert reservation_service.find_conflicts([a, b]) == set()


def test_別の部屋なら重ならない(session):
    a = _book(session, date(2026, 7, 1), date(2026, 7, 5), _bed(0))
    b = _book(session, date(2026, 7, 1), date(2026, 7, 5), _bed(1))

    assert reservation_service.find_conflicts([a, b]) == set()


def test_部屋未定どうしは重複にしない(session):
    a = _book(session, date(2026, 7, 1), date(2026, 7, 5), None)
    b = _book(session, date(2026, 7, 1), date(2026, 7, 5), None)

    assert reservation_service.find_conflicts([a, b]) == set()


def _row(grid, bed_id):
    return next(row for row in grid.rows if row.bed.id == bed_id)


def test_予約表では重なった日のマスだけ赤枠になり警告に出る(session):
    a = _book(session, date(2026, 7, 1), date(2026, 7, 5), _bed())
    b = _book(session, date(2026, 7, 3), date(2026, 7, 7), _bed())

    grid = grid_service.build_grid([a, b], 2026, 7)
    row = _row(grid, _bed())

    conflict_days = [c.day.day for c in row.cells if c.is_conflict]
    assert conflict_days == [3, 4, 5]
    assert row.lane_count == 2  # 上下2段に分けて両方見せる

    assert {entry.reservation.id for entry in grid.conflicts} == {a.id, b.id}
    assert all(entry.day == date(2026, 7, 3) for entry in grid.conflicts)


def test_予約表で入れ替わりは2段に分けるが赤枠にしない(session):
    a = _book(session, date(2026, 7, 1), date(2026, 7, 5), _bed())
    b = _book(session, date(2026, 7, 5), date(2026, 7, 8), _bed())

    grid = grid_service.build_grid([a, b], 2026, 7)
    row = _row(grid, _bed())

    assert not any(c.is_conflict for c in row.cells)
    assert row.lane_count == 2
    assert grid.conflicts == []


def test_先月から続く重複の飛び先は今月の中の日(session):
    a = _book(session, date(2026, 6, 25), date(2026, 7, 4), _bed())
    b = _book(session, date(2026, 6, 28), date(2026, 7, 3), _bed())

    grid = grid_service.build_grid([a, b], 2026, 7)

    assert all(entry.day == date(2026, 7, 1) for entry in grid.conflicts)
