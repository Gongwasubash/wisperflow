"""WhisperFlow Desktop — Ctrl+Shift+D to open dictation bar."""

import json
import io
import os
import sys
import threading
import time
import wave
import argparse
from pathlib import Path as P

import unicodedata
import numpy as np
import sounddevice as sd
import requests
import pyautogui
import pyperclip
import keyboard
import pystray
from PIL import Image, ImageDraw
import tkinter as tk
from tkinter import font as tkfont
from npttf2utf.base.preetimapper import convert as unicode_to_preeti
from nepali_ime import roman_to_devanagari, get_suggestions, to_nepali_digits

CONFIG_DIR = P(os.environ.get("APPDATA", ".")) / "WhisperFlow"
CONFIG_PATH = CONFIG_DIR / "config.json"
BAR_HEIGHT = 52
EXPANDED_HEIGHT = 220
SAMPLE_RATE = 16000

config = {"api_key": "", "grammar_fix": True}
recording = False
audio_buffer = []
tray_icon = None
bar = None
bar_root = None


def load_config():
    global config
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_PATH.exists():
            config.update(json.loads(CONFIG_PATH.read_text("utf-8")))
    except Exception:
        pass
    if not config.get("api_key"):
        script_dir = P(__file__).parent.resolve()
        for candidate in (script_dir / "groq.key", script_dir.parent / "groq.key", P("groq.key")):
            if candidate.exists():
                try:
                    text = candidate.read_text("utf-8").strip()
                    for prefix in ("GROQ_API_KEY=", "export GROQ_API_KEY="):
                        if text.startswith(prefix):
                            text = text[len(prefix):]
                    text = text.strip().strip('"').strip("'")
                    if text.startswith("gsk_"):
                        config["api_key"] = text
                        save_config()
                except Exception:
                    pass


def save_config():
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2), "utf-8")
    except Exception:
        pass


def create_icon_image(recording=False):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bg = (255, 60, 60) if recording else (14, 206, 206)
    draw.ellipse([4, 4, size - 4, size - 4], fill=bg)
    if recording:
        sq = size // 4
        cx = size // 2 - sq // 2
        cy = size // 2 - sq // 2
        draw.rectangle([cx, cy, cx + sq, cy + sq], fill=(0, 0, 0, 180))
    else:
        tri = size // 5
        cx = size // 2
        cy = size // 2
        pts = [(cx, cy - tri), (cx - tri, cy + 2), (cx + tri, cy + 2)]
        draw.polygon(pts, fill=(0, 0, 0, 200))
    return img


def notify(title, message):
    if tray_icon:
        try:
            tray_icon.notify(message, title)
        except Exception:
            pass


def retry_request(fn, retries=3, delay=2):
    last_err = None
    for attempt in range(retries):
        try:
            return fn()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay * (2 ** attempt))
        except Exception:
            raise
    raise Exception(f"Connection failed after {retries} retries: {last_err}")


def transcribe_audio(wav_bytes, language=""):
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    data = {"model": "whisper-large-v3"}
    if language:
        data["language"] = language

    def do_request():
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        if not resp.ok:
            try:
                err = resp.json()
                msg = err.get("error", {}).get("message", f"STT failed: {resp.status_code}")
            except Exception:
                msg = f"STT failed: {resp.status_code}"
            raise Exception(msg)
        return resp.json()["text"].strip()

    text = retry_request(do_request)
    return text, language or ""


def fix_grammar(text, detected_lang=""):
    if not config.get("grammar_fix", True) or not text:
        return text
    lang_hint = f" The detected language is {detected_lang.upper()}." if detected_lang else ""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a grammar and spelling correction assistant. "
                    "Fix spelling, grammar, and punctuation errors. "
                    "Support English, Nepali (नेपाली), and Hindi (हिन्दी). "
                    "Detect the input language and correct it properly in that language. "
                    "Preserve original meaning and script (Devanagari for Nepali/Hindi). "
                    "Output only the corrected text, nothing else."
                    + lang_hint
                )
            },
            {"role": "user", "content": text}
        ]
    }

    def do_request():
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if not resp.ok:
            err = resp.json()
            raise Exception(err.get("error", {}).get("message", f"Grammar fix failed: {resp.status_code}"))
        return resp.json()["choices"][0]["message"]["content"].strip()

    return retry_request(do_request)


def save_wav_bytes(audio_data):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_data.tobytes())
    return buf.getvalue()
