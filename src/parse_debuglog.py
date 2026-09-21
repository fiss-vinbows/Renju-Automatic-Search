"""
Rapfi/YixinBoard の debuglog.txt を解析して評価値ログを構造化データとして取り出す。

settings.txt の「record debug log」を 1 にすると、GUI と engine.exe の全通信が
debuglog.txt に記録される。画面右側に表示される評価値ログはこのファイルから
画像認識なしで正確に読み取れる。

実行例：
    python parse_debuglog.py                  # 最新の解析結果を表示して JSON 保存
    python parse_debuglog.py --follow         # 追記を監視して新着を逐次表示
    python parse_debuglog.py --follow --max-mb 50   # 50MBを超えたら自動で切り詰めつつ監視
    python parse_debuglog.py --truncate       # ログを空にする（Yixin起動中でも安全）
    python parse_debuglog.py --log 別パス.txt --out 出力.json
"""

import argparse
import json
import os
import re
import shutil
import sys
import time

BOARD_SIZE = 15
def app_dir():
    """設定ファイル等を置く基準フォルダ。exe 化時は exe のあるフォルダ、通常は prototype フォルダ。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def rapfi_dir():
    """
    Rapfi（debuglog.txt）のあるフォルダ。app_dir の親フォルダ。
    exe は Rapfi フォルダ直下のサブフォルダ（例: RAS フォルダ）に置く。開発時は src フォルダが同じ役割。
    """
    return os.path.dirname(app_dir())


DEFAULT_LOG = os.path.join(rapfi_dir(), "debuglog.txt")

# 行の形式： "RECEIVE_COMMAND [時計情報]: 本文" / "SEND_COMMAND [...]: 本文"
LINE_RE = re.compile(r"^(SEND|RECEIVE)_COMMAND \[[^\]]*\]: (.*)$")
# 例： "EXECUTE_COMMAND [時計情報]: nbest 2"（コマンド入力欄・toolbar から実行された GUI コマンド）
EXEC_RE = re.compile(r"^EXECUTE_COMMAND \[[^\]]*\]:\s*(.*)$")
# 例： "MESSAGE Depth 15-24 | Eval -451 | Time 10s | J5 E8 K4 ..."
DEPTH_RE = re.compile(r"^MESSAGE Depth (\d+)-(\d+) \| Eval (\S+) \| Time (\S+) \| ?(.*)$")
# 例： "MESSAGE (118) -M14 | 18-12 | M13 M8 N7 ..."
PVLINE_RE = re.compile(r"^MESSAGE \((\d+)\) (\S+) \| (\d+)-(\d+) \| ?(.*)$")
# 例： "MESSAGE Speed 5720K | Depth 19-29 | Eval 637 | Node 14M | Time 2454ms"
SPEED_RE = re.compile(r"^MESSAGE Speed (.*)$")


def coord_to_name(rc):
    """エンジン座標 "行,列"（どちらも0始まり、行は上から）を "M13" 形式に変換する。"""
    r, c = (int(v) for v in rc.split(",")[:2])  # 3項目目（色）は無視
    return f"{chr(ord('A') + c)}{BOARD_SIZE - r}"


def parse_eval(text):
    """評価値文字列を解釈する。数値ならint、"+M14"/"-M14" は詰み手数として返す。"""
    m = re.fullmatch(r"([+-]?)M(\d+)", text)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        return {"mate": sign * int(m.group(2))}
    try:
        return {"cp": int(text)}
    except ValueError:
        return {"raw": text}


class DebugLogParser:
    """行を1本ずつ流し込むと、完成したレコード（dict）を返すストリーム型パーサー。"""

    def __init__(self):
        self.current_pv = None   # 組み立て中の INFO PV ブロック
        self.moves = []          # GUI が送った着手列（局面追跡用）
        self.in_board = False    # yxboard/board ～ done の間か

    def feed(self, line):
        line = line.rstrip("\r\n")
        m = EXEC_RE.match(line)
        if m:
            return {"type": "command", "command": m.group(1).strip()}
        m = LINE_RE.match(line)
        if not m:
            return None
        direction, body = m.group(1), m.group(2).strip()
        if direction == "SEND":
            return self._on_send(body)
        return self._on_receive(body)

    # ---- GUI → エンジン（局面追跡） ----
    def _on_send(self, body):
        # yxboard / yxquerydatabaseallt / yxsearchdefend などの後に「行,列[,色]」の並びと "done" が続き、
        # それが現在の局面を表す。コマンド名で始まる行が来たら着手列を積み直す。
        if re.match(r"^(yx\w+|board)$", body.split()[0]):
            self.in_board = True
            self.moves = []
            return None
        if body == "done":
            if self.in_board:
                self.in_board = False
                return {"type": "position", "moves": [coord_to_name(x) for x in self.moves]}
            return None
        if self.in_board and re.fullmatch(r"\d+,\d+(,\d+)?", body):
            self.moves.append(body)
            return None
        if body.startswith("turn "):
            self.moves.append(body[5:].strip())
            return {"type": "position", "moves": [coord_to_name(x) for x in self.moves]}
        return None

    # ---- エンジン → GUI ----
    def _on_receive(self, body):
        if body.startswith("INFO "):
            parts = body[5:].split(" ", 1)
            key = parts[0]
            val = parts[1] if len(parts) > 1 else ""
            if key == "PV":
                if val == "DONE":
                    rec, self.current_pv = self.current_pv, None
                    if rec is not None:
                        rec["type"] = "pv"
                    return rec
                self.current_pv = {"pv_index": int(val)}
                return None
            if self.current_pv is not None:
                if key == "BESTLINE":
                    names = [coord_to_name(x) for x in val.split()]
                    self.current_pv["bestline"] = names
                    self.current_pv["move"] = names[0] if names else None
                elif key == "EVAL":
                    self.current_pv["eval"] = parse_eval(val)
                    self.current_pv["eval_text"] = val
                elif key == "WINRATE":
                    # エンジンは 0〜1 の小数で送ってくる。GUI 表示に合わせて 0〜100 の%に丸める
                    self.current_pv["winrate"] = round(float(val) * 100)
                elif key in ("NUMPV", "DEPTH", "SELDEPTH", "NODES", "TOTALNODES", "TOTALTIME", "SPEED"):
                    try:
                        self.current_pv[key.lower()] = int(val)
                    except ValueError:
                        self.current_pv[key.lower()] = val
            return None

        m = DEPTH_RE.match(body)
        if m:
            return {
                "type": "depth",
                "depth": int(m.group(1)), "seldepth": int(m.group(2)),
                "eval": parse_eval(m.group(3)), "eval_text": m.group(3),
                "time": m.group(4), "line": m.group(5).split(),
            }
        m = PVLINE_RE.match(body)
        if m:
            return {
                "type": "pv_summary",
                "rank": int(m.group(1)),
                "eval": parse_eval(m.group(2)), "eval_text": m.group(2),
                "depth": int(m.group(3)), "seldepth": int(m.group(4)),
                "line": m.group(5).split(),
            }
        m = SPEED_RE.match(body)
        if m:
            return {"type": "speed", "text": m.group(1)}
        if body.startswith("MESSAGE REALTIME BEST "):
            return {"type": "realtime_best", "move": coord_to_name(body.split()[-1])}
        if re.fullmatch(r"\d+,\d+", body):
            # エンジンの着手（対局モード）
            self.moves.append(body)
            return {"type": "engine_move", "move": coord_to_name(body)}
        return None


def parse_file(path):
    """ファイル全体を解析し、レコードのリストを返す。"""
    parser = DebugLogParser()
    records = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            rec = parser.feed(line)
            if rec:
                records.append(rec)
    return records


def summarize_latest(records):
    """最後の局面（position 以降）についての、候補手ごとの最新評価をまとめる。"""
    # GUI はデータベース問い合わせ等で同じ局面を何度も送り直すため、
    # 「最後の局面と同じ手順が続いている区間」の先頭まで遡って対象にする
    positions = [i for i, r in enumerate(records) if r["type"] == "position"]
    moves = records[positions[-1]]["moves"] if positions else []
    start = 0
    for i in reversed(positions):
        if records[i]["moves"] != moves:
            start = i + 1
            break
    tail = records[start:]

    # 候補手ごとに最新の pv レコードで上書き（深い探索結果ほど後ろに来る）
    by_move = {}
    depth_lines = []
    for r in tail:
        if r["type"] == "pv" and r.get("move"):
            by_move[r["move"]] = r
        elif r["type"] == "depth":
            depth_lines.append(r)

    def sort_key(r):
        e = r["eval"]
        if "mate" in e:
            # 勝ち詰みは最上位、負け詰みは最下位（手数が長いほうがマシ）
            return (2, -e["mate"]) if e["mate"] > 0 else (0, e["mate"])
        return (1, e.get("cp", 0))

    candidates = sorted(by_move.values(), key=sort_key, reverse=True)
    return {"moves": moves, "candidates": candidates, "depth_lines": depth_lines}


def eval_label(rec):
    """盤面上の表示に近い短い表記（"39%" / "L14" / "W7"）を作る。"""
    e = rec["eval"]
    if "mate" in e:
        return f"W{e['mate']}" if e["mate"] > 0 else f"L{-e['mate']}"
    if "winrate" in rec:
        return f"{rec['winrate']}%"
    return rec["eval_text"]


def print_summary(summary):
    print(f"局面（{len(summary['moves'])}手）: {' '.join(summary['moves'])}")
    print(f"候補手 {len(summary['candidates'])} 件")
    print(f"{'順位':>4} {'手':>4} {'表示':>6} {'評価':>7} {'勝率':>4} {'深さ':>6}  読み筋")
    for i, r in enumerate(summary["candidates"], 1):
        depth = f"{r.get('depth','?')}-{r.get('seldepth','?')}"
        print(f"{i:>4} {r['move']:>4} {eval_label(r):>6} {r['eval_text']:>7} {r.get('winrate','?'):>3}% {depth:>6}  {' '.join(r['bestline'][:10])}")
    if summary["depth_lines"]:
        d = summary["depth_lines"][-1]
        print(f"最新の深さ行: 深さ {d['depth']}-{d['seldepth']} | 値 {d['eval_text']} | 時間 {d['time']} | {' '.join(d['line'])}")


def truncate_log(path, backup_dir=None):
    """
    ログを0バイトに切り詰める。Yixin は追記モードで書いているため、起動中に行っても
    次の書き込みは先頭から正常に始まる（2026-09-13 実機確認済み）。
    backup_dir を指定すると、切り詰め前の内容を日時付きファイル名で退避する。
    """
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        dst = os.path.join(backup_dir, "debuglog_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt")
        shutil.copyfile(path, dst)
        print(f"退避: {dst}")
    with open(path, "r+b") as f:
        f.truncate(0)
    print(f"切り詰め: {path}")


def follow(path, max_bytes=0, backup_dir=None):
    """
    ファイルの追記を監視し、新しいレコードを逐次表示する。
    max_bytes を指定すると、ファイルがその大きさを超えた時点で自動的に切り詰める。
    外部から切り詰められた場合（サイズが読み取り位置より小さくなった場合）も先頭から読み直す。
    """
    parser = DebugLogParser()
    print(f"監視中: {path}（Ctrl+C で終了）")
    f = open(path, encoding="utf-8", errors="replace")
    f.seek(0, os.SEEK_END)
    pos = f.tell()
    try:
        while True:
            line = f.readline()
            if not line:
                # 追記なし。切り詰め（サイズ < 読み取り位置）を検知したら先頭に戻る
                size = os.path.getsize(path)
                if size < pos:
                    print("[ログが切り詰められたため先頭から読み直します]")
                    f.close()
                    f = open(path, encoding="utf-8", errors="replace")
                    pos = 0
                    continue
                if max_bytes and size > max_bytes:
                    f.close()
                    truncate_log(path, backup_dir)
                    f = open(path, encoding="utf-8", errors="replace")
                    pos = 0
                    continue
                time.sleep(0.2)
                continue
            pos = f.tell()
            rec = parser.feed(line)
            if not rec:
                continue
            if rec["type"] == "pv":
                print(f"[PV {rec['pv_index']+1:>3}] {rec['move']:>4} {eval_label(rec):>6} 評価={rec['eval_text']:>6} 深さ={rec.get('depth')}-{rec.get('seldepth')} {' '.join(rec['bestline'][:8])}")
            elif rec["type"] == "depth":
                print(f"[深さ] {rec['depth']}-{rec['seldepth']} 値={rec['eval_text']} 時間={rec['time']} {' '.join(rec['line'][:8])}")
            elif rec["type"] == "position":
                print(f"[局面] {' '.join(rec['moves'])}")
            elif rec["type"] in ("engine_move", "realtime_best"):
                print(f"[{rec['type']}] {rec['move']}")
            elif rec["type"] == "command":
                print(f"[コマンド実行] {rec['command']}")
    finally:
        f.close()


def main():
    # Windows のコンソールで日本語が化けないように UTF-8 に固定する
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Rapfi debuglog.txt 解析ツール")
    ap.add_argument("--log", default=DEFAULT_LOG, help="debuglog.txt のパス")
    ap.add_argument("--out", default=None, help="解析結果の JSON 出力先")
    ap.add_argument("--follow", action="store_true", help="追記を監視して逐次表示する")
    ap.add_argument("--max-mb", type=float, default=0, help="--follow 中、ログがこのMBを超えたら自動で切り詰める（0=しない）")
    ap.add_argument("--truncate", action="store_true", help="ログを0バイトに切り詰めて終了する（Yixin起動中でも可）")
    ap.add_argument("--backup-dir", default=None, help="切り詰め前の内容を退避するフォルダ")
    args = ap.parse_args()

    if not os.path.exists(args.log):
        print(f"ログファイルが見つかりません: {args.log}", file=sys.stderr)
        sys.exit(1)

    if args.truncate:
        truncate_log(args.log, args.backup_dir)
        return
    if args.follow:
        follow(args.log, max_bytes=int(args.max_mb * 1024 * 1024), backup_dir=args.backup_dir)
        return

    records = parse_file(args.log)
    summary = summarize_latest(records)
    print_summary(summary)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "records": records}, f, ensure_ascii=False, indent=1)
        print(f"JSON 保存: {args.out}")


if __name__ == "__main__":
    main()
