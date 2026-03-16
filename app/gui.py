from __future__ import annotations

import json
import logging
import threading
import time
import tkinter as tk
from dataclasses import asdict
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

from app.capture import ScreenCapturer
from app.config import CONFIG_DIR, AppConfig, MatchConfig, Region, RegionsConfig, parse_ocr_gpu_preference, target_games_to_win
from app.detector import ScoreDetector, ScoreReading
from app.ocr import build_engine, preprocess_for_ocr, preprocess_luma_mask
from app.state import StateManager


LOGGER = logging.getLogger("gui")


class RegionSelector(tk.Toplevel):
    def __init__(self, master: tk.Tk, title: str):
        super().__init__(master)
        self.title(title)
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
        self.windows: list[tk.Toplevel] = []

    def show(self, team_a: Region, team_b: Region, timer: Region) -> None:
        self.hide()
        self.windows.append(self._create_box(team_a, "#2dd4ff"))
        self.windows.append(self._create_box(team_b, "#f973ff"))
        self.windows.append(self._create_box(timer, "#22c55e"))

    def _create_box(self, region: Region, color: str) -> tk.Toplevel:
        win = tk.Toplevel(self.master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.35)
        win.geometry(f"{region.width}x{region.height}+{region.left}+{region.top}")
        c = tk.Canvas(win, bg="black", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.create_rectangle(2, 2, region.width - 2, region.height - 2, outline=color, width=3)
        return win

    def hide(self) -> None:
        for win in self.windows:
            win.destroy()
        self.windows = []


class OCRWorker:
    def __init__(
        self,
        app_cfg: AppConfig,
        regions_cfg: RegionsConfig,
        state: StateManager,
        preview_callback=None,
        error_callback=None,
    ) -> None:
        self.app_cfg = app_cfg
        self.regions_cfg = regions_cfg
        self.state = state
        self.preview_callback = preview_callback
        self.error_callback = error_callback
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

    def is_running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def _notify_error(self, message: str) -> None:
        if self.error_callback:
            self.error_callback(message)

    def _validate_regions(self) -> None:
        for name, region in {
            "team_a_score": self.regions_cfg.team_a_score,
            "team_b_score": self.regions_cfg.team_b_score,
            "game_timer": self.regions_cfg.game_timer,
        }.items():
            if region.width <= 0 or region.height <= 0:
                raise ValueError(f"Invalid {name} size ({region.width}x{region.height})")
            if region.left < 0 or region.top < 0:
                raise ValueError(f"Invalid {name} position ({region.left},{region.top})")

    def _run(self) -> None:
        try:
            self._validate_regions()
            capturer = ScreenCapturer(self.regions_cfg)
            engine = build_engine(
                self.app_cfg.engine,
                tesseract_cmd=self.app_cfg.tesseract_cmd,
                easyocr_use_gpu=parse_ocr_gpu_preference(self.app_cfg.ocr_use_gpu),
            )
            detector = ScoreDetector(self.app_cfg, self.state)
        except Exception as exc:
            LOGGER.exception("OCR worker startup failed: %s", exc)
            self._notify_error(f"OCR worker startup failed: {exc}")
            return

        consecutive_failures = 0
        last_failure_log_ts = 0.0

        while not self.stop_event.is_set():
            start = time.perf_counter()
            try:
                frame = capturer.grab()
                if frame.team_a_crop.size == 0 or frame.team_b_crop.size == 0 or frame.timer_crop.size == 0:
                    raise RuntimeError("One or more capture regions returned empty frames. Recheck OCR regions.")

                a_mask = preprocess_luma_mask(frame.team_a_crop, self.app_cfg.luma_threshold)
                b_mask = preprocess_luma_mask(frame.team_b_crop, self.app_cfg.luma_threshold)
                timer = preprocess_for_ocr(frame.timer_crop)
                t_res = engine.read_timer(timer)

                detector.process(
                    ScoreReading(
                        a_mask=a_mask,
                        b_mask=b_mask,
                        timer_value=t_res.timer,
                        timer_conf=t_res.confidence,
                        timer_raw=t_res.raw_text,
                    )
                )

                if self.preview_callback:
                    self.preview_callback(a_mask, b_mask, timer)
                consecutive_failures = 0
            except Exception as exc:
                consecutive_failures += 1
                now = time.time()
                if consecutive_failures <= 3 or (now - last_failure_log_ts) >= 2.0:
                    LOGGER.exception(
                        "OCR worker frame processing failed (count=%s). Potential causes: invalid regions, display capture failure, OCR backend issue.",
                        consecutive_failures,
                    )
                    self._notify_error(f"OCR worker processing error: {exc}")
                    last_failure_log_ts = now
                time.sleep(0.2)

            delay = 1.0 / max(1, self.app_cfg.fps)
            elapsed = time.perf_counter() - start
            if delay - elapsed > 0:
                time.sleep(delay - elapsed)


class ControlGUI:
    def __init__(self, app_cfg: AppConfig, regions_cfg: RegionsConfig, match_cfg: MatchConfig) -> None:
        self.root = tk.Tk()
        self.root.title("Rocket League OCR Control Panel")
        self.root.geometry("980x700")

        self.app_cfg = app_cfg
        self.regions_cfg = regions_cfg
        self.state = StateManager(app_cfg.overlay_state_path, match_cfg)
        self.preview_lock = threading.Lock()
        self.latest_preview_arrays: dict[str, object] = {}
        self.last_worker_error = "No worker errors"

        self.worker = OCRWorker(
            app_cfg,
            regions_cfg,
            self.state,
            preview_callback=self._update_preview_frame,
            error_callback=self._on_worker_error,
        )
        self.overlay = RegionOverlay(self.root)
        self.overlay_visible = False

        self._build_ui()
        self._update_preview_image()
        self._refresh_state()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.report_callback_exception = self._handle_tk_exception

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        top = ttk.LabelFrame(frame, text="Match")
        top.pack(fill="x", pady=6)
        snap = self.state.snapshot()

        self.team_a_var = tk.StringVar(value=snap.team_a_name)
        self.team_b_var = tk.StringVar(value=snap.team_b_name)
        self.series_var = tk.StringVar(value=snap.series_type)

        ttk.Label(top, text="Team A").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.team_a_var, width=20).grid(row=0, column=1, padx=4)
        ttk.Label(top, text="Team B").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(top, textvariable=self.team_b_var, width=20).grid(row=0, column=3, padx=4)
        ttk.Label(top, text="Series").grid(row=0, column=4, sticky="w", padx=4)
        ttk.Combobox(top, textvariable=self.series_var, values=["bo3", "bo5", "bo7"], state="readonly", width=8).grid(row=0, column=5, padx=4)
        ttk.Button(top, text="Apply", command=self._apply_match).grid(row=0, column=6, padx=6)

        perf = ttk.LabelFrame(frame, text="OCR Device + Performance")
        perf.pack(fill="x", pady=6)
        self.device_var = tk.StringVar(value=self._to_device_ui_value(self.app_cfg.ocr_use_gpu))
        self.fps_var = tk.IntVar(value=max(1, int(self.app_cfg.fps)))
        self.hw_status_var = tk.StringVar(value=self._detect_hardware_status())

        ttk.Label(perf, text="OCR Device").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(perf, textvariable=self.device_var, values=["Auto", "GPU", "CPU"], state="readonly", width=10).grid(row=0, column=1, padx=4)
        ttk.Label(perf, text="FPS").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Spinbox(perf, from_=1, to=30, textvariable=self.fps_var, width=6).grid(row=0, column=3, padx=4)

        ttk.Label(perf, text="Luma Threshold").grid(row=0, column=4, sticky="w", padx=4)
        self.luma_var = tk.IntVar(value=self.app_cfg.luma_threshold)
        ttk.Scale(perf, from_=150, to=255, variable=self.luma_var, orient="horizontal", length=120).grid(row=0, column=5, padx=4)
        ttk.Spinbox(perf, from_=150, to=255, textvariable=self.luma_var, width=5).grid(row=0, column=6, padx=4)

        ttk.Label(perf, text="Pixel Change Threshold").grid(row=0, column=7, sticky="w", padx=4)
        self.change_threshold_var = tk.IntVar(value=self.app_cfg.pixel_change_count_threshold)
        ttk.Spinbox(perf, from_=1, to=50000, textvariable=self.change_threshold_var, width=8).grid(row=0, column=8, padx=4)

        ttk.Button(perf, text="Apply", command=self._apply_device_fps_luma).grid(row=0, column=9, padx=6)
        ttk.Button(perf, text="Save as Default", command=self._save_runtime_defaults).grid(row=0, column=10, padx=6)
        ttk.Label(perf, textvariable=self.hw_status_var).grid(row=1, column=0, columnspan=11, sticky="w", padx=4, pady=4)

        self.error_var = tk.StringVar(value="Worker: healthy")
        ttk.Label(perf, textvariable=self.error_var, foreground="#f87171").grid(row=2, column=0, columnspan=11, sticky="w", padx=4, pady=2)

        ctl = ttk.LabelFrame(frame, text="OCR Regions (absolute screen regions)")
        ctl.pack(fill="x", pady=6)

        self.region_label = tk.StringVar()
        ttk.Label(ctl, textvariable=self.region_label).grid(row=0, column=0, columnspan=4, sticky="w", padx=4, pady=4)
        ttk.Button(ctl, text="Select Team A Region", command=lambda: self._select_region("team_a_score")).grid(row=1, column=0, padx=4, pady=4)
        ttk.Button(ctl, text="Select Team B Region", command=lambda: self._select_region("team_b_score")).grid(row=1, column=1, padx=4, pady=4)
        ttk.Button(ctl, text="Select Timer Region", command=lambda: self._select_region("game_timer")).grid(row=1, column=2, padx=4, pady=4)
        ttk.Button(ctl, text="Save Regions", command=self._save_region).grid(row=1, column=3, padx=4, pady=4)
        ttk.Button(ctl, text="Toggle Region Borders", command=self._toggle_overlay).grid(row=2, column=0, padx=4, pady=4)

        self.run_label = tk.StringVar(value="OCR: stopped")
        ttk.Label(ctl, textvariable=self.run_label).grid(row=2, column=1, sticky="w", padx=4, pady=6)
        ttk.Button(ctl, text="Start OCR", command=self._start_ocr).grid(row=2, column=2, padx=4)
        ttk.Button(ctl, text="Stop OCR", command=self._stop_ocr).grid(row=2, column=3, padx=4)

        content = ttk.Frame(frame)
        content.pack(fill="both", expand=True, pady=6)

        live = ttk.LabelFrame(content, text="Live State")
        live.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.live_text = tk.Text(live, height=14)
        self.live_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.live_text.configure(state="disabled")

        preview_box = ttk.LabelFrame(content, text="Region Luma/Preprocess Preview")
        preview_box.pack(side="right", fill="both", expand=False)

        toggles = ttk.Frame(preview_box)
        toggles.pack(fill="x", padx=8, pady=4)
        self.show_preview_a_var = tk.BooleanVar(value=True)
        self.show_preview_b_var = tk.BooleanVar(value=True)
        self.show_preview_timer_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toggles, text="Show Team A", variable=self.show_preview_a_var, command=self._refresh_preview_toggle_state).pack(anchor="w")
        ttk.Checkbutton(toggles, text="Show Team B", variable=self.show_preview_b_var, command=self._refresh_preview_toggle_state).pack(anchor="w")
        ttk.Checkbutton(toggles, text="Show Timer", variable=self.show_preview_timer_var, command=self._refresh_preview_toggle_state).pack(anchor="w")

        self.preview_a_label = ttk.Label(preview_box, text="Team A: no preview")
        self.preview_a_label.pack(padx=8, pady=4)
        self.preview_b_label = ttk.Label(preview_box, text="Team B: no preview")
        self.preview_b_label.pack(padx=8, pady=4)
        self.preview_timer_label = ttk.Label(preview_box, text="Timer: no preview")
        self.preview_timer_label.pack(padx=8, pady=4)

        self._update_region_label()

    def _on_worker_error(self, message: str) -> None:
        self.last_worker_error = message
        LOGGER.error(message)

    def _refresh_preview_toggle_state(self) -> None:
        if not self.show_preview_a_var.get():
            self.preview_a_label.configure(image="", text="Team A preview hidden")
            self.preview_a_label.image = None
        if not self.show_preview_b_var.get():
            self.preview_b_label.configure(image="", text="Team B preview hidden")
            self.preview_b_label.image = None
        if not self.show_preview_timer_var.get():
            self.preview_timer_label.configure(image="", text="Timer preview hidden")
            self.preview_timer_label.image = None

    def _build_preview_photo(self, image, size=(260, 70)) -> ImageTk.PhotoImage:
        resized = cv2.resize(image, size, interpolation=cv2.INTER_NEAREST)
        if len(resized.shape) == 2:
            rgb = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return ImageTk.PhotoImage(image=Image.fromarray(rgb))

    def _update_preview_frame(self, a_mask, b_mask, timer_image) -> None:
        # Worker thread only stores ndarray snapshots.
        with self.preview_lock:
            self.latest_preview_arrays["a"] = a_mask.copy()
            self.latest_preview_arrays["b"] = b_mask.copy()
            self.latest_preview_arrays["timer"] = timer_image.copy()

    def _update_preview_image(self) -> None:
        # Tk image objects must be created on the Tk main thread.
        with self.preview_lock:
            a_arr = self.latest_preview_arrays.get("a")
            b_arr = self.latest_preview_arrays.get("b")
            t_arr = self.latest_preview_arrays.get("timer")
        if self.show_preview_a_var.get() and a_arr is not None:
            a_photo = self._build_preview_photo(a_arr)
            self.preview_a_label.configure(image=a_photo, text="")
            self.preview_a_label.image = a_photo
        elif not self.show_preview_a_var.get():
            self.preview_a_label.configure(image="", text="Team A preview hidden")
            self.preview_a_label.image = None

        if self.show_preview_b_var.get() and b_arr is not None:
            b_photo = self._build_preview_photo(b_arr)
            self.preview_b_label.configure(image=b_photo, text="")
            self.preview_b_label.image = b_photo
        elif not self.show_preview_b_var.get():
            self.preview_b_label.configure(image="", text="Team B preview hidden")
            self.preview_b_label.image = None

        if self.show_preview_timer_var.get() and t_arr is not None:
            t_photo = self._build_preview_photo(t_arr)
            self.preview_timer_label.configure(image=t_photo, text="")
            self.preview_timer_label.image = t_photo
        elif not self.show_preview_timer_var.get():
            self.preview_timer_label.configure(image="", text="Timer preview hidden")
            self.preview_timer_label.image = None
        self.root.after(120, self._update_preview_image)

    def _handle_tk_exception(self, exc_type, exc_value, exc_traceback) -> None:
        LOGGER.exception("Tkinter callback exception", exc_info=(exc_type, exc_value, exc_traceback))
        self.last_worker_error = f"GUI error: {exc_value}"

    def _detect_hardware_status(self) -> str:
        try:
            import torch

            return (
                f"Hardware detect: torch={getattr(torch, '__version__', 'unknown')} | "
                f"cuda_available={torch.cuda.is_available()} | "
                f"cuda_devices={torch.cuda.device_count() if torch.cuda.is_available() else 0}"
            )
        except Exception:
            return "Hardware detect: torch not available yet. Install dependencies first."

    def _to_device_ui_value(self, cfg_val: str) -> str:
        normalized = (cfg_val or "auto").strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return "GPU"
        if normalized in {"false", "0", "no", "off"}:
            return "CPU"
        return "Auto"

    def _from_device_ui_value(self, ui_val: str) -> str:
        if ui_val == "GPU":
            return "true"
        if ui_val == "CPU":
            return "false"
        return "auto"

    def _apply_device_fps_luma(self) -> None:
        desired_gpu = self._from_device_ui_value(self.device_var.get())
        desired_fps = max(1, min(30, int(self.fps_var.get())))
        desired_luma = max(150, min(255, int(self.luma_var.get())))
        desired_change_threshold = max(1, int(self.change_threshold_var.get()))

        was_running = self.worker.is_running()
        if was_running:
            self.worker.stop()

        self.app_cfg.ocr_use_gpu = desired_gpu
        self.app_cfg.fps = desired_fps
        self.app_cfg.luma_threshold = desired_luma
        self.app_cfg.pixel_change_count_threshold = desired_change_threshold
        self.hw_status_var.set(self._detect_hardware_status())

        if was_running:
            self.worker.start()
        messagebox.showinfo("Applied", f"Applied device={self.device_var.get()}, FPS={desired_fps}, luma={desired_luma}, pixel_change_threshold={desired_change_threshold}")

    def _save_runtime_defaults(self) -> None:
        settings_path = CONFIG_DIR / "settings.json"
        settings: dict = {}
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except Exception:
                settings = {}

        settings["fps"] = int(self.fps_var.get())
        settings["ocr_use_gpu"] = self._from_device_ui_value(self.device_var.get())
        settings["luma_threshold"] = int(self.luma_var.get())
        settings["pixel_change_count_threshold"] = int(self.change_threshold_var.get())
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        messagebox.showinfo("Saved", f"Saved defaults to {settings_path}")

    def _apply_match(self) -> None:
        series = self.series_var.get()
        self.state.update(
            team_a_name=self.team_a_var.get().strip() or "Team Alpha",
            team_b_name=self.team_b_var.get().strip() or "Team Bravo",
            series_type=series,
            target_games_to_win=target_games_to_win(series),
        )

    def _select_region(self, target: str) -> None:
        titles = {
            "team_a_score": "Select Team A (Left Score) Region",
            "team_b_score": "Select Team B (Right Score) Region",
            "game_timer": "Select Game Timer Region",
        }
        selector = RegionSelector(self.root, titles[target])
        self.root.wait_window(selector)
        if not selector.result:
            return

        left, top, width, height = selector.result
        setattr(self.regions_cfg, target, Region(top=top, left=left, width=width, height=height))
        self._update_region_label()
        if self.overlay_visible:
            self.overlay.show(self.regions_cfg.team_a_score, self.regions_cfg.team_b_score, self.regions_cfg.game_timer)

    def _save_region(self) -> None:
        payload = {
            "team_a_score": asdict(self.regions_cfg.team_a_score),
            "team_b_score": asdict(self.regions_cfg.team_b_score),
            "game_timer": asdict(self.regions_cfg.game_timer),
        }
        path = CONFIG_DIR / "regions.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        messagebox.showinfo("Saved", f"Saved OCR regions to {path}")

    def _toggle_overlay(self) -> None:
        self.overlay_visible = not self.overlay_visible
        if self.overlay_visible:
            self.overlay.show(self.regions_cfg.team_a_score, self.regions_cfg.team_b_score, self.regions_cfg.game_timer)
        else:
            self.overlay.hide()

    def _start_ocr(self) -> None:
        self.last_worker_error = "No worker errors"
        self.error_var.set("Worker: healthy")
        self.worker.start()
        self.run_label.set("OCR: running")

    def _stop_ocr(self) -> None:
        self.worker.stop()
        self.run_label.set("OCR: stopped")

    def _update_region_label(self) -> None:
        a = self.regions_cfg.team_a_score
        b = self.regions_cfg.team_b_score
        t = self.regions_cfg.game_timer
        self.region_label.set(
            f"Team A(left)=({a.left},{a.top},{a.width},{a.height}) | "
            f"Team B(right)=({b.left},{b.top},{b.width},{b.height}) | "
            f"Timer=({t.left},{t.top},{t.width},{t.height})"
        )

    def _refresh_state(self) -> None:
        snap = self.state.snapshot()
        self.error_var.set(f"Worker: {self.last_worker_error}")
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
                    "game_timer": snap.game_timer,
                    "team_a_games": snap.team_a_games,
                    "team_b_games": snap.team_b_games,
                    "series_type": snap.series_type,
                    "target_games_to_win": snap.target_games_to_win,
                    "current_game_number": snap.current_game_number,
                    "match_status": snap.match_status,
                    "last_update": snap.last_update,
                    "ocr_debug": snap.ocr_debug,
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
