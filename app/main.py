from __future__ import annotations

import argparse
import logging
import threading
import time

import cv2

from app.capture import ScreenCapturer
from app.config import DEBUG_DIR, LOG_DIR, load_configs
from app.detector import ScoreDetector, ScoreReading
from app.gui import ControlGUI
from app.logging_utils import setup_logging
from app.ocr import build_engine, preprocess_for_ocr, save_debug_crop
from app.state import StateManager


LOGGER = logging.getLogger("main")


def _start_hotkeys(state: StateManager) -> None:
    try:
        import keyboard

        keyboard.add_hotkey("ctrl+alt+r", lambda: _safe_reset(state))
        keyboard.add_hotkey("ctrl+alt+1", lambda: _safe_award(state, "a"))
        keyboard.add_hotkey("ctrl+alt+2", lambda: _safe_award(state, "b"))
        LOGGER.info("Hotkeys enabled: Ctrl+Alt+R reset, Ctrl+Alt+1 award A, Ctrl+Alt+2 award B")
    except Exception as exc:
        LOGGER.warning("Could not initialize global hotkeys: %s", exc)


def _start_cli_thread(state: StateManager) -> None:
    def _runner() -> None:
        while True:
            try:
                cmd = input().strip().lower()
            except EOFError:
                return
            if cmd in {"reset", "r"}:
                _safe_reset(state)
            elif cmd in {"award a", "a"}:
                _safe_award(state, "a")
            elif cmd in {"award b", "b"}:
                _safe_award(state, "b")

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()


def _safe_reset(state: StateManager) -> None:
    state.reset_current_game_score()
    LOGGER.info("Manual reset: current game score set to 0-0")


def _safe_award(state: StateManager, side: str) -> None:
    state.award_game(side)
    LOGGER.info("Manual award: side %s received a game win", side)


def _draw_preview(frame, a_text: str, b_text: str) -> None:
    preview = frame.copy()
    cv2.putText(preview, f"A: {a_text}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.putText(preview, f"B: {b_text}", (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.imshow("Rocket League OCR Debug", preview)
    cv2.waitKey(1)


def run() -> None:
    parser = argparse.ArgumentParser(description="Rocket League OCR score tracker")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--gui", action="store_true", help="Launch Tk GUI control panel")
    args = parser.parse_args()

    app_cfg, regions_cfg, match_cfg = load_configs()
    if args.debug:
        app_cfg.debug_mode = True

    setup_logging(LOG_DIR, debug=app_cfg.debug_mode)
    LOGGER.info("Starting with OCR engine=%s fps=%s", app_cfg.engine, app_cfg.fps)

    if args.gui:
        ControlGUI(app_cfg, regions_cfg, match_cfg).run()
        return

    state = StateManager(app_cfg.overlay_state_path, match_cfg)
    capturer = ScreenCapturer(regions_cfg)
    engine = build_engine(app_cfg.engine, tesseract_cmd=app_cfg.tesseract_cmd)
    detector = ScoreDetector(app_cfg, state)

    if app_cfg.hotkeys_enabled:
        _start_hotkeys(state)
    _start_cli_thread(state)

    poll_delay = 1.0 / max(1, app_cfg.fps)

    while True:
        start = time.perf_counter()
        result = capturer.grab()

        a_pp = preprocess_for_ocr(result.team_a_crop)
        b_pp = preprocess_for_ocr(result.team_b_crop)

        if app_cfg.debug_mode:
            save_debug_crop(a_pp, DEBUG_DIR, "team_a")
            save_debug_crop(b_pp, DEBUG_DIR, "team_b")

        a_res = engine.read_score(a_pp)
        b_res = engine.read_score(b_pp)

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

        if app_cfg.show_preview:
            _draw_preview(result.full_frame, f"{a_res.value}/{a_res.confidence:.2f}", f"{b_res.value}/{b_res.confidence:.2f}")

        elapsed = time.perf_counter() - start
        to_sleep = poll_delay - elapsed
        if to_sleep > 0:
            time.sleep(to_sleep)


if __name__ == "__main__":
    run()
