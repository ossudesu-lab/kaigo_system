"""利用者マスタの登録・変更・削除。

一度登録したら使い回す台帳なので、予約と違って頻繁には変わらない。
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from app.config import load_config
from app.models import CareManager, Gender, Inquiry, Reservation, UserMaster
from app.services.common import UNSET
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
    session: Session,
    name: str | None,
    gender: Gender | None,
    kana: str | None,
    bathing_type: str | None,
    fixed_bed_id: str | None,
    care_manager_id: int | None,
) -> None:
    if name is None or not name.strip():
        raise ValidationError("利用者名を入力してください")

    if gender is None:
        raise ValidationError("性別を選んでください")

    if kana is not None and not _KANA_PATTERN.match(kana):
        raise ValidationError("ふりがなは、ひらがなかカタカナで入力してください")

    config = load_config()

    if bathing_type is not None and bathing_type not in config.bathing_types:
        raise ValidationError(f"入浴種別の選択肢にありません: {bathing_type}")

    if fixed_bed_id is not None and config.bed_by_id(fixed_bed_id) is None:
        raise ValidationError(f"存在しない部屋番号です: {fixed_bed_id}")

    if care_manager_id is not None and session.get(CareManager, care_manager_id) is None:
        raise ValidationError(f"CMが見つかりません: {care_manager_id}")


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
    care_manager_id: int | None = None,
) -> UserMaster:
    bathing_type = _clean(bathing_type)
    fixed_bed_id = _clean(fixed_bed_id)
    kana = normalize_kana(kana)
    _validate(session, name, gender, kana, bathing_type, fixed_bed_id, care_manager_id)

    user = UserMaster(
        name=name.strip(),
        kana=kana,
        gender=gender,
        condition=_clean(condition),
        notes=_clean(notes),
        training=_clean(training),
        bathing_type=bathing_type,
        fixed_bed_id=fixed_bed_id,
        care_manager_id=care_manager_id,
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
    name: str | None = UNSET,
    gender: Gender | None = UNSET,
    kana: str | None = UNSET,
    condition: str | None = UNSET,
    notes: str | None = UNSET,
    training: str | None = UNSET,
    bathing_type: str | None = UNSET,
    fixed_bed_id: str | None = UNSET,
    care_manager_id: int | None = UNSET,
) -> UserMaster:
    """利用者の内容を変える。

    渡さなかった項目（UNSET）はそのまま。None や空文字を渡した項目は消す。
    編集画面で欄を空にして保存したら、その項目が消えるようにするため。
    """
    user = session.get(UserMaster, user_id)
    if user is None:
        raise ValidationError(f"利用者が見つかりません: {user_id}")

    new_name = user.name if name is UNSET else name
    new_gender = user.gender if gender is UNSET else gender
    new_kana = user.kana if kana is UNSET else normalize_kana(kana)
    new_bathing = user.bathing_type if bathing_type is UNSET else _clean(bathing_type)
    new_bed = user.fixed_bed_id if fixed_bed_id is UNSET else _clean(fixed_bed_id)
    new_cm = user.care_manager_id if care_manager_id is UNSET else care_manager_id
    _validate(session, new_name, new_gender, new_kana, new_bathing, new_bed, new_cm)

    user.name = new_name.strip()  # type: ignore[union-attr]
    user.gender = new_gender  # type: ignore[assignment]
    user.kana = new_kana
    user.bathing_type = new_bathing
    user.fixed_bed_id = new_bed
    user.care_manager_id = new_cm

    for field, value in (
        ("condition", condition),
        ("notes", notes),
        ("training", training),
    ):
        if value is not UNSET:
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

    # 問い合わせの記録は残す。名前はマスタから消えるので、問い合わせ側に
    # 書き写しておく。そうしないと「（利用者未定）」と表示されてしまう。
    for inquiry in session.exec(
        select(Inquiry).where(Inquiry.user_master_id == user_id)
    ):
        inquiry.user_master_id = None
        inquiry.guest_name = user.name
        session.add(inquiry)

    session.delete(user)
    session.commit()