class DictationBar:
    LANG_FLAGS = {"en": "EN", "ne": "NP", "hi": "HI", "es": "ES", "fr": "FR",
                  "de": "DE", "ja": "JA", "ko": "KO", "zh": "ZH", "ru": "RU"}

    def __init__(self, root):
        self.root = root
        self.recording = False
        self.audio_buffer = []
        self.recording_thread = None
        self.accumulated_text = ""
        self.current_text = ""
        self.detected_lang = ""
        self.update_timer_id = None
        self.rec_start_time = 0
        self.auto_type_on_done = False
        self.selected_lang = None
        self.lang_chips = {}
        self.unicode_text = ""
        self.preeti_mode = config.get("preeti_mode", False)
        self.num_mode = config.get("num_mode", False)
        self.ime_mode = False
        self.ime_current_roman = ""
        self.ime_suggestions = []
        self.ime_input = None
        self.suggestion_labels = []
        self.ime_frame = None
        self.suggestion_frame = None
        self.ime_preview = None

        root.title("WhisperFlow")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg="#141414")
        try:
            root.wm_attributes("-alpha", 0.95)
        except Exception:
            pass

        self.BG = "#141414"
        self.BG2 = "#1A1A1A"
        self.FG = "#E8E8E8"
        self.FG2 = "#888888"
        self.ACCENT = "#0ECECE"
        self.BORDER = "#222222"
        self.RED = "#FF4444"

        screen_w = root.winfo_screenwidth()
        bar_w = min(620, screen_w - 40)
        x = (screen_w - bar_w) // 2
        root.geometry(f"{bar_w}x{BAR_HEIGHT}+{x}+0")
        root.resizable(True, False)

        self.display_font_name = config.get("display_font", "Segoe UI")
        self.typing_mode = config.get("typing_mode", "paste")
        self.base_font = tkfont.Font(family=self.display_font_name, size=10)
        self.mono_font = tkfont.Font(family=self.display_font_name, size=11)

        self.build_ui()
        self.setup_drag()

        root.bind("<Map>", lambda e: self.on_show())
        root.protocol("WM_DELETE_WINDOW", self.close)

    def build_ui(self):
        main_frame = tk.Frame(self.root, bg=self.BG)
        main_frame.pack(fill="both", expand=True)
        main_frame.bind("<Button-1>", self.start_drag)

        row = tk.Frame(main_frame, bg=self.BG)
        row.pack(fill="x", padx=10, pady=(0, 0))
        row.bind("<Button-1>", self.start_drag)

        self.dot = tk.Canvas(row, width=10, height=10, bg=self.BG, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 6))
        self.dot.bind("<Button-1>", self.start_drag)
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=self.FG2, outline="")

        title = tk.Label(row, text="WhisperFlow", fg=self.FG2, bg=self.BG,
                         font=("Segoe UI", 9, "bold"))
        title.pack(side="left", padx=(0, 6))
        title.bind("<Button-1>", self.start_drag)

        lang_frame = tk.Frame(row, bg=self.BG)
        lang_frame.pack(side="left", padx=(0, 8))
        for code, label in [("en", "EN"), ("ne", "NP"), ("hi", "HI")]:
            chip = tk.Button(lang_frame, text=label,
                             command=lambda c=code: self.select_language(c),
                             bg=self.BG2, fg=self.FG2,
                             activebackground=self.BG2, activeforeground=self.ACCENT,
                             bd=0, padx=6, pady=1,
                             font=("Segoe UI", 8, "bold"), cursor="hand2",
                             highlightthickness=0)
            chip.pack(side="left", padx=1)
            self.lang_chips[code] = chip

        self.preview = tk.Label(row, text="", fg=self.FG2, bg=self.BG,
                                font=self.base_font, anchor="w", justify="left")
        self.preview.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_frame = tk.Frame(row, bg=self.BG)
        btn_frame.pack(side="right")

        self.record_btn = self._btn(btn_frame, "\u25a0 Stop", self.toggle_record)
        self.record_btn.pack(side="left", padx=1)

        self.type_btn = self._btn(btn_frame, "\u2328 Type", self.type_text)
        self.type_btn.pack(side="left", padx=1)

        self.test_btn = self._btn(btn_frame, "\u2713 Test", self.test_dictation)
        self.test_btn.pack(side="left", padx=1)

        self.clear_btn = self._btn(btn_frame, "\u21b6 Clear", self.clear_text)
        self.clear_btn.pack(side="left", padx=1)

        close_btn = self._btn(btn_frame, "\u00d7", self.close, w=26)
        close_btn.pack(side="left", padx=(4, 0))

        self.expand_frame = tk.Frame(main_frame, bg=self.BG)
        self.text_box = tk.Text(self.expand_frame, bg=self.BG2, fg=self.FG,
                                insertbackground=self.FG, font=self.mono_font,
                                relief="flat", bd=0, height=5, wrap="word",
                                state="disabled")
        self.text_box.pack(fill="both", expand=True, padx=0, pady=(6, 0))

        self.options_row = tk.Frame(self.expand_frame, bg=self.BG)
        tk.Label(self.options_row, text="Font:", fg=self.FG2, bg=self.BG,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 3))
        self.font_var = tk.StringVar(value=self.display_font_name)
        self.font_btn = tk.Menubutton(self.options_row,
                                       textvariable=self.font_var,
                                       bg=self.BG2, fg=self.FG,
                                       activebackground="#2A2A2A",
                                       activeforeground=self.FG,
                                       bd=0, padx=5, pady=0,
                                       font=("Segoe UI", 8),
                                       cursor="hand2",
                                       highlightthickness=0,
                                       relief="flat")
        font_menu = tk.Menu(self.font_btn, tearoff=0,
                            bg="#2A2A2A", fg=self.FG,
                            activebackground="#3A3A3A",
                            activeforeground=self.FG,
                            font=("Segoe UI", 9),
                            bd=1)
        available = set(tkfont.families())
        for fn in ["Segoe UI", "Consolas", "Mangal", "Nirmala UI",
                    "Arial", "Calibri", "Tahoma", "Courier New",
                    "Microsoft Sans Serif", "Times New Roman",
                    "MS Gothic", "Noto Sans Devanagari"]:
            if fn in available:
                font_menu.add_radiobutton(label=fn, variable=self.font_var,
                                           command=self.on_font_change)
        self.font_btn.config(menu=font_menu)
        self.font_btn.pack(side="left", padx=(0, 12))
        tk.Label(self.options_row, text="Mode:", fg=self.FG2, bg=self.BG,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 3))
        self.mode_var = tk.StringVar(value=self.typing_mode)
        self.mode_btn = tk.Button(self.options_row,
                                  textvariable=self.mode_var,
                                  command=self.toggle_mode,
                                  bg=self.BG2, fg=self.FG,
                                  activebackground="#2A2A2A",
                                  activeforeground=self.FG,
                                  bd=0, padx=6, pady=0,
                                  font=("Segoe UI", 8),
                                  cursor="hand2",
                                  highlightthickness=0)
        self.mode_btn.pack(side="left")
        self.preeti_btn = tk.Button(self.options_row,
                                    text="NP-Preeti: OFF",
                                    command=self.toggle_preeti,
                                    bg=self.BG2, fg=self.FG2,
                                    activebackground="#2A2A2A",
                                    activeforeground=self.FG,
                                    bd=0, padx=6, pady=0,
                                    font=("Segoe UI", 8),
                                    cursor="hand2",
                                    highlightthickness=0)
        self.preeti_btn.pack(side="left", padx=(12, 0))
        self.update_preeti_btn()
        self.num_btn = tk.Button(self.options_row,
                                 text="NP-Num: OFF",
                                 command=self.toggle_num_mode,
                                 bg=self.BG2, fg=self.FG2,
                                 activebackground="#2A2A2A",
                                 activeforeground=self.FG,
                                 bd=0, padx=6, pady=0,
                                 font=("Segoe UI", 8),
                                 cursor="hand2",
                                 highlightthickness=0)
        self.num_btn.pack(side="left", padx=(6, 0))
        self.update_num_btn()
        self.sym_btn = tk.Button(self.options_row,
                                 text="NP-Sym: OFF",
                                 command=self.toggle_sym_mode,
                                 bg=self.BG2, fg=self.FG2,
                                 activebackground="#2A2A2A",
                                 activeforeground=self.FG,
                                 bd=0, padx=6, pady=0,
                                 font=("Segoe UI", 8),
                                 cursor="hand2",
                                 highlightthickness=0)
        self.sym_btn.pack(side="left", padx=(6, 0))
        self.sym_packed = False
        self.update_sym_btn()
        self.options_row.pack(fill="x", pady=(2, 4))

        # IME mode components (hidden by default)
        self.ime_frame = tk.Frame(main_frame, bg=self.BG)

        ime_top = tk.Frame(self.ime_frame, bg=self.BG)
        ime_top.pack(fill="x", padx=0, pady=(4, 0))

        self.ime_input = tk.Entry(
            ime_top, bg="#0C0C0C", fg=self.FG,
            insertbackground=self.FG, font=self.mono_font,
            relief="flat", bd=1, highlightthickness=0,
        )
        self.ime_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.ime_input.bind("<KeyRelease>", self._on_ime_key)
        self.ime_input.bind("<KeyPress>", self._on_ime_keypress)
        self.ime_input.bind("<Control-Return>", lambda e: self._ime_type_all())

        self.ime_preview = tk.Label(
            ime_top, text="", fg=self.ACCENT, bg=self.BG,
            font=self.mono_font, anchor="w", width=20,
        )
        self.ime_preview.pack(side="right")

        self.suggestion_frame = tk.Frame(self.ime_frame, bg=self.BG, height=0)
        self.suggestion_cells = []
        for i in range(4):
            sep = tk.Frame(self.suggestion_frame, bg=self.BG, width=4, height=0)
            sep.pack(side="left")
            cell = tk.Frame(self.suggestion_frame, bg=self.BG2, bd=0, highlightthickness=0)
            num_lbl = tk.Label(
                cell, text="", fg=self.ACCENT, bg=self.BG2,
                font=("Segoe UI", 8, "bold"), width=2, anchor="e",
            )
            num_lbl.pack(side="left", padx=(4, 1))

            lbl = tk.Label(
                cell, text="", fg=self.FG2, bg=self.BG2,
                font=("Segoe UI", 9), cursor="hand2",
            )
            lbl.pack(side="left", padx=(0, 4))
            lbl.bind("<Button-1>", lambda e, idx=i: self._ime_select(idx))
            cell.bind("<Button-1>", lambda e, idx=i: self._ime_select(idx))

            cell.pack(side="left", fill="x", expand=True)
            self.suggestion_cells.append((num_lbl, lbl, cell))

        self.suggestion_frame.pack(fill="x", padx=0, pady=0)

        SYM_ROWS = [
            ['।', '॥', 'ऽ', 'ॐ', '॰', '₹', '\u0902', '\u0901', '\u0903'],
            ['\u0951', '\u0952', 'ॽ', 'ॱ', 'ꣳ', '†', '‡', '•', '…'],
            ['@', '#', '%', '&', '*', '+', '-', '×', '÷', '='],
            ['(', ')', '{', '}', '[', ']', '"', "'", ':', ';'],
            ['!', '?', '<', '>', '±', '~', '|', '✓', '©', '®'],
        ]
        self.sym_outer = tk.Frame(self.ime_frame, bg=self.BG)
        self.sym_canvas = tk.Canvas(self.sym_outer, bg=self.BG,
                                    highlightthickness=0, bd=0,
                                    height=95)
        self.sym_scrollbar = tk.Scrollbar(self.sym_outer, orient="vertical",
                                           command=self.sym_canvas.yview)
        self.sym_canvas.configure(yscrollcommand=self.sym_scrollbar.set)
        self.sym_canvas.pack(side="left", fill="x", expand=True)
        self.sym_scrollbar.pack(side="right", fill="y")
        self.sym_frame = tk.Frame(self.sym_canvas, bg=self.BG)
        self.sym_canvas.create_window((0, 0), window=self.sym_frame, anchor="nw")
        self.sym_buttons = []
        for row_syms in SYM_ROWS:
            row_f = tk.Frame(self.sym_frame, bg=self.BG)
            row_f.pack(fill="x")
            for sym in row_syms:
                btn = tk.Button(row_f, text=sym,
                                command=lambda s=sym: self._ime_insert_symbol(s),
                                bg=self.BG2, fg=self.FG,
                                activebackground="#2A2A2A",
                                activeforeground=self.ACCENT,
                                bd=0, padx=6, pady=0,
                                font=("Segoe UI", 10),
                                cursor="hand2",
                                highlightthickness=0)
                btn.pack(side="left", padx=1, pady=1)
                self.sym_buttons.append(btn)
        self.sym_frame.bind("<Configure>",
                            lambda e: self.sym_canvas.configure(
                                scrollregion=self.sym_canvas.bbox("all")))
        self._bind_mousewheel(self.sym_canvas)

        self.is_expanded = False

    def _btn(self, parent, text, cmd, w=None):
        btn = tk.Button(parent, text=text, command=cmd,
                        bg=self.BG2, fg=self.FG, activebackground="#2A2A2A",
                        activeforeground=self.FG, bd=0, padx=8, pady=2,
                        font=self.base_font, cursor="hand2", highlightthickness=0)
        if w:
            btn.config(width=0, padx=4)
        return btn

    def setup_drag(self):
        self.drag_data = {"x": 0, "y": 0, "dragging": False}

    def start_drag(self, event):
        self.drag_data["x"] = event.x_root
        self.drag_data["y"] = event.y_root
        self.drag_data["dragging"] = True

    def on_drag(self, event):
        if self.drag_data["dragging"]:
            dx = event.x_root - self.drag_data["x"]
            dy = event.y_root - self.drag_data["y"]
            x = self.root.winfo_x() + dx
            y = max(0, self.root.winfo_y() + dy)
            self.root.geometry(f"+{int(x)}+{int(y)}")
            self.drag_data["x"] = event.x_root
            self.drag_data["y"] = event.y_root

    def on_release(self, event):
        self.drag_data["dragging"] = False

    def on_show(self):
        self.root.bind("<B1-Motion>", self.on_drag)
        self.root.bind("<ButtonRelease-1>", self.on_release)

    def set_status(self, recording, lang=""):
        color = self.RED if recording else self.FG2
        self.dot.itemconfig(self.dot_id, fill=color)
        self.record_btn.config(text="\u25a0 Stop" if recording else "\u25b6 Record")
        if not recording:
            self.set_lang_chips(False)
        self.recording = recording

    def update_preview(self, text):
        one_line = text.replace("\n", " ").strip()
        if len(one_line) > 60:
            one_line = one_line[:57] + "..."
        self.preview.config(text=one_line)

    def show_text(self, text):
        self.current_text = text
        self.text_box.config(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("end", text)
        self.text_box.config(state="disabled")
        self.text_box.see("end")
        self.update_preview(text)
        if text and not self.is_expanded:
            self.expand()
        elif not text and self.is_expanded:
            self.collapse()

    def expand(self):
        if self.is_expanded:
            return
        self.is_expanded = True
        bar_w = self.root.winfo_width()
        x = self.root.winfo_x()
        extra = self.SYM_EXTRA if self.sym_packed else 0
        self.root.geometry(f"{bar_w}x{EXPANDED_HEIGHT + extra}+{x}+0")
        self.expand_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    def collapse(self):
        if not self.is_expanded:
            return
        self.is_expanded = False
        self.expand_frame.pack_forget()
        bar_w = self.root.winfo_width()
        x = self.root.winfo_x()
        if self.sym_packed:
            self.sym_outer.pack_forget()
            self.sym_packed = False
            self.update_sym_btn()
        self.root.geometry(f"{bar_w}x{BAR_HEIGHT}+{x}+0")

    def on_font_change(self):
        name = self.font_var.get()
        self.display_font_name = name
        self.base_font = tkfont.Font(family=name, size=10)
        self.mono_font = tkfont.Font(family=name, size=11)
        self.preview.config(font=self.base_font)
        self.text_box.config(font=self.mono_font)
        config["display_font"] = name
        save_config()

    def toggle_mode(self):
        cur = self.mode_var.get()
        new = "type" if cur == "paste" else "paste"
        self.mode_var.set(new)
        self.typing_mode = new
        config["typing_mode"] = new
        save_config()

    def toggle_preeti(self):
        if self.preeti_mode:
            self.preeti_mode = False
            config["preeti_mode"] = False
            save_config()
            if self.unicode_text:
                self.accumulated_text = self.unicode_text
                self.current_text = self.unicode_text
                self.show_text(self.unicode_text)
            self.update_preeti_btn()
        elif self.unicode_text:
            self.preeti_mode = True
            config["preeti_mode"] = True
            save_config()
            preeti = unicode_to_preeti(self.unicode_text)
            self.accumulated_text = preeti
            self.current_text = preeti
            self.show_text(preeti)
            self.update_preeti_btn()
            self.root.after(100, self.type_text)
        else:
            self.root.after(0, lambda: self.preview.config(text="Record something first"))

    def update_preeti_btn(self):
        on = self.preeti_mode
        self.preeti_btn.config(
            text="NP-Preeti \u2192 Type" if not on else "NP-Preeti: ON",
            bg=self.ACCENT if on else self.BG2,
            fg="#000" if on else self.FG2,
        )

    def toggle_num_mode(self):
        self.num_mode = not self.num_mode
        config["num_mode"] = self.num_mode
        save_config()
        self.update_num_btn()

    def update_num_btn(self):
        on = self.num_mode
        self.num_btn.config(
            text="NP-Num: ON" if on else "NP-Num: OFF",
            bg=self.ACCENT if on else self.BG2,
            fg="#000" if on else self.FG2,
        )

    SYM_EXTRA = 105

    def toggle_sym_mode(self):
        bar_w = self.root.winfo_width()
        x = self.root.winfo_x()
        if self.sym_packed:
            self.sym_outer.pack_forget()
            self.sym_packed = False
            h = self.root.winfo_height() - self.SYM_EXTRA
            self.root.geometry(f"{bar_w}x{h}+{x}+0")
        else:
            self.sym_outer.pack(fill="x", padx=10, pady=(0, 4))
            self.sym_packed = True
            h = self.root.winfo_height() + self.SYM_EXTRA
            self.root.geometry(f"{bar_w}x{h}+{x}+0")
        self.update_sym_btn()

    def update_sym_btn(self):
        on = self.sym_packed
        self.sym_btn.config(
            text="NP-Sym: ON" if on else "NP-Sym: OFF",
            bg=self.ACCENT if on else self.BG2,
            fg="#000" if on else self.FG2,
        )

    def _bind_mousewheel(self, widget):
        def _on_mousewheel(event):
            widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
        widget.bind("<Enter>", lambda e: widget.bind_all("<MouseWheel>", _on_mousewheel))
        widget.bind("<Leave>", lambda e: widget.unbind_all("<MouseWheel>"))

    def _ime_insert_symbol(self, sym):
        if self.unicode_text:
            self.unicode_text += sym
        else:
            self.unicode_text = sym
        self.current_text = self.unicode_text
        display = unicode_to_preeti(self.unicode_text) if self.preeti_mode else self.unicode_text
        self.accumulated_text = display
        self.show_text(display)
        self.ime_input.focus_set()

    def _ime_enable(self):
        self.ime_mode = True
        self.ime_current_roman = ""

        if not self.is_expanded:
            self.expand()

        self.ime_frame.pack(fill="x", expand=False, padx=10, pady=(0, 6))
        self.ime_input.delete(0, "end")
        self.ime_input.focus_set()
        self._ime_clear_suggestions()

    def _ime_disable(self):
        self.ime_mode = False
        self.ime_frame.pack_forget()
        self.sym_outer.pack_forget()
        self.sym_packed = False
        self.update_sym_btn()
        self._ime_clear_suggestions()

        if not self.accumulated_text and not self.current_text:
            self.collapse()

    def _ime_clear_suggestions(self):
        for num_lbl, lbl, cell in self.suggestion_cells:
            num_lbl.config(text="")
            lbl.config(text="")
        self.ime_suggestions = []

    def _ime_show_suggestions(self, suggestions):
        self._ime_clear_suggestions()
        self.ime_suggestions = suggestions
        for i, (roman, dev) in enumerate(suggestions):
            num_lbl, lbl, cell = self.suggestion_cells[i]
            num_lbl.config(text=str(i + 1))
            lbl.config(text=dev)
        self.ime_input.focus_set()

    def _on_ime_keypress(self, event):
        if event.keysym in ("1", "2", "3", "4"):
            idx = int(event.keysym) - 1
            if idx < len(self.ime_suggestions):
                self._ime_select(idx)
                return "break"
        elif event.keysym == "space":
            self._ime_commit_word()
            return "break"
        elif event.keysym == "Return":
            self._ime_type_all()
            return "break"
        return None

    def _on_ime_key(self, event):
        if event.keysym in ("1", "2", "3", "4", "space", "Return"):
            return
        self._ime_update()

    def _ime_update(self):
        roman = self.ime_input.get()
        if not roman:
            self.ime_current_roman = ""
            self.ime_preview.config(text="")
            self._ime_clear_suggestions()
            return
        self.ime_current_roman = roman
        dev = roman_to_devanagari(roman)
        if self.num_mode:
            dev = to_nepali_digits(dev)
        self.ime_preview.config(text=dev)
        suggestions = get_suggestions(roman)
        self._ime_show_suggestions(suggestions)

    def _ime_select(self, index):
        if index < 0 or index >= len(self.ime_suggestions):
            return
        roman, dev = self.ime_suggestions[index]
        if self.num_mode:
            dev = to_nepali_digits(dev)
        if self.unicode_text:
            self.unicode_text += " " + dev
        else:
            self.unicode_text = dev
        self.current_text = self.unicode_text
        display = unicode_to_preeti(self.unicode_text) if self.preeti_mode else self.unicode_text
        self.accumulated_text = display
        self.show_text(display)
        self.ime_input.delete(0, "end")
        self.ime_preview.config(text="")
        self._ime_clear_suggestions()
        self.ime_input.focus_set()

    def _ime_commit_word(self):
        roman = self.ime_input.get().strip()
        if not roman:
            return
        dev = roman_to_devanagari(roman)
        if self.num_mode:
            dev = to_nepali_digits(dev)
        if self.unicode_text:
            self.unicode_text += " " + dev
        else:
            self.unicode_text = dev
        self.current_text = self.unicode_text
        display = unicode_to_preeti(self.unicode_text) if self.preeti_mode else self.unicode_text
        self.accumulated_text = display
        self.show_text(display)
        self.ime_input.delete(0, "end")
        self.ime_preview.config(text="")
        self._ime_clear_suggestions()
        self.ime_input.focus_set()

    def _ime_type_all(self):
        self._ime_commit_pending()
        text = self.accumulated_text or self.current_text
        if not text.strip():
            self.preview.config(text="Nothing to type")
            return
        try:
            text = unicodedata.normalize("NFC", text)
            mode = self.mode_var.get()
            self.root.withdraw()
            self.root.update()
            time.sleep(0.2)
            if mode == "type":
                keyboard.write(text, delay=0.008)
            else:
                pyperclip.copy(text)
                time.sleep(0.15)
                keyboard.send("ctrl+v")
                time.sleep(0.1)
            self.preview.config(text=f"Typed {len(text.split())} words")
            preview = text[:50] + "..." if len(text) > 50 else text
            notify("WhisperFlow", f"Typed: {preview}")
        except Exception as e:
            self.preview.config(text=f"Type failed: {e}")
        finally:
            try:
                self.root.deiconify()
            except Exception:
                pass

    def _ime_commit_pending(self):
        roman = self.ime_input.get().strip()
        if roman:
            dev = roman_to_devanagari(roman)
            if self.num_mode:
                dev = to_nepali_digits(dev)
            if self.unicode_text:
                self.unicode_text += " " + dev
            else:
                self.unicode_text = dev
            self.current_text = self.unicode_text
            display = unicode_to_preeti(self.unicode_text) if self.preeti_mode else self.unicode_text
            self.accumulated_text = display
            self.show_text(display)
            self.ime_input.delete(0, "end")
            self.ime_preview.config(text="")
            self._ime_clear_suggestions()

    def set_lang_chips(self, recording):
        state = "disabled" if recording else "normal"
        for code, chip in self.lang_chips.items():
            chip.config(state=state)

    def select_language(self, code):
        if self.recording:
            return
        self.selected_lang = code
        for c, chip in self.lang_chips.items():
            active = c == code
            chip.config(
                bg=self.ACCENT if active else self.BG2,
                fg="#000" if active else self.FG2,
                font=("Segoe UI", 8, "bold")
            )
        if code == "ne":
            self._ime_enable()
        else:
            self._ime_disable()
            self.lang_label = tk.Label(self.root, text="", fg=self.ACCENT, bg=self.BG,
                                       font=("Segoe UI", 8))
            self.record_btn.config(text="\u25a0 Stop")
            self.start_recording()

    def toggle_record(self):
        print(f"[DEBUG] toggle_record called. recording={self.recording}")
        if self.recording:
            self.stop_recording(auto_type=True)
        elif self.selected_lang:
            self.start_recording()
        else:
            self.preview.config(text="Select a language first")

    def start_recording(self):
        if not config.get("api_key"):
            notify("No API Key", "Set your Groq API key in tray menu.")
            return
        self.recording = True
        self.audio_buffer = []
        self.rec_start_time = time.time()
        self.set_status(True)
        self.set_lang_chips(True)
        self.preview.config(text=f"Recording [{self.selected_lang.upper()}]...")

        def worker():
            try:
                with sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                    blocksize=1024,
                    callback=lambda indata, frames, t, s: (
                        self.audio_buffer.append(indata.copy())
                        if self.recording else None
                    )
                ):
                    while self.recording:
                        sd.sleep(100)
            except Exception as e:
                self.root.after(0, lambda: self.show_error(str(e)))

        self.recording_thread = threading.Thread(target=worker, daemon=True)
        self.recording_thread.start()

        if self.update_timer_id:
            self.root.after_cancel(self.update_timer_id)
        self.update_recording_timer()

    def update_recording_timer(self):
        if not self.recording:
            return
        elapsed = int(time.time() - self.rec_start_time)
        self.preview.config(text=f"Recording... {elapsed}s")
        self.update_timer_id = self.root.after(1000, self.update_recording_timer)

    def stop_recording(self, auto_type=False):
        print(f"[DEBUG] stop_recording called with auto_type={auto_type}")
        self.recording = False
        self.set_status(False)
        self.auto_type_on_done = auto_type
        if self.update_timer_id:
            self.root.after_cancel(self.update_timer_id)
            self.update_timer_id = None

        audio_data = np.concatenate(self.audio_buffer) if self.audio_buffer else np.array([], dtype=np.int16)
        self.audio_buffer = []

        if len(audio_data) < SAMPLE_RATE // 4:
            self.preview.config(text="Too short - say more")
            return

        self.preview.config(text="Transcribing...")
        self.root.update()

        def transcribe_worker():
            try:
                wav_bytes = save_wav_bytes(audio_data)
                text, detected = transcribe_audio(wav_bytes, self.selected_lang or "")
                corrected = fix_grammar(text, detected) if config.get("grammar_fix", True) else text
                if self.unicode_text:
                    corrected = self.unicode_text + " " + corrected
                self.unicode_text = corrected
                display = unicode_to_preeti(corrected) if self.preeti_mode else corrected
                self.accumulated_text = display
                self.root.after(0, lambda: self.on_transcription_done(display, detected))
            except Exception as e:
                self.root.after(0, lambda: self.show_error(str(e)))

        threading.Thread(target=transcribe_worker, daemon=True).start()

    def on_transcription_done(self, text, lang):
        self.detected_lang = lang
        self.set_status(False, lang)
        self.show_text(text)
        print(f"[DEBUG] Transcription done. auto_type={self.auto_type_on_done}, text_len={len(text)}")
        if self.auto_type_on_done:
            self.auto_type_on_done = False
            print(f"[DEBUG] Starting auto-typing...")
            self.root.after(150, self.type_text)

    def show_error(self, msg):
        self.set_status(False)
        self.preview.config(text=f"Error: {msg}")

    def type_text(self):
        if self.ime_mode:
            self._ime_type_all()
            return
        text = self.accumulated_text or self.current_text
        if not text.strip():
            self.preview.config(text="Nothing to type")
            return
        try:
            text = unicodedata.normalize("NFC", text)
            mode = self.mode_var.get()
            self.root.withdraw()
            self.root.update()
            time.sleep(0.2)
            if mode == "type":
                keyboard.write(text, delay=0.008)
            else:
                pyperclip.copy(text)
                time.sleep(0.15)
                keyboard.send("ctrl+v")
                time.sleep(0.1)
            self.preview.config(text=f"Typed {len(text.split())} words")
            preview = text[:50] + "..." if len(text) > 50 else text
            notify("WhisperFlow", f"Typed: {preview}")
        except Exception as e:
            self.preview.config(text=f"Type failed: {e}")
            print(f"Dictation error: {e}")
        finally:
            try:
                self.root.deiconify()
            except Exception:
                pass

    def clear_text(self):
        self.accumulated_text = ""
        self.current_text = ""
        self.unicode_text = ""
        self.show_text("")
        self.preview.config(text="")
        if self.ime_mode:
            self.ime_input.delete(0, "end")
            self.ime_preview.config(text="")
            self._ime_clear_suggestions()

    def test_dictation(self):
        text = self.accumulated_text or self.current_text
        if not text.strip():
            self.preview.config(text="No text to test - record something first")
            return
        self.preview.config(text="Testing dictation...")
        self.root.after(100, lambda: self._do_test_dictation(text))

    def _do_test_dictation(self, text):
        try:
            text = unicodedata.normalize("NFC", text)
            mode = self.mode_var.get()
            self.root.withdraw()
            self.root.update()
            time.sleep(0.2)
            if mode == "type":
                keyboard.write(text, delay=0.008)
            else:
                pyperclip.copy(text)
                time.sleep(0.15)
                keyboard.send("ctrl+v")
                time.sleep(0.1)
            self.preview.config(text=f"Test typed: {len(text.split())} words")
            print(f"[DEBUG] Test dictation success: {len(text.split())} words")
        except Exception as e:
            self.preview.config(text=f"Test failed: {e}")
            print(f"[DEBUG] Test dictation error: {e}")
        finally:
            try:
                self.root.deiconify()
            except Exception:
                pass

    def close(self):
        self.recording = False
        if self.ime_mode:
            self._ime_disable()
        if self.update_timer_id:
            self.root.after_cancel(self.update_timer_id)
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if self.ime_mode:
            self.ime_input.focus_set()
        if not self.selected_lang and not self.accumulated_text:
            self.preview.config(text="Select EN, NP, or HI to start")

    def is_visible(self):
        return self.root.winfo_viewable()


