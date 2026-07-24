"""予約データを、画面に描くためのグリッド（部屋 × 日付）に組み立てる。

reservation_spec.md「① 画面の見た目・色分けルール」の優先順位を
ここで解決してしまい、テンプレート側は出てきた結果を並べるだけにする。

  1. 入所日・退所日 … セル全体を専用色にする（最優先）
  2. それ以外の宿泊中 … 性別で色分け
  3. 仮予約 … 点線の枠を重ねる（色は変えない）
  4. 重なり・連続利用 … 予約を上下の段に分けて、両方をフル高さで見せる

3は「色の上に重ねる」ものなので、1・2で決まる色とは別のフィールドで持つ。

4は当初セルに赤枠を重ねていたが、どの予約とどの予約が重なっているのかが
読み取りにくかったため、段をずらす表現に変えた（UI改善仕様）。
段の割り振りは _assign_lanes が行う。段があるベッドは行の高さを段数ぶん
広げて、1マスに詰め込まず各段をフル高さで見せる。

退所日と同じ日に次の人が入所する「連続利用」も、1マスに斜めで押し込めず
上下の段に分ける。ただしこれは普通の引き継ぎで重複ではないので、実際に
泊まりが重なる「真の重複」とは区別し、赤い区切り線は真の重複にだけ出す。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.config import Bed, load_config
from app.models import Gender, Reservation
from app.services.reservations import (
    MixedGenderPair,
    find_conflicts,
    find_mixed_gender_pairs,
)


@dataclass
class Bar:
    """マスの中に描く帯。1つの段（レーン）の、その日ぶん。

    重なっていない予約は1段だけで、マスいっぱいに描かれる（従来どおり）。
    重なっている予約だけ段が増え、上下にずらして両方が見えるようにする。
    """

    day: date

    # 何段目か（0が上）と、そのかたまりで必要な段数。
    lane: int = 0
    lane_count: int = 1

    # 1・2で決まる、帯の状態
    # "empty" / "checkin" / "checkout" / "stay" / "turnover" / "daytrip"
    kind: str = "empty"

    # kind == "stay" のときの性別（色に使う）
    gender: Gender | None = None

    # 3の重ねる表現
    is_tentative: bool = False

    # この段に関係する予約。通常1件、入れ替わりの日だけ2件。
    reservations: list[Reservation] = field(default_factory=list)

    @property
    def top_percent(self) -> float:
        return 100 * self.lane / self.lane_count

    @property
    def height_percent(self) -> float:
        return 100 / self.lane_count

    @property
    def primary(self) -> Reservation | None:
        """代表となる予約。クリックしたときに開く対象。

        入れ替わりの日は、これから泊まる人（入所側）を優先する。
        退所する人はもう出ていくので、操作したいのは入所側のことが多い。
        """
        if not self.reservations:
            return None
        for reservation in self.reservations:
            if reservation.check_in == self.day:
                return reservation
        return self.reservations[0]

    @property
    def label(self) -> str:
        """マスに出す文字。入所日にだけ名前を出す。

        毎日名前を出すと横に長く伸びて読みにくいので、始まりの日にだけ置く。
        """
        primary = self.primary
        if primary is None:
            return ""
        if primary.check_in == self.day:
            return primary.guest_name
        return ""

    @property
    def continues_right(self) -> bool:
        """このバーの予約が翌日も続いているか。

        続いているマスだけ、テンプレート側で塗りを右へ1pxはみ出させて
        セルの縦罫線を覆い、連続予約を切れ目のない1本の帯に見せる。
        退所日は covers が翌日を含まないので False になり、帯は端で止まる。
        """
        if not self.reservations:
            return False
        return self.reservations[0].covers(self.day + timedelta(days=1))

    @property
    def continues_left(self) -> bool:
        """このバーの予約が前日から続いているか。

        続いていない側（＝帯の始まり／終わり）の角だけを丸めて、1本の棒の
        ように見せるために使う。始まりは入所日、終わりは退所日にあたる。
        """
        if not self.reservations:
            return False
        return self.reservations[0].covers(self.day - timedelta(days=1))


@dataclass
class Cell:
    """グリッドのマス1つ分。中に段（Bar）を0〜N本持つ。"""

    day: date
    bars: list[Bar] = field(default_factory=list)

    # 準個室に男女が同室になっている印。施設の設定で有効にしたときだけ付く。
    is_mixed_gender: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.bars

    @property
    def is_conflict(self) -> bool:
        """そのマスが、実際に部屋を取り合っているか（真の重複か）。

        連続利用（片方が退所する日に、もう片方が入所する日）は、上下の段に
        分かれて2段になるが、同じ夜に2人が寝ているわけではないので重複では
        ない。そのため段数ではなく、実際に泊まりが重なっているかで判定する。
        """
        res = self.reservations
        if len(res) < 2:
            return False

        for i, a in enumerate(res):
            for b in res[i + 1 :]:
                # 片方が退所し片方が入所するだけの日は、普通の引き継ぎ。
                if (a.check_out == self.day and b.check_in == self.day) or (
                    b.check_out == self.day and a.check_in == self.day
                ):
                    continue
                return True
        return False

    @property
    def reservations(self) -> list[Reservation]:
        return [r for bar in self.bars for r in bar.reservations]

    @property
    def primary(self) -> Reservation | None:
        """マスを代表する予約。ドラッグの可否の判定に使う。"""
        for bar in self.bars:
            if bar.primary is not None:
                return bar.primary
        return None


@dataclass
class ConflictEntry:
    """画面上部の重複警告リストの1件。

    押すと該当のマスまで飛ばせるように（UI改善仕様①）、予約そのものに
    加えて「どのマスへ飛ぶか」を持たせる。
    """

    reservation: Reservation

    # 飛び先の日。表示中の月の中で、実際に取り合いになっている最初の日を指す。
    # 予約の入所日をそのまま使わないのは、先月から続いている予約だと
    # 入所日が今のグリッドの外にあり、飛び先が無くなってしまうため。
    day: date

    @property
    def bed_id(self) -> str | None:
        return self.reservation.bed_id


@dataclass
class Row:
    """グリッドの1行 = ベッド1つ分。"""

    bed: Bed
    cells: list[Cell]

    # このベッドで同時に必要になる段の最大数。1なら従来どおりの高さ、
    # 2以上ならその段数ぶん行を高くして、各段をフル高さで見せる。
    lane_count: int = 1


@dataclass
class Grid:
    year: int
    month: int
    days: list[date]
    rows: list[Row]

    # 重複している予約。グリッドの赤枠だけだと、画面を下までスクロール
    # しないと気づけないので、上にまとめて出すために持っておく。
    conflicts: list[ConflictEntry] = field(default_factory=list)

    # 準個室の男女同室。設定が無効な施設では常に空になる。
    mixed_gender: list[MixedGenderPair] = field(default_factory=list)

    @property
    def prev_month(self) -> tuple[int, int]:
        if self.month == 1:
            return self.year - 1, 12
        return self.year, self.month - 1

    @property
    def next_month(self) -> tuple[int, int]:
        if self.month == 12:
            return self.year + 1, 1
        return self.year, self.month + 1


def month_range(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def urgency_of(check_in: date, today: date) -> str:
    """部屋未定の予約が、入所日までの近さでどれくらい急ぎか（UI改善⑤）。

    "urgent" … 今日・明日に入所、または既に入所日を過ぎている（要対応）
    "soon"   … 2〜3日以内に入所
    "normal" … それ以降
    """
    days = (check_in - today).days
    if days <= 1:
        return "urgent"
    if days <= 3:
        return "soon"
    return "normal"


def _classify(cell: Bar) -> None:
    """その段に乗っている予約から、帯の状態を決める。"""
    day = cell.day

    if len(cell.reservations) == 1:
        # 1人だけのマス。日帰りは入所日と退所日が同じ日になるので、
        # 「入れ替わり」と混同しないよう先に分けておく。
        reservation = cell.reservations[0]
        if reservation.check_in == day == reservation.check_out:
            cell.kind = "daytrip"
        elif reservation.check_in == day:
            cell.kind = "checkin"
        elif reservation.check_out == day:
            cell.kind = "checkout"
        else:
            cell.kind = "stay"
            cell.gender = reservation.gender
    else:
        checking_in = [r for r in cell.reservations if r.check_in == day]
        checking_out = [r for r in cell.reservations if r.check_out == day]

        if checking_in and checking_out:
            # 出る人と入る人が同じ日にいる（入れ替わり）
            cell.kind = "turnover"
        elif checking_in:
            cell.kind = "checkin"
        elif checking_out:
            cell.kind = "checkout"
        else:
            cell.kind = "stay"
            cell.gender = cell.reservations[0].gender

    # 仮予約の点線は、代表の予約の状態で出す
    primary = cell.primary
    cell.is_tentative = primary.is_tentative if primary else False


def _assign_lanes(here: list[Reservation]) -> tuple[dict[int, int], int]:
    """同じベッドの予約に、上下の段を割り振る。

    返すのは (予約ID → 何段目か, そのベッドで必要な段の最大数)。
    段数はベッド（行）ごとにそろえる。行の高さは1本ぶんの高さ × この段数で
    決め、どの段もフル高さ（≒1マス）で描けるようにするため。

    段を分けるのは「日付が重なる、または隣り合う」予約どうし。同じ日に
    退所と入所が接する連続利用も、同じ段に押し込めず別の段に分ける
    （斜め1マスではなく、上下に並べて見せるため）。まったく離れた予約は
    同じ段を使い回せるので、行がむやみに高くならない。
    """
    lanes: dict[int, int] = {}
    lane_ends: list[date] = []  # 各段の、今埋まっている最後の日（退所日）

    # 入所日の順に、上から空いている段へ詰めていく。
    for reservation in sorted(here, key=lambda r: (r.check_in, r.check_out)):
        placed = False
        for i, end in enumerate(lane_ends):
            # その段の前の人が完全に退所し、退所日の翌日以降に始まる予約だけ、
            # 同じ段を使い回す。退所日と同じ日に始まる連続利用は使い回さない
            # （別の段に分けて上下に並べる）。
            if end < reservation.check_in:
                lane_ends[i] = reservation.check_out
                if reservation.id is not None:
                    lanes[reservation.id] = i
                placed = True
                break

        if not placed:
            lane_ends.append(reservation.check_out)
            if reservation.id is not None:
                lanes[reservation.id] = len(lane_ends) - 1

    return lanes, max(len(lane_ends), 1)


def _jump_day(
    reservation: Reservation,
    conflict_days: dict[str, list[date]],
    start: date,
) -> date:
    """重複警告を押したときに飛ぶ日を決める。

    その予約が実際に取り合っている最初の日を選ぶ。見つからないときは
    月初と入所日の遅いほうにする（先月から続いている予約でも、
    グリッドの中の日を必ず返すため）。
    """
    for day in conflict_days.get(reservation.bed_id or "", []):
        if reservation.covers(day):
            return day
    return max(reservation.check_in, start)


def build_grid(reservations: list[Reservation], year: int, month: int) -> Grid:
    """その月のグリッドを組み立てる。

    reservations は、その月にかかる予約をあらかじめ取ってきたもの。
    ここではDBを触らない（純粋な組み立てだけにして、テストしやすくする）。
    """
    config = load_config()
    start, end = month_range(year, month)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    conflicted_ids = find_conflicts(reservations)

    # 準個室の男女同室。警告を出さない設定の施設では、計算そのものを行わない。
    mixed_pairs: list[MixedGenderPair] = []
    mixed_marks: set[tuple[str, date]] = set()
    if config.warnings.mixed_gender_in_shared_room:
        mixed_pairs = find_mixed_gender_pairs(reservations)
        for pair in mixed_pairs:
            night = pair.start
            while night <= pair.end:
                for bed_id in (pair.a.bed_id, pair.b.bed_id):
                    if bed_id is not None:
                        mixed_marks.add((bed_id, night))
                night += timedelta(days=1)

    # ベッドごとに予約を振り分けておく（毎マス全件走査すると 40×31 で無駄が多い）
    by_bed: dict[str, list[Reservation]] = {}
    for reservation in reservations:
        if reservation.bed_id is not None:
            by_bed.setdefault(reservation.bed_id, []).append(reservation)

    # 警告リストの飛び先を出すために、実際に赤枠が付いた日を控えておく。
    conflict_days: dict[str, list[date]] = {}

    rows: list[Row] = []
    for bed in config.beds:
        here = by_bed.get(bed.id, [])
        lanes, lane_count = _assign_lanes(here)
        cells: list[Cell] = []

        for day in days:
            cell = Cell(day=day, is_mixed_gender=(bed.id, day) in mixed_marks)

            # その日にかかっている予約を、割り当てられた段ごとに1本の帯にする。
            # 段の高さはベッドの段数（lane_count）でそろえて、どの段も
            # フル高さで描く。
            for reservation in here:
                if not reservation.covers(day):
                    continue
                lane = lanes.get(reservation.id or -1, 0)
                bar = Bar(
                    day=day,
                    lane=lane,
                    lane_count=lane_count,
                    reservations=[reservation],
                )
                _classify(bar)
                cell.bars.append(bar)

            cell.bars.sort(key=lambda b: b.lane)

            if cell.is_conflict:
                conflict_days.setdefault(bed.id, []).append(day)

            cells.append(cell)

        rows.append(Row(bed=bed, cells=cells, lane_count=lane_count))

    conflicts = [
        ConflictEntry(reservation=r, day=_jump_day(r, conflict_days, start))
        for r in sorted(
            (r for r in reservations if r.id in conflicted_ids),
            key=lambda r: (r.bed_id or "", r.check_in),
        )
    ]

    return Grid(
        year=year,
        month=month,
        days=days,
        rows=rows,
        conflicts=conflicts,
        mixed_gender=mixed_pairs,
    )
