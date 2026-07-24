"""予約の登録・変更・削除と、重複の検出。

画面（Jinja2）からもAPI（JSON）からも、この層だけを呼ぶ。
業務ロジックをここに閉じ込めておくと、将来フロントを別のものに
差し替えても、この層はそのまま使い回せる。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from app.config import load_config
from app.models import Reservation, UserMaster


class ValidationError(ValueError):
    """入力が受け付けられないときに投げる。

    「現場の例外を止めない」方針（README設計方針3）があるので、
    ここで弾くのは本当に辻褄が合わないものだけにする。
    部屋の重複や部屋未定は、弾かずに警告として扱う。
    """


def _validate(
    session: Session,
    user_master_id: int,
    check_in: date,
    check_out: date,
    bed_id: str | None,
) -> None:
    # 名前は利用者マスタが持つので、ここでは「実在する利用者か」だけ見る。
    # マスタから選ぶ形にしているのは、毎回手入力すると表記ゆれが起きて
    # 当日台帳や入浴表と紐付かなくなるため。
    if session.get(UserMaster, user_master_id) is None:
        raise ValidationError(f"利用者が見つかりません: {user_master_id}")

    if check_out < check_in:
        raise ValidationError("退所日が入所日より前になっています")

    # 部屋番号は空でよい（部屋未定）。入っている場合だけ、実在するか見る。
    if bed_id is not None:
        if load_config().bed_by_id(bed_id) is None:
            raise ValidationError(f"存在しない部屋番号です: {bed_id}")


def create_reservation(
    session: Session,
    *,
    user_master_id: int,
    check_in: date,
    check_out: date,
    bed_id: str | None = None,
    is_tentative: bool = False,
) -> Reservation:
    _validate(session, user_master_id, check_in, check_out, bed_id)

    reservation = Reservation(
        user_master_id=user_master_id,
        bed_id=bed_id,
        check_in=check_in,
        check_out=check_out,
        is_tentative=is_tentative,
    )
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    return reservation


def get_reservation(session: Session, reservation_id: int) -> Reservation | None:
    return session.get(Reservation, reservation_id)


def update_reservation(
    session: Session,
    reservation_id: int,
    *,
    user_master_id: int | None = None,
    check_in: date | None = None,
    check_out: date | None = None,
    is_tentative: bool | None = None,
) -> Reservation:
    """予約の内容を変える。部屋の割り当ては assign_bed / unassign_bed を使う。

    名前や性別を直したいときは、この予約ではなく利用者マスタ側を直す。
    マスタを直せば、その人の予約すべてに反映される。
    """
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise ValidationError(f"予約が見つかりません: {reservation_id}")

    new_user = (
        user_master_id if user_master_id is not None else reservation.user_master_id
    )
    new_in = check_in if check_in is not None else reservation.check_in
    new_out = check_out if check_out is not None else reservation.check_out
    _validate(session, new_user, new_in, new_out, reservation.bed_id)

    reservation.user_master_id = new_user
    reservation.check_in = new_in
    reservation.check_out = new_out
    if is_tentative is not None:
        reservation.is_tentative = is_tentative

    session.add(reservation)
    session.commit()
    session.refresh(reservation)

    # 日程が縮んで、手動で決めた入浴日が滞在期間の外に出ることがある。
    # 残しておくと帳票には出ないのにデータだけ居座るので、ここで掃除する。
    # （循環importを避けるため、関数の中でimportしている）
    from app.services import bathing

    bathing.prune_out_of_range(session, reservation)
    session.refresh(reservation)

    return reservation


def delete_reservation(session: Session, reservation_id: int) -> None:
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise ValidationError(f"予約が見つかりません: {reservation_id}")
    session.delete(reservation)
    session.commit()


def assign_bed(session: Session, reservation_id: int, bed_id: str) -> Reservation:
    """部屋未定の予約に部屋を割り当てる。すでに埋まっていても止めない。

    重複はブロックせず、グリッド側で警告として見せる方針
    （reservation_spec.md ④）。
    """
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise ValidationError(f"予約が見つかりません: {reservation_id}")
    if load_config().bed_by_id(bed_id) is None:
        raise ValidationError(f"存在しない部屋番号です: {bed_id}")

    reservation.bed_id = bed_id
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    return reservation


def unassign_bed(session: Session, reservation_id: int) -> Reservation:
    """部屋の割り当てを外して、部屋未定リストに戻す。"""
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise ValidationError(f"予約が見つかりません: {reservation_id}")

    reservation.bed_id = None
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    return reservation


def list_in_period(
    session: Session, start: date, end: date, *, assigned_only: bool = False
) -> list[Reservation]:
    """start〜end に少しでもかかる予約を返す。

    期間が重なる条件は「入所日が期間の終わり以前」かつ「退所日が期間の始まり以降」。
    """
    statement = select(Reservation).where(
        Reservation.check_in <= end,
        Reservation.check_out >= start,
    )
    if assigned_only:
        statement = statement.where(Reservation.bed_id.is_not(None))  # type: ignore[union-attr]

    return list(session.exec(statement))


def list_unassigned(session: Session) -> list[Reservation]:
    """部屋未定リスト。部屋が決まっていない予約を入所日の順に返す。"""
    statement = (
        select(Reservation)
        .where(Reservation.bed_id.is_(None))  # type: ignore[union-attr]
        .order_by(Reservation.check_in)  # type: ignore[arg-type]
    )
    return list(session.exec(statement))


def overlaps(a: Reservation, b: Reservation) -> bool:
    """2件の予約が、同じベッドを実際に取り合っているか。

    退所日と入所日が同じ日のケース（Aさんが5日に退所、Bさんが5日に入所）は
    重複としない。ショートステイでは普通の入れ替わりで、警告を出すと
    毎日赤枠だらけになって、本当の重複が埋もれてしまう。

    そのため「泊まりが重なる日があるか」で判定する。
    """
    latest_in = max(a.check_in, b.check_in)
    earliest_out = min(a.check_out, b.check_out)
    return latest_in < earliest_out


def find_occupied_beds(session: Session, reservation: Reservation) -> set[str]:
    """その予約の期間に、すでに泊まりが重なっているベッドのIDを返す。

    部屋未定の予約に部屋を割り当てるとき、プルダウンで「空きなし」を
    見せるために使う（UI改善仕様③）。

    判定は overlaps() をそのまま使う。ここで「空きなし」と出る部屋と、
    グリッドで赤枠が出る部屋を必ず一致させるため。別々のルールで書くと、
    プルダウンでは空きに見えるのに割り当てたら赤枠が出る、という
    ちぐはぐな見え方になる。
    """
    others = list_in_period(
        session,
        reservation.check_in,
        reservation.check_out,
        assigned_only=True,
    )

    return {
        other.bed_id
        for other in others
        if other.bed_id is not None
        and other.id != reservation.id
        and overlaps(reservation, other)
    }


@dataclass(frozen=True)
class MixedGenderPair:
    """準個室に男女が同時に泊まっている組み合わせ。

    start 〜 end は、実際に2人とも泊まっている夜の範囲。
    """

    room_id: str
    a: Reservation
    b: Reservation
    start: date
    end: date


def find_mixed_gender_pairs(
    reservations: list[Reservation],
) -> list[MixedGenderPair]:
    """準個室で男女が同室になっている組み合わせを探す。

    施設によっては男女同室を認めていないため、設定で警告を出せるようにする
    （config.toml の warnings.mixed_gender_in_shared_room）。
    設定が無効な施設ではそもそも呼ばれない。

    判定は「同じ夜に2人とも泊まっているか」で行う。片方が退所する日に
    もう片方が入所しても、その夜に同室になるわけではないため。
    """
    config = load_config()

    by_bed: dict[str, list[Reservation]] = {}
    for reservation in reservations:
        if reservation.bed_id is not None:
            by_bed.setdefault(reservation.bed_id, []).append(reservation)

    # 準個室だけを、部屋単位でまとめる
    shared_rooms: dict[str, list[str]] = {}
    for bed in config.beds:
        if bed.is_shared:
            shared_rooms.setdefault(bed.room_id, []).append(bed.id)

    pairs: list[MixedGenderPair] = []
    for room_id, bed_ids in shared_rooms.items():
        if len(bed_ids) < 2:
            continue

        first, second = bed_ids[0], bed_ids[1]
        for a in by_bed.get(first, []):
            for b in by_bed.get(second, []):
                if a.gender == b.gender:
                    continue

                # 2人とも泊まっている夜の範囲
                start = max(a.check_in, b.check_in)
                end = min(a.check_out, b.check_out)
                if start >= end:
                    continue

                pairs.append(
                    MixedGenderPair(
                        room_id=room_id,
                        a=a,
                        b=b,
                        start=start,
                        # end は退所日なのでその前夜までが同室
                        end=end - timedelta(days=1),
                    )
                )

    return sorted(pairs, key=lambda p: (p.room_id, p.start))


def find_conflicts(reservations: list[Reservation]) -> set[int]:
    """重複している予約のIDを返す。

    部屋が未定のものは、まだどこも取り合っていないので対象外。
    """
    conflicted: set[int] = set()

    by_bed: dict[str, list[Reservation]] = {}
    for reservation in reservations:
        if reservation.bed_id is None:
            continue
        by_bed.setdefault(reservation.bed_id, []).append(reservation)

    for same_bed in by_bed.values():
        for i, a in enumerate(same_bed):
            for b in same_bed[i + 1 :]:
                if overlaps(a, b) and a.id is not None and b.id is not None:
                    conflicted.add(a.id)
                    conflicted.add(b.id)

    return conflicted
