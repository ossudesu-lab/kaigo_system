"""利用者マスタ：担当CMの紐づけと、項目を空にして保存できること。"""

from __future__ import annotations

import pytest

from app.models import Gender
from app.services import care_managers as cm_service
from app.services import users as service
from app.services.reservations import ValidationError


@pytest.fixture
def cm(session):
    return cm_service.create_care_manager(
        session, name="山田 一郎", office="みどり居宅", phone="03-0000-0000"
    )


# ------------------------------------------------ 担当CM（不具合1）


def test_create_user_with_care_manager(session, cm):
    user = service.create_user(
        session, name="佐藤 花子", gender=Gender.FEMALE, care_manager_id=cm.id
    )
    assert user.care_manager_id == cm.id
    assert user.care_manager.name == "山田 一郎"


def test_unknown_care_manager_is_rejected(session):
    with pytest.raises(ValidationError):
        service.create_user(
            session, name="佐藤 花子", gender=Gender.FEMALE, care_manager_id=999
        )


def test_api_sets_and_changes_care_manager(client, session, cm):
    other = cm_service.create_care_manager(session, name="鈴木 二郎")

    res = client.post(
        "/api/users",
        json={"name": "佐藤 花子", "gender": "女性", "care_manager_id": cm.id},
    )
    assert res.status_code == 201
    user_id = res.json()["id"]
    assert res.json()["care_manager_id"] == cm.id

    res = client.patch(f"/api/users/{user_id}", json={"care_manager_id": other.id})
    assert res.json()["care_manager_id"] == other.id

    res = client.patch(f"/api/users/{user_id}", json={"care_manager_id": None})
    assert res.json()["care_manager_id"] is None


def test_users_page_shows_care_manager(client, session, cm):
    service.create_user(
        session, name="佐藤 花子", gender=Gender.FEMALE, care_manager_id=cm.id
    )
    html = client.get("/users").text
    # 一覧の担当CM列と、フォームのプルダウンの両方に出る
    assert html.count("山田 一郎") >= 2
    assert "03-0000-0000" in html
    assert 'name="care_manager_id"' in html


# ------------------------------------------------ 空にして保存（不具合2）


def _make_full_user(session, cm):
    return service.create_user(
        session,
        name="佐藤 花子",
        gender=Gender.FEMALE,
        kana="さとう はなこ",
        condition="糖尿病",
        notes="転倒リスク高い",
        training="エアロバイク",
        bathing_type="リフト",
        fixed_bed_id="A6",
        care_manager_id=cm.id,
    )


def test_edit_form_can_clear_fields(client, session, cm):
    """編集画面は空欄を null で送る。その項目が消えること。"""
    user = _make_full_user(session, cm)

    res = client.patch(
        f"/api/users/{user.id}",
        json={
            "name": "佐藤 花子",
            "gender": "女性",
            "kana": None,
            "condition": None,
            "notes": None,
            "training": None,
            "bathing_type": None,
            "fixed_bed_id": None,
            "care_manager_id": None,
        },
    )
    assert res.status_code == 200
    data = res.json()
    for field in (
        "kana", "condition", "notes", "training",
        "bathing_type", "fixed_bed_id", "care_manager_id",
    ):
        assert data[field] is None, field


def test_empty_string_also_clears(client, session, cm):
    user = _make_full_user(session, cm)
    res = client.patch(f"/api/users/{user.id}", json={"notes": "   "})
    assert res.json()["notes"] is None


def test_fields_not_sent_are_kept(client, session, cm):
    """送らなかった項目は、そのまま残ること。"""
    user = _make_full_user(session, cm)

    res = client.patch(f"/api/users/{user.id}", json={"notes": "夜間トイレ介助"})
    data = res.json()
    assert data["notes"] == "夜間トイレ介助"
    assert data["condition"] == "糖尿病"
    assert data["training"] == "エアロバイク"
    assert data["care_manager_id"] == cm.id
    assert data["fixed_bed_id"] == "A6"


def test_name_and_gender_cannot_be_cleared(client, session, cm):
    user = _make_full_user(session, cm)
    assert client.patch(f"/api/users/{user.id}", json={"name": None}).status_code == 400
    assert client.patch(f"/api/users/{user.id}", json={"name": " "}).status_code == 400
    assert client.patch(f"/api/users/{user.id}", json={"gender": None}).status_code == 400
