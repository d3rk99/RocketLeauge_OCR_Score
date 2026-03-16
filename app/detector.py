from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np

from app.config import AppConfig
from app.state import MatchState, StateManager


@dataclass
class ScoreReading:
    a_mask: np.ndarray
    b_mask: np.ndarray
    timer_value: str | None
    timer_conf: float
    timer_raw: str


class ScoreDetector:
    def __init__(self, config: AppConfig, state: StateManager) -> None:
        self.cfg = config
        self.state = state
        self.last_a_mask: np.ndarray | None = None
        self.last_b_mask: np.ndarray | None = None
        self.last_a_increment_ms = 0
        self.last_b_increment_ms = 0
        self.no_white_since_ms: int | None = None
        self.game_ended_waiting_for_white = False
        self.last_timer_update_ts = 0.0

    def process(self, reading: ScoreReading) -> None:
        now_ms = int(time.time() * 1000)
        current = self.state.snapshot()

        a_white = int(np.count_nonzero(reading.a_mask))
        b_white = int(np.count_nonzero(reading.b_mask))
        a_changed_pixels = self._changed_pixels(self.last_a_mask, reading.a_mask)
        b_changed_pixels = self._changed_pixels(self.last_b_mask, reading.b_mask)

        if reading.timer_value is not None and reading.timer_conf >= self.cfg.min_ocr_confidence:
            now = time.time()
            if now - self.last_timer_update_ts >= 0.25:
                self.state.update(game_timer=reading.timer_value)
                self.last_timer_update_ts = now
                current = self.state.snapshot()

        debug_payload = {
            "tracking_mode": "pixel_change_count",
            "luma_threshold": self.cfg.luma_threshold,
            "pixel_change_count_threshold": self.cfg.pixel_change_count_threshold,
            "a_white_pixels": a_white,
            "b_white_pixels": b_white,
            "a_changed_pixels": a_changed_pixels,
            "b_changed_pixels": b_changed_pixels,
            "timer_raw": reading.timer_raw,
            "timer_conf": reading.timer_conf,
            "timer_parsed": reading.timer_value,
            "timer_parse_mismatch": bool(reading.timer_raw and reading.timer_value is None),
            "game_ended_waiting_for_white": self.game_ended_waiting_for_white,
        }

        if self.game_ended_waiting_for_white:
            if a_white >= self.cfg.white_pixel_min_count and b_white >= self.cfg.white_pixel_min_count:
                self.game_ended_waiting_for_white = False
                self.no_white_since_ms = None
                self.last_a_mask = reading.a_mask
                self.last_b_mask = reading.b_mask
                self.state.update(match_status="live", ocr_debug=debug_payload)
            else:
                self.state.update(ocr_debug=debug_payload)
            return

        self._track_score_increment(current, now_ms, a_changed_pixels, b_changed_pixels, a_white, b_white, debug_payload)
        current = self.state.snapshot()

        both_dark = a_white < self.cfg.white_pixel_min_count and b_white < self.cfg.white_pixel_min_count
        if both_dark:
            if self.no_white_since_ms is None:
                self.no_white_since_ms = now_ms
            elif now_ms - self.no_white_since_ms >= self.cfg.game_end_no_white_ms:
                self._finalize_game(current, debug_payload)
                self.game_ended_waiting_for_white = True
                self.no_white_since_ms = None
        else:
            self.no_white_since_ms = None
            self.state.update(match_status="live", ocr_debug=debug_payload)

        self.last_a_mask = reading.a_mask
        self.last_b_mask = reading.b_mask

    def _track_score_increment(
        self,
        current: MatchState,
        now_ms: int,
        a_changed_pixels: int,
        b_changed_pixels: int,
        a_white: int,
        b_white: int,
        debug_payload: dict,
    ) -> None:
        changed = False
        if (
            a_white >= self.cfg.white_pixel_min_count
            and a_changed_pixels >= self.cfg.pixel_change_count_threshold
            and now_ms - self.last_a_increment_ms >= self.cfg.score_increment_cooldown_ms
        ):
            self.state.update(team_a_score=current.team_a_score + 1, match_status="live", ocr_debug=debug_payload)
            self.last_a_increment_ms = now_ms
            changed = True

        current = self.state.snapshot()
        if (
            b_white >= self.cfg.white_pixel_min_count
            and b_changed_pixels >= self.cfg.pixel_change_count_threshold
            and now_ms - self.last_b_increment_ms >= self.cfg.score_increment_cooldown_ms
        ):
            self.state.update(team_b_score=current.team_b_score + 1, match_status="live", ocr_debug=debug_payload)
            self.last_b_increment_ms = now_ms
            changed = True

        if not changed:
            self.state.update(ocr_debug=debug_payload)

    def _finalize_game(self, current: MatchState, debug_payload: dict) -> None:
        if current.team_a_score == current.team_b_score:
            self.state.update(team_a_score=0, team_b_score=0, game_timer="5:00", match_status="game_final", ocr_debug=debug_payload)
            return

        updates = {
            "team_a_score": 0,
            "team_b_score": 0,
            "game_timer": "5:00",
            "match_status": "game_final",
            "current_game_number": current.current_game_number + 1,
            "ocr_debug": debug_payload,
        }
        if current.team_a_score > current.team_b_score:
            updates["team_a_games"] = current.team_a_games + 1
        else:
            updates["team_b_games"] = current.team_b_games + 1

        new_state = self.state.update(**updates)
        if new_state.team_a_games >= new_state.target_games_to_win or new_state.team_b_games >= new_state.target_games_to_win:
            self.state.update(match_status="series_final", ocr_debug=debug_payload)

    @staticmethod
    def _changed_pixels(previous: np.ndarray | None, current: np.ndarray) -> int:
        if previous is None or previous.shape != current.shape:
            return 0
        diff = np.bitwise_xor(previous, current)
        return int(np.count_nonzero(diff))
