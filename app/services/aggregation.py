"""予約データからの自動集計。

新しい入力は要らず、①で持っている予約データから計算だけで出す。
日次表示と月次レポートは、どちらもこの「1日ごとの計算」を土台にしていて、
月次は日次を1ヶ月分ためて並べたもの（aggregation_spec.md 設計メモ）。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from app.models import Reservation


@dataclass(frozen=True)
class DailyCount:
    """ある1日の集計。"""

    day: date

    check_ins: int  # 入所人数
    check_outs: int  # 退所人数
    total: int  # 合計利用者数（日帰りも含む）
    overnight: int  # 泊り人数

    # その日にかかっている仮予約の件数。
    #
    # 上の4つの数に入っているかどうかは、施設の設定
    # （config.toml の aggregation.include_tentative）で変わる。
    # 既定では入っていない。集計から外していても件数は見えるようにしてある。
    tentative: int


@dataclass(frozen=True)
class PeriodSummary:
    """期間全体のまとめ。月次レポートにも、月の途中までの集計にも使う。"""

    days: list[DailyCount]
    capacity: int

    @property
    def person_days(self) -> int:
        """延べ利用者数。合計利用者数を期間分ぜんぶ足したもの。"""
        return sum(d.total for d in self.days)

    @property
    def occupancy_rate(self) -> float:
        """稼働率。

        分母は部屋数ではなく定員（人数）。部屋番号が未定の予約がありうる
        設計なので、部屋数を基準にすると数が合わなくなるため
        （aggregation_spec.md の補足）。

        期間を切って渡せば月の途中までの稼働率になる。日次表示の
        「今日時点までの当月の稼働率」はその使い方をしている。
        """
        denominator = self.capacity * len(self.days)
        if denominator == 0:
            return 0.0
        return self.person_days / denominator

    @property
    def occupancy_percent(self) -> float:
        return self.occupancy_rate * 100

    @property
    def peak(self) -> DailyCount | None:
        """一番混む日。月次レポートで目立たせる。"""
        return max(self.days, key=lambda d: d.total) if self.days else None


def count_day(
    reservations: list[Reservation],
    day: date,
    *,
    include_tentative: bool = False,
) -> DailyCount:
    """1日分の集計。

    泊り人数は「合計利用者数 − 退所人数」。退所日当日はもう泊まらないので、
    この引き算で日帰り（入所日=退所日）も自動的に外れる。

    仮予約は既定では数に入れない。成立しないことが多く、含めると稼働率が
    実績より高く出てしまうため。件数だけは tentative で返すので、
    「確定◯人＋仮予約◯件」という見せ方ができる。
    """
    check_ins = 0
    check_outs = 0
    total = 0
    tentative = 0

    for reservation in reservations:
        if not reservation.covers(day):
            continue

        if reservation.is_tentative:
            tentative += 1
            if not include_tentative:
                continue

        total += 1
        if reservation.check_in == day:
            check_ins += 1
        if reservation.check_out == day:
            check_outs += 1

    return DailyCount(
        day=day,
        check_ins=check_ins,
        check_outs=check_outs,
        total=total,
        overnight=total - check_outs,
        tentative=tentative,
    )


def count_period(
    reservations: list[Reservation],
    start: date,
    end: date,
    capacity: int,
    *,
    include_tentative: bool = False,
) -> PeriodSummary:
    """start〜end の各日を集計してまとめる。"""
    days = [
        count_day(
            reservations,
            start + timedelta(days=i),
            include_tentative=include_tentative,
        )
        for i in range((end - start).days + 1)
    ]
    return PeriodSummary(days=days, capacity=capacity)


def count_month(
    reservations: list[Reservation],
    year: int,
    month: int,
    capacity: int,
    *,
    include_tentative: bool = False,
) -> PeriodSummary:
    last_day = calendar.monthrange(year, month)[1]
    return count_period(
        reservations,
        date(year, month, 1),
        date(year, month, last_day),
        capacity,
        include_tentative=include_tentative,
    )


def month_to_date(summary: PeriodSummary, through: date) -> PeriodSummary:
    """月初から指定日までに切り詰める。

    月の途中でも稼働率を出せるようにするためのもの。月末まで通した分母で
    割ると、月の前半はいつも低い数字になってしまい、目安として使えない。
    """
    days = [d for d in summary.days if d.day <= through]
    return PeriodSummary(days=days, capacity=summary.capacity)
