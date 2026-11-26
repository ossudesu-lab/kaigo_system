"""問い合わせの記録・検索と、予約データへの変換。

予約になる前の段階の記録を残しておき、話がまとまったらワンクリックで
予約に変換する（inquiry_spec.md 1・4）。
"""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, or_, select

from app.config import load_config
from app.models import CareManager, Gender, Inquiry, Reservation, UserMaster
from app.services import reservations as reservation_service
from app.services import users as user_service
from app.services.common import UNSET
from app.services.reservations import ValidationError
from app.services.users import _clean


def _validate(
    session: Session,
    kind: str,
    status: str,
    user_master_id: int | None,
    guest_name: str | None,
    care_manager_id: int | None,
    desired_check_in: date | None,
    desired_check_out: date | None,
) -> None:
    config = load_config()

    if kind not in config.inquiry.kinds:
        raise ValidationError(f"内容の選択肢にありません: {kind}")

    if status not in config.inquiry.statuses:
        raise ValidationError(f"対応状況の選択肢にありません: {status}")

    # 誰の話か分からない問い合わせは記録しても後で使えない。
    # マスタから選ぶか、名前を手入力するかのどちらかは要る。
    if user_master_id is None and not (guest_name or "").strip():
        raise ValidationError("対象の利用者を選ぶか、名前を入力してください")

    if user_master_id is not None and session.get(UserMaster, user_master_id) is None:
        raise ValidationError(f"利用者が見つかりません: {user_master_id}")

    if care_manager_id is not None and session.get(CareManager, care_manager_id) is None:
        raise ValidationError(f"CMが見つかりません: {care_manager_id}")

    # 希望日程は空でもよい（まだ決まっていない相談もある）。
    # 両方入っているときだけ前後関係を見る。
    if desired_check_in and desired_check_out and desired_check_out < desired_check_in:
        raise ValidationError("退所希望日が入所希望日より前になっています")


def create_inquiry(
    session: Session,
    *,
    inquiry_date: date,
    kind: str,
    status: str | None = None,
    care_manager_id: int | None = None,
    user_master_id: int | None = None,
    guest_name: str | None = None,
    desired_check_in: date | None = None,
    desired_check_out: date | None = None,
    memo: str | None = None,
) -> Inquiry:
    config = load_config()
    status = status or config.inquiry.default_status
    guest_name = _clean(guest_name)

    _validate(
        session, kind, status, user_master_id, guest_name,
        care_manager_id, desired_check_in, desired_check_out,
    )

    # マスタから選べたなら、手入力の名前は残さない。
    # 両方あると、あとでどちらが正しいのか分からなくなる。
    if user_master_id is not None:
        guest_name = None

    inquiry = Inquiry(
        inquiry_date=inquiry_date,
        kind=kind,
        status=status,
        care_manager_id=care_manager_id,
        user_master_id=user_master_id,
        guest_name=guest_name,
        desired_check_in=desired_check_in,
        desired_check_out=desired_check_out,
        memo=_clean(memo),
    )
    session.add(inquiry)
    session.commit()
    session.refresh(inquiry)
    return inquiry


def get_inquiry(session: Session, inquiry_id: int) -> Inquiry | None:
    return session.get(Inquiry, inquiry_id)


def update_inquiry(
    session: Session,
    inquiry_id: int,
    *,
    inquiry_date: date | None = UNSET,
    kind: str | None = UNSET,
    status: str | None = UNSET,
    care_manager_id: int | None = UNSET,
    user_master_id: int | None = UNSET,
    guest_name: str | None = UNSET,
    desired_check_in: date | None = UNSET,
    desired_check_out: date | None = UNSET,
    memo: str | None = UNSET,
) -> Inquiry:
    """問い合わせの内容を変える。

    渡さなかった項目（UNSET）はそのまま。None を渡した項目は消す。
    編集画面で希望日やメモを空にして保存したら、その通りに消えるようにするため。
    """
    inquiry = session.get(Inquiry, inquiry_id)
    if inquiry is None:
        raise ValidationError(f"問い合わせが見つかりません: {inquiry_id}")

    def pick(value, current):
        return current if value is UNSET else value

    new_date = pick(inquiry_date, inquiry.inquiry_date)
    if new_date is None:
        raise ValidationError("問い合わせ日を入力してください")

    new_kind = pick(kind, inquiry.kind)
    new_status = pick(status, inquiry.status)
    new_user = pick(user_master_id, inquiry.user_master_id)
    new_guest = inquiry.guest_name if guest_name is UNSET else _clean(guest_name)
    new_cm = pick(care_manager_id, inquiry.care_manager_id)
    new_in = pick(desired_check_in, inquiry.desired_check_in)
    new_out = pick(desired_check_out, inquiry.desired_check_out)
    new_memo = inquiry.memo if memo is UNSET else _clean(memo)

    _validate(session, new_kind, new_status, new_user, new_guest, new_cm, new_in, new_out)

    if new_user is not None:
        new_guest = None

    inquiry.inquiry_date = new_date
    inquiry.kind = new_kind
    inquiry.status = new_status
    inquiry.care_manager_id = new_cm
    inquiry.user_master_id = new_user
    inquiry.guest_name = new_guest
    inquiry.desired_check_in = new_in
    inquiry.desired_check_out = new_out
    inquiry.memo = new_memo

    session.add(inquiry)
    session.commit()
    session.refresh(inquiry)
    return inquiry


