"""config.toml を読み込んで、アプリから使いやすい形にする。

施設ごとの違いはすべて config.toml 側に置き、このモジュールは
「読み込んで組み立てる」だけに徹する。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass(frozen=True)
class Bed:
    """グリッドの1行にあたる、ベッド1つ分。

    準個室（二人部屋）は1部屋にベッドが2つあるので、A1-1 と A1-2 は
    別々の Bed になる。誰がどちらのベッドかを表現するため、グリッドの
    行は部屋単位ではなくベッド単位にしている。
    """

    id: str  # "A1-1" / "A6" … 予約データが持つ部屋番号はこの文字列
    wing: str  # "A" / "B" / "C"
    room_no: str  # 棟の中での部屋番号 "1" / "6"
    bed_no: str | None  # 準個室なら "1" / "2"、個室なら None
    is_shared: bool  # 準個室（二人部屋）なら True

    @property
    def room_id(self) -> str:
        """同じ部屋のベッドで共通になるID。準個室の相方を探すのに使う。"""
        return f"{self.wing}{self.room_no}"


@dataclass(frozen=True)
class GridColors:
    stay: str
    checkin: str
    checkout: str
    male: str
    female: str
    conflict: str
    mixed_gender: str
    daytrip: str


@dataclass(frozen=True)
class Bathing:
    """入浴の運用。施設ごとに回数の決め方が違うので設定で吸収する。"""

    types: tuple[str, ...]
    interval_nights: int
    include_daytrip: bool


@dataclass(frozen=True)
class Reports:
    """帳票の体裁。"""

    ledger_blocks: int


@dataclass(frozen=True)
class Inquiry:
    """問い合わせの選択肢。施設ごとに区分の呼び方が違うので設定で吸収する。"""

    kinds: tuple[str, ...]
    statuses: tuple[str, ...]

    # 予約を削除したとき、元の問い合わせをこの状態にする。
    # 現場では「予約を消す」＝「キャンセル」なので、未対応には戻さない。
    cancelled_status: str = "キャンセル"

    @property
    def default_status(self) -> str:
        """新しい問い合わせの初期状態。並べた先頭を使う。"""
        return self.statuses[0] if self.statuses else "未対応"


@dataclass(frozen=True)
class Aggregation:
    """集計の取り扱い。施設によって数え方が違う部分を設定で吸収する。"""

    include_tentative: bool


@dataclass(frozen=True)
class Warnings:
    """何を警告として出すか。施設ごとに運用が違うので設定で切り替える。"""

    mixed_gender_in_shared_room: bool


@dataclass(frozen=True)
class Config:
    facility_name: str
    capacity: int
    beds: tuple[Bed, ...]

    colors: GridColors
    warnings: Warnings
    aggregation: Aggregation
    bathing: Bathing
    reports: Reports
    inquiry: Inquiry

    @property
    def bathing_types(self) -> tuple[str, ...]:
        """入浴種別の選択肢。よく使うので短く書けるようにしておく。"""
        return self.bathing.types

    def beds_in_room(self, room_id: str) -> list[Bed]:
        """同じ部屋にあるベッドを返す。準個室なら2つ、個室なら1つ。"""
        return [bed for bed in self.beds if bed.room_id == room_id]

    def bed_by_id(self, bed_id: str) -> Bed | None:
        for bed in self.beds:
            if bed.id == bed_id:
                return bed
        return None


def _parse_bed(wing: str, token: str) -> Bed:
    """config.toml の "1-1" や "6" を Bed に変換する。

    ハイフンがあれば準個室のベッド、なければ個室。
    """
    if "-" in token:
        room_no, bed_no = token.split("-", 1)
        return Bed(
            id=f"{wing}{token}",
            wing=wing,
            room_no=room_no,
            bed_no=bed_no,
            is_shared=True,
        )
    return Bed(
        id=f"{wing}{token}",
        wing=wing,
        room_no=token,
        bed_no=None,
        is_shared=False,
    )


def _statuses_with_cancelled(inquiry_raw: dict) -> tuple[str, ...]:
    """対応状況の選択肢。キャンセル用の状態が並んでいなければ末尾に足す。

    予約を削除したときに問い合わせをその状態にするので、選択肢に無いと
    編集画面で選べず、検索でも絞り込めなくなるため。
    """
    statuses = list(inquiry_raw.get("statuses", ["未対応", "対応中", "対応済み", "キャンセル"]))
    cancelled = inquiry_raw.get("cancelled_status", "キャンセル")
    if cancelled not in statuses:
        statuses.append(cancelled)
    return tuple(statuses)


@lru_cache(maxsize=1)
def load_config(path: Path | None = None) -> Config:
    # utf-8-sig にしているのは、config.toml を Windows のメモ帳で編集すると
    # 先頭に BOM が付いてしまい、素の utf-8 では読めなくなるため。
    raw = tomllib.loads((path or CONFIG_PATH).read_text(encoding="utf-8-sig"))

    beds: list[Bed] = []
    for wing, tokens in raw["rooms"].items():
        for token in tokens:
            beds.append(_parse_bed(wing, token))

    duplicates = _find_duplicate_ids(beds)
    if duplicates:
        raise ValueError(
            f"config.toml の部屋番号が重複しています: {', '.join(duplicates)}"
        )

    grid = raw["grid"]
    # [warnings] を書いていない設定ファイルでも動くよう、既定は「警告しない」。
    # 警告は施設が意図して有効にするもの、という扱いにしている。
    warnings_raw = raw.get("warnings", {})

    # 仮予約は成立しないことが多いため、既定では集計に入れない。
    aggregation_raw = raw.get("aggregation", {})
    bathing_raw = raw.get("bathing", {})
    inquiry_raw = raw.get("inquiry", {})

    return Config(
        facility_name=raw["facility"]["name"],
        capacity=raw["facility"]["capacity"],
        beds=tuple(beds),
        bathing=Bathing(
            types=tuple(bathing_raw.get("types", ["一般", "リフト"])),
            interval_nights=bathing_raw.get("interval_nights", 3),
            include_daytrip=bathing_raw.get("include_daytrip", True),
        ),
        reports=Reports(
            ledger_blocks=raw.get("reports", {}).get("ledger_blocks", 2),
        ),
        inquiry=Inquiry(
            kinds=tuple(inquiry_raw.get("kinds", ["空き確認", "新規相談", "変更", "キャンセル", "その他"])),
            statuses=_statuses_with_cancelled(inquiry_raw),
            cancelled_status=inquiry_raw.get("cancelled_status", "キャンセル"),
        ),
        aggregation=Aggregation(
            include_tentative=aggregation_raw.get("include_tentative", False),
        ),
        warnings=Warnings(
            mixed_gender_in_shared_room=warnings_raw.get(
                "mixed_gender_in_shared_room", False
            ),
        ),
        colors=GridColors(
            stay=grid.get("color_stay", "#0072B2"),
            checkin=grid["color_checkin"],
            checkout=grid["color_checkout"],
            male=grid["color_male"],
            female=grid["color_female"],
            conflict=grid["color_conflict"],
            mixed_gender=grid.get("color_mixed_gender", "#7b1fa2"),
            daytrip=grid.get("color_daytrip", "#6d4c41"),
        ),
    )


def _find_duplicate_ids(beds: list[Bed]) -> list[str]:
    """同じ部屋番号が2回書かれていたら、その番号を返す。

    今回の部屋リストは手で書き写したもので、実際に "2-1" が2回
    書かれる打ち間違いが起きた。黙って1行にまとめると30床のはずが
    29行になって気づけないので、起動時に止める。
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    for bed in beds:
        if bed.id in seen and bed.id not in duplicates:
            duplicates.append(bed.id)
        seen.add(bed.id)
    return duplicates
