"""入浴回数の計算と、入浴日の割り当て。

  入浴回数 = 宿泊日数 ÷ interval_nights（切り上げ）

割り当てのルール（daily_reports_spec.md）:
  1. 最終回は「退所日」または「退所日の前日」に置く
  2. 複数回ある場合、残りは滞在期間内になるべく均等に散らす
  3. システムは候補を出すところまで。最終調整は人が上書きできる

3の上書きぶんだけ BathingDay に保存し、自動のままの予約は保存しない。
そうしておくと、予約の日程を動かしたとき入浴日も自動で追従する。
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from sqlmodel import Session, select

from app.config import load_config
from app.models import BathingDay, Reservation
from app.services.reservations import ValidationError


def bath_count(nights: int) -> int:
    """その滞在で何回入浴するか。

    日帰り（0泊）は計算上0回になる。実際に入浴する施設もあるので、
    設定で1回として扱えるようにしてある。
    """
    config = load_config()

    if nights <= 0:
        return 1 if config.bathing.include_daytrip else 0

    return math.ceil(nights / config.bathing.interval_nights)


def auto_days(reservation: Reservation) -> list[date]:
    """ルールから入浴日の候補を出す。

    最終回を退所日の前日に置き、そこから interval_nights 日ずつ
    さかのぼって並べる。こうすると自然に等間隔になり、かつ最初の回が
    入所日より前になることはない
    （回数の決め方が切り上げなので (回数-1)×間隔 ≦ 泊数-1 が常に成り立つ）。

    退所日ではなく前日にしているのは、退所日の朝は帰り支度があって
    入浴が難しいことが多いため。仕様はどちらでもよいとしているので、
    合わない場合は現場で1日ずらしてもらう。
    """
    config = load_config()
    count = bath_count(reservation.nights)
    if count == 0:
        return []

    if reservation.nights <= 0:
        # 日帰りはその日しかない
        return [reservation.check_in]

    last = reservation.check_out - timedelta(days=1)
    interval = config.bathing.interval_nights

    days = [
        last - timedelta(days=(count - 1 - i) * interval) for i in range(count)
    ]

    # 念のため。滞在の頭より前に出た場合は入所日に寄せる。
    return [max(day, reservation.check_in) for day in days]


def days_for(session: Session, reservation: Reservation) -> list[date]:
    """この予約の入浴日。人が調整済みならその内容、そうでなければ候補。"""
    if not reservation.bathing_is_manual:
        return auto_days(reservation)

    rows = session.exec(
        select(BathingDay)
        .where(BathingDay.reservation_id == reservation.id)
        .order_by(BathingDay.day)  # type: ignore[arg-type]
    )
    return [row.day for row in rows]


def set_days(
    session: Session, reservation_id: int, days: list[date]
) -> list[date]:
    """入浴日を手動で決め直す。

    以降この予約は自動計算の対象から外れる。日程を変えても入浴日が
    追従しなくなるが、せっかく合わせた予定が勝手に動くほうが困るため。
    """
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise ValidationError(f"予約が見つかりません: {reservation_id}")

    for day in days:
        if not reservation.covers(day):
            raise ValidationError(
                f"滞在期間の外です: {day}"
                f"（{reservation.check_in} 〜 {reservation.check_out}）"
            )

    existing = session.exec(
        select(BathingDay).where(BathingDay.reservation_id == reservation_id)
    )
    for row in existing:
        session.delete(row)

    unique_days = sorted(set(days))
    for day in unique_days:
        session.add(BathingDay(reservation_id=reservation_id, day=day))

    reservation.bathing_is_manual = True
    session.add(reservation)
    session.commit()

    return unique_days


def prune_out_of_range(session: Session, reservation: Reservation) -> list[date]:
    """滞在期間の外に出てしまった入浴日を消す。

    手動で入浴日を決めたあとに予約の日程を縮めると、期間の外に取り残される
    日が出る。そのままだと帳票には出ないのにデータだけ残り、回数が合わない
    理由が分からなくなるので、日程を変えたタイミングで掃除する。

    消した日を返す。呼び出し側で「何日ぶん減った」と伝えるために使う。
    """
    if not reservation.bathing_is_manual:
        return []

    rows = list(
        session.exec(
            select(BathingDay).where(BathingDay.reservation_id == reservation.id)
        )
    )

    removed: list[date] = []
    for row in rows:
        if not reservation.covers(row.day):
            removed.append(row.day)
            session.delete(row)

    if removed:
        session.commit()

    return sorted(removed)


def reset_days(session: Session, reservation_id: int) -> list[date]:
    """手動の調整を捨てて、自動の候補に戻す。"""
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise ValidationError(f"予約が見つかりません: {reservation_id}")

    existing = session.exec(
        select(BathingDay).where(BathingDay.reservation_id == reservation_id)
    )
    for row in existing:
        session.delete(row)

    reservation.bathing_is_manual = False
    session.add(reservation)
    session.commit()

    return auto_days(reservation)
