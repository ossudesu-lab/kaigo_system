"""点検で見つかった不具合の再発防止。

- 予約を削除したら、元の問い合わせはキャンセル扱いになり、もう一度予約にできる
- 問い合わせのある利用者を削除しても、問い合わせの名前が消えない
- URLにありえない月（month=13 など）を入れても500エラーにならない
"""

from __future__ import annotations

from datetime import date

from app.models import Gender, Inquiry
from app.services import inquiries as inquiry_service
from app.services import reservations as reservation_service
from app.services import users as user_service


def _inquiry(session, **kwargs):
    defaults = dict(
        inquiry_date=date(2026, 7, 1),
        kind="空き確認",
        desired_check_in=date(2026, 7, 20),
        desired_check_out=date(2026, 7, 22),
    )
    defaults.update(kwargs)
    return inquiry_service.create_inquiry(session, **defaults)


def test_予約を消すと問い合わせはキャンセルになり再変換できる(session):
    user = user_service.create_user(session, name="佐藤 花子", gender=Gender.FEMALE)
    inquiry = _inquiry(session, user_master_id=user.id)
    reservation = inquiry_service.convert_to_reservation(session, inquiry.id)

    reservation_service.delete_reservation(session, reservation.id)

    session.refresh(inquiry)
    assert inquiry.reservation_id is None
    assert inquiry.status == "キャンセル"

    # 「やっぱり来ます」となったときに、もう一度予約にできる
    again = inquiry_service.convert_to_reservation(session, inquiry.id)
    assert again.id is not None


def test_問い合わせと関係ない予約を消しても問い合わせは変わらない(session):
    user = user_service.create_user(session, name="佐藤 花子", gender=Gender.FEMALE)
    inquiry = _inquiry(session, user_master_id=user.id)
    other = reservation_service.create_reservation(
        session, user_master_id=user.id,
        check_in=date(2026, 8, 1), check_out=date(2026, 8, 3), bed_id=None,
    )

    reservation_service.delete_reservation(session, other.id)

    session.refresh(inquiry)
    assert inquiry.status == "未対応"


def test_利用者を消しても問い合わせに名前が残る(session):
    user = user_service.create_user(session, name="佐藤 花子", gender=Gender.FEMALE)
    inquiry = _inquiry(session, user_master_id=user.id)

    user_service.delete_user(session, user.id)

    inquiry = session.get(Inquiry, inquiry.id)
    assert inquiry.user_master_id is None
    assert inquiry.display_name == "佐藤 花子"


def test_ありえない月は今月へ移す(client):
    today = date.today()
    for path in ("/grid", "/report"):
        for query in ("?year=2026&month=13", "?year=2026&month=0", "?year=99999&month=1", ""):
            res = client.get(path + query, follow_redirects=False)
            assert res.status_code in (302, 303, 307), (path, query, res.status_code)
            assert res.headers["location"] == f"{path}?year={today.year}&month={today.month}"


def test_正しい月はそのまま表示する(client):
    for path in ("/grid", "/report"):
        assert client.get(f"{path}?year=2026&month=12").status_code == 200
