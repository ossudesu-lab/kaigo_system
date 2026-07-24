@echo off
rem 予約システムの起動用バッチ。ダブルクリックで開発サーバーを立ち上げる。
rem 止めるときはこの黒い画面で Ctrl+C を押すか、ウィンドウを閉じる。

cd /d "%~dp0"

echo ============================================
echo   介護予約システムを起動します
echo   起動後、ブラウザで下記を開いてください:
echo.
echo   予約表  http://127.0.0.1:8000/
echo.
echo   止めるには この画面で Ctrl+C を押します
echo ============================================
echo.

rem 使う Python（プロジェクト内の仮想環境）が無ければ、その場で知らせて止める。
if not exist ".venv\Scripts\python.exe" (
  echo [エラー] .venv\Scripts\python.exe が見つかりません。
  echo 仮想環境が壊れている可能性があります。セットアップをやり直してください。
  echo.
  pause
  exit /b 1
)

rem サーバーが立ち上がるのを数秒待ってから、既定のブラウザで予約表を開く。
rem （PowerShell を裏で走らせるので、下の uvicorn の起動を妨げない）
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:8000/'"

".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000

rem サーバーが終了（Ctrl+Cなど）したら、閉じる前に一時停止して状況を見せる
echo.
echo サーバーが停止しました。何かキーを押すと閉じます。
pause
