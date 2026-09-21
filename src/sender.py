"""
Rapfi（YixinBoard）のコマンド入力欄へコマンドを送る送信部（第4段階）。

Windows 標準 API（user32）だけを ctypes 経由で使うため、追加ライブラリは不要。
GTK 製の Yixin は入力欄が独立したウィンドウを持たないため、入力欄の位置は
一度「校正」してウィンドウ相対座標として保存し、以後はその位置をクリックしてから文字を送る。

使い方：
    python sender.py --calibrate          # 5秒以内にマウスを入力欄の上に置く → 位置を保存
    python sender.py --send "echo test"   # コマンドを1つ送る
    python sender.py --check              # Yixin ウィンドウの検出と校正値の確認だけ行う

安全策：
  ・送信直前に前面ウィンドウが Yixin であることを確認し、違えば送らない。
  ・送るのは英数字・記号のみ（コマンド文字列）。
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 座標は常に物理ピクセルで扱う（高DPI環境で GUI 側と食い違わないよう、このモジュールの読み込み時に DPI 対応にする）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


def system_dpi_scale():
    """システムの DPI 倍率（96dpi = 1.0）。"""
    try:
        return user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0

from parse_debuglog import app_dir

CONFIG_PATH = os.path.join(app_dir(), "sender_config.json")
WINDOW_TITLE_PREFIX = "Yixin"

# ---- SendInput 用の構造体 ----
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_MENU = 0x12
VK_A = 0x41
VK_END = 0x23
VK_BACK = 0x08

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def _send_inputs(inputs):
    arr = (INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if n != len(inputs):
        raise RuntimeError(f"SendInput 失敗: {n}/{len(inputs)} 件のみ送信")


def _key(vk, up=False):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=0)
    return inp


def _char(ch, up=False):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0),
                          time=0, dwExtraInfo=0)
    return inp


def _mouse(flag):
    inp = INPUT(type=INPUT_MOUSE)
    inp.u.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flag, time=0, dwExtraInfo=0)
    return inp


# ---- ウィンドウ操作 ----
def find_yixin_window():
    """タイトルが "Yixin" で始まる可視トップレベルウィンドウのハンドルを返す。無ければ None。"""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value.startswith(WINDOW_TITLE_PREFIX):
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(enum_proc, 0)
    return found[0] if found else None


def window_rect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def cursor_pos():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def is_minimized(hwnd):
    return bool(user32.IsIconic(hwnd))


def _set_foreground(hwnd):
    """
    他プロセスからの SetForegroundWindow 制限を、前面ウィンドウのスレッドに入力キューを一時的に接続して回避する。
    （以前は Alt キーの注入で回避していたが、他アプリにキー入力が届くため廃止。2026-09-18）
    """
    fg = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(fg_tid, cur_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(fg_tid, cur_tid, False)


def bring_to_front(hwnd, timeout=2.0):
    """Yixin を前面化し、実際に前面になったことを確認する。"""
    if is_minimized(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.3)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        _set_foreground(hwnd)
        time.sleep(0.1)
    return user32.GetForegroundWindow() == hwnd


# ---- 校正値 ----
def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("dpi_aware"):
        # 旧版（DPI 非対応時）の校正値は論理ピクセル。物理ピクセルへ換算して保存し直す
        k = system_dpi_scale()
        for key in ("offset_x", "offset_y", "window_w", "window_h"):
            cfg[key] = int(round(cfg[key] * k))
        cfg["dpi_aware"] = True
        save_config(cfg)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


def calibrate(wait=5):
    win = find_yixin_window()
    if not win:
        raise RuntimeError("Yixin のウィンドウが見つかりません。起動してから実行してください。")
    hwnd, title = win
    print(f"ウィンドウ検出: {title}")
    print(f"{wait} 秒以内に、マウスカーソルを Rapfi のコマンド入力欄（ログ下のテキスト欄）の上に置いてください。")
    for i in range(wait, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    x, y = cursor_pos()
    l, t, r, b = window_rect(hwnd)
    if not (l <= x <= r and t <= y <= b):
        raise RuntimeError("マウスが Yixin のウィンドウ外にあります。やり直してください。")
    cfg = {"offset_x": x - l, "offset_y": y - t, "window_w": r - l, "window_h": b - t, "dpi_aware": True,
           "note": "コマンド入力欄のウィンドウ左上からの相対位置（物理ピクセル）"}
    save_config(cfg)
    print(f"保存しました: {CONFIG_PATH}  相対位置=({cfg['offset_x']}, {cfg['offset_y']})  ウィンドウ={cfg['window_w']}x{cfg['window_h']}")


# ---- 送信 ----
class Sender:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        if not self.cfg:
            raise RuntimeError("校正値がありません。先に `python sender.py --calibrate` を実行してください。")

    def restore_focus(self):
        """send(restore_focus=False) で保留した「前面ウィンドウとカーソル位置の復元」を行う。"""
        prev = getattr(self, "_prev_fg", None)
        cur = getattr(self, "_prev_cursor", None)
        self._prev_fg = None
        self._prev_cursor = None
        win = find_yixin_window()
        if prev and win and prev != win[0] and user32.IsWindow(prev):
            _set_foreground(prev)
        if cur:
            user32.SetCursorPos(*cur)

    def send(self, command, settle=0.15, restore_focus=True):
        """
        コマンド文字列を入力欄に打ち込んで Enter を送る。
        送信できた場合 True。前面化できない・ウィンドウ無し・サイズ変化などの場合は例外。
        restore_focus=True なら、送信後に直前まで前面だったウィンドウを前面に戻す
        （バックグラウンド運用のため。Yixin が前面になるのは送信中の約0.5秒だけ）。
        """
        prev = user32.GetForegroundWindow()
        prev_cursor = cursor_pos()  # 送信後にマウスカーソルを元の位置へ戻す
        win0 = find_yixin_window()
        if win0 and prev == win0[0]:
            # すでに Yixin が前面（連続送信中）なら、最初に保留した復元先を維持する
            prev = getattr(self, "_prev_fg", None)
            prev_cursor = getattr(self, "_prev_cursor", None) or prev_cursor
        if not all(32 <= ord(c) < 127 for c in command):
            raise ValueError(f"送信できない文字を含んでいます: {command!r}")
        win = find_yixin_window()
        if not win:
            raise RuntimeError("Yixin のウィンドウが見つかりません。")
        hwnd, title = win
        if not bring_to_front(hwnd):
            raise RuntimeError("Yixin を前面にできませんでした。")
        l, t, r, b = window_rect(hwnd)
        if (r - l, b - t) != (self.cfg["window_w"], self.cfg["window_h"]):
            raise RuntimeError(f"ウィンドウサイズが校正時と異なります（校正 {self.cfg['window_w']}x{self.cfg['window_h']} / 現在 {r-l}x{b-t}）。--calibrate をやり直してください。")
        x, y = l + self.cfg["offset_x"], t + self.cfg["offset_y"]

        # 入力欄をクリックしてフォーカスを与える
        user32.SetCursorPos(x, y)
        time.sleep(0.05)
        _send_inputs([_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP)])
        time.sleep(settle)
        # 送信直前にもう一度、前面が Yixin であることを確認（他アプリへの誤入力防止）
        if user32.GetForegroundWindow() != hwnd:
            raise RuntimeError("送信直前に前面ウィンドウが Yixin ではなくなりました。送信を中止します。")

        # 入力欄は Enter 後に必ず空になるため、消去用のキー（Ctrl+A / Backspace）は送らない（効果音の原因になり得る）
        inputs = []
        for ch in command:
            inputs += [_char(ch), _char(ch, up=True)]
        inputs += [_key(VK_RETURN), _key(VK_RETURN, up=True)]
        _send_inputs(inputs)
        time.sleep(settle)
        if restore_focus:
            # 注意：Yixin がキー入力を処理し終える前にフォーカスを移すと、入力が別のウィンドウに渡る恐れがある。
            # 連続送信する場合は restore_focus=False で送り、最後に restore_focus() を呼ぶこと。
            time.sleep(0.4)
            if prev and prev != hwnd and user32.IsWindow(prev):
                _set_foreground(prev)
            if prev_cursor:
                user32.SetCursorPos(*prev_cursor)
        else:
            self._prev_fg = prev
            self._prev_cursor = prev_cursor
        return True


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Rapfi コマンド送信部")
    ap.add_argument("--calibrate", action="store_true", help="入力欄の位置を校正して保存する")
    ap.add_argument("--send", metavar="COMMAND", help="コマンドを1つ送る")
    ap.add_argument("--check", action="store_true", help="ウィンドウ検出と校正値を表示する")
    args = ap.parse_args()

    if args.calibrate:
        calibrate()
        return
    win = find_yixin_window()
    print("ウィンドウ:", f"{win[1]} (hwnd={win[0]}) rect={window_rect(win[0])}" if win else "見つかりません")
    print("校正値:", load_config())
    if args.send:
        Sender().send(args.send)
        print(f"送信しました: {args.send}")


if __name__ == "__main__":
    main()
