# トラブルシューティング

Windows環境（特に日本語版）で起こりやすい問題と、その対処法をまとめています。

---

## `start.bat` をダブルクリックしても起動しない

**何が起きているか**
バッチファイルの文字コードが原因です。日本語版Windowsの `cmd.exe` は、
バッチファイルを Shift-JIS（CP932）として読み込みます。
ファイルがUTF-8で保存されていると、日本語コメントの部分で読み取り位置がずれ、
コマンドが正しく認識されないまま起動に失敗します。

**対処**
`.bat` ファイルは **CP932（Shift-JIS）＋ CRLF改行** で保存してください。
このリポジトリでは `.gitattributes` に次の設定を入れ、
Gitが改行コードを勝手にLFへ変換しないようにしています。

\`\`\`
*.bat text eol=crlf
\`\`\`

---

## コードを直したのに、画面に変更が反映されない

考えられる原因は2つあります。上から順に確認してください。

### 原因1：古いサーバープロセスが残っている

開発中に `--reload` 付きでサーバーを起動していた場合、
コンソール画面を「×」ボタンで閉じるとプロセスが完全に終了せず、
バックグラウンドに残ることがあります（Windows特有の挙動です）。
この残ったプロセスがポート8000を占有していると、
新しく起動したサーバーの変更が画面に出てきません。

**対処**：PowerShellで残ったプロセスを一掃してから、起動し直します。

\`\`\`powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { \$_.CommandLine -match 'uvicorn main:app' -or \$_.CommandLine -match 'multiprocessing' } |
  ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }
\`\`\`

実行後、次のコマンドで**何も表示されなければ**ポートが空いた状態です。

\`\`\`powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
\`\`\`

### 原因2：ブラウザがファイルをキャッシュしている

サーバーを正しく再起動しても、ブラウザがCSSやJavaScriptを
古いまま覚えている（キャッシュ）ことがあります。
`Ctrl + F5`（強制リロード）でも直らない場合は、
ブラウザを一度完全に閉じてから開き直してください。

---

## 補足：`start.bat` を何度も起動してしまったとき

ポート8000を今どのプロセスが使っているかは、次のコマンドで確認できます。

\`\`\`powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
\`\`\`

複数表示される場合は、上の「原因1」の一掃コマンドを実行してから、
あらためて `start.bat` を1回だけ起動してください。