def delete_inquiry(session: Session, inquiry_id: int) -> None:
    inquiry = session.get(Inquiry, inquiry_id)
    if inquiry is None:
        raise ValidationError(f"問い合わせが見つかりません: {inquiry_id}")
    session.delete(inquiry)
    session.commit()


def search_inquiries(
    session: Session,
    *,
    status: str | None = None,
    kind: str | None = None,
    care_manager_id: int | None = None,
    office: str | None = None,
    guest_keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    desired_from: date | None = None,
    desired_to: date | None = None,
    keyword: str | None = None,
) -> list[Inquiry]:
    """条件で絞り込んだ問い合わせ一覧（inquiry_spec.md 絞り込み機能）。

    新しいものが上に来るよう、問い合わせ日の降順で返す。
    未対応のものを探す場面が多いので、同じ日なら後から入れたものが上。
    """
    statement = select(Inquiry)

    if status:
        statement = statement.where(Inquiry.status == status)
    if kind:
        statement = statement.where(Inquiry.kind == kind)
    if care_manager_id is not None:
        statement = statement.where(Inquiry.care_manager_id == care_manager_id)

    if office:
        statement = statement.join(CareManager).where(
            CareManager.office.contains(office)  # type: ignore[union-attr]
        )

    if guest_keyword:
        # マスタから選んだ場合は利用者マスタ側、手入力の場合は問い合わせ側に
        # 名前があるので、両方を探す。
        matching_users = select(UserMaster.id).where(
            UserMaster.name.contains(guest_keyword)  # type: ignore[union-attr]
            | UserMaster.kana.contains(guest_keyword)  # type: ignore[union-attr]
        )
        statement = statement.where(
            or_(
                Inquiry.user_master_id.in_(matching_users),  # type: ignore[union-attr]
                Inquiry.guest_name.contains(guest_keyword),  # type: ignore[union-attr]
            )
        )

    if date_from:
        statement = statement.where(Inquiry.inquiry_date >= date_from)
    if date_to:
        statement = statement.where(Inquiry.inquiry_date <= date_to)

    if desired_from:
        statement = statement.where(Inquiry.desired_check_out >= desired_from)
    if desired_to:
        statement = statement.where(Inquiry.desired_check_in <= desired_to)

    if keyword:
        # フリーワードは、メモと手入力の名前を対象にする
        statement = statement.where(
            or_(
                Inquiry.memo.contains(keyword),  # type: ignore[union-attr]
                Inquiry.guest_name.contains(keyword),  # type: ignore[union-attr]
            )
        )

    statement = statement.order_by(
        Inquiry.inquiry_date.desc(),  # type: ignore[union-attr]
        Inquiry.id.desc(),  # type: ignore[union-attr]
    )
    return list(session.exec(statement))


# ------------------------------------------------ 予約データへの変換


def convert_to_reservation(
    session: Session,
    inquiry_id: int,
    *,
    is_tentative: bool | None = None,
    gender: Gender | None = None,
) -> Reservation:
    """問い合わせを予約データに変換する（inquiry_spec.md 4）。

    部屋番号は空のままにして、部屋未定リストに入れる。どの部屋に入れるかは
    埋まり具合を見て後から決めるため。

    仮予約かどうかの初期値は、この問い合わせを受けた時点で利用者マスタに
    登録済みだったかどうかで出し分ける。既存の方は空きがあればそのまま
    決まることがほとんどで、新規の方はケースバイケースになるという
    現場の実態に合わせている。呼び出し側の指定があればそちらを優先する。

    マスタ未登録の方は、この変換の中でマスタに登録する。予約は利用者マスタを
    参照する作りなので、登録しないと予約が作れないため。gender はその
    登録に要る（マスタの必須項目で、予約表の色分けにも使う）。
    """
    inquiry = session.get(Inquiry, inquiry_id)
    if inquiry is None:
        raise ValidationError(f"問い合わせが見つかりません: {inquiry_id}")

    if inquiry.reservation_id is not None:
        raise ValidationError("この問い合わせはすでに予約に変換されています")

    if inquiry.desired_check_in is None or inquiry.desired_check_out is None:
        raise ValidationError("希望日程が入っていません。入所日と退所日を埋めてください。")

    # 仮予約かどうかは、マスタに登録する前の状態で決める。
    # 先に登録してしまうと全員「登録済み」になり、新規の方も本予約になってしまう。
    was_registered = inquiry.is_registered_user
    if is_tentative is None:
        is_tentative = not was_registered

    user_master_id = inquiry.user_master_id
    if user_master_id is None:
        if gender is None:
            raise ValidationError(
                "この方は利用者マスタに未登録です。登録して予約にするので、性別を選んでください。"
            )
        user = user_service.create_user(
            session,
            name=inquiry.guest_name or "",
            gender=gender,
        )
        user_master_id = user.id
        # 以降この問い合わせはマスタの方を指すようにする。
        # 名前を直したいときはマスタ側だけ見ればよくなる。
        inquiry.user_master_id = user_master_id
        inquiry.guest_name = None

    reservation = reservation_service.create_reservation(
        session,
        user_master_id=user_master_id,  # type: ignore[arg-type]
        check_in=inquiry.desired_check_in,
        check_out=inquiry.desired_check_out,
        bed_id=None,
        is_tentative=is_tentative,
    )

    inquiry.reservation_id = reservation.id
    session.add(inquiry)
    session.commit()
    session.refresh(inquiry)

    return reservation
