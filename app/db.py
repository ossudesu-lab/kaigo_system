"""DB接続。

SQLite を1ファイルで持つ。施設に配って動かすことを想定しているので、
別途DBサーバを立てなくていい形にしている。
将来 PostgreSQL に移す場合も、書き換えるのはこのファイルだけで済む。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

DB_PATH = Path(__file__).resolve().parent.parent / "kaigo.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    # SQLite は既定だと接続を作ったスレッド以外から触れない。
    # FastAPI はリクエストを別スレッドで処理することがあるため外す。
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    # Reservation を import しておかないとテーブル定義が登録されない
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
