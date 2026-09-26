"""
RAS（Renju Automatic Search）の表示文言（日本語／英語）。

使い方：
    from i18n import tr, set_language
    set_language("en")
    tr("kind_send")                 # → "Send"
    tr("msg_undo_wait", cur=44, target=42, n=2)
"""

LANG = "ja"

STRINGS = {
    # ---- ログの種別（見出し） ----
    "kind_transition": ("状態遷移", "State"),
    "kind_four": ("四を検知", "Four detected"),
    "kind_command": ("コマンド実行", "Command"),
    "kind_warning": ("警告", "Warning"),
    "kind_position": ("局面変更", "Position"),
    "kind_stable": ("安定確認", "Stability"),
    "kind_hold": ("保留", "Hold"),
    "kind_timeout": ("探索時間終了", "Time is up"),
    "kind_all_lost": ("全候補が負け", "All moves lose"),
    "kind_best_move": ("最善手を着手", "Play best move"),
    "kind_win_found": ("勝ち筋を検出", "Win found"),
    "kind_forced": ("最善手以外が負け", "Only one move survives"),
    "kind_plan": ("送信予定", "Planned"),
    "kind_send": ("送信", "Send"),
    "kind_flush": ("ログ書き出し", "Log flush"),
    "kind_resend": ("再送", "Resend"),
    "kind_undo_wait": ("操作待ち", "Waiting"),
    "kind_confirmed": ("完了確認", "Confirmed"),
    "kind_pause": ("異常一時停止", "Stopped"),
    "kind_end": ("終了", "End"),
    "kind_start": ("開始", "Start"),
    "kind_wait": ("待機", "Idle"),
    "kind_status": ("状況", "Status"),
    "kind_note": ("注意", "Note"),
    "kind_autostart": ("探索開始", "Search start"),

    # ---- 探索側の呼び名 ----
    "side_defend": ("defend探索側", "defend side"),
    "side_nbest": ("nbest探索側", "nbest side"),
    "side_search": ("探索", "search"),

    # ---- 操作の題名 ----
    "title_four": ("四への応手", "Answer to four"),
    "title_timeout_nbest": ("時間切れ→着手して defend探索", "Time up → play engine move, defend search"),
    "title_timeout_move": ("時間切れ→最善手を着手", "Time up → play best move"),
    "title_win_found": ("勝ち筋検出→戻る", "Win found → undo"),
    "title_forced": ("最善手以外が負け→着手", "Only one move survives → play it"),
    "title_all_lost": ("全候補が負け→戻る", "All moves lose → undo"),
    "title_autostart": ("探索開始", "Start search"),
    "cmd_undo_until": ("undo one（局面が {target} 手になるまで繰り返す）", "undo one (repeat until {target} moves)"),

    # ---- メッセージ ----
    "msg_transition": ("→ {state}（{reason}）", "→ {state} ({reason})"),
    "msg_four_chain": ("四への応手 {moves} は実質1通りのため探索せず着手します", "Forced answer(s) to four: {moves}. Playing without search"),
    "msg_four_now": ("{side}：四への応手 {move} は実質1通りのため探索を打ち切って着手します", "{side}: forced answer to four {move}. Stopping search and playing it"),
    "msg_thinking_start": ("thinking start はエンジンが着手する対局用コマンドです（自動操作では使用禁止）", "'thinking start' makes the engine play a move (not used by RAS)"),
    "msg_manual": ("手動操作を検知したため自動探索を停止: {cmd}", "Manual command detected, automatic search turned off: {cmd}"),
    "msg_position": ("{before}手 → {after}手: {moves}", "{before} → {after} moves: {moves}"),
    "msg_stable": ("{n}/{req} 周回（{summary}）", "{n}/{req} rounds ({summary})"),
    "msg_hold": ("周回条件は満たしたが探索開始から {sec} 秒未満のため保留", "Rounds satisfied, holding until {sec} s since search start"),
    "msg_timeout": ("{side}：{limit}秒経過。{summary}", "{side}: {limit} s elapsed. {summary}"),
    "msg_timeout_win": ("{side}の探索時間終了時に勝ち筋（+M）の候補手が残っています（想定外）", "{side}: a winning move (+M) remains at time up (unexpected)"),
    "msg_all_lost_timeout": ("{side}：探索時間終了時点で全候補手が -M → 戻して defend探索。{summary}", "{side}: all moves are -M at time up → undo and defend search. {summary}"),
    "msg_timeout_unknown": ("探索時間終了時に候補手の評価を判定できません（{summary}）", "Cannot classify candidates at time up ({summary})"),
    "msg_best_move": ("{side}：最大評価値 {move}（{eval}）を着手", "{side}: playing best move {move} ({eval})"),
    "msg_win_found": ("{side}：{wins} → 直前の手を戻して defend探索", "{side}: {wins} → undo last move and defend search"),
    "msg_win_unexpected": ("{side}で勝ち筋（+M）の候補手を検出: {moves}（想定外）", "{side}: winning move (+M) detected: {moves} (unexpected)"),
    "msg_forced": ("{side}：{move}（{eval}）以外が全て -M → 着手して次の手から探索", "{side}: every move except {move} ({eval}) is -M → play it and continue"),
    "msg_all_lost": ("{side}：全候補手が -M → 戻して defend探索。{summary}", "{side}: all moves are -M → undo and defend search. {summary}"),
    "msg_putpos_unknown": ("{title}：現在の局面が不明（0手）のため putpos を送りません。盤面を壊す恐れがあります", "{title}: current position unknown (0 moves), putpos not sent to protect the board"),
    "msg_putpos_short": ("{title}：putpos の手順（{n}手）が現在の局面（{cur}手）より長くないため送りません", "{title}: putpos ({n} moves) is not longer than current position ({cur}), not sent"),
    "msg_send_fail": ("送信失敗（{cmd}）: {err}", "Send failed ({cmd}): {err}"),
    "msg_send_undo": ("undo one（現在 {cur} 手 → 目標 {target} 手）", "undo one (now {cur} → target {target} moves)"),
    "msg_flush": ("確認待ちが続くためログの強制書き出しを送信（{n}回目）", "Forcing log flush while waiting for confirmation ({n})"),
    "msg_flush_fail": ("ログ強制書き出しの送信に失敗: {err}", "Log flush failed: {err}"),
    "msg_resend": ("{cmd}（受付確認が6秒以内に取れなかったため）", "{cmd} (no acknowledgement within 6 s)"),
    "msg_resend_fail": ("再送失敗（{cmd}）: {err}", "Resend failed ({cmd}): {err}"),
    "msg_op_timeout": ("操作の完了確認が {sec} 秒以内に取れませんでした（期待: {expect}）", "Operation not confirmed within {sec} s (expected: {expect})"),
    "msg_undo_over": ("戻しすぎ：局面が {cur} 手（目標 {target} 手）", "Undo overshoot: {cur} moves (target {target})"),
    "msg_undo_wait": ("現在 {cur} 手、目標 {target} 手。undo one をあと {n} 回", "Now {cur} moves, target {target}. {n} more undo"),
    "msg_replay_end": ("リプレイ完了", "Replay finished"),
    "msg_start": ("監視開始: {path}", "Monitoring: {path}"),
    "msg_resume": ("すでに探索中のため途中から開始（{n}手: {moves}）", "Search already running, resuming ({n} moves: {moves})"),
    "msg_wait": ("Rapfi で searchdefend（または nbest）を実行すると監視に入ります", "Run searchdefend (or nbest) in Rapfi to start monitoring"),
    "msg_autostart": ("探索が止まっているため searchdefend を送って開始します（{n}手）", "Search is idle; sending searchdefend to start ({n} moves)"),
    "msg_status": ("残り {remain}秒。{n}手。{summary}", "{remain} s left. {n} moves. {summary}"),
    "msg_status_op": ("操作待ち：次に期待するログ変化 = {expect}", "Waiting for: {expect}"),
    "msg_truncated": ("ログが切り詰められたため先頭から読み直します", "Log was truncated, reading from the beginning"),
    "msg_ctrlc": ("Ctrl+C により終了", "Stopped by Ctrl+C"),
    "msg_op_done": ("操作完了", "operation finished"),
    "msg_detect_defend": ("{side}（searchdefend）を検知", "{side} (searchdefend) detected"),
    "msg_detect_nbest": ("{side}（nbest）を検知", "{side} (nbest) detected"),
    "summary": ("候補{n}件（整数{ints} / -M{losses} / +M{wins} / 不明{unknown}）", "{n} candidates (int {ints} / -M {losses} / +M {wins} / unknown {unknown})"),

    # ---- GUI ----
    "app_title": ("RAS - Renju Automatic Search", "RAS - Renju Automatic Search"),
    "gui_auto_mode": ("自動探索モード", "Automatic search"),
    "gui_stopped": ("停止中", "Stopped"),
    "gui_on": ("自動探索 ON", "Automatic search ON"),
    "gui_settings": (" 探索設定 ", " Search settings "),
    "gui_mode": ("探索モード", "Search mode"),
    "gui_mode_nbest": ("nbest探索あり", "With nbest"),
    "gui_mode_defend": ("nbest探索なし", "Defend only"),
    "gui_language": ("言語", "Language"),
    "gui_save": ("設定を保存", "Save settings"),
    "gui_calibrate": ("入力欄を校正（予備）", "Calibrate input box (fallback)"),
    "gui_truncate": ("ログを切り詰め", "Truncate log"),
    "gui_state": ("状態", "State"),
    "gui_remain": ("残り時間", "Time left"),
    "gui_moves": ("局面", "Position"),
    "gui_cands": ("候補手", "Candidates"),
    "gui_last": ("最後の操作", "Last operation"),
    "gui_state_wait": ("待機（Rapfi で searchdefend / nbest を実行してください）", "Idle (run searchdefend / nbest in Rapfi)"),
    "gui_state_op": ("操作中", "Operating"),
    "gui_state_paused": ("停止", "Stopped"),
    "gui_saved": ("設定を保存しました: {path}", "Settings saved: {path}"),
    "gui_off": ("自動探索モード オフ（{reason}）", "Automatic search OFF ({reason})"),
    "gui_manual_off": ("手動でオフ", "turned off manually"),
    "gui_thread_error": ("監視スレッドでエラー: {err}", "Monitor thread error: {err}"),
    "gui_thread_end": ("監視を終了しました", "Monitoring ended"),
    "gui_err_setting": ("設定エラー", "Settings error"),
    "gui_err_value": ("「{label}」に正の数値を入力してください（入力値: {raw}）", "Enter a positive number for \"{label}\" (got: {raw})"),
    "gui_err_nolog": ("ログなし", "No log"),
    "gui_err_nolog_msg": ("{path} が見つかりません。\nsettings.txt の「record debug log」を 1 にして Yixin を起動してください。", "{path} not found.\nSet 'record debug log' to 1 in settings.txt and start Yixin."),
    "gui_err_sender": ("送信部エラー", "Sender error"),
    "gui_err_sender_msg": ("{err}\n「入力欄を校正」を先に行ってください。", "{err}\nRun 'Calibrate input box' first."),
    "gui_err_noyixin": ("Yixin なし", "Yixin not found"),
    "gui_err_noyixin_msg": ("Yixin のウィンドウが見つかりません。起動してから再度オンにしてください。", "Yixin window not found. Start Yixin and turn on again."),
    "gui_log_truncated": ("debuglog.txt が {mb:.0f} MB あったため切り詰めました", "debuglog.txt was {mb:.0f} MB, truncated"),
    "gui_log_truncate_fail": ("ログ切り詰めに失敗: {err}", "Log truncation failed: {err}"),
    "gui_mode_locked": ("自動探索モードをオフにしてから切り替えてください。", "Turn off automatic search before switching."),
    "gui_calib_locked": ("自動探索モードをオフにしてから校正してください。", "Turn off automatic search before calibrating."),
    "gui_calib_title": ("校正", "Calibration"),
    "gui_calib_msg": ("通常は入力欄を自動検出するため校正は不要です。自動検出できない場合のみ使ってください。\nOK を押してから 5 秒以内に、マウスカーソルを Rapfi のコマンド入力欄の上に置いてください。",
                      "The input box is detected automatically, so calibration is normally unnecessary; use it only if detection fails.\nAfter pressing OK, move the mouse over Rapfi's command input box within 5 seconds."),
    "gui_calib_count": ("校正: {i}...", "Calibration: {i}..."),
    "gui_calib_outside": ("マウスが Yixin のウィンドウ外にあります。やり直してください。", "Mouse is outside the Yixin window. Try again."),
    "gui_calib_saved": ("校正を保存しました: 相対位置=({x}, {y}) ウィンドウ={w}x{h}", "Calibration saved: offset=({x}, {y}) window={w}x{h}"),
    "gui_calib_fail": ("校正失敗: {err}", "Calibration failed: {err}"),
    "gui_trunc_locked": ("自動探索モードをオフにしてから行ってください。", "Turn off automatic search first."),
    "gui_trunc_done": ("debuglog.txt を切り詰めました（{mb:.1f} MB → 0）", "debuglog.txt truncated ({mb:.1f} MB → 0)"),
    "gui_trunc_fail": ("切り詰め失敗", "Truncation failed"),
    "gui_lang_changed": ("言語を切り替えました。表示を更新するにはアプリを再起動してください。", "Language changed. Restart the app to refresh the display."),

    # ---- 設定項目 ----
    "f_a_limit": ("defend探索側 探索時間（秒）", "Defend side search time (s)"),
    "d_a_limit": ("searchdefend の制限時間。経過したら最大評価値を着手して nbest探索側へ", "Time limit for searchdefend. When it expires, the best move is played and the nbest side starts"),
    "f_b_limit": ("nbest探索側 探索時間（秒）", "nbest side search time (s)"),
    "d_b_limit": ("nbest の制限時間。経過したら停止し、エンジンの手を採用して defend探索側へ", "Time limit for nbest. When it expires, the engine's move is kept and the defend side starts"),
    "f_defend_mode": ("探索時間（秒）", "Search time (s)"),
    "d_defend_mode": ("searchdefend の制限時間。経過したら最大評価値を着手し、相手側も searchdefend", "Time limit for searchdefend. When it expires, the best move is played and the other side also runs searchdefend"),
    "f_stable_rounds": ("安定確認 周回数", "Stability rounds"),
    "d_stable_rounds": ("「全候補が負け」「最善手以外が負け」の成立に必要な連続周回数", "Consecutive rounds required before 'all moves lose' / 'only one move survives' triggers"),
    "f_stable_seconds": ("安定確認 最低秒数", "Stability minimum (s)"),
    "d_stable_seconds": ("同上の成立に必要な探索開始からの最低経過秒数（2〜3秒で十分）", "Minimum seconds since search start for the above (2–3 s is enough)"),
    "f_op_timeout": ("操作タイムアウト（秒）", "Operation timeout (s)"),
    "d_op_timeout": ("コマンド送信後、完了確認をこの秒数待って取れなければ停止", "Stop if a command is not confirmed within this many seconds"),
    "f_nbest": ("nbest 候補手数", "nbest candidates"),
    "d_nbest": ("nbest探索側で送る nbest の候補数", "Number of candidates for the nbest command"),
    "f_ripple_lead": ("送信予告（秒）", "Send warning lead (s)"),
    "d_ripple_lead": ("コマンド送信のこの秒数前に波紋で知らせ、その間は送信を待つ", "Ripple warning this many seconds before a command is sent; sending waits until then"),
    "f_idle_wait": ("操作の静止待ち（秒）", "Input idle wait (s)"),
    "d_idle_wait": ("マウス・キーボードがこの秒数止まってから送信する（最大10秒待つ）", "Send only after mouse/keyboard have been idle this long (waits up to 10 s)"),
    "gui_ripple": ("波紋通知", "Ripple warning"),
    "gui_ripple_color": ("波紋の色", "Ripple color"),
    "gui_ripple_test": ("試す", "Test"),
    "d_ripple": ("送信前にマウスポインタから波紋を出して知らせる。色の四角をクリックで変更", "Show ripples from the mouse pointer before sending. Click the swatch to change the color"),
    "gui_ripple_fail": ("波紋表示に失敗: {err}", "Ripple overlay failed: {err}"),
    "gui_detect_ok": ("コマンド入力欄を自動検出しました（ウィンドウ相対 {box}）。ウィンドウを動かしても追従します", "Command input box detected automatically (window-relative {box}); it follows the window"),
    "gui_detect_fallback": ("入力欄を自動検出できなかったため、校正値から位置を推定します", "Could not detect the input box; falling back to the calibrated position"),
    "gui_detect_none": ("入力欄を自動検出できず、校正値もありません。Yixin を前面にして「入力欄を校正」を実行してください。", "Could not detect the input box and there is no calibration. Bring Yixin to the front and run 'Calibrate input box'."),
    "gui_detect_fail": ("入力欄の自動検出でエラー: {err}", "Input box detection failed: {err}"),
}


def set_language(lang):
    global LANG
    LANG = "en" if lang == "en" else "ja"


def tr(key, **kw):
    pair = STRINGS.get(key)
    if pair is None:
        return key
    text = pair[1] if LANG == "en" else pair[0]
    if kw:
        try:
            return text.format(**kw)
        except (KeyError, IndexError):
            return text
    return text
