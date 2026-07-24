"""予約データと利用者マスタのモデル。

予約の項目は reservation_spec.md「③ 裏側で持っておくデータの形」、
利用者マスタは user_master_spec.md に対応する。

このファイルだけ `from __future__ import annotations` を使っていない。
有効にすると型注釈がすべて文字列になり、SQLAlchemy がリレーションの
相手のクラスを解決できずに起動時エラーになるため。
"""

import enum
from datetime import date

from sqlmodel import Field, Relationship, SQLModel


class Gender(str, enum.Enum):
    MALE = "男性"
    FEMALE = "女性"


class CareManager(SQLModel, table=True):
    """担当ケアマネジャーの台帳。

    利用者マスタと同じ考え方で、一度登録したら使い回す
    （inquiry_spec.md 2）。問い合わせを記録するとき、氏名を選ぶだけで
    事業所名と連絡先が付いてくるようにするためのもの。
    """

    id: int | None = Field(default=None, primary_key=True)

    name: str = Field(index=True)
    office: str | None = Field(default=None, index=True)
    phone: str | None = Field(default=None)
    fax: str | None = Field(default=None)
    email: str | None = Field(default=None)
    notes: str | None = Field(default=None)

    users: list["UserMaster"] = Relationship(back_populates="care_manager")
    inquiries: list["Inquiry"] = Relationship(back_populates="care_manager")


class UserMaster(SQLModel, table=True):
    """利用者ひとりぶんの台帳。

    一度登録したら使い回す、あまり変わらない情報を持つ。日々変わる情報
    （いつ来て、どの部屋か）は予約データ側にある。

    予約を作るときはここから利用者を選ぶ。毎回名前を手入力すると
    「田中太郎」「田中　太郎」のような表記ゆれが起き、当日台帳や入浴表と
    紐付かなくなるため（user_master_spec.md）。
    """

    id: int | None = Field(default=None, primary_key=True)

    name: str = Field(index=True)

    # ふりがな。一覧やプルダウンの並び順に使う。
    #
    # 漢字のままだと文字コード順に並んでしまい、人間には意味のない順序になる
    # （「中村」より「伊藤」が後ろに来るなど）。名簿として使うには読みが要る。
    #
    # 表記ゆれで並びが崩れないよう、保存時にひらがなへ揃えている。
    # 既存データには入っていないので、当面は空を許す。
    kana: str | None = Field(default=None, index=True)

    gender: Gender

    # 当日台帳に出す情報。どれも任意。
    condition: str | None = Field(default=None)  # 疾患
    notes: str | None = Field(default=None)  # 注意事項（例：転倒リスク高い）
    training: str | None = Field(default=None)  # できる訓練（例：エアロバイク）

    # 入浴種別。選択肢は config.toml の bathing.types で施設ごとに変えられる。
    bathing_type: str | None = Field(default=None)

    # 部屋が固定の利用者だけ設定する。多くは未設定のまま。
    # 実際にどの部屋に入るかは予約データ側が持つ。ここは予約を作るときの
    # 初期値として使うだけ。
    fixed_bed_id: str | None = Field(default=None)

    # 担当ケアマネジャー。⑤のCMマスタを参照する。
    #
    # ③の時点では氏名・事業所名・連絡先を自由入力で持っていたが、
    # 同じCMの情報が利用者ごとに散らばると、名前の書き方がばらついて
    # 「同じ人かどうか」が判定できなくなる。利用者名と同じ理由でマスタ化した。
    care_manager_id: int | None = Field(
        default=None, foreign_key="caremanager.id", index=True
    )
    care_manager: "CareManager" = Relationship(back_populates="users")

    reservations: list["Reservation"] = Relationship(back_populates="user")


