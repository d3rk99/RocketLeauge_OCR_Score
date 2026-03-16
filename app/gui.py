from __future__ import annotations

import json
import threading
import time
import tkinter as tk
from dataclasses import asdict
from tkinter import ttk, messagebox

from app.capture import ScreenCapturer
from app.config import CONFIG_DIR, AppConfig, MatchConfig, Region, RegionsConfig, parse_ocr_gpu_preference, target_games_to_win
from app.detector import ScoreDetector, ScoreReading
from app.ocr import build_engine, preprocess_for_ocr
from app.state import StateManager


class RegionSelector(tk.Toplevel):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.title("Select OCR Region")
        self.attributes("-fullscreen", True)
        self.attributes("-alpha", 0.25)
        self.configure(bg="black")
        self.canvas = tk.Canvas(self, cursor="cross", bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.start_x = 0
        self.start_y = 0
        self.rect_id = None
        self.result: tuple[int, int, int, int] | None = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=2)

    def _on_drag(self, event):
        if self.rect_id:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event):
        x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
        x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)
        if (x2 - x1) < 10 or (y2 - y1) < 10:
            return
        self.result = (x1, y1, x2 - x1, y2 - y1)
        self.destroy()


class RegionOverlay:
    def __init__(self, master: tk.Tk):
        self.master = master
        self.window: tk.Toplevel | None = None

    def show(self, region: Region) -> None:
        self.hide()
        self.window = tk.Toplevel(self.master)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.45)
        self.window.geometry(f"{region.width}x{region.height}+{region.left}+{region.top}")
        canvas = tk.Canvas(self.window, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_rectangle(2, 2, region.width - 2, region.height - 2, outline="#00ff00", width=3)

    def hide(self) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class OCRWorker:
    def __init__(self, app_cfg: AppConfig, regions_cfg: RegionsConfig, state: StateManager) -> None:
        self.app_cfg = app_cfg
        self.regions_cfg = regions_cfg
        self.state = state
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def _run(self) -> None:
        capturer = ScreenCapturer(self.regions_cfg)
        engine = build_engine(
            self.app_cfg.engine,
            tesseract_cmd=self.app_cfg.tesseract_cmd,
            easyocr_use_gpu=parse_ocr_gpu_preference(self.app_cfg.ocr_use_gpu),
        )
        detector = ScoreDetector(self.app_cfg, self.state)
        delay = 1.0 / max(1, self.app_cfg.fps)

        while not self.stop_event.is_set():
            start = time.perf_counter()
            frame = capturer.grab()
            a = preprocess_for_ocr(frame.team_a_crop)
            b = preprocess_for_ocr(frame.team_b_crop)
            a_res = engine.read_score(a)
            b_res = engine.read_score(b)
            detector.process(
                ScoreReading(
                    a_value=a_res.value,
                    b_value=b_res.value,
                    a_conf=a_res.confidence,
                    b_conf=b_res.confidence,
                    a_raw=a_res.raw_text,
                    b_raw=b_res.raw_text,
                )
            )
            elapsed = time.perf_counter() - start
            if delay - elapsed > 0:
                time.sleep(delay - elapsed)


class ControlGUI:
    def __init__(self, app_cfg: AppConfig, regions_cfg: RegionsConfig, match_cfg: MatchConfig) -> None:
        self.root = tk.Tk()
        self.root.title("Rocket League OCR Control Panel")
        self.root.geometry("760x520")

        self.app_cfg = app_cfg
        self.regions_cfg = regions_cfg
        self.state = StateManager(app_cfg.overlay_state_path, match_cfg)
        self.worker = OCRWorker(app_cfg, regions_cfg, self.state)
        self.overlay = RegionOverlay(self.root)
        self.overlay_visible = False

        self._build_ui()
        self._refresh_state()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        top = ttk.LabelFrame(frame, text="Match")
        top.pack(fill="x", pady=6)

        self.team_a_var = tk.StringVar(value=self.state.snapshot().team_a_name)
        self.team_b_var = tk.StringVar(value=self.state.snapshot().team_b_name)
        self.series_var = tk.StringVar(value=self.state.snapshot().series_type)

        ttk.Label(top, text="Team A").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.team_a_var, width=20).grid(row=0, column=1, padx=4)
        ttk.Label(top, text="Team B").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(top, textvariable=self.team_b_var, width=20).grid(row=0, column=3, padx=4)
        ttk.Label(top, text="Series").grid(row=0, column=4, sticky="w", padx=4)
        ttk.Combobox(top, textvariable=self.series_var, values=["bo3", "bo5", "bo7"], state="readonly", width=8).grid(row=0, column=5, padx=4)
        ttk.Button(top, text="Apply", command=self._apply_match).grid(row=0, column=6, padx=6)

        ctl = ttk.LabelFrame(frame, text="OCR / Region")
        ctl.pack(fill="x", pady=6)

        self.region_label = tk.StringVar()
        ttk.Label(ctl, textvariable=self.region_label).grid(row=0, column=0, columnspan=4, sticky="w", padx=4, pady=4)
        ttk.Button(ctl, text="Select OCR Region", command=self._select_region).grid(row=1, column=0, padx=4, pady=4)
        ttk.Button(ctl, text="Save Region", command=self._save_region).grid(row=1, column=1, padx=4, pady=4)
        ttk.Button(ctl, text="Toggle Region Border", command=self._toggle_overlay).grid(row=1, column=2, padx=4, pady=4)

        self.run_label = tk.StringVar(value="OCR: stopped")
        ttk.Label(ctl, textvariable=self.run_label).grid(row=2, column=0, sticky="w", padx=4, pady=6)
        ttk.Button(ctl, text="Start OCR", command=self._start_ocr).grid(row=2, column=1, padx=4)
        ttk.Button(ctl, text="Stop OCR", command=self._stop_ocr).grid(row=2, column=2, padx=4)

        score = ttk.LabelFrame(frame, text="Scoreboard Controls")
        score.pack(fill="x", pady=6)
        ttk.Button(score, text="Reset Current Game", command=lambda: self.state.reset_current_game_score()).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(score, text="Award Team A Game", command=lambda: self.state.award_game("a")).grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(score, text="Award Team B Game", command=lambda: self.state.award_game("b")).grid(row=0, column=2, padx=4, pady=4)

        live = ttk.LabelFrame(frame, text="Live State")
        live.pack(fill="both", expand=True, pady=6)
        self.live_text = tk.Text(live, height=14)
        self.live_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.live_text.configure(state="disabled")

        self._update_region_label()

    def _apply_match(self) -> None:
        series = self.series_var.get()
        self.state.update(
            team_a_name=self.team_a_var.get().strip() or "Team Alpha",
            team_b_name=self.team_b_var.get().strip() or "Team Bravo",
            series_type=series,
            target_games_to_win=target_games_to_win(series),
        )

    def _select_region(self) -> None:
        selector = RegionSelector(self.root)
        self.root.wait_window(selector)
        if not selector.result:
            return
        left, top, width, height = selector.result
        self.regions_cfg.scoreboard = Region(top=top, left=left, width=width, height=height)

        # Calibration default: score digits are usually around left/right thirds of scoreboard bar.
        sw = max(1, width)
        sh = max(1, height)
        self.regions_cfg.team_a_score = Region(top=int(sh * 0.2), left=int(sw * 0.25), width=int(sw * 0.15), height=int(sh * 0.6))
        self.regions_cfg.team_b_score = Region(top=int(sh * 0.2), left=int(sw * 0.6), width=int(sw * 0.15), height=int(sh * 0.6))
        self._update_region_label()
        if self.overlay_visible:
            self.overlay.show(self.regions_cfg.scoreboard)

    def _save_region(self) -> None:
        payload = {
            "scoreboard": asdict(self.regions_cfg.scoreboard),
            "team_a_score": asdict(self.regions_cfg.team_a_score),
            "team_b_score": asdict(self.regions_cfg.team_b_score),
        }
        path = CONFIG_DIR / "regions.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        messagebox.showinfo("Saved", f"Saved OCR region to {path}")

    def _toggle_overlay(self) -> None:
        self.overlay_visible = not self.overlay_visible
        if self.overlay_visible:
            self.overlay.show(self.regions_cfg.scoreboard)
        else:
            self.overlay.hide()

    def _start_ocr(self) -> None:
        self.worker.start()
        self.run_label.set("OCR: running")

    def _stop_ocr(self) -> None:
        self.worker.stop()
        self.run_label.set("OCR: stopped")

    def _update_region_label(self) -> None:
        r = self.regions_cfg.scoreboard
        self.region_label.set(f"OCR region: left={r.left}, top={r.top}, width={r.width}, height={r.height}")

    def _refresh_state(self) -> None:
        snap = self.state.snapshot()
        self.live_text.configure(state="normal")
        self.live_text.delete("1.0", "end")
        self.live_text.insert(
            "1.0",
            json.dumps(
                {
                    "team_a_name": snap.team_a_name,
                    "team_b_name": snap.team_b_name,
                    "team_a_score": snap.team_a_score,
                    "team_b_score": snap.team_b_score,
                    "team_a_games": snap.team_a_games,
                    "team_b_games": snap.team_b_games,
                    "series_type": snap.series_type,
                    "target_games_to_win": snap.target_games_to_win,
                    "current_game_number": snap.current_game_number,
                    "match_status": snap.match_status,
                    "last_update": snap.last_update,
                },
                indent=2,
            ),
        )
        self.live_text.configure(state="disabled")
        self.root.after(350, self._refresh_state)

    def _on_close(self) -> None:
        self.worker.stop()
        self.overlay.hide()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
