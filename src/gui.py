"""
RAS（Renju Automatic Search）GUI（tkinter、追加ライブラリ不要）。

・探索時間などの設定を編集して monitor_config.json に保存
・自動探索モードのトグルスイッチ（オンで監視＋自動送信を開始、オフで停止）
・状態・残り時間・候補手の要約・ログを表示
・人が Rapfi を操作した／異常が起きたら自動探索モードは自動でオフになる

見た目は games.html（ダーク基調、アクセント #63e6be、丸いトグル）に合わせている。
"""

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import monitor
import sender
from parse_debuglog import DEFAULT_LOG, truncate_log
from i18n import tr, set_language

# ---- 配色（games.html より） ----
BG = "#1b1f27"
PANEL = "#1f242e"
LINE = "#4a5568"
CELL = "#2f3644"
HOVER = "#3a4356"
TEXT = "#e8eaf0"
MUTED = "#8b91a0"
ACCENT = "#63e6be"
ACCENT_TEXT = "#10201a"
BLUE = "#4dabf7"
RED = "#ff6b6b"
YELLOW = "#ffd43b"
FONT = ("Yu Gothic UI", 10)
FONT_BOLD = ("Yu Gothic UI", 10, "bold")
FONT_TITLE = ("Yu Gothic UI", 13, "bold")
FONT_MONO = ("Consolas", 9)

# 設定項目：(キー, 表示名キー, 説明キー, 表示するモード)  モード: "nbest" / "defend" / None=共通
SETTING_FIELDS = [
    ("a_limit_seconds", "f_a_limit", "d_a_limit", "nbest"),
    ("b_limit_seconds", "f_b_limit", "d_b_limit", "nbest"),
    ("defend_mode_seconds", "f_defend_mode", "d_defend_mode", "defend"),
    ("stable_rounds", "f_stable_rounds", "d_stable_rounds", None),
    ("stable_seconds", "f_stable_seconds", "d_stable_seconds", None),
    ("op_timeout_seconds", "f_op_timeout", "d_op_timeout", None),
    ("nbest", "f_nbest", "d_nbest", "nbest"),
]
MODES = [("nbest", "gui_mode_nbest"), ("defend", "gui_mode_defend")]
LANGS = [("ja", "日本語"), ("en", "English")]


def _mix(c1, c2, t):
    """2色を t (0〜1) で線形補間して "#rrggbb" を返す。"""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


class ToggleSwitch(tk.Canvas):
    """
    games.html のトグルスイッチ（42x24、丸いつまみ、0.15秒のスライド）を Canvas で再現。
    Tk の Canvas はアンチエイリアスがないため、内部で 3 倍の大きさに描いた見た目に近づけるよう
    輪郭を背景に馴染む中間色で 2 重に描いて縁のギザつきを抑えている。
    """

    def __init__(self, master, command=None, **kw):
        self.s = kw.pop("scale", 1.0)
        self.bgc = kw.pop("bg", PANEL)
        super().__init__(master, width=int(44 * self.s), height=int(26 * self.s), bg=self.bgc,
                         highlightthickness=0, cursor="hand2")
        self.command = command
        self.value = False
        self.t = 0.0          # 0=オフ位置, 1=オン位置（アニメーション用）
        self._anim = None
        self.bind("<Button-1>", self._click)
        self._draw()

    def _round_rect(self, x1, y1, x2, y2, r, fill, outline):
        # 角丸長方形（トラック）を多角形で描く
        pts = []
        import math
        steps = 12
        for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
            for i in range(steps + 1):
                a = math.radians(a0 + 90 * i / steps)
                pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
        return self.create_polygon(pts, fill=fill, outline=outline, smooth=True, splinesteps=8)

    def _circle(self, cx, cy, r, fill, edge):
        # 縁を背景との中間色で一回り大きく描き、その上に本体を描くことでギザつきを緩和
        self.create_oval(cx - r - 0.7, cy - r - 0.7, cx + r + 0.7, cy + r + 0.7, fill=edge, outline="")
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")

    def _draw(self):
        self.delete("all")
        k = self.s
        t = self.t
        track = _mix(HOVER, ACCENT, t)
        border = _mix(LINE, ACCENT, t)
        thumb = _mix(TEXT, ACCENT_TEXT, t)
        self._round_rect(1 * k, 1 * k, 43 * k, 25 * k, 12 * k, fill=track, outline=border)
        cx = (13 + 18 * t) * k
        cy = 13 * k
        self._circle(cx, cy, 9 * k, fill=thumb, edge=_mix(track, thumb, 0.5))

    def _click(self, _):
        self.set(not self.value, fire=True)

    def _animate(self, target, step=0):
        # 0.15 秒（6 フレーム × 25ms）で滑らかに移動。イージング（ease-out）
        n = 6
        u = min(1.0, (step + 1) / n)
        eased = 1 - (1 - u) ** 2
        start = self._anim_from
        self.t = start + (target - start) * eased
        self._draw()
        if step + 1 < n:
            self._anim = self.after(25, self._animate, target, step + 1)
        else:
            self._anim = None

    def set(self, value, fire=False):
        self.value = bool(value)
        if self._anim:
            self.after_cancel(self._anim)
        self._anim_from = self.t
        self._animate(1.0 if self.value else 0.0)
        if fire and self.command:
            self.command(self.value)