class Reservation(SQLModel, table=True):
    """予約1件。

    ショートステイは部屋が固定でない利用者が多いため、bed_id は空でもよい。
    空の間は「部屋未定リスト」に表示され、部屋が決まった時点で埋める。
    """

    id: int | None = Field(default=None, primary_key=True)

    # 誰の予約か。名前と性別は利用者マスタ側が持つので、ここでは持たない。
    # 名前を予約にも持たせると、マスタで直しても予約側が古いままになる。
    user_master_id: int = Field(foreign_key="usermaster.id", index=True)
    user: UserMaster = Relationship(back_populates="reservations")

    # 部屋（ベッド）番号。"A1-1" のような config.toml 由来の文字列。
    # 未定のときは None。
    bed_id: str | None = Field(default=None, index=True)

    check_in: date = Field(index=True)
    check_out: date = Field(index=True)

    # 仮予約なら True。グリッド上では点線枠で表示する。
    is_tentative: bool = Field(default=False)

    # 入浴日を人が調整したかどうか。
    #
    # False の間は、入浴日は保存せず毎回ルールから計算する。予約の日程を
    # 動かせば入浴日も自動で追従するので、そのほうが手間がない。
    # 一度でも人が動かしたら True にし、以降は BathingDay の内容をそのまま使う。
    # そうしないと、せっかく調整した入浴日が次の表示で消えてしまう。
    bathing_is_manual: bool = Field(default=False)

    bathing_days: list["BathingDay"] = Relationship(
        back_populates="reservation",
        # 予約を消したら入浴日も一緒に消す。残しても行き場がない。
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    @property
    def guest_name(self) -> str:
        """表示用の名前。マスタから引く。"""
        return self.user.name

    @property
    def gender(self) -> Gender:
        """性別。グリッドの色分けに使う。マスタから引く。"""
        return self.user.gender

    @property
    def nights(self) -> int:
        """泊数。退所日当日は宿泊しないので、単純な日数の差。

        日帰り（入所日 = 退所日）は 0 になる。
        """
        return (self.check_out - self.check_in).days

    def covers(self, day: date) -> bool:
        """その日がこの予約の占有期間に入っているか。

        退所日も「その部屋に紐づいている日」として含める。退所日の午前中は
        まだ施設内にいるため、グリッド上は退所日のセルも塗る必要がある
        （泊数の計算とは別の話なので、nights とは境界が違う）。
        """
        return self.check_in <= day <= self.check_out

    def stays_night(self, day: date) -> bool:
        """その日の夜、実際にそのベッドで寝ているか。

        covers() と違って退所日を含めない。「同じ部屋に男女が泊まっている」
        のような、寝ている人だけを見たい判定に使う。
        日帰り（0泊）はどの日も False になる。
        """
        return self.check_in <= day < self.check_out


class BathingDay(SQLModel, table=True):
    """人が調整した入浴日。

    自動のままの予約はここに行が入らない（毎回ルールから計算する）。
    行があるのは、現場が手で動かした予約だけ。

    「自動で候補を出し、最終調整は人がやる」という運用なので、
    人の判断だけを残して、機械で出せるものは持たない形にしている。
    """

    id: int | None = Field(default=None, primary_key=True)

    reservation_id: int = Field(foreign_key="reservation.id", index=True)
    reservation: Reservation = Relationship(back_populates="bathing_days")

    day: date = Field(index=True)


class Inquiry(SQLModel, table=True):
    """問い合わせ1件。

    予約になる前の段階の記録。空き確認や新規相談の電話・FAXを受けたときに
    残しておき、話がまとまったら予約データに変換する（inquiry_spec.md 4）。
    """

    id: int | None = Field(default=None, primary_key=True)

    inquiry_date: date = Field(index=True)

    care_manager_id: int | None = Field(
        default=None, foreign_key="caremanager.id", index=True
    )
    care_manager: CareManager | None = Relationship(back_populates="inquiries")

    # 対象の利用者。マスタから選ぶのが基本だが、まだ登録していない
    # 新規の方の相談も受けるので、名前だけの手入力も許す。
    # その場合 user_master_id は空で、guest_name に名前が入る。
    user_master_id: int | None = Field(
        default=None, foreign_key="usermaster.id", index=True
    )
    user: UserMaster | None = Relationship()
    guest_name: str | None = Field(default=None, index=True)

    # 希望日程。まだ決まっていない段階の問い合わせもあるので空を許す。
    desired_check_in: date | None = Field(default=None, index=True)
    desired_check_out: date | None = Field(default=None)

    # 選択肢は config.toml の [inquiry] で施設ごとに変えられる
    kind: str = Field(index=True)
    status: str = Field(index=True)

    memo: str | None = Field(default=None)

    # 予約に変換したあと、経緯をたどれるようにしておく（inquiry_spec.md 補足）
    reservation_id: int | None = Field(
        default=None, foreign_key="reservation.id", index=True
    )
    reservation: Reservation | None = Relationship()

    @property
    def display_name(self) -> str:
        """対象の利用者名。マスタにいればそちらを優先する。

        マスタ側で名前を直したとき、問い合わせの表示も追従してほしいため。
        """
        if self.user is not None:
            return self.user.name
        return self.guest_name or "（利用者未定）"

    @property
    def is_registered_user(self) -> bool:
        """利用者マスタに登録済みの方か。

        予約に変換するとき、本予約と仮予約のどちらを初期値にするかの
        判断に使う（既存の方は決まることがほとんど、新規はケースバイケース）。
        """
        return self.user_master_id is not None

    @property
    def is_converted(self) -> bool:
        return self.reservation_id is not None
