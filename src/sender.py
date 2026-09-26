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
gdi32 = ctypes.windll.gdi32

def enable_dpi_awareness():
    """
    座標を常に物理ピクセルで扱うため、プロセスを「モニタ単位」の DPI 対応にする。
    「システム単位」（旧実装）だと、異なる拡大率のモニタに置かれたウィンドウの座標が
    実際の画面位置とずれ、クリックが別の場所に飛ぶ（2026-09-26 に多モニタ環境で確認）。
    """
    try:  # Windows 10 1703 以降：モニタ単位 v2
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    for level in (2, 1):  # 2 = モニタ単位, 1 = システム単位
        try:
            if ctypes.windll.shcore.SetProcessDpiAwareness(level) == 0:
                return
        except Exception:
            pass


enable_dpi_awareness()


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


# ---- ウィンドウの画像取得とコマンド入力欄の自動検出 ----
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def capture_window(hwnd):
    """
    Yixin のウィンドウ領域を画面から取り込み、(画素バイト列, 幅, 高さ) を返す。
    画素は 32bit（BGRA）で、(x, y) の色は buf[(y*W+x)*4 + 2/1/0] が R/G/B。
    ウィンドウが他のウィンドウに隠れていると別の内容が写るため、前面化してから呼ぶこと。
    """
    l, t, r, b = window_rect(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None, 0, 0
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    try:
        gdi32.SelectObject(mem, bmp)
        gdi32.BitBlt(mem, 0, 0, w, h, hdc, l, t, 0x00CC0020)  # SRCCOPY
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = w
        info.bmiHeader.biHeight = -h  # 上から下へ
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        buf = (ctypes.c_ubyte * (w * h * 4))()
        if not gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0):
            return None, 0, 0
        return buf, w, h
    finally:
        user32.ReleaseDC(0, hdc)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)


def find_input_box(buf, w, h):
    """
    ウィンドウ画像からコマンド入力欄（ログ欄の下のテキスト欄）の矩形を探し、
    (左, 上, 右, 下) をウィンドウ相対座標で返す。見つからなければ None。

    入力欄は「ウィンドウの右下にあり、周囲のパネルとは異なる一様な色で塗られた横長の矩形」である。
    色そのものはテーマ（ダーク／ライト）で変わるため、色を決め打ちせず
    「右端近くの列を下から上へたどり、色が変わる境目」で矩形を切り出す。
    """
    if not buf or w < 200 or h < 200:
        return None

    def rgb(x, y):
        i = (y * w + x) * 4
        return buf[i + 2], buf[i + 1], buf[i]

    def same(c1, c2, tol=3):
        # ログ欄と入力欄は同じ塗り色で、間の区切り（数 px）だけがわずかに明るい。
        # 許容差を大きくするとこの区切りを跨いで両者がつながってしまうため、小さく取る。
        return abs(c1[0] - c2[0]) <= tol and abs(c1[1] - c2[1]) <= tol and abs(c1[2] - c2[2]) <= tol

    col = w - 20  # 右端の枠を避けた列
    y = h - 10    # 下端の枠を避けた位置から上へ
    runs = []     # (下端y, 上端y, 色) を下から順に
    while y > h // 2 and len(runs) < 6:
        c = rgb(col, y)
        y2 = y
        while y2 > 0 and same(rgb(col, y2 - 1), c):
            y2 -= 1
        if y - y2 >= 3:
            runs.append((y, y2, c))
        y = y2 - 1

    for bottom, top, color in runs:
        height = bottom - top + 1
        if not (20 <= height <= max(60, h // 3)):
            continue
        # 文字の無い行で横幅を測る（中央付近は入力文字やプレースホルダで途切れるため下寄りを見る）
        mid = bottom - max(3, height // 6)
        # 同じ色が横にどこまで続くか（左へ）を見て、横長の矩形であることを確かめる
        left = col
        while left > 0 and same(rgb(left - 1, mid), color):
            left -= 1
        right = col
        while right < w - 1 and same(rgb(right + 1, mid), color):
            right += 1
        # 入力欄はウィンドウの右端に沿って置かれる。右端から離れた矩形は別の部品とみなす
        if right - left >= 150 and right >= w - 60:
            return left, top, right, bottom
    return None


def input_box_center(hwnd):
    """入力欄を自動検出し、クリックすべき画面座標 (x, y) を返す。検出できなければ None。"""
    buf, w, h = capture_window(hwnd)
    box = find_input_box(buf, w, h)
    if not box:
        return None
    l, t, _, _ = window_rect(hwnd)
    bl, bt, br, bb = box
    return l + (bl + br) // 2, t + (bt + bb) // 2


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
    cfg = {"offset_x": x - l, "offset_y": y - t, "offset_right": r - x, "offset_bottom": b - y,
           "window_w": r - l, "window_h": b - t, "dpi_aware": True,
           "note": "コマンド入力欄の位置（物理ピクセル）。offset_right/offset_bottom はウィンドウ右下からの距離"}
    save_config(cfg)
    print(f"保存しました: {CONFIG_PATH}  相対位置=({cfg['offset_x']}, {cfg['offset_y']})  ウィンドウ={cfg['window_w']}x{cfg['window_h']}")


# ---- 送信 ----
class Sender:
    def __init__(self, cfg=None, require_config=False):
        self.cfg = cfg or load_config()
        self._box_rect = None
        self._box_point = None
        if not self.cfg and require_config and not find_yixin_window():
            raise RuntimeError("Yixin が見つからず、校正値もありません。Yixin を起動してください。")

    def input_point(self, hwnd):
        """
        入力欄をクリックする画面座標を返す。
        まずウィンドウ画像から自動検出し（ウィンドウを動かしてもサイズを変えても追従する）、
        検出できない場合は校正値をウィンドウ右下からの距離として当てはめる。
        検出結果はウィンドウの位置・サイズが変わるまで使い回す。
        """
        rect = window_rect(hwnd)
        l, t, r, b = rect
        if getattr(self, "_box_rect", None) == rect and getattr(self, "_box_point", None):
            return self._box_point
        pt = input_box_center(hwnd)
        if pt:
            self._box_rect, self._box_point = rect, pt
            return pt
        cfg = self.cfg
        if cfg is None:
            raise RuntimeError("入力欄を自動検出できず、校正値もありません。GUI の「入力欄を校正」を実行してください。")
        # 入力欄はウィンドウの右下に固定されているため、右下からの距離を優先して当てはめる
        if "offset_right" in cfg and "offset_bottom" in cfg:
            x, y = r - cfg["offset_right"], b - cfg["offset_bottom"]
        else:
            x, y = l + cfg["offset_x"], t + cfg["offset_y"]
        x = min(max(x, l + 5), r - 5)
        y = min(max(y, t + 5), b - 5)
        return x, y

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
        x, y = self.input_point(hwnd)

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
    if win:
        bring_to_front(win[0])
        time.sleep(0.4)
        buf, w, h = capture_window(win[0])
        box = find_input_box(buf, w, h)
        print("入力欄の自動検出:", f"{box}（ウィンドウ相対）" if box else "検出できませんでした")
    if args.send:
        Sender().send(args.send)
        print(f"送信しました: {args.send}")


if __name__ == "__main__":
    main()
