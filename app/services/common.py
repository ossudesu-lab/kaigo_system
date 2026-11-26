"""サービス層で共通に使う小物。"""

from __future__ import annotations

from typing import Any


class _Unset:
    """「この項目は送られてこなかった（変更しない）」を表す印。

    更新処理では「変更しない」と「空にする」を区別する必要がある。
    以前は両方を None で表していたため、編集画面で欄を空にして保存しても
    「変更しない」と受け取られ、一度入れた注意事項などが消せなかった。

    None は「空にする」、UNSET は「触らない」と使い分ける。
    """

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Any = _Unset()