def enable_dpi_awareness():
    """高DPI環境でぼやけないよう、プロセスを DPI 対応にする（Windows 8.1 以降）。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        enable_dpi_awareness()
        super().__init__()
        try:
            import ctypes
            dpi = ctypes.windll.user32.GetDpiForWindow(self.winfo_id())
            self.tk.call("tk", "scaling", dpi / 72)
            self._scale = dpi / 96
        except Exception:
            self._scale = 1.0
        self.title(tr("app_title"))
        self.configure(bg=BG)
        self.geometry(f"{int(760 * self._scale)}x{int(640 * self._scale)}")
        self.minsize(int(640 * self._scale), int(520 * self._scale))
        try:
            self.iconbitmap(os.path.join(os.path.dirname(DEFAULT_LOG), "icon.ico"))
        except Exception:
            pass

        self.cfg = monitor.load_monitor_config()
        self.log_queue = queue.Queue()
        self.thread = None
        self.stop_event = threading.Event()
        self.mon = None
        self.entries = {}

        self._build()
        self.after(300, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 画面構築 ----------
    def _build(self):
        for w in list(self.winfo_children()):
            w.destroy()
        self.entries = {}
        self.title(tr("app_title"))
        # 上部ナビ：タイトル＋トグル
        nav = tk.Frame(self, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        nav.pack(fill="x")
        tk.Label(nav, text="RAS", bg=PANEL, fg=TEXT, font=FONT_TITLE).pack(side="left", padx=(18, 6), pady=12)
        tk.Label(nav, text="Renju Automatic Search", bg=PANEL, fg=MUTED, font=FONT).pack(side="left", padx=(0, 14))
        self.state_label = tk.Label(nav, text=tr("gui_stopped"), bg=PANEL, fg=MUTED, font=FONT_BOLD)
        self.state_label.pack(side="left", padx=6)
        right = tk.Frame(nav, bg=PANEL)
        right.pack(side="right", padx=18)
        tk.Label(right, text=tr("gui_auto_mode"), bg=PANEL, fg=TEXT, font=FONT).pack(side="left", padx=(0, 10))
        self.toggle = ToggleSwitch(right, command=self._on_toggle, bg=PANEL, scale=self._scale)
        self.toggle.t = 0.0
        self.toggle.pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=16)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        # 左：設定パネル
        settings = tk.LabelFrame(body, text=tr("gui_settings"), bg=BG, fg=MUTED, font=FONT, bd=1, relief="solid",
                                 highlightbackground=LINE, labelanchor="nw")
        settings.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(0, 16))
        # 探索モード切替（games.html の gameNavBtn 風）
        modef = tk.Frame(settings, bg=BG)
        modef.grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4))
        tk.Label(modef, text=tr("gui_mode"), bg=BG, fg=MUTED, font=("Yu Gothic UI", 8)).pack(side="left", padx=(0, 8))
        self.mode = tk.StringVar(value=self.cfg.get("search_mode", "nbest"))
        self.mode_btns = {}
        for key, label_key in MODES:
            b = tk.Button(modef, text=tr(label_key), font=FONT_BOLD, relief="flat", bd=0, cursor="hand2", padx=12, pady=6,
                          highlightthickness=1, highlightbackground=LINE, command=lambda k=key: self._set_mode(k))
            b.pack(side="left", padx=(0, 6))
            self.mode_btns[key] = b
        # 言語切替
        langf = tk.Frame(settings, bg=BG)
        langf.grid(row=99, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 10))
        tk.Label(langf, text=tr("gui_language"), bg=BG, fg=MUTED, font=("Yu Gothic UI", 8)).pack(side="left", padx=(0, 8))
        self.lang_btns = {}
        for key, label in LANGS:
            active = key == self.cfg.get("language", "ja")
            b = tk.Button(langf, text=label, font=FONT, relief="flat", bd=0, cursor="hand2", padx=10, pady=4,
                          bg=ACCENT if active else BG, fg=ACCENT_TEXT if active else TEXT,
                          activebackground=ACCENT if active else HOVER, activeforeground=ACCENT_TEXT if active else TEXT,
                          highlightthickness=1, highlightbackground=LINE, command=lambda k=key: self._set_language(k))
            b.pack(side="left", padx=(0, 6))
            self.lang_btns[key] = b
        self.field_rows = {}
        for i, (key, label_key, desc_key, mode) in enumerate(SETTING_FIELDS):
            r = 1 + i * 2
            label, desc = tr(label_key), tr(desc_key)
            lab = tk.Label(settings, text=label, bg=BG, fg=TEXT, font=FONT, anchor="w")
            lab.grid(row=r, column=0, sticky="w", padx=12, pady=(10, 0))
            var = tk.StringVar(value=str(self.cfg.get(key, "")))
            ent = tk.Entry(settings, textvariable=var, width=10, bg=CELL, fg=TEXT, insertbackground=TEXT,
                           relief="flat", font=FONT, justify="right", highlightthickness=1, highlightbackground=LINE,
                           highlightcolor=ACCENT)
            ent.grid(row=r, column=1, sticky="e", padx=12, pady=(10, 0))
            dl = tk.Label(settings, text=desc, bg=BG, fg=MUTED, font=("Yu Gothic UI", 8), anchor="w",
                          wraplength=int(300 * self._scale), justify="left")
            dl.grid(row=r + 1, column=0, columnspan=2, sticky="w", padx=12)
            self.entries[key] = var
            self.field_rows[key] = (mode, lab, ent, dl)
        self._set_mode(self.mode.get(), init=True)
        btns = tk.Frame(settings, bg=BG)
        btns.grid(row=1 + len(SETTING_FIELDS) * 2, column=0, columnspan=2, sticky="ew", padx=12, pady=14)
        self._button(btns, tr("gui_save"), self._save_settings, primary=True).pack(side="left")
        self._button(btns, tr("gui_calibrate"), self._calibrate).pack(side="left", padx=8)
        self._button(btns, tr("gui_truncate"), self._truncate).pack(side="left")

        # 右上：状態パネル
        status = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        status.grid(row=0, column=1, sticky="ew", pady=(0, 12))
        self.status_vars = {}
        for i, (key, label_key) in enumerate([("state", "gui_state"), ("remain", "gui_remain"), ("moves", "gui_moves"),
                                              ("cands", "gui_cands"), ("last", "gui_last")]):
            tk.Label(status, text=tr(label_key), bg=PANEL, fg=MUTED, font=FONT, width=13, anchor="w").grid(row=i, column=0, sticky="w", padx=(14, 6), pady=3)
            var = tk.StringVar(value="-")
            tk.Label(status, textvariable=var, bg=PANEL, fg=TEXT, font=FONT_BOLD, anchor="w").grid(row=i, column=1, sticky="w", padx=6, pady=3)
            self.status_vars[key] = var

        # 右下：ログ
        logf = tk.Frame(body, bg=BG)
        logf.grid(row=1, column=1, sticky="nsew")
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        self.log_text = tk.Text(logf, bg=CELL, fg=TEXT, font=FONT_MONO, relief="flat", wrap="none",
                                highlightthickness=1, highlightbackground=LINE, state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(logf, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.tag_configure("branch", foreground=ACCENT)
        self.log_text.tag_configure("send", foreground=BLUE)
        self.log_text.tag_configure("error", foreground=RED)
        self.log_text.tag_configure("warn", foreground=YELLOW)
        self.log_text.tag_configure("muted", foreground=MUTED)

    def _button(self, master, text, command, primary=False):
        b = tk.Button(master, text=text, command=command, font=FONT_BOLD, relief="flat", cursor="hand2",
                      bg=ACCENT if primary else PANEL, fg=ACCENT_TEXT if primary else TEXT,
                      activebackground=ACCENT if primary else HOVER, activeforeground=ACCENT_TEXT if primary else TEXT,
                      highlightbackground=LINE, highlightthickness=1, padx=12, pady=6, bd=0)
        return b

    # ---------- 設定 ----------
    def _set_language(self, key):
        if getattr(self, "toggle", None) and self.toggle.value:
            messagebox.showinfo(tr("gui_language"), tr("gui_mode_locked"))
            return
        if key == self.cfg.get("language", "ja"):
            return
        try:
            self.cfg = self._read_settings()
        except ValueError:
            pass
        self.cfg["language"] = key
        set_language(key)
        self._write_config(self.cfg)
        self._build()  # 画面を作り直して文言を反映

    def _set_mode(self, key, init=False):
        if not init and getattr(self, "toggle", None) and self.toggle.value:
            messagebox.showinfo(tr("gui_mode"), tr("gui_mode_locked"))
            return
        self.mode.set(key)
        for k, b in self.mode_btns.items():
            active = k == key
            b.configure(bg=ACCENT if active else BG, fg=ACCENT_TEXT if active else TEXT,
                        activebackground=ACCENT if active else HOVER, activeforeground=ACCENT_TEXT if active else TEXT)
        for fkey, (mode, lab, ent, dl) in self.field_rows.items():
            show = mode is None or mode == key
            for w in (lab, ent, dl):
                if show:
                    w.grid()
                else:
                    w.grid_remove()

    def _read_settings(self):
        cfg = dict(self.cfg)
        cfg["search_mode"] = self.mode.get()
        for key, label_key, _, mode in SETTING_FIELDS:
            if mode is not None and mode != cfg["search_mode"]:
                continue
            label = tr(label_key)
            raw = self.entries[key].get().strip()
            try:
                v = float(raw)
                if key in ("stable_rounds", "nbest"):
                    v = int(v)
                if v <= 0:
                    raise ValueError
            except ValueError:
                raise ValueError(tr("gui_err_value", label=label, raw=raw))
            cfg[key] = v
        return cfg

    def _write_config(self, cfg):
        # 説明文（_ で始まるキー）は元ファイルのものを残す
        data = {}
        if os.path.exists(monitor.CONFIG_PATH):
            with open(monitor.CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        data.update({k: v for k, v in cfg.items()})
        with open(monitor.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def _save_settings(self):
        try:
            cfg = self._read_settings()
        except ValueError as e:
            messagebox.showerror(tr("gui_err_setting"), str(e))
            return
        self.cfg = cfg
        self._write_config(cfg)
        self._append(tr("gui_saved", path=monitor.CONFIG_PATH), "muted")

    # ---------- 自動探索の開始／停止 ----------
    def _on_toggle(self, on):
        if on:
            self._start()
        else:
            self._stop(tr("gui_manual_off"))

    def _start(self):
        try:
            self.cfg = self._read_settings()
        except ValueError as e:
            messagebox.showerror(tr("gui_err_setting"), str(e))
            self.toggle.set(False)
            return
        self._write_config(self.cfg)
        if not os.path.exists(DEFAULT_LOG):
            messagebox.showerror(tr("gui_err_nolog"), tr("gui_err_nolog_msg", path=DEFAULT_LOG))
            self.toggle.set(False)
            return
        try:
            snd = sender.Sender()
        except Exception as e:
            messagebox.showerror(tr("gui_err_sender"), tr("gui_err_sender_msg", err=e))
            self.toggle.set(False)
            return
        if not sender.find_yixin_window():
            messagebox.showerror(tr("gui_err_noyixin"), tr("gui_err_noyixin_msg"))
            self.toggle.set(False)
            return
        # ログが大きいと読み取りが遅れるため、100MB を超えていれば自動で切り詰める（Yixin 起動中でも安全）
        try:
            size = os.path.getsize(DEFAULT_LOG)
            if size > 100 * 1024 * 1024:
                truncate_log(DEFAULT_LOG)
                self._append(tr("gui_log_truncated", mb=size / 1e6), "muted")
        except Exception as e:
            self._append(tr("gui_log_truncate_fail", err=e), "warn")
        record = os.path.join(os.path.dirname(DEFAULT_LOG), "output", "monitor_log.jsonl")
        os.makedirs(os.path.dirname(record), exist_ok=True)
        self.stop_event = threading.Event()
        self.mon = monitor.Monitor(self.cfg, record, sender=snd, on_log=self._on_log, on_pause=self._on_pause)
        initial = monitor.detect_initial_state(DEFAULT_LOG)
        self.thread = threading.Thread(target=self._run_thread, args=(initial,), daemon=True)
        self.thread.start()
        self.state_label.configure(text=tr("gui_on"), fg=ACCENT)

    def _run_thread(self, initial):
        try:
            monitor.run(DEFAULT_LOG, self.mon, stop_event=self.stop_event, initial_state=initial)
        except Exception as e:
            self.log_queue.put((tr("gui_thread_error", err=e), "error", None))
        finally:
            self.log_queue.put((tr("gui_thread_end"), "muted", None))

    def _stop(self, reason):
        self.stop_event.set()
        self.state_label.configure(text=tr("gui_stopped"), fg=MUTED)
        if self.mon:
            self._append(tr("gui_off", reason=reason), "warn")

    def _on_log(self, text, rec):
        kind = rec.get("kind", "")
        tag = None
        K = lambda *keys: {tr(k) for k in keys}
        if kind in K("kind_all_lost", "kind_best_move", "kind_win_found", "kind_timeout", "kind_forced", "kind_four", "kind_autostart"):
            tag = "branch"
        elif kind in K("kind_send", "kind_confirmed", "kind_resend", "kind_flush"):
            tag = "send"
        elif kind in K("kind_pause", "kind_warning"):
            tag = "error"
        elif kind in K("kind_status", "kind_position", "kind_command", "kind_stable"):
            tag = "muted"
        self.log_queue.put((text, tag, rec))

    def _on_pause(self, reason):
        # 監視スレッドから呼ばれる。GUI 操作はメインスレッドで行う
        self.log_queue.put((None, "pause", reason))

    # ---------- 定期更新 ----------
    def _poll(self):
        try:
            while True:
                text, tag, extra = self.log_queue.get_nowait()
                if tag == "pause":
                    self.toggle.set(False)
                    self._stop(extra)
                    continue
                self._append(text, tag)
        except queue.Empty:
            pass
        self._update_status()
        self.after(300, self._poll)

    def _update_status(self):
        m = self.mon
        if not m or self.stop_event.is_set():
            self.status_vars["state"].set(tr("gui_stopped"))
            self.status_vars["remain"].set("-")
            return
        if m.state in ("A_MONITOR", "B_MONITOR"):
            cmd = "searchdefend" if m.state == "A_MONITOR" else "nbest"
            name = f"{m.side_name()} ({cmd})"
        else:
            name = {"WAIT_START": tr("gui_state_wait"), "OPERATING": tr("gui_state_op"), "PAUSED": tr("gui_state_paused")}.get(m.state, m.state)
        self.status_vars["state"].set(name)
        if m.state == "A_MONITOR":
            self.status_vars["remain"].set(f"{max(0, m.a_limit - m.elapsed()):.0f} s")
        elif m.state == "B_MONITOR":
            self.status_vars["remain"].set(f"{max(0, m.b_limit - m.elapsed()):.0f} s")
        else:
            self.status_vars["remain"].set("-")
        self.status_vars["moves"].set(f"{len(m.moves)}  {' '.join(m.moves[-6:])}")
        self.status_vars["cands"].set(m.summary_text())
        if m.pending and m.pending.get("steps"):
            self.status_vars["last"].set(f"{m.pending['title']}: {m.pending['steps'][0][0][:40]}")

    def _append(self, text, tag=None):
        if text is None:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag)
        # 行数を抑える
        if int(self.log_text.index("end-1c").split(".")[0]) > 2000:
            self.log_text.delete("1.0", "500.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ---------- 補助操作 ----------
    def _calibrate(self):
        if self.toggle.value:
            messagebox.showinfo(tr("gui_calib_title"), tr("gui_calib_locked"))
            return
        if not sender.find_yixin_window():
            messagebox.showerror(tr("gui_err_noyixin"), tr("gui_err_noyixin_msg"))
            return
        messagebox.showinfo(tr("gui_calib_title"), tr("gui_calib_msg"))

        def worker():
            try:
                for i in range(5, 0, -1):
                    self.log_queue.put((tr("gui_calib_count", i=i), "muted", None))
                    time.sleep(1)
                x, y = sender.cursor_pos()
                hwnd, _ = sender.find_yixin_window()
                l, t, r, b = sender.window_rect(hwnd)
                if not (l <= x <= r and t <= y <= b):
                    raise RuntimeError(tr("gui_calib_outside"))
                sender.save_config({"offset_x": x - l, "offset_y": y - t, "window_w": r - l, "window_h": b - t,
                                    "dpi_aware": True, "note": "コマンド入力欄のウィンドウ左上からの相対位置（物理ピクセル）"})
                self.log_queue.put((tr("gui_calib_saved", x=x - l, y=y - t, w=r - l, h=b - t), "branch", None))
            except Exception as e:
                self.log_queue.put((tr("gui_calib_fail", err=e), "error", None))
        threading.Thread(target=worker, daemon=True).start()

    def _truncate(self):
        if self.toggle.value:
            messagebox.showinfo(tr("gui_truncate"), tr("gui_trunc_locked"))
            return
        try:
            size = os.path.getsize(DEFAULT_LOG)
            truncate_log(DEFAULT_LOG)
            self._append(tr("gui_trunc_done", mb=size / 1e6), "muted")
        except Exception as e:
            messagebox.showerror(tr("gui_trunc_fail"), str(e))

    def _on_close(self):
        self.stop_event.set()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