def toggle_dictation_bar():
    global bar
    if bar is None:
        return
    if bar.is_visible() and bar.recording:
        bar.stop_recording(auto_type=True)
    elif bar.is_visible():
        if bar.ime_mode:
            bar._ime_commit_pending()
        bar.close()
        if tray_icon:
            tray_icon.icon = create_icon_image(False)
    else:
        bar.selected_lang = None
        bar.show()
        bar.root.after(100, lambda: bar.ime_input.focus_set() if bar.ime_mode else None)
        if tray_icon:
            tray_icon.icon = create_icon_image(True)


def show_settings():
    from tkinter import Tk, Label, Entry, Button, Checkbutton, BooleanVar, StringVar, messagebox

    root = Tk()
    root.title("WhisperFlow Settings")
    root.geometry("420x330")
    root.resizable(False, False)
    root.configure(bg="#141414")

    style = {"bg": "#141414", "fg": "#E8E8E8", "font": ("Segoe UI", 10)}
    entry_style = {"bg": "#0C0C0C", "fg": "#E8E8E8", "insertbackground": "#E8E8E8",
                   "relief": "flat", "bd": 1, "font": ("Segoe UI", 10)}

    Label(root, text="Groq API Key", **style).pack(anchor="w", padx=20, pady=(20, 4))
    api_var = StringVar(value=config.get("api_key", ""))
    Entry(root, textvariable=api_var, show="*", **entry_style).pack(fill="x", padx=20, pady=(0, 10))

    grammar_var = BooleanVar(value=config.get("grammar_fix", True))
    Checkbutton(root, text="Auto-fix grammar before typing", variable=grammar_var,
                bg="#141414", fg="#E8E8E8", selectcolor="#0C0C0C",
                activebackground="#141414", activeforeground="#E8E8E8",
                font=("Segoe UI", 10)).pack(anchor="w", padx=20, pady=(0, 10))

    mode_var = StringVar(value=config.get("typing_mode", "paste"))
    mode_frame = tk.Frame(root, bg="#141414")
    mode_frame.pack(anchor="w", padx=20, pady=(0, 10))
    Label(mode_frame, text="Typing mode:", **style).pack(side="left", padx=(0, 10))
    for val, lbl in [("paste", "Paste (clipboard)"), ("type", "Type (character-by-character)")]:
        tk.Radiobutton(mode_frame, text=lbl, variable=mode_var, value=val,
                       bg="#141414", fg="#E8E8E8", selectcolor="#0C0C0C",
                       activebackground="#141414", activeforeground="#E8E8E8",
                       font=("Segoe UI", 10)).pack(side="left", padx=(0, 10))

    preeti_var = BooleanVar(value=config.get("preeti_mode", False))
    Checkbutton(root, text="Convert NP text to Preeti encoding", variable=preeti_var,
                bg="#141414", fg="#E8E8E8", selectcolor="#0C0C0C",
                activebackground="#141414", activeforeground="#E8E8E8",
                font=("Segoe UI", 10)).pack(anchor="w", padx=20, pady=(0, 4))

    num_var = BooleanVar(value=config.get("num_mode", False))
    Checkbutton(root, text="Convert English digits to Nepali digits (123→१२३)", variable=num_var,
                bg="#141414", fg="#E8E8E8", selectcolor="#0C0C0C",
                activebackground="#141414", activeforeground="#E8E8E8",
                font=("Segoe UI", 10)).pack(anchor="w", padx=20, pady=(0, 10))

    def save():
        key = api_var.get().strip()
        if not key:
            messagebox.showwarning("No Key", "API key is required.")
            return
        config["api_key"] = key
        config["grammar_fix"] = grammar_var.get()
        config["typing_mode"] = mode_var.get()
        config["preeti_mode"] = preeti_var.get()
        config["num_mode"] = num_var.get()
        save_config()
        if bar:
            bar.typing_mode = mode_var.get()
            bar.mode_var.set(mode_var.get())
            bar.preeti_mode = preeti_var.get()
            bar.update_preeti_btn()
            bar.num_mode = num_var.get()
            bar.update_num_btn()
        root.destroy()
        notify("WhisperFlow", "Settings saved.")

    Button(root, text="Save & Close", command=save,
           bg="#0ECECE", fg="#000", font=("Segoe UI", 10, "bold"),
           relief="flat", padx=20, pady=6).pack(pady=(10, 0))

    root.mainloop()


