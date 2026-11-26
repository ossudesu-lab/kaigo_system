"""画面（HTML）を返すルート。

APIと同じく app/services を呼ぶだけ。ここには業務ロジックを書かない。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.config import load_config
from app.db import get_session
from app.services import aggregation
from app.services import care_managers as cm_service
from app.services import inquiries as inquiry_service
from app.services import reports
from app.services import reservations as service
from app.services import users as users_service
from app.services.grid import build_grid, month_range, urgency_of

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def static_v(filename: str) -> int:
    """静的ファイル（CSS/JS）のキャッシュ破棄用バージョン。

    ブラウザは /static/grid.js などを積極的にキャッシュするため、ファイルを
    直しても古い版が実行され「反映されない」ことがある（Ctrl+F5でも効かない
    ことがある）。ファイルの更新時刻を `?v=` として付けると、直すたびにURLが
    変わり、普通の再読み込みでも必ず新しい版が読まれる。
    """
    try:
        return int((STATIC_DIR / filename).stat().st_mtime)
    except OSError:
        return 0


# テンプレートから {{ static_v('grid.js') }} の形で呼べるようにする。
templates.env.globals["static_v"] = static_v

router = APIRouter()

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


def _nav(day: date | None = None, month_of: date | None = None) -> dict:
    """全画面共通のナビゲーションが使うリンク先。

    画面ごとにリンクを並べていると足し忘れが起きるので、共通のヘッダーに
    まとめている（実際に問い合わせ画面への導線が抜けていた）。

    日付を引き回しているのは、見ている日を保ったまま画面を移れるようにするため。
    入浴表で7/11を見ているときに当日台帳へ移ると、同じ7/11が開く。
    """
    today = date.today()
    day = day or today
    month_of = month_of or today
    return {
        "nav_day": day,
        "nav_year": month_of.year,
        "nav_month": month_of.month,
        "today": today,
    }


def _ticks(scale_max: int) -> list[int]:
    """グラフの目盛り。5,10,20…のきりのいい数で刻む。

    半端な数（7とか13とか）で刻むと目盛りが読めないので、
    目盛りが4〜8本くらいに収まるきりのいい間隔を選ぶ。
    """
    for step in (1, 2, 5, 10, 20, 50, 100):
        if scale_max / step <= 8:
            break
    return list(range(0, scale_max + 1, step))


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    today = date.today()
    return RedirectResponse(url=f"/grid?year={today.year}&month={today.month}")


@router.get("/grid", response_class=HTMLResponse)
def grid_page(
    request: Request,
    year: int,
    month: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    config = load_config()
    start, end = month_range(year, month)

    reservations = service.list_in_period(session, start, end)
    grid = build_grid(reservations, year, month)
    unassigned = service.list_unassigned(session)

    # 部屋未定の予約ごとに、その期間で埋まっている部屋（UI改善仕様③）。
    # 予約の期間は表示中の月からはみ出すことがあるので、上の reservations は
    # 使い回さず、予約ごとに期間で取り直す。
    occupied_beds = {
        r.id: service.find_occupied_beds(session, r) for r in unassigned
    }

    today = date.today()

    # 部屋未定の予約を、入所日の近さで色分けするための緊急度（UI改善⑤）。
    # 並び順自体は list_unassigned が入所日の昇順で返している。
    urgency = {r.id: urgency_of(r.check_in, today) for r in unassigned}
    has_urgent = "urgent" in urgency.values()

    # 予約表は「表そのものを一望する作業画面」に振り切ったので、今日の人数・
    # 稼働率といった集計はここには出さない（「今日」ページへ移設）。ただし
    # グリッド下の日ごと集計は表の一部なので、ここで満月版を作って渡す。
    full_summary = aggregation.count_month(
        reservations,
        year,
        month,
        config.capacity,
        include_tentative=config.aggregation.include_tentative,
    )

    return templates.TemplateResponse(
        request=request,
        name="grid.html",
        context={
            **_nav(month_of=date(year, month, 1)),
            "config": config,
            "grid": grid,
            "unassigned": unassigned,
            "occupied_beds": occupied_beds,
            "urgency": urgency,
            "has_urgent": has_urgent,
            "today": today,
            "weekday_labels": WEEKDAY_LABELS,
            # グリッド下に出す、日ごとの集計（合計・入所・退所・泊り）。
            # 列（日付）と同じ順・同じ日数なので、そのまま横に並べる。
            "day_counts": full_summary.days,
            # 予約フォームのプルダウン用
            "users": users_service.list_users(session),
        },
    )


@router.get("/today", response_class=HTMLResponse)
def today_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """今日の状況（ダッシュボード）。

    予約表を「表そのもの」に振り切ったぶん、今日の利用者数・入退所・稼働率と
    いった"今日の把握"はこの画面に集約する。数字は予約データからの計算だけで、
    ここで入力するものは何もない。
    """
    config = load_config()
    today = date.today()

    # 今日の人数（合計・泊り・入所・退所・仮予約）。
    today_reservations = service.list_in_period(session, today, today)
    today_count = aggregation.count_day(
        today_reservations,
        today,
        include_tentative=config.aggregation.include_tentative,
    )

    # 稼働率は今月ぶんを今日までで締める。月末までの日数で割ると、月の前半は
    # 必ず低く出てしまい目安にならないため（予約表にあった扱いと同じ）。
    start, end = month_range(today.year, today.month)
    month_reservations = service.list_in_period(session, start, end)
    full_summary = aggregation.count_month(
        month_reservations,
        today.year,
        today.month,
        config.capacity,
        include_tentative=config.aggregation.include_tentative,
    )
    summary = aggregation.month_to_date(full_summary, today)

    # 「今日のレポート」らしさとして、今日の入所・退所の顔ぶれも出す。
    check_ins = [r for r in today_reservations if r.check_in == today]
    check_outs = [r for r in today_reservations if r.check_out == today]

    return templates.TemplateResponse(
        request=request,
        name="today.html",
        context={
            **_nav(),
            "config": config,
            "today": today,
            "weekday_labels": WEEKDAY_LABELS,
            "today_count": today_count,
            "summary": summary,
            "check_ins": check_ins,
            "check_outs": check_outs,
        },
    )


@router.get("/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    keyword: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """利用者マスタの一覧・登録画面。"""
    config = load_config()
    users = users_service.list_users(session, keyword=keyword)

    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context={
            **_nav(),
            "config": config,
            "users": users,
            # 担当CMのプルダウン用（CMマスタから選ぶ）
            "care_managers": cm_service.list_care_managers(session),
            "keyword": keyword or "",
            "today": date.today(),
        },
    )


@router.get("/report", response_class=HTMLResponse)
def report_page(
    request: Request,
    year: int,
    month: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """月次レポート。日次の集計を1ヶ月分ためて並べたもの。"""
    config = load_config()
    start, end = month_range(year, month)

    reservations = service.list_in_period(session, start, end)
    summary = aggregation.count_month(
        reservations,
        year,
        month,
        config.capacity,
        include_tentative=config.aggregation.include_tentative,
    )

    # 棒の高さの基準。定員を超える日があってもグラフから飛び出さないよう、
    # 実際の最大値と定員の大きいほうに合わせる。
    peak = summary.peak
    scale_max = max(config.capacity, peak.total if peak else 0)

    # 棒の高さを割り当てる基準は、目盛りの最大値より少し上に取る。
    # 目盛りぴったりにすると、定員ちょうどの日の線がグラフの一番上に
    # 重なって、基準線ではなく枠線に見えてしまうため。
    plot_max = scale_max * 1.12

    # 入退所は人数の桁が違う（定員30に対して1日数人）ので、
    # 利用者数のグラフと同じ目盛りにすると棒がほぼ見えない。別の基準にする。
    checkin_scale = max(1, max((d.check_ins for d in summary.days), default=1))

    today = date.today()
    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            **_nav(month_of=date(year, month, 1)),
            "config": config,
            "summary": summary,
            "year": year,
            "month": month,
            "scale_max": scale_max,
            "plot_max": plot_max,
            "ticks": _ticks(scale_max),
            "checkin_scale": checkin_scale,
            "checkin_plot_max": checkin_scale * 1.12,
            "checkin_ticks": _ticks(checkin_scale),
            "today": today,
            "weekday_labels": WEEKDAY_LABELS,
            "prev_month": (year - 1, 12) if month == 1 else (year, month - 1),
            "next_month": (year + 1, 1) if month == 12 else (year, month + 1),
        },
    )


@router.get("/ledger", response_class=HTMLResponse)
def ledger_page(
    request: Request,
    day: date | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """当日台帳。予約データ × 利用者マスタから作る。"""
    config = load_config()
    target = day or date.today()

    attendees = reports.attendees_on(session, target)

    return templates.TemplateResponse(
        request=request,
        name="ledger.html",
        context={
            **_nav(day=target, month_of=target),
            "config": config,
            "day": target,
            "attendees": attendees,
            "blocks": reports.ledger_blocks(attendees),
            "weekday_labels": WEEKDAY_LABELS,
            "prev_day": target - timedelta(days=1),
            "next_day": target + timedelta(days=1),
            "today": date.today(),
        },
    )


@router.get("/bathing", response_class=HTMLResponse)
def bathing_page(
    request: Request,
    day: date | None = None,
    span: str = "day",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """入浴表。当日分と1週間分を切り替えられる。

    1週間分の画面は、そのまま入浴日の調整にも使う。自動で出した候補を
    現場が動かせる必要があるため（daily_reports_spec.md）。
    """
    config = load_config()
    target = day or date.today()
    is_week = span == "week"

    sheets = (
        reports.bathing_week(session, target)
        if is_week
        else [reports.bathing_sheet(session, target)]
    )

    # 1週間分では、その週にいる人を縦に並べて、日ごとに丸を付ける形にする。
    # 日ごとの一覧を7つ並べるより、誰がいつ入るかを見比べやすい。
    week_attendees: list[reports.Attendee] = []
    if is_week:
        seen: set[int] = set()
        for i in range(7):
            for attendee in reports.attendees_on(session, target + timedelta(days=i)):
                key = attendee.reservation.id
                if key is not None and key not in seen:
                    seen.add(key)
                    week_attendees.append(attendee)

    return templates.TemplateResponse(
        request=request,
        name="bathing.html",
        context={
            **_nav(day=target, month_of=target),
            "config": config,
            "day": target,
            "span": span,
            "is_week": is_week,
            "sheets": sheets,
            "week_days": [target + timedelta(days=i) for i in range(7)],
            "week_attendees": week_attendees,
            "weekday_labels": WEEKDAY_LABELS,
            "prev_day": target - timedelta(days=7 if is_week else 1),
            "next_day": target + timedelta(days=7 if is_week else 1),
            "today": date.today(),
        },
    )


@router.get("/inquiries", response_class=HTMLResponse)
def inquiries_page(
    request: Request,
    status: str | None = None,
    kind: str | None = None,
    care_manager_id: int | None = None,
    guest_keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """問い合わせの一覧・記録画面。"""
    config = load_config()

    rows = inquiry_service.search_inquiries(
        session,
        status=status,
        kind=kind,
        care_manager_id=care_manager_id,
        guest_keyword=guest_keyword,
        date_from=date_from,
        date_to=date_to,
        keyword=keyword,
    )

    return templates.TemplateResponse(
        request=request,
        name="inquiries.html",
        context={
            **_nav(),
            "config": config,
            "inquiries": rows,
            "users": users_service.list_users(session),
            "care_managers": cm_service.list_care_managers(session),
            "today": date.today(),
            # 絞り込みの入力内容を画面に戻すため
            "filters": {
                "status": status or "",
                "kind": kind or "",
                "care_manager_id": care_manager_id or "",
                "guest_keyword": guest_keyword or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
                "keyword": keyword or "",
            },
            "has_filter": any([status, kind, care_manager_id, guest_keyword,
                               date_from, date_to, keyword]),
        },
    )


@router.get("/care-managers", response_class=HTMLResponse)
def care_managers_page(
    request: Request,
    keyword: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """CMマスタの一覧・登録画面。"""
    config = load_config()

    return templates.TemplateResponse(
        request=request,
        name="care_managers.html",
        context={
            **_nav(),
            "config": config,
            "care_managers": cm_service.list_care_managers(session, keyword=keyword),
            "keyword": keyword or "",
            "today": date.today(),
        },
    )
