RAS（Renju Automatic Search）説明書
==================================================

■ 同梱ファイル
  RAS.exe              本体（Python 不要）
  monitor_config.json  設定ファイル（GUI から編集できます）
  README.txt           この説明書

■ 動作環境
  Windows 10 / 11、YixinBoard（Rapfi エンジン同梱版）

■ フォルダ構成（重要）
  RAS は「自分のフォルダの1つ上」にある debuglog.txt を読みます。
  必ず YixinBoard のフォルダのすぐ下に RAS フォルダを置いてください。

    YixinBoard\             ← Yixin の exe や settings.txt があるフォルダ
    ├─ settings.txt
    ├─ debuglog.txt         ← 下の手順1のあと Yixin を起動すると作られる
    └─ RAS\
       ├─ RAS.exe
       ├─ monitor_config.json
       └─ README.txt

  ※ ZIP を展開すると RAS\RAS\RAS.exe のように二重になることがあります。
    RAS.exe が YixinBoard\RAS\RAS.exe の位置になるように置き直してください。

■ セットアップ
  1. YixinBoard を終了した状態で settings.txt をメモ帳で開き、
     「;record debug log」の行の値を 0 から 1 に変えて保存する
  2. 上のフォルダ構成のとおりに RAS フォルダを置く
  3. YixinBoard を起動し、次に RAS.exe を起動する
  4. 探索モードと探索時間を設定し、「設定を保存」を押す
  5. 「自動探索モード」をオンにする（探索が止まっていれば自動で開始します）
  止めるときはトグルをオフにします。Yixin を手動で操作した場合も自動でオフになります。

■ 注意
  ・Yixin のウィンドウは最小化しないでください。
  ・コマンド送信の瞬間（約0.5秒）は Yixin が前面になり、マウスカーソルが動きます。
    波紋が出ている間はキーボードを触らないでください（文字が混ざります）。
  ・debuglog.txt は探索中に増え続けます（約30MB/時間）。
    自動探索モードをオンにしたとき 100MB を超えていれば自動で切り詰めます。

■ 認識されないとき
  ・「Yixin のウィンドウが見つかりません」
      → Yixin を起動してから自動探索モードをオンにし直す
  ・オンにしても反応しない
      → RAS フォルダの1つ上に debuglog.txt があるか確認する。
        無ければセットアップ手順1の設定を確認する

■ 主な設定
  勝ち判定 評価値（win_eval_threshold）
      整数の評価値がこの値以上の候補手を +M と同様に勝ちとみなして進みます
      （安定確認あり）。0 で無効。
  その他の項目は GUI の各欄の説明を参照してください。

詳しくは https://github.com/fiss-vinbows/Renju-Automatic-Search


==================================================
RAS (Renju Automatic Search) - Quick guide
==================================================

Files: RAS.exe (no Python needed), monitor_config.json (settings), README.txt.
Requires Windows 10/11 and YixinBoard (with the Rapfi engine).

Folder layout (important): RAS reads debuglog.txt from its PARENT folder,
so put the RAS folder directly under the YixinBoard folder:

    YixinBoard\
    ├─ settings.txt
    ├─ debuglog.txt
    └─ RAS\
       ├─ RAS.exe
       ├─ monitor_config.json
       └─ README.txt

If unzipping produced RAS\RAS\RAS.exe, move it so the path is YixinBoard\RAS\RAS.exe.

Setup:
  1. With YixinBoard closed, open settings.txt and change ";record debug log" from 0 to 1
  2. Place the RAS folder as shown above
  3. Start YixinBoard, then RAS.exe
  4. Set the search mode and time, click "Save settings"
  5. Turn on "Auto search"

Notes: do not minimize Yixin; do not type while the ripple is shown.
If "Yixin window not found": start Yixin and turn Auto search on again.
If nothing happens: check that debuglog.txt exists in the parent of the RAS folder.