def build_menu():
    return pystray.Menu(
        pystray.MenuItem("Open Dictation", lambda: bar.show() if bar else None, default=True),
        pystray.MenuItem("Settings", show_settings),
        pystray.MenuItem("Exit", exit_app)
    )


def exit_app():
    global recording, bar
    recording = False
    if bar:
        bar.recording = False
        try:
            bar.root.destroy()
        except Exception:
            pass
    if tray_icon:
        tray_icon.stop()
    os._exit(0)


def main():
    global tray_icon, bar, bar_root

    parser = argparse.ArgumentParser(description="WhisperFlow Desktop Dictation")
    parser.parse_args()

    load_config()

    tray_icon = pystray.Icon(
        "whisperflow",
        create_icon_image(False),
        "WhisperFlow - Ctrl+Shift+D",
        build_menu()
    )

    def start_tray():
        tray_icon.run()

    threading.Thread(target=start_tray, daemon=True).start()

    bar_root = tk.Tk()
    bar = DictationBar(bar_root)

    keyboard.add_hotkey("ctrl+shift+d", lambda: (
        bar_root.after(0, toggle_dictation_bar) if bar_root else None
    ))

    bar_root.protocol("WM_DELETE_WINDOW", lambda: bar.close())

    bar_root.mainloop()


if __name__ == "__main__":
    main()
