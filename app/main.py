from __future__ import annotations

import argparse
import logging
import threading
import time

import cv2

from app.capture import ScreenCapturer
from app.config import DEBUG_DIR, LOG_DIR, RegionsConfig, load_configs, parse_ocr_gpu_preference
from app.detector import ScoreDetector, ScoreReading
from app.gui import ControlGUI
from app.logging_utils import setup_logging
from app.ocr import build_engine, preprocess_for_ocr, preprocess_luma_mask, save_debug_crop
from app.state import StateManager


LOGGER = logging.getLogger("main")


def _validate_regions(regions_cfg: RegionsConfig) -> None:
    for name, region in {
        "team_a_score": regions_cfg.team_a_score,
        "team_b_score": regions_cfg.team_b_score,
        "game_timer": regions_cfg.game_timer,
    }.items():
        if region.width <= 0 or region.height <= 0:
            raise ValueError(f"Invalid {name} region size: width={region.width}, height={region.height}")
        if region.left < 0 or region.top < 0:
            raise ValueError(f"Invalid {name} region position: left={region.left}, top={region.top}")


def _start_hotkeys(state: StateManager) -> None:
    try:
        import keyboard

        keyboard.add_hotkey("ctrl+alt+r", lambda: _safe_reset(state))
        keyboard.add_hotkey("ctrl+alt+1", lambda: _safe_award(state, "a"))
        keyboard.add_hotkey("ctrl+alt+2", lambda: _safe_award(state, "b"))
        LOGGER.info("Hotkeys enabled: Ctrl+Alt+R reset, Ctrl+Alt+1 award A, Ctrl+Alt+2 award B")
    except Exception as exc:
        LOGGER.error("Could not initialize global hotkeys: %s", exc)


def _start_cli_thread(state: StateManager) -> None:
    def _runner() -> None:
        while True:
            try:
                cmd = input().strip().lower()
            except EOFError:
                return
            except Exception:
                LOGGER.exception("CLI input thread hit an unexpected error")
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
    cv2.putText(preview, f"A mask: {a_text}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.putText(preview, f"B mask: {b_text}", (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.imshow("Rocket League OCR Debug", preview)
    cv2.waitKey(1)


def _safe_mask(region_name: str, crop, luma_threshold: int):
    if crop is None or crop.size == 0:
        raise RuntimeError(f"Capture for {region_name} is empty. Check region coordinates.")
    return preprocess_luma_mask(crop, luma_threshold)


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

    try:
        _validate_regions(regions_cfg)
    except Exception as exc:
        LOGGER.exception("Invalid capture region configuration: %s", exc)
        raise SystemExit(2) from exc

    if args.gui:
        ControlGUI(app_cfg, regions_cfg, match_cfg).run()
        return

    state = StateManager(app_cfg.overlay_state_path, match_cfg)
    try:
        capturer = ScreenCapturer(regions_cfg)
        engine = build_engine(
            app_cfg.engine,
            tesseract_cmd=app_cfg.tesseract_cmd,
            easyocr_use_gpu=parse_ocr_gpu_preference(app_cfg.ocr_use_gpu),
        )
        detector = ScoreDetector(app_cfg, state)
    except Exception as exc:
        LOGGER.exception("Startup failure while initializing capturer/OCR/detector: %s", exc)
        raise SystemExit(3) from exc

    if app_cfg.hotkeys_enabled:
        _start_hotkeys(state)
    _start_cli_thread(state)

    poll_delay = 1.0 / max(1, app_cfg.fps)
    consecutive_failures = 0
    last_failure_log_ts = 0.0

    while True:
        start = time.perf_counter()
        try:
            result = capturer.grab()
            a_mask = _safe_mask("team_a_score", result.team_a_crop, app_cfg.luma_threshold)
            b_mask = _safe_mask("team_b_score", result.team_b_crop, app_cfg.luma_threshold)
            t_pp = preprocess_for_ocr(result.timer_crop)

            if app_cfg.debug_mode:
                save_debug_crop(a_mask, DEBUG_DIR, "team_a_mask")
                save_debug_crop(b_mask, DEBUG_DIR, "team_b_mask")
                save_debug_crop(t_pp, DEBUG_DIR, "timer")

            t_res = engine.read_timer(t_pp)
            detector.process(
                ScoreReading(
                    a_mask=a_mask,
                    b_mask=b_mask,
                    timer_value=t_res.timer,
                    timer_conf=t_res.confidence,
                    timer_raw=t_res.raw_text,
                )
            )

            if app_cfg.show_preview:
                _draw_preview(
                    result.full_frame,
                    str(cv2.countNonZero(a_mask)),
                    str(cv2.countNonZero(b_mask)),
                )

            consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            now = time.time()
            # Log first few failures immediately, then throttle to avoid spam.
            if consecutive_failures <= 3 or (now - last_failure_log_ts) >= 2.0:
                LOGGER.exception(
                    "Processing loop failure (count=%s). Common causes: bad regions, lost display capture, OCR backend crash.",
                    consecutive_failures,
                )
                last_failure_log_ts = now
            time.sleep(0.2)

        elapsed = time.perf_counter() - start
        to_sleep = poll_delay - elapsed
        if to_sleep > 0:
            time.sleep(to_sleep)


if __name__ == "__main__":
    run()
