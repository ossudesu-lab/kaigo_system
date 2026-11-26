"""CMマスタ（担当ケアマネジャー）の登録・変更・削除。

利用者マスタと同じ考え方で、一度登録したら使い回す台帳
（inquiry_spec.md 2）。問い合わせを記録するとき、氏名を選ぶだけで
事業所名・連絡先が付いてくるようにするためのもの。
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models import CareManager, Inquiry, UserMaster
from app.services.common import UNSET
from app.services.reservations import ValidationError
from app.services.users import _clean


def create_care_manager(
    session: Session,
    *,
    name: str,
    office: str | None = None,
    phone: str | None = None,
    fax: str | None = None,
    email: str | None = None,
    notes: str | None = None,
) -> CareManager:
    if not name.strip():
        raise ValidationError("CMの氏名を入力してください")

    care_manager = CareManager(
        name=name.strip(),
        office=_clean(office),
        phone=_clean(phone),
        fax=_clean(fax),
        email=_clean(email),
        notes=_clean(notes),
    )
    session.add(care_manager)
    session.commit()
    session.refresh(care_manager)
    return care_manager


def get_care_manager(session: Session, care_manager_id: int) -> CareManager | None:
    return session.get(CareManager, care_manager_id)


def list_care_managers(
    session: Session, *, keyword: str | None = None
) -> list[CareManager]:
    """CMの一覧。事業所ごとにまとまるよう、事業所名→氏名の順で並べる。"""
    statement = select(CareManager).order_by(
        CareManager.office,  # type: ignore[arg-type]
        CareManager.name,  # type: ignore[arg-type]
    )
    if keyword:
        statement = statement.where(
            CareManager.name.contains(keyword)  # type: ignore[union-attr]
            | CareManager.office.contains(keyword)  # type: ignore[union-attr]
        )
    return list(session.exec(statement))


def update_care_manager(
    session: Session,
    care_manager_id: int,
    *,
    name: str | None = UNSET,
    office: str | None = UNSET,
    phone: str | None = UNSET,
    fax: str | None = UNSET,
    email: str | None = UNSET,
    notes: str | None = UNSET,
) -> CareManager:
    """CMの内容を変える。渡さなかった項目はそのまま、None や空文字は消す。"""
    care_manager = session.get(CareManager, care_manager_id)
    if care_manager is None:
        raise ValidationError(f"CMが見つかりません: {care_manager_id}")

    if name is not UNSET:
        if name is None or not name.strip():
            raise ValidationError("CMの氏名を入力してください")
        care_manager.name = name.strip()

    for field, value in (
        ("office", office),
        ("phone", phone),
        ("fax", fax),
        ("email", email),
        ("notes", notes),
    ):
        if value is not UNSET:
            setattr(care_manager, field, _clean(value))

    session.add(care_manager)
    session.commit()
    session.refresh(care_manager)
    return care_manager


def delete_care_manager(session: Session, care_manager_id: int) -> None:
    """CMを消す。利用者や問い合わせから参照されていれば消させない。

    消すと、その利用者の担当が誰だったか分からなくなるため。
    """
    care_manager = session.get(CareManager, care_manager_id)
    if care_manager is None:
        raise ValidationError(f"CMが見つかりません: {care_manager_id}")

    users = len(
        list(
            session.exec(
                select(UserMaster).where(
                    UserMaster.care_manager_id == care_manager_id
                )
            )
        )
    )
    inquiries = len(
        list(
            session.exec(
                select(Inquiry).where(Inquiry.care_manager_id == care_manager_id)
            )
        )
    )

    if users or inquiries:
        parts = []
        if users:
            parts.append(f"利用者{users}件")
        if inquiries:
            parts.append(f"問い合わせ{inquiries}件")
        raise ValidationError(
            f"このCMは{'・'.join(parts)}から参照されています。先にそちらの担当を変更してください。"
        )

    session.delete(care_manager)
    session.commit()
