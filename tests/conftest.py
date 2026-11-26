"""テスト共通の準備。

本番の kaigo.db には一切触らない。テストごとにメモリ上へ空のDBを作り、
画面・APIからの接続もそちらへ向ける。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  テーブル定義を登録するため
from app.db import get_session
from main import app


@pytest.fixture
def engine():
    # StaticPool にしておかないと、接続ごとに別の空DBができてしまう
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(engine):
    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    # with を使わないので起動処理（本番DBの作成）は走らない
    yield TestClient(app)
    app.dependency_overrides.clear()
