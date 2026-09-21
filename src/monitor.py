"""
Rapfi 自動探索アプリ 監視・操作部

debuglog.txt を追記監視して探索状況を判定し、条件成立時にコマンド列を Rapfi へ送る（--auto）。
--auto なしでは送る予定のコマンドを表示するだけで、人が入力欄に打つとその完了を検知して次へ進む。

実行例：
    python monitor.py --auto                   # 本番：monitor_config.json の設定で自動運転
    python monitor.py --auto --a-limit 60 --b-limit 30   # 短縮時間で検証（引数は設定ファイルを上書き）
    python monitor.py                          # コマンドを送らず、送る予定を表示するだけ（人が打つ）
設定項目（時間条件・戻る回数など）は monitor_config.json を参照。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

from parse_debuglog import DebugLogParser, DEFAULT_LOG, eval_label, BOARD_SIZE, app_dir, rapfi_dir
from i18n import tr, set_language

CONFIG_PATH = os.path.join(app_dir(), "monitor_config.json")


def load_monitor_config():
    """monitor_config.json を読む。無ければ既定値。_ で始まるキーは説明文なので無視する。"""
    defaults = {"a_limit_seconds": 3600, "b_limit_seconds": 1800, "stable_rounds": 3, "stable_seconds": 10,
                "op_timeout_seconds": 20, "nbest": 2, "undo_offset_branch1": -2, "undo_offset_branch3": -1,
                "undo_offset_branch4": None, "poll_seconds": 0.2, "status_interval_seconds": 30,
                "search_mode": "nbest", "defend_mode_seconds": 3600, "language": "ja", "auto_start_search": True}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if not k.startswith("_"):
                    defaults[k] = v
    set_language(defaults.get("language", "ja"))
    return defaults


class Monitor:
    def __init__(self, cfg, record_path, sender=None, on_log=None, on_pause=None):
        self.cfg = cfg
        self.on_log = on_log      # GUI 等へログ行を渡すコールバック (text, rec)
        self.on_pause = on_pause  # 異常一時停止時のコールバック (reason)
        self.mode = cfg.get("search_mode", "nbest")   # "nbest"：defend探索側 / nbest探索側 を交互、"defend"：双方 searchdefend
        if self.mode == "nbest":
            self.a_limit = cfg["a_limit_seconds"]
            self.b_limit = cfg["b_limit_seconds"]
        else:
            self.a_limit = self.b_limit = cfg.get("defend_mode_seconds", cfg["a_limit_seconds"])
        self.stable_required = cfg["stable_rounds"]
        self.stable_seconds = cfg["stable_seconds"]  # ①成立に必要な状態A開始からの最低経過秒数
        self.sender = sender                          # None なら送信しない（人が打つ）
        self.op_timeout = cfg["op_timeout_seconds"]   # 1ステップの完了確認を待つ上限秒数
        self.nbest = cfg["nbest"]
        self.step_sent_at = None              # 現在ステップのコマンド送信時刻
        self.sent_cmd = None                  # 受付確認（EXECUTE_COMMAND）待ちのコマンド
        self.resent = False                   # 現在ステップで再送済みか
        self.flush_count = 0                  # 現在ステップで送ったログ強制書き出し（echo）の回数
        self.undo_inflight = False            # undo one を送って、その EXECUTE_COMMAND がまだ届いていない
        self.hold_logged = False              # ①保留を1回だけ表示するためのフラグ
        self.forced_rounds = 0                # 「最善手以外が負け」の安定確認周回数
        self.record = open(record_path, "a", encoding="utf-8")

        self.state = "WAIT_START"
        self.state_since = None          # 状態に入った単調時刻
        self.moves = []                  # 現在局面の手順
        self.candidates = {}             # 格子位置 → 最新の pv レコード
        self.rounds_ok = 0               # 条件を満たしたまま完了した INFO PV の周回数
        self.last_pv_index = -1
        self.pending = None              # 操作中：{"branch","commands","expect":[...]} 期待するログ変化の列
        self.round_complete = False

    # ---- 記録 ----
    def log(self, kind, message, **extra):
        stamp = datetime.now().strftime("%H:%M:%S")
        elapsed = f"{self.elapsed():7.1f}s" if self.state_since is not None else "       "
        text = f"{stamp} [{self.state:>10}] {elapsed} {kind}: {message}"
        print(text)
        rec = {"time": datetime.now().isoformat(timespec="seconds"), "state": self.state,
               "elapsed": self.elapsed() if self.state_since is not None else None,
               "kind": kind, "message": message}
        rec.update(extra)
        if self.on_log:
            try:
                self.on_log(text, rec)
            except Exception:
                pass
        self.record.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.record.flush()

    def elapsed(self):
        return time.monotonic() - self.state_since if self.state_since is not None else 0.0

    def enter(self, state, reason):
        self.state = state
        self.state_since = time.monotonic()
        self.rounds_ok = 0
        self.forced_rounds = 0
        self.hold_logged = False
        self.log(tr("kind_transition"), tr("msg_transition", state=state, reason=reason))

    # ---- 候補手の分類 ----
    def classify(self):
        """候補手を EVAL で分類して (整数EVAL一覧, -M一覧, +M一覧, 不明一覧) を返す。"""
        ints, losses, wins, unknown = [], [], [], []
        for r in self.candidates.values():
            e = r["eval"]
            if "mate" in e:
                (wins if e["mate"] > 0 else losses).append(r)
            elif "cp" in e:
                ints.append(r)
            else:
                unknown.append(r)
        return ints, losses, wins, unknown

    @staticmethod
    def pick_max(ints):
        """整数 EVAL の最大値。同値なら上の行（行番号が大きい）→ 左の列（列文字が小さい）を優先。"""
        def key(r):
            col = ord(r["move"][0]) - ord("A")
            row = int(r["move"][1:])
            return (r["eval"]["cp"], row, -col)
        return max(ints, key=key)

    def summary_text(self):
        ints, losses, wins, unknown = self.classify()
        return tr("summary", n=len(self.candidates), ints=len(ints), losses=len(losses), wins=len(wins), unknown=len(unknown))

    # ---- 探索モードと呼び名 ----
    def side_name(self, state=None):
        """状態に対応する探索側の呼び名。nbest モードでは defend探索側 / nbest探索側、defend モードでは単に 探索。"""
        state = state or self.state
        if self.mode != "nbest":
            return tr("side_search")
        return tr("side_defend") if state == "A_MONITOR" else tr("side_nbest")

    def search_after_moves(self, from_state, n_added):
        """
        from_state の手番から n_added 手進めたあとに送る探索コマンドと、その状態を返す。
        nbest モード：手番が交互に入れ替わるので、奇数手進めば相手側の探索、偶数手なら同じ側。
        defend モード：常に searchdefend。
        """
        if self.mode != "nbest":
            return "searchdefend", "yxsearchdefend", "A_MONITOR"
        flip = n_added % 2 == 1
        to_b = (from_state == "A_MONITOR") == flip
        if to_b:
            return f"nbest {self.nbest}", "yxnbest", "B_MONITOR"
        return "searchdefend", "yxsearchdefend", "A_MONITOR"

    # ---- 四（次に五が揃う）の検出 ----
    @staticmethod
    def forced_block(moves):
        """
        手番側が「相手の四」を止めなければならない場合、その唯一の止める位置を返す。
        ・相手が次に置くと五になる空点をすべて数え、ちょうど1つならそれを返す（0 なら None、2 以上は止め切れないので None）。
        ・手番側が自分で五を作れる空点を持つなら、止める必要はない（勝ち）ので None。
        黒は第1手目から交互。黒は 5 連ちょうど、白は 5 連以上を五とみなす。
        """
        n = BOARD_SIZE
        board = {}
        for i, m in enumerate(moves):
            col = ord(m[0]) - ord("A")
            row = int(m[1:]) - 1
            board[(col, row)] = i % 2  # 0 = 黒, 1 = 白
        me = len(moves) % 2
        opp = 1 - me

        def makes_five(color, col, row):
            for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
                cnt = 1
                for sgn in (1, -1):
                    c, r = col + dc * sgn, row + dr * sgn
                    while 0 <= c < n and 0 <= r < n and board.get((c, r)) == color:
                        cnt += 1
                        c += dc * sgn
                        r += dr * sgn
                if cnt == 5 or (cnt > 5 and color == 1):
                    return True
            return False

        my_wins, opp_wins = [], []
        for col in range(n):
            for row in range(n):
                if (col, row) in board:
                    continue
                if makes_five(me, col, row):
                    my_wins.append((col, row))
                if makes_five(opp, col, row):
                    opp_wins.append((col, row))
        if my_wins or len(opp_wins) != 1:
            return None
        col, row = opp_wins[0]
        return f"{chr(ord('A') + col)}{row + 1}"

    def extend_with_forced_blocks(self, moves, max_steps=6):
        """着手列 moves の末尾から、四への応手が続く限り（最大 max_steps 手）応手を追加して返す。"""
        added = []
        for _ in range(max_steps):
            blk = self.forced_block(moves + added)
            if not blk:
                break
            added.append(blk)
        return added

    def plan_moves_then_search(self, code, title, from_state, new_moves):
        """
        thinking stop → putpos（new_moves に四への応手を続けて追加）→ 次の探索コマンド、という計画を立てる。
        new_moves は現在の局面より長い着手列であること。
        """
        blocks = self.extend_with_forced_blocks(new_moves)
        if blocks:
            self.log(tr("kind_four"), tr("msg_four_chain", moves=" ".join(blocks)))
        final = new_moves + blocks
        n_added = len(final) - len(self.moves)
        search_cmd, expect_kind, next_state = self.search_after_moves(from_state, n_added)
        putpos = "putpos " + "".join(m.lower() for m in final)
        self.plan(code, title, ["thinking stop", putpos, search_cmd],
                  [("yxstop", None), ("position", final), (expect_kind, None)], next_state=next_state)

    def plan_stop_undo_defend(self, code, title, offset, search="defend"):
        """
        thinking stop →（offset が数値なら停止前の手数+offset まで undo one）→ 探索コマンド、の計画を作る。
        search="defend" なら searchdefend（状態A）、"nbest" なら nbest（状態B）。
        """
        commands = ["thinking stop"]
        expect = [("yxstop", None)]
        if offset is not None:
            target = len(self.moves) + offset
            commands.append(tr("cmd_undo_until", target=target))
            expect.append(("undo_to", target))
        if search == "nbest" and self.mode == "nbest":
            commands.append(f"nbest {self.nbest}")
            expect.append(("yxnbest", None))
            self.plan(code, title, commands, expect, next_state="B_MONITOR")
        else:
            commands.append("searchdefend")
            expect.append(("yxsearchdefend", None))
            self.plan(code, title, commands, expect, next_state="A_MONITOR")

    def check_four_now(self):
        """監視に入った直後、いまの局面が四を止めるだけの局面なら探索を待たずに着手する。"""
        if not self.moves:
            return False
        blk = self.forced_block(self.moves)
        if not blk:
            return False
        self.log(tr("kind_four"), tr("msg_four_now", side=self.side_name(), move=blk))
        self.plan_moves_then_search("four", tr("title_four"), self.state, self.moves + [blk])
        return True

    # ---- レコード処理 ----
    def on_record(self, rec):
        t = rec["type"]

        if t == "command":
            self.log(tr("kind_command"), rec["command"][:80])
            if rec["command"].startswith("thinking start"):
                self.log(tr("kind_warning"), tr("msg_thinking_start"))
            # 自動運転中（監視状態）に人が Rapfi を操作すると状態が食い違うため、自動探索を止める
            if self.sender and self.state in ("A_MONITOR", "B_MONITOR") and rec["command"].split()[0] not in ("help", "echo"):
                self.pause(tr("msg_manual", cmd=rec["command"]))
                return

        if t == "position":
            if rec["moves"] != self.moves:
                self.log(tr("kind_position"), tr("msg_position", before=len(self.moves), after=len(rec["moves"]), moves=" ".join(rec["moves"])))
                self.moves = rec["moves"]
                self.candidates = {}
                self.rounds_ok = 0
                self.last_pv_index = -1

        if t == "pv" and rec.get("move"):
            self.candidates[rec["move"]] = rec
            # pv_index が巻き戻ったら1周回完了
            self.round_complete = rec["pv_index"] <= self.last_pv_index
            self.last_pv_index = rec["pv_index"]

        # 操作中は期待するログ変化の到着だけを見る
        if self.state == "OPERATING":
            self.check_pending(rec)
            return

        if self.state == "WAIT_START":
            if t == "engine_cmd" and rec["command"] == "yxsearchdefend":
                self.enter("A_MONITOR", tr("msg_detect_defend", side=self.side_name("A_MONITOR")))
                self.check_four_now()
            elif t == "engine_cmd" and rec["command"].startswith("yxnbest"):
                st = "B_MONITOR" if self.mode == "nbest" else "A_MONITOR"
                self.enter(st, tr("msg_detect_nbest", side=self.side_name(st)))
                self.check_four_now()
            return

        if self.state == "A_MONITOR":
            self.judge(rec, "A_MONITOR")
        elif self.state == "B_MONITOR":
            self.judge(rec, "B_MONITOR")

    # ---- 判定（両状態共通） ----
    def stable_ok(self, rec, counter_name):
        """周回数＋最低経過秒数の安定確認。条件を満たした周回を数え、成立なら True。"""
        if rec["type"] == "pv" and self.round_complete:
            setattr(self, counter_name, getattr(self, counter_name) + 1)
            self.log(tr("kind_stable"), tr("msg_stable", n=getattr(self, counter_name), req=self.stable_required, summary=self.summary_text()))
        if getattr(self, counter_name) < self.stable_required:
            return False
        if self.elapsed() < self.stable_seconds:
            if not self.hold_logged:
                self.hold_logged = True
                self.log(tr("kind_hold"), tr("msg_hold", sec=self.stable_seconds))
            return False
        return True

    def judge(self, rec, state):
        side = self.side_name(state)
        limit = self.a_limit if state == "A_MONITOR" else self.b_limit
        is_nbest_side = self.mode == "nbest" and state == "B_MONITOR"

        # 期限判定を先に行う（期限ちょうどは時間側を優先）
        if self.elapsed() >= limit:
            ints, losses, wins, unknown = self.classify()
            self.log(tr("kind_timeout"), tr("msg_timeout", side=side, limit=f"{limit:.0f}", summary=self.summary_text()))
            if is_nbest_side:
                # nbest側が時間内に勝ち筋を見つけられない → 停止時にエンジンが打つ手を採用し、defend探索側へ
                self.plan_stop_undo_defend("timeout_nbest", tr("title_timeout_nbest"), self.cfg["undo_offset_branch4"])
                return
            if wins:
                # 時間切れの時点で勝ち筋がある＝直前の相手の手が悪手。戻して相手側の探索をやり直す
                self.log(tr("kind_win_found"), tr("msg_win_found", side=side, wins=" ".join(f"{r['move']}({r['eval_text']})" for r in wins)))
                self.plan_stop_undo_defend("win_found", tr("title_win_found"), self.cfg["undo_offset_branch3"],
                                           search="defend" if is_nbest_side else "nbest")
                return
            if not ints:
                if losses and not unknown:
                    # 時間切れの時点で全候補が -M（読み切り）なら、安定確認の周回を待たずに「全候補が負け」として戻す
                    self.log(tr("kind_all_lost"), tr("msg_all_lost_timeout", side=side, summary=self.summary_text()))
                    self.plan_stop_undo_defend("all_lost", tr("title_all_lost"), self.cfg["undo_offset_branch1"])
                    return
                self.pause(tr("msg_timeout_unknown", summary=self.summary_text()))
                return
            best = self.pick_max(ints)
            self.log(tr("kind_best_move"), tr("msg_best_move", side=side, move=best["move"], eval=best["eval_text"]),
                     candidates=[{"move": r["move"], "eval": r["eval_text"]} for r in sorted(ints, key=lambda r: -r["eval"]["cp"])])
            self.plan_moves_then_search("timeout_move", tr("title_timeout_move"), state, self.moves + [best["move"]])
            return

        if rec["type"] not in ("pv", "tick"):
            return
        ints, losses, wins, unknown = self.classify()

        # 勝ち筋（+M）：手番側に勝ち筋がある＝直前の相手の手が悪手 → 1手戻して相手側の探索をやり直す
        #   nbest探索側で +M → 戻して defend探索（defend側の手が悪手）
        #   defend探索側で +M → 戻して nbest探索（nbest側の手が悪手）。nbest なしモードでは常に searchdefend
        if wins:
            if rec["type"] == "pv" and (self.round_complete or len(wins) == len(self.candidates)):
                self.rounds_ok += 1
            if self.rounds_ok >= 1:  # +M は読み切りなので1回の確認で成立
                self.log(tr("kind_win_found"), tr("msg_win_found", side=side, wins=" ".join(f"{r['move']}({r['eval_text']})" for r in wins)))
                self.plan_stop_undo_defend("win_found", tr("title_win_found"), self.cfg["undo_offset_branch3"],
                                           search="defend" if is_nbest_side else "nbest")
            return

        # 最善手以外が全て負け → 最善手を着手して次の手から探索
        non_loss = ints
        if len(non_loss) == 1 and losses and not unknown:
            if self.stable_ok(rec, "forced_rounds"):
                best = non_loss[0]
                self.log(tr("kind_forced"), tr("msg_forced", side=side, move=best["move"], eval=best["eval_text"]),
                         candidates=[{"move": r["move"], "eval": r["eval_text"]} for r in self.candidates.values()])
                self.plan_moves_then_search("forced_move", tr("title_forced"), state, self.moves + [best["move"]])
            return
        self.forced_rounds = 0

        # 全候補が負け → 2手戻して defend探索
        if losses and not ints and not unknown:
            if self.stable_ok(rec, "rounds_ok"):
                self.log(tr("kind_all_lost"), tr("msg_all_lost", side=side, summary=self.summary_text()))
                self.plan_stop_undo_defend("all_lost", tr("title_all_lost"), self.cfg["undo_offset_branch1"])
            return
        self.rounds_ok = 0

    # ---- 操作 ----
    def plan(self, code, title, commands, expect, next_state):
        """commands[i] と expect[i] は対応する（undo_to のコマンドは "undo one" を必要回数送る）。"""
        # 安全策：putpos を含む計画は、現在の局面が分かっていて（1手以上）、送る手順がそれより長い場合だけ許す
        for cmd, (kind, arg) in zip(commands, expect):
            if cmd.startswith("putpos"):
                if not self.moves:
                    self.pause(tr("msg_putpos_unknown", title=title))
                    return
                if kind == "position" and len(arg) <= len(self.moves):
                    self.pause(tr("msg_putpos_short", title=title, n=len(arg), cur=len(self.moves)))
                    return
        steps = list(zip(commands, expect))
        self.pending = {"code": code, "title": title, "steps": steps, "next": next_state}
        self.enter("OPERATING", title)
        mode = "自動送信します" if self.sender else "Rapfi のコマンド入力欄に順に入力してください（自動送信はしません）"
        print("=" * 70)
        print(f"  {title}：以下のコマンドを{mode}")
        for c in commands:
            print(f"    > {c}")
        print("=" * 70)
        self.log(tr("kind_plan"), " / ".join(c if len(c) < 60 else c[:57] + "..." for c in commands), commands=commands, code=code)
        self.send_current()

    def current_command(self):
        """現在ステップで実際に送るコマンド文字列（undo_to は "undo one"）。"""
        cmd, (kind, arg) = self.pending["steps"][0]
        return "undo one" if kind == "undo_to" else cmd

    def send_current(self):
        """自動送信モードなら現在ステップのコマンドを送る。undo_to のステップでは送らない（send_undo が担当）。"""
        self.step_sent_at = time.monotonic()
        if not self.sender or not self.pending or not self.pending["steps"]:
            return
        if self.pending["steps"][0][1][0] == "undo_to":
            return
        cmd = self.current_command()
        try:
            self.sender.send(cmd, restore_focus=False)
            self.sent_cmd, self.resent, self.flush_count = cmd, False, 0
            self.log(tr("kind_send"), cmd if len(cmd) < 60 else cmd[:57] + "...")
        except Exception as e:
            self.pause(tr("msg_send_fail", cmd=cmd[:30], err=e))

    def send_undo(self, target):
        """
        undo one を1回だけ送る。前回送った undo one の EXECUTE_COMMAND が届く（処理される）まで次は送らない。
        局面の送り直しは重複して届くため、これをしないと送りすぎて目標を通り過ぎる。
        """
        if not self.sender or self.undo_inflight:
            return
        if len(self.moves) <= target:
            return
        self.undo_inflight = True
        self.step_sent_at = time.monotonic()
        try:
            self.sender.send("undo one", restore_focus=False)
            self.sent_cmd, self.resent, self.flush_count = "undo one", False, 0
            self.log(tr("kind_send"), tr("msg_send_undo", cur=len(self.moves), target=target))
        except Exception as e:
            self.pause(tr("msg_send_fail", cmd="undo one", err=e))

    def advance(self):
        """現在ステップを完了として次へ進む。全ステップ完了なら次状態へ。"""
        self.pending["steps"].pop(0)
        self.undo_inflight = False
        if self.pending["steps"]:
            self.send_current()
            return
        nxt = self.pending["next"]
        self.pending = None
        self.step_sent_at = None
        self.sent_cmd = None
        if self.sender:
            try:
                self.sender.restore_focus()
            except Exception:
                pass
        self.candidates = {}
        self.rounds_ok = 0
        self.enter(nxt, tr("msg_op_done"))

    FLUSH_PING = "echo flush" + "x" * 4200  # Yixin のログ書き込みバッファ（数KB）を確実に埋める長さ

    def flush_log_buffer(self):
        """
        Yixin はログをバッファ方式で書くため、探索が止まると停止の記録がファイルに出てこないことがある。
        4KB 超の echo を送って EXECUTE_COMMAND 行を書かせ、バッファを強制的に書き出させる（Rapfi の動作には影響しない）。
        """
        if not self.sender:
            return
        self.flush_count += 1
        self.log(tr("kind_flush"), tr("msg_flush", n=self.flush_count))
        try:
            self.sender.send(self.FLUSH_PING, restore_focus=False)
        except Exception as e:
            self.log(tr("kind_warning"), tr("msg_flush_fail", err=e))

    def check_ack_resend(self):
        """
        送ったコマンドの受付確認（EXECUTE_COMMAND）が出ない場合の回復処理。
        2秒・8秒でログの強制書き出しを送り、それでも6秒以内に受付確認が出なければ1回だけ再送する（undo one は再送しない）。
        """
        if not self.sender or not self.step_sent_at:
            return
        waited = time.monotonic() - self.step_sent_at
        if waited >= 2.0 and self.flush_count == 0 or waited >= 8.0 and self.flush_count == 1:
            self.flush_log_buffer()
            return
        if not self.sent_cmd or self.resent or waited < 6.0:
            return
        if self.sent_cmd == "undo one":
            return
        cmd = self.sent_cmd
        self.resent = True
        self.log(tr("kind_resend"), tr("msg_resend", cmd=cmd if len(cmd) < 40 else cmd[:37] + "..."))
        try:
            self.sender.send(cmd, restore_focus=False)
        except Exception as e:
            self.pause(tr("msg_resend_fail", cmd=cmd[:30], err=e))

    def check_timeout(self):
        if self.state == "OPERATING" and self.step_sent_at and time.monotonic() - self.step_sent_at > self.op_timeout:
            kind, arg = self.pending["steps"][0][1]
            self.pause(tr("msg_op_timeout", sec=self.op_timeout, expect=f"{kind} {arg if arg and kind != 'position' else ''}".strip()))

    def check_pending(self, rec):
        if not self.pending or not self.pending["steps"]:
            return
        cmd, (kind, arg) = self.pending["steps"][0]
        if rec["type"] == "command" and self.sent_cmd and rec["command"] == self.sent_cmd:
            self.sent_cmd = None  # 受付確認が取れた
        if rec["type"] == "tick":
            self.check_ack_resend()
            self.check_timeout()
            if kind == "undo_to" and self.state == "OPERATING":
                self.send_undo(arg)  # 局面の送り直しが来ない場合の保険
            return
        ok = False
        if kind in ("yxstop", "yxsearchdefend", "yxnbest"):
            ok = rec["type"] == "engine_cmd" and rec["command"].split()[0] == kind
        elif kind == "position":
            ok = rec["type"] == "position" and rec["moves"] == arg
        elif kind == "undo_to":
            # 目標手数に達するまで undo one を1回ずつ送る。目標より短くなったら行き過ぎなので異常停止
            if rec["type"] == "command" and rec["command"] == "undo one":
                self.undo_inflight = False  # 前回の undo one が処理された
            if rec["type"] == "position":
                if len(rec["moves"]) == arg:
                    ok = True
                elif len(rec["moves"]) < arg:
                    self.pause(tr("msg_undo_over", cur=len(rec["moves"]), target=arg))
                    return
                else:
                    self.log(tr("kind_undo_wait"), tr("msg_undo_wait", cur=len(rec["moves"]), target=arg, n=len(rec["moves"]) - arg))
                    self.send_undo(arg)
        if ok:
            self.log(tr("kind_confirmed"), f"{kind} {arg if arg and kind != 'position' else ''}".strip())
            self.advance()

    def pause(self, reason):
        if self.sender:
            try:
                self.sender.restore_focus()
            except Exception:
                pass
        self.enter("PAUSED", reason)
        self.log(tr("kind_pause"), reason)
        if self.on_pause:
            try:
                self.on_pause(reason)
            except Exception:
                pass
        print("=" * 70)
        print(f"  異常一時停止：{reason}")
        print("  Rapfi の状態を確認し、再開する場合は監視を起動し直してください。")
        print("=" * 70)


class ExtendedParser(DebugLogParser):
    """SEND のエンジン向けコマンド（yxstop 等）もレコードとして返す。"""

    def _on_send(self, body):
        rec = super()._on_send(body)
        if rec is None and body.split() and body.split()[0] in ("yxstop", "yxsearchdefend", "yxnbest", "yxblockreset"):
            return {"type": "engine_cmd", "command": body}
        return rec


def detect_initial_state(path, tail_bytes=4_000_000):
    """
    ログ末尾から、現在 Rapfi がどの探索中かを推定する。
    戻り値: ("A_MONITOR", moves) / ("B_MONITOR", moves) / ("WAIT_START", moves)
    """
    parser = ExtendedParser()
    size = os.path.getsize(path)
    last_mode = None
    moves = []  # 最後に「完成した」局面（done まで届いたもの）。送信途中のバッファは使わない
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(max(0, size - tail_bytes))
        if size > tail_bytes:
            f.readline()  # 途中行を捨てる
        for line in f:
            rec = parser.feed(line)
            if not rec:
                continue
            if rec["type"] == "position":
                moves = rec["moves"]
            elif rec["type"] == "engine_cmd":
                c = rec["command"].split()[0]
                if c == "yxsearchdefend":
                    last_mode = "A_MONITOR"
                elif c == "yxnbest":
                    last_mode = "B_MONITOR"
                elif c == "yxstop":
                    last_mode = None
    if last_mode and not moves:
        # 局面が分からないまま途中開始すると putpos で盤面を壊すため、待機から始める
        last_mode = None
    return (last_mode or "WAIT_START"), moves


def replay(path, monitor):
    """既存ログを先頭から一気に流し込む（判定ロジックのオフライン検証用。時間条件は実時間）。"""
    parser = ExtendedParser()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            rec = parser.feed(line)
            if rec:
                monitor.on_record(rec)
            if monitor.state == "PAUSED":
                break
    monitor.log(tr("kind_end"), tr("msg_replay_end"))


def run(path, monitor, poll=0.2, status_interval=30, stop_event=None, initial_state=None):
    poll = monitor.cfg.get("poll_seconds", poll)
    status_interval = monitor.cfg.get("status_interval_seconds", status_interval)
    parser = ExtendedParser()
    f = open(path, encoding="utf-8", errors="replace")
    f.seek(0, os.SEEK_END)
    pos = f.tell()
    monitor.log(tr("kind_start"), tr("msg_start", path=path))
    if initial_state and initial_state[0] != "WAIT_START":
        monitor.moves = list(initial_state[1])
        monitor.enter(initial_state[0], tr("msg_resume", n=len(monitor.moves), moves=" ".join(monitor.moves[-6:])))
    elif initial_state and initial_state[1] and monitor.sender and monitor.cfg.get("auto_start_search", True):
        # 探索が止まっていて局面が分かっているなら、待たずに searchdefend を送って探索を始める
        monitor.moves = list(initial_state[1])
        monitor.log(tr("kind_autostart"), tr("msg_autostart", n=len(monitor.moves)))
        monitor.plan("autostart", tr("title_autostart"), ["searchdefend"], [("yxsearchdefend", None)], next_state="A_MONITOR")
    else:
        monitor.log(tr("kind_wait"), tr("msg_wait"))
    last_status = time.monotonic()
    try:
        while monitor.state != "PAUSED" and not (stop_event and stop_event.is_set()):
            if time.monotonic() - last_status >= status_interval:
                last_status = time.monotonic()
                if monitor.state in ("A_MONITOR", "B_MONITOR"):
                    limit = monitor.a_limit if monitor.state == "A_MONITOR" else monitor.b_limit
                    monitor.log(tr("kind_status"), tr("msg_status", remain=f"{limit - monitor.elapsed():.0f}", n=len(monitor.moves), summary=monitor.summary_text()))
                elif monitor.state == "OPERATING":
                    nxt = monitor.pending["steps"][0][1] if monitor.pending and monitor.pending["steps"] else "-"
                    monitor.log(tr("kind_status"), tr("msg_status_op", expect=nxt))
            line = f.readline()
            if not line:
                size = os.path.getsize(path)
                if size < pos:
                    monitor.log(tr("kind_note"), tr("msg_truncated"))
                    f.close()
                    f = open(path, encoding="utf-8", errors="replace")
                    pos = 0
                    continue
                # 追記がなくても期限判定は進める
                if monitor.state in ("A_MONITOR", "B_MONITOR", "OPERATING"):
                    monitor.on_record({"type": "tick"})
                time.sleep(poll)
                continue
            pos = f.tell()
            if line.startswith("----------new record"):
                monitor.pause("Rapfi が再起動されました（new record）")
                break
            rec = parser.feed(line)
            if rec:
                monitor.on_record(rec)
    except KeyboardInterrupt:
        monitor.log(tr("kind_end"), tr("msg_ctrlc"))
    finally:
        f.close()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cfg = load_monitor_config()
    ap = argparse.ArgumentParser(description="Rapfi 自動操作アプリ 監視・操作部（設定は monitor_config.json、引数で上書き）")
    ap.add_argument("--log", default=DEFAULT_LOG, help="debuglog.txt のパス")
    ap.add_argument("--a-limit", type=float, default=None, help=f"状態Aの制限時間（秒）既定 {cfg['a_limit_seconds']}")
    ap.add_argument("--b-limit", type=float, default=None, help=f"状態Bの制限時間（秒）既定 {cfg['b_limit_seconds']}")
    ap.add_argument("--stable", type=int, default=None, help=f"安定確認に必要な周回数 既定 {cfg['stable_rounds']}")
    ap.add_argument("--stable-seconds", type=float, default=None, help=f"安定確認の最低経過秒数 既定 {cfg['stable_seconds']}")
    ap.add_argument("--op-timeout", type=float, default=None, help=f"操作の完了確認を待つ上限秒数 既定 {cfg['op_timeout_seconds']}")
    ap.add_argument("--record", default=os.path.join(rapfi_dir(), "output", "monitor_log.jsonl"),
                    help="判定ログ（JSON Lines）の出力先")
    ap.add_argument("--replay", action="store_true", help="ログを先頭から流し込んで判定だけ検証する")
    ap.add_argument("--auto", action="store_true", help="コマンドを自動送信する（sender.py の校正が必要）")
    args = ap.parse_args()
    for arg, key in (("a_limit", "a_limit_seconds"), ("b_limit", "b_limit_seconds"), ("stable", "stable_rounds"),
                     ("stable_seconds", "stable_seconds"), ("op_timeout", "op_timeout_seconds")):
        if getattr(args, arg) is not None:
            cfg[key] = getattr(args, arg)
    print("設定:", cfg)
    if not os.path.exists(args.log):
        print(f"ログファイルが見つかりません: {args.log}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(os.path.dirname(args.record), exist_ok=True)
    sender = None
    if args.auto:
        from sender import Sender
        sender = Sender()
        print("自動送信モード：条件成立時にコマンドを Rapfi へ送信します")
    monitor = Monitor(cfg, args.record, sender=sender)
    if args.replay:
        replay(args.log, monitor)
    else:
        run(args.log, monitor)


if __name__ == "__main__":
    main()
