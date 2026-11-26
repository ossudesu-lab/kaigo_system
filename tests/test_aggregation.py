"""人数と稼働率の集計（aggregation_spec.md）。

- 泊り人数 = 合計利用者数 − 退所人数（退所日は泊まらない）
- 仮予約は既定で数に入れないが、件数は別に見える
- 稼働率の分母は定員 × 日数
- 月の途中までの稼働率は、その日までで割る
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models import Reservation
from app.services import aggregation


def _r(check_in: date, check_out: date, *, tentative: bool = False) -> Reservation:
    return Reservation(
        user_master_id=1,
        check_in=check_in,
        check_out=check_out,
        is_tentative=tentative,
    )


D = date(2026, 7, 10)


def test_入所退所泊りの人数():
    reservations = [
        _r(date(2026, 7, 10), date(2026, 7, 12)),  # 今日入所
        _r(date(2026, 7, 8), date(2026, 7, 10)),  # 今日退所
        _r(date(2026, 7, 5), date(2026, 7, 15)),  # 滞在中
        _r(date(2026, 7, 11), date(2026, 7, 13)),  # まだ来ていない
    ]
    count = aggregation.count_day(reservations, D)

    assert count.check_ins == 1
    assert count.check_outs == 1
    assert count.total == 3
    assert count.overnight == 2  # 退所する人は泊まらない


def test_日帰りは合計に入るが泊りには入らない():
    count = aggregation.count_day([_r(D, D)], D)

    assert count.total == 1
    assert count.check_ins == 1
    assert count.check_outs == 1
    assert count.overnight == 0


def test_仮予約は既定で数に入れず件数だけ数える():
    reservations = [_r(date(2026, 7, 9), date(2026, 7, 12), tentative=True)]

    count = aggregation.count_day(reservations, D)
    assert count.total == 0
    assert count.tentative == 1

    included = aggregation.count_day(reservations, D, include_tentative=True)
    assert included.total == 1
    assert included.tentative == 1


def test_稼働率は延べ人数を定員かける日数で割る():
    # 定員2人・3日間。7/1〜7/3 の各日に1人ずつ（退所日も数える）
    reservations = [_r(date(2026, 7, 1), date(2026, 7, 3))]
    summary = aggregation.count_period(
        reservations, date(2026, 7, 1), date(2026, 7, 3), capacity=2
    )

    assert summary.person_days == 3
    assert summary.occupancy_rate == pytest.approx(3 / 6)
    assert summary.occupancy_percent == pytest.approx(50.0)


def test_仮予約は稼働率も上げない():
    reservations = [_r(date(2026, 7, 1), date(2026, 7, 3), tentative=True)]
    summary = aggregation.count_period(
        reservations, date(2026, 7, 1), date(2026, 7, 3), capacity=2
    )
    assert summary.occupancy_rate == 0.0


def test_月次は月の日数ぶん並ぶ():
    assert len(aggregation.count_month([], 2026, 2, capacity=30).days) == 28
    assert len(aggregation.count_month([], 2028, 2, capacity=30).days) == 29  # うるう年
    assert len(aggregation.count_month([], 2026, 7, capacity=30).days) == 31


def test_月の途中までの稼働率はその日までで割る():
    # 7/1〜7/10 だけ1人いる。月末まで通すと低く出るが、10日時点では満員に近い
    reservations = [_r(date(2026, 7, 1), date(2026, 7, 10))]
    month = aggregation.count_month(reservations, 2026, 7, capacity=1)
    to_date = aggregation.month_to_date(month, date(2026, 7, 10))

    assert len(to_date.days) == 10
    assert to_date.occupancy_rate == pytest.approx(1.0)
    assert month.occupancy_rate == pytest.approx(10 / 31)


def test_一番混む日():
    reservations = [
        _r(date(2026, 7, 1), date(2026, 7, 3)),
        _r(date(2026, 7, 2), date(2026, 7, 4)),
    ]
    summary = aggregation.count_period(
        reservations, date(2026, 7, 1), date(2026, 7, 4), capacity=30
    )
    assert summary.peak.day == date(2026, 7, 2)
    assert summary.peak.total == 2


def test_予約がない期間でも0除算にならない():
    summary = aggregation.count_period([], date(2026, 7, 1), date(2026, 7, 1), capacity=0)
    assert summary.occupancy_rate == 0.0
