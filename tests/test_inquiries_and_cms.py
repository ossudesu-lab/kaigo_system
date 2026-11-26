"""問い合わせ・CMマスタ：項目を空にして保存できること（不具合2）。"""

from __future__ import annotations

from datetime import date

import pytest

from app.models import Gender
from app.services import care_managers as cm_service
from app.services import inquiries as inquiry_service
from app.services import users as user_service


@pytest.fixture
def cm(session):
    return cm_service.create_care_manager(
        session, name="山田 一郎", office="みどり居宅", phone="03-0000-0000",
        fax="03-0000-0001", email="a@example.com", notes="午前中が繋がりやすい",
    )


@pytest.fixture
def user(session):
    return user_service.create_user(session, name="佐藤 花子", gender=Gender.FEMALE)


@pytest.fixture
def inquiry(session, cm, user):
    return inquiry_service.create_inquiry(
        session,
        inquiry_date=date(2026, 7, 1),
        kind="空き確認",
        care_manager_id=cm.id,
        user_master_id=user.id,
        desired_check_in=date(2026, 7, 20),
        desired_check_out=date(2026, 7, 22),
        memo="折り返し希望",
    )


def test_inquiry_edit_form_can_clear_fields(client, inquiry, user):
    """編集画面と同じ形（空欄は null）で送ると、その項目が消えること。"""
    res = client.patch(
        f"/api/inquiries/{inquiry.id}",
        json={
            "inquiry_date": "2026-07-01",
            "kind": "空き確認",
            "status": "未対応",
            "care_manager_id": None,
            "user_master_id": user.id,
            "guest_name": None,
            "desired_check_in": None,
            "desired_check_out": None,
            "memo": None,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["care_manager_id"] is None
    assert data["desired_check_in"] is None
    assert data["desired_check_out"] is None
    assert data["memo"] is None
    assert data["user_master_id"] == user.id


def test_inquiry_can_switch_from_master_to_typed_name(client, inquiry):
    res = client.patch(
        f"/api/inquiries/{inquiry.id}",
        json={"user_master_id": None, "guest_name": "新規 太郎"},
    )
    data = res.json()
    assert data["user_master_id"] is None
    assert data["display_name"] == "新規 太郎"


def test_inquiry_without_anyone_is_rejected(client, inquiry):
    res = client.patch(
        f"/api/inquiries/{inquiry.id}",
        json={"user_master_id": None, "guest_name": None},
    )
    assert res.status_code == 400


def test_inquiry_fields_not_sent_are_kept(client, inquiry, cm):
    res = client.patch(f"/api/inquiries/{inquiry.id}", json={"status": "対応中"})
    data = res.json()
    assert data["status"] == "対応中"
    assert data["memo"] == "折り返し希望"
    assert data["care_manager_id"] == cm.id
    assert data["desired_check_in"] == "2026-07-20"


def test_inquiry_required_fields_cannot_be_cleared(client, inquiry):
    for field in ("inquiry_date", "kind", "status"):
        res = client.patch(f"/api/inquiries/{inquiry.id}", json={field: None})
        assert res.status_code == 400, field


def test_care_manager_edit_form_can_clear_fields(client, cm):
    res = client.patch(
        f"/api/care-managers/{cm.id}",
        json={
            "name": "山田 一郎",
            "office": None, "phone": None, "fax": None, "email": None, "notes": None,
        },
    )
    data = res.json()
    for field in ("office", "phone", "fax", "email", "notes"):
        assert data[field] is None, field


def test_care_manager_fields_not_sent_are_kept(client, cm):
    res = client.patch(f"/api/care-managers/{cm.id}", json={"phone": "03-9999-9999"})
    data = res.json()
    assert data["phone"] == "03-9999-9999"
    assert data["office"] == "みどり居宅"


def test_care_manager_name_cannot_be_cleared(client, cm):
    assert client.patch(f"/api/care-managers/{cm.id}", json={"name": None}).status_code == 400
