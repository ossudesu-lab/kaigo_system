"""デモ用ダミーデータ投入スクリプト。

ポートフォリオ掲載用のスクリーンショットを撮るために、実運用に近い密度の
ダミーデータを投入する。氏名・事業所名はすべて架空。機能は一切足さない。

使い方（プロジェクト直下で実行）:

    python scripts/seed_demo.py            # 既存データを残したまま追加する
    python scripts/seed_demo.py --reset    # 既存データを全削除してから投入する

乱数シードを固定してあるので、何度実行しても同じデータが出る
（スクリーンショットを撮り直しても再現できる）。ただし「部屋未定」の
入所日だけは、緊急度バッジの見た目を今日基準で見せるため date.today() を
起点にしている。ここだけは実行日に追従する。

生成物のねらい（demo_data_and_ui_spec.md「1. デモ用ダミーデータの投入」）:
  - 2026年6〜8月の3か月ぶん、月間稼働率75〜85%
  - 滞在日数・曜日・リピートのばらつき
  - 仮予約（集計から除外される挙動）、部屋未定（右パネル）、
    意図的な部屋の重複（警告バナー＋ジャンプ）
  - 入浴表の自動／手動の対比、入浴種別の混在
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from random import Random

# プロジェクト直下を import パスに入れる（`python scripts/seed_demo.py` で動くように）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, delete, select  # noqa: E402

from app.config import load_config  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    BathingDay,
    CareManager,
    Gender,
    Inquiry,
    Reservation,
    UserMaster,
)
from app.services import bathing  # noqa: E402

# 乱数シード。日付にちなんだ固定値。ここを変えない限り毎回同じデータが出る。
SEED = 20260722

WINDOW_START = date(2026, 6, 1)
WINDOW_END = date(2026, 8, 31)


# --- 架空の氏名・属性のもと ---------------------------------------------------
#
# 既存データ（佐藤 花子 / 鈴木 一郎 の系統）を踏襲した、明らかな架空名。
# ふりがなを自前で用意できるよう、姓・名それぞれ (漢字, 読み) の組で持つ。

SURNAMES: list[tuple[str, str]] = [
    ("佐藤", "さとう"), ("鈴木", "すずき"), ("高橋", "たかはし"),
    ("田中", "たなか"), ("渡辺", "わたなべ"), ("伊藤", "いとう"),
    ("山本", "やまもと"), ("中村", "なかむら"), ("小林", "こばやし"),
    ("加藤", "かとう"), ("吉田", "よしだ"), ("山田", "やまだ"),
    ("佐々木", "ささき"), ("山口", "やまぐち"), ("松本", "まつもと"),
    ("井上", "いのうえ"), ("木村", "きむら"), ("清水", "しみず"),
    ("森", "もり"), ("池田", "いけだ"),
]

GIVEN_MALE: list[tuple[str, str]] = [
    ("一郎", "いちろう"), ("三郎", "さぶろう"), ("五郎", "ごろう"),
    ("七郎", "しちろう"), ("八郎", "はちろう"), ("太郎", "たろう"),
    ("健一", "けんいち"), ("正男", "まさお"), ("茂", "しげる"),
    ("勇", "いさむ"),
]

GIVEN_FEMALE: list[tuple[str, str]] = [
    ("花子", "はなこ"), ("幸子", "さちこ"), ("六子", "むつこ"),
    ("春子", "はるこ"), ("秋子", "あきこ"), ("和子", "かずこ"),
    ("洋子", "ようこ"), ("京子", "きょうこ"), ("節子", "せつこ"),
    ("文子", "ふみこ"),
]

# 疾患・注意事項・訓練。いずれも一般的な表現に留める（個人が特定されない）。
CONDITIONS = [
    "認知症", "パーキンソン病", "脳梗塞後遺症", "糖尿病", "高血圧",
    "関節リウマチ", "骨粗しょう症", "心不全", None, None,
]
NOTES = [
    "転倒リスク高い", "移乗全介助", "見守り必要", "難聴あり",
    "服薬管理必要", "車椅子使用", None, None,
]
TRAININGS = [
    "エアロバイク", "歩行訓練", "平行棒", "上肢ROM訓練", None, None,
]

# 担当ケアマネジャー（架空）。事業所名・連絡先も架空。
CARE_MANAGERS = [
    ("山田 太郎", "○○居宅介護支援事業所", "03-1234-5678"),
    ("高橋 誠", "さくら居宅介護支援", "03-2345-6789"),
    ("鈴木 恵子", "ひまわりケアプラン", "03-3456-7890"),
    ("佐々木 恵", "あおぞら居宅", "03-4567-8901"),
    ("中島 保", "みどり介護支援センター", "03-5678-9012"),
]


# --- 生成の途中で持ち回る、確定前の予約 ---------------------------------------


class Draft:
    """DBに入れる前の予約。ベッドや利用者の割り当てを後から差し替えるため、
    いったんただの入れ物として持っておく。"""

    __slots__ = ("bed_id", "check_in", "check_out", "is_tentative",
                 "user_id", "manual")

    def __init__(self, bed_id, check_in, check_out, is_tentative=False):
        self.bed_id = bed_id
        self.check_in = check_in
        self.check_out = check_out
        self.is_tentative = is_tentative
        self.user_id: int | None = None
        self.manual = False


def _sample_nights(rng: Random) -> int:
    """滞在日数（泊数）。短期を多めに、長期も混ぜる。"""
    r = rng.random()
    if r < 0.35:
        return 1
    if r < 0.65:
        return rng.randint(2, 3)
    if r < 0.90:
        return rng.randint(5, 7)
    return rng.randint(10, 16)


def _sample_gap(rng: Random) -> int:
    """次の入所までの空き日数。小さめ（回転が速い）。1以上にして、
    退所日と翌入所日が重なって偶発的な重複が出ないようにする。"""
    r = rng.random()
    if r < 0.50:
        return 1
    if r < 0.80:
        return 2
    if r < 0.95:
        return 3
    return rng.randint(4, 6)


def _bias_weekday(day: date, rng: Random) -> date:
    """入所日を土日・月曜に寄せる（現場は週末・週明けの入所が多い）。
    前方向へ最大3日だけずらす。ずらすと空きが増えるので稼働率も少し下がる。"""
    if rng.random() < 0.45:
        for shift in range(0, 4):
            candidate = day + timedelta(days=shift)
            if candidate.weekday() in (5, 6, 0):  # 土・日・月
                return candidate
    return day


def _generate_bed(bed_id: str, rng: Random) -> list[Draft]:
    """1ベッドぶんの予約列を、期間の頭から末尾まで敷き詰める。"""
    drafts: list[Draft] = []
    # 全ベッドが同じ日に始まると不自然なので、開始位置を少し散らす。
    # 期間の頭より前から始めると、先月からの連続利用も表現できる。
    cursor = WINDOW_START - timedelta(days=rng.randint(0, 8))
    while cursor <= WINDOW_END:
        check_in = _bias_weekday(cursor, rng)
        if check_in > WINDOW_END:
            break
        nights = _sample_nights(rng)
        check_out = check_in + timedelta(days=nights)
        drafts.append(Draft(bed_id, check_in, check_out))
        cursor = check_out + timedelta(days=_sample_gap(rng))
    return drafts


def _find_july_gap(drafts: list[Draft], length: int) -> tuple[date, date] | None:
    """そのベッドの7月の中で、length日ぶん空いている窓を探す。
    仮予約を、確定予約と重ならない場所（＝偶発的な重複を出さない場所）に
    置くために使う。"""
    jul_start, jul_end = date(2026, 7, 1), date(2026, 7, 28)
    # 置こうとする窓は最大で jul_end + length まで伸びるので、その範囲に
    # かかる予約はすべて衝突判定の対象にする（境界の外の予約と重なって
    # 偶発的な重複を作らないため）。
    horizon = jul_end + timedelta(days=length)
    occupied = sorted(
        (d.check_in, d.check_out) for d in drafts
        if d.check_in <= horizon and d.check_out >= jul_start
    )
    day = jul_start
    while day <= jul_end:
        end = day + timedelta(days=length)
        clash = any(ci <= end and co >= day for ci, co in occupied)
        if not clash:
            return day, end
        day += timedelta(days=1)
    return None


def _wipe(session: Session) -> None:
    """--reset 用。FKの向きに合わせて子から消す。"""
    session.exec(delete(BathingDay))
    session.exec(delete(Inquiry))
    session.exec(delete(Reservation))
    session.exec(delete(UserMaster))
    session.exec(delete(CareManager))
    session.commit()


def _create_care_managers(session: Session) -> list[int]:
    ids: list[int] = []
    for name, office, phone in CARE_MANAGERS:
        cm = CareManager(name=name, office=office, phone=phone)
        session.add(cm)
        session.commit()
        session.refresh(cm)
        ids.append(cm.id)
    return ids


def _create_users(session: Session, rng: Random, cm_ids: list[int]) -> list[int]:
    """30名の利用者を作る（定員30に合わせる）。姓×名の組をシャッフルして
    重複しない氏名にする。"""
    combos: list[tuple[tuple[str, str], tuple[str, str], Gender]] = []
    for surname in SURNAMES:
        for given in GIVEN_MALE:
            combos.append((surname, given, Gender.MALE))
        for given in GIVEN_FEMALE:
            combos.append((surname, given, Gender.FEMALE))
    rng.shuffle(combos)

    ids: list[int] = []
    for i in range(30):
        (sk, sr), (gk, gr), gender = combos[i]
        # 入浴種別は「一般」を基本に、2割ほど「リフト」を混ぜる。
        bathing_type = "リフト" if rng.random() < 0.2 else "一般"
        user = UserMaster(
            name=f"{sk} {gk}",
            kana=f"{sr}{gr}",
            gender=gender,
            condition=rng.choice(CONDITIONS),
            notes=rng.choice(NOTES),
            training=rng.choice(TRAININGS),
            bathing_type=bathing_type,
            care_manager_id=rng.choice(cm_ids),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        ids.append(user.id)
    return ids


def _assign_users(drafts: list[Draft], user_ids: list[int], rng: Random) -> None:
    """各予約に利用者を割り当てる。同じ人が同じ夜に別ベッドで二重に泊まる
    見た目を避けるため、その人の既存の夜と重ならない相手を優先して選ぶ。
    どうしても取れなければ諦めてそのまま入れる（デモなので厳密でなくてよい）。"""
    nights_by_user: dict[int, list[tuple[date, date]]] = {}

    def overlaps_existing(uid: int, ci: date, co: date) -> bool:
        for eci, eco in nights_by_user.get(uid, []):
            if max(ci, eci) < min(co, eco):
                return True
        return False

    for draft in drafts:
        if draft.user_id is not None:
            continue  # 重複ペアなど、あらかじめ割り当て済みのものは触らない
        chosen = None
        for _ in range(12):
            uid = rng.choice(user_ids)
            if not overlaps_existing(uid, draft.check_in, draft.check_out):
                chosen = uid
                break
        if chosen is None:
            chosen = rng.choice(user_ids)
        draft.user_id = chosen
        nights_by_user.setdefault(chosen, []).append(
            (draft.check_in, draft.check_out)
        )


def _create_inquiries(
    session: Session, rng: Random, user_ids: list[int], cm_ids: list[int]
) -> int:
    """問い合わせ画面が空にならないよう、数件だけ架空の問い合わせを入れる。"""
    config = load_config()
    kinds = list(config.inquiry.kinds)
    statuses = list(config.inquiry.statuses)
    today = date.today()

    count = 0
    for i in range(8):
        inquiry_date = today - timedelta(days=rng.randint(0, 20))
        registered = rng.random() < 0.6
        user_id = rng.choice(user_ids) if registered else None
        guest = None if registered else rng.choice([
            "問い合わせ 一郎", "相談 花子", "見学 太郎",
        ])
        desired_in = today + timedelta(days=rng.randint(1, 25))
        session.add(Inquiry(
            inquiry_date=inquiry_date,
            care_manager_id=rng.choice(cm_ids),
            user_master_id=user_id,
            guest_name=guest,
            desired_check_in=desired_in,
            desired_check_out=desired_in + timedelta(days=rng.randint(1, 7)),
            kind=rng.choice(kinds),
            status=rng.choice(statuses),
            memo=rng.choice([
                "空き状況の確認。", "退院後の受け入れ相談。",
                "定期利用の希望あり。", None,
            ]),
        ))
        count += 1
    session.commit()
    return count


def seed(reset: bool) -> None:
    config = load_config()
    rng = Random(SEED)

    init_db()
    with Session(engine) as session:
        if reset:
            _wipe(session)

        cm_ids = _create_care_managers(session)
        user_ids = _create_users(session, rng, cm_ids)

        bed_ids = [bed.id for bed in config.beds]

        # 1) 全ベッドを敷き詰める。
        by_bed: dict[str, list[Draft]] = {
            bed_id: _generate_bed(bed_id, rng) for bed_id in bed_ids
        }

        # 2) 意図的な部屋の重複を2件だけ作る（警告バナー／ジャンプの見どころ）。
        #    7月中旬をまたぐ既存予約に、同じベッドで重なる予約を1本足す。
        conflict_beds = 0
        for bed_id in bed_ids:
            if conflict_beds >= 2:
                break
            for base in by_bed[bed_id]:
                if base.check_in <= date(2026, 7, 17) and base.check_out >= date(2026, 7, 14):
                    # base の期間の内側から始めて、必ず宿泊が重なるようにする。
                    ci = max(base.check_in + timedelta(days=1), date(2026, 7, 14))
                    if ci >= base.check_out:
                        continue
                    co = ci + timedelta(days=4)
                    by_bed[bed_id].append(Draft(bed_id, ci, co))
                    conflict_beds += 1
                    break

        # 3) 仮予約（グリッド上に点線で出るよう、確定予約と重ならない空き窓に置く）。
        tentative_on_grid = 0
        for bed_id in bed_ids:
            if tentative_on_grid >= 4:
                break
            gap = _find_july_gap(by_bed[bed_id], length=3)
            if gap is not None:
                by_bed[bed_id].append(Draft(bed_id, gap[0], gap[1], is_tentative=True))
                tentative_on_grid += 1

        drafts: list[Draft] = [d for lst in by_bed.values() for d in lst]

        # 4) 部屋未定（右パネル）。緊急度バッジを見せたいので入所日を今日基準にする。
        today = date.today()
        undecided_offsets = [0, 2, 5]  # urgent（今日）/ soon（2日後）/ normal（5日後）
        for off in undecided_offsets:
            ci = today + timedelta(days=off)
            drafts.append(Draft(None, ci, ci + timedelta(days=rng.randint(2, 6))))

        # 5) 仮予約のうち1件は部屋未定のまま（未定にも仮予約があると分かる）。
        ci = today + timedelta(days=3)
        drafts.append(
            Draft(None, ci, ci + timedelta(days=rng.randint(1, 4)), is_tentative=True)
        )

        # 6) 利用者を割り当てる。
        _assign_users(drafts, user_ids, rng)

        # 7) 入浴の手動調整を一部に持たせる（自動バッジとの対比）。3泊以上を対象。
        for draft in drafts:
            nights = (draft.check_out - draft.check_in).days
            if nights >= 3 and not draft.is_tentative and rng.random() < 0.35:
                draft.manual = True

        # --- DBへ書き込む ---
        reservations: list[Reservation] = []
        for draft in drafts:
            res = Reservation(
                user_master_id=draft.user_id,
                bed_id=draft.bed_id,
                check_in=draft.check_in,
                check_out=draft.check_out,
                is_tentative=draft.is_tentative,
            )
            session.add(res)
            reservations.append(res)
        session.commit()
        for res in reservations:
            session.refresh(res)

        # 8) 手動調整ぶんの入浴日を作る。自動候補を1日ずらして「人が動かした」状態にする。
        manual_count = 0
        for draft, res in zip(drafts, reservations):
            if not draft.manual:
                continue
            auto = bathing.auto_days(res)
            if not auto:
                continue
            # 最初の入浴日を1日後ろへ。滞在期間内かつ他の日と重ならない範囲で。
            shifted = list(auto)
            moved = shifted[0] + timedelta(days=1)
            if res.covers(moved) and moved not in shifted[1:]:
                shifted[0] = moved
            bathing.set_days(session, res.id, shifted)
            manual_count += 1

        inquiry_count = _create_inquiries(session, rng, user_ids, cm_ids)

        _report(session, config, len(reservations), manual_count,
                 conflict_beds, tentative_on_grid, inquiry_count)


def _report(session, config, res_count, manual_count, conflict_beds,
            tentative_on_grid, inquiry_count) -> None:
    """投入後の自己確認。完了確認チェックリスト（指示書）に対応する数字を出す。"""
    from app.services import aggregation

    all_res = list(session.exec(select(Reservation)).all())
    user_total = len(session.exec(select(UserMaster)).all())
    tentative_total = sum(1 for r in all_res if r.is_tentative)
    unassigned_total = sum(1 for r in all_res if r.bed_id is None)

    print("=" * 56)
    print("デモデータ投入 完了")
    print("=" * 56)
    print(f"利用者マスタ  : {user_total}名")
    print(f"予約          : {res_count}件")
    print(f"入浴 手動調整 : {manual_count}件（残りは自動）")
    print(f"仮予約        : {tentative_total}件")
    print(f"部屋未定      : {unassigned_total}件")
    print(f"意図的な重複  : {conflict_beds}ベッド")
    print(f"問い合わせ    : {inquiry_count}件")
    print("-" * 56)

    for y, m in ((2026, 6), (2026, 7), (2026, 8)):
        summary = aggregation.count_month(
            all_res, y, m, config.capacity,
            include_tentative=config.aggregation.include_tentative,
        )
        occ = summary.occupancy_percent
        flag = "OK" if 75 <= occ <= 85 else "範囲外!"
        peak = summary.peak.total if summary.peak else 0
        print(f"{y}年{m:2d}月  稼働率 {occ:5.1f}%  [{flag}]  "
              f"延べ{summary.person_days}人日  最多{peak}人/日")
    print("=" * 56)


def main() -> None:
    reset = "--reset" in sys.argv[1:]
    seed(reset=reset)


if __name__ == "__main__":
    main()
