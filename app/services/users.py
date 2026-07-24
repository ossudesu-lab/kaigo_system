"""利用者マスタの登録・変更・削除。

一度登録したら使い回す台帳なので、予約と違って頻繁には変わらない。
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from app.config import load_config
from app.models import Gender, Reservation, UserMaster
from app.services.reservations import ValidationError


def _clean(value: str | None) -> str | None:
    """未入力を None に寄せる。

    空文字と None が混ざると「未入力かどうか」の判定が2通りになるので、
    入口で None に統一する。
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# ふりがなとして受け付ける文字。ひらがな・カタカナ・長音符・空白のみ。
# 漢字を入れられると並べ替えの意味がなくなるので、入口で弾く。
_KANA_PATTERN = re.compile(r"^[ぁ-ゟァ-ヿー\s]+$")


def normalize_kana(value: str | None) -> str | None:
    """ふりがなをひらがなに揃える。

    「さとう」と「サトウ」が混ざると並び順が崩れるため、
    カタカナはひらがなに寄せてから保存する。
    """
    cleaned = _clean(value)
    if cleaned is None:
        return None

    # カタカナ（ァ〜ヶ）はコード上、対応するひらがなの 0x60 先にある
    converted = "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char
        for char in cleaned
    )
    return converted


def _validate(
    name: str,
    kana: str | None,
    bathing_type: str | None,
    fixed_bed_id: str | None,
) -> None:
    if not name.strip():
        raise ValidationError("利用者名を入力してください")

    if kana is not None and not _KANA_PATTERN.match(kana):
        raise ValidationError("ふりがなは、ひらがなかカタカナで入力してください")

    config = load_config()

    if bathing_type is not None and bathing_type not in config.bathing_types:
        raise ValidationError(f"入浴種別の選択肢にありません: {bathing_type}")

    if fixed_bed_id is not None and config.bed_by_id(fixed_bed_id) is None:
        raise ValidationError(f"存在しない部屋番号です: {fixed_bed_id}")


def create_user(
    session: Session,
    *,
    name: str,
    gender: Gender,
    kana: str | None = None,
    condition: str | None = None,
    notes: str | None = None,
    training: str | None = None,
    bathing_type: str | None = None,
    fixed_bed_id: str | None = None,
    cm_name: str | None = None,
    cm_office: str | None = None,
    cm_phone: str | None = None,
) -> UserMaster:
    bathing_type = _clean(bathing_type)
    fixed_bed_id = _clean(fixed_bed_id)
    kana = normalize_kana(kana)
    _validate(name, kana, bathing_type, fixed_bed_id)

    user = UserMaster(
        name=name.strip(),
        kana=kana,
        gender=gender,
        condition=_clean(condition),
        notes=_clean(notes),
        training=_clean(training),
        bathing_type=bathing_type,
        fixed_bed_id=fixed_bed_id,
        cm_name=_clean(cm_name),
        cm_office=_clean(cm_office),
        cm_phone=_clean(cm_phone),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def get_user(session: Session, user_id: int) -> UserMaster | None:
    return session.get(UserMaster, user_id)


def list_users(session: Session, *, keyword: str | None = None) -> list[UserMaster]:
    """利用者の一覧。ふりがな順。

    人数が増えると予約時のプルダウンから探しにくくなるので、
    名前・ふりがなでの絞り込みができるようにしている。
    """
    # ふりがな順。未入力の人は末尾にまとめる（埋めるべき人が一目で分かる）。
    statement = select(UserMaster).order_by(
        UserMaster.kana.is_(None),  # type: ignore[union-attr]
        UserMaster.kana,  # type: ignore[arg-type]
        UserMaster.name,  # type: ignore[arg-type]
    )
    if keyword:
        # 漢字が思い出せなくても読みで探せるよう、両方を対象にする
        statement = statement.where(
            UserMaster.name.contains(keyword)  # type: ignore[union-attr]
            | UserMaster.kana.contains(keyword)  # type: ignore[union-attr]
        )
    return list(session.exec(statement))


def update_user(
    session: Session,
    user_id: int,
    *,
    name: str | None = None,
    gender: Gender | None = None,
    kana: str | None = None,
    condition: str | None = None,
    notes: str | None = None,
    training: str | None = None,
    bathing_type: str | None = None,
    fixed_bed_id: str | None = None,
    cm_name: str | None = None,
    cm_office: str | None = None,
    cm_phone: str | None = None,
) -> UserMaster:
    user = session.get(UserMaster, user_id)
    if user is None:
        raise ValidationError(f"利用者が見つかりません: {user_id}")

    new_name = name if name is not None else user.name
    new_bathing = _clean(bathing_type) if bathing_type is not None else user.bathing_type
    new_bed = _clean(fixed_bed_id) if fixed_bed_id is not None else user.fixed_bed_id
    new_kana = normalize_kana(kana) if kana is not None else user.kana
    _validate(new_name, new_kana, new_bathing, new_bed)

    user.name = new_name.strip()
    user.kana = new_kana
    if gender is not None:
        user.gender = gender
    user.bathing_type = new_bathing
    user.fixed_bed_id = new_bed

    # 任意項目は「送られてきたら上書き」。空文字を送れば消せる。
    for field, value in (
        ("condition", condition),
        ("notes", notes),
        ("training", training),
        ("cm_name", cm_name),
        ("cm_office", cm_office),
        ("cm_phone", cm_phone),
    ):
        if value is not None:
            setattr(user, field, _clean(value))

    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def delete_user(session: Session, user_id: int) -> None:
    """利用者を消す。予約が1件でも残っていれば消させない。

    消すと、その人の予約が誰のものか分からなくなるため。
    もう来ない利用者はマスタに残しておいても害がないので、
    「使わなくなったら消す」運用は想定していない。
    """
    user = session.get(UserMaster, user_id)
    if user is None:
        raise ValidationError(f"利用者が見つかりません: {user_id}")

    count = len(
        list(session.exec(select(Reservation).where(Reservation.user_master_id == user_id)))
    )
    if count:
        raise ValidationError(
            f"この利用者には予約が{count}件あります。先に予約を削除してください。"
        )

    session.delete(user)
    session.commit()
