from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import time

from app.config import AppConfig
from app.state import StateManager


@dataclass
class ScoreReading:
    a_value: int | None
    b_value: int | None
    timer_value: str | None
    a_conf: float
    b_conf: float
    timer_conf: float
    a_raw: str
    b_raw: str
    timer_raw: str


class ScoreDetector:
    def __init__(self, config: AppConfig, state: StateManager) -> None:
        self.cfg = config
        self.state = state
        self.a_hist: deque[int] = deque(maxlen=config.vote_window)
        self.b_hist: deque[int] = deque(maxlen=config.vote_window)
        self.timer_hist: deque[str] = deque(maxlen=config.vote_window)
        self.last_score_change_ts = 0.0
        self.last_timer_update_ts = 0.0
        self.game_end_candidate_ts: float | None = None
        self.last_increment_game_number = state.snapshot().current_game_number

    def process(self, reading: ScoreReading) -> None:
        if reading.a_value is not None and reading.a_conf >= self.cfg.min_ocr_confidence:
            self.a_hist.append(reading.a_value)
        if reading.b_value is not None and reading.b_conf >= self.cfg.min_ocr_confidence:
            self.b_hist.append(reading.b_value)
        if reading.timer_value is not None and reading.timer_conf >= self.cfg.min_ocr_confidence:
            self.timer_hist.append(reading.timer_value)

        stable_a = self._stable_value(self.a_hist)
        stable_b = self._stable_value(self.b_hist)
        stable_timer = self._stable_value(self.timer_hist)

        current = self.state.snapshot()
        debug_payload = {
            "ocr": {
                "a_raw": reading.a_raw,
                "b_raw": reading.b_raw,
                "timer_raw": reading.timer_raw,
                "a_conf": reading.a_conf,
                "b_conf": reading.b_conf,
                "timer_conf": reading.timer_conf,
            },
            "stable": {"a": stable_a, "b": stable_b, "timer": stable_timer},
        }

        if stable_timer is not None and stable_timer != current.game_timer:
            now = time.time()
            if now - self.last_timer_update_ts >= 0.25:
                self.state.update(game_timer=stable_timer, ocr_debug=debug_payload)
                self.last_timer_update_ts = now
                current = self.state.snapshot()

        if stable_a is None or stable_b is None:
            self.state.update(ocr_debug=debug_payload)
            return

        now = time.time()
        score_changed = stable_a != current.team_a_score or stable_b != current.team_b_score
        if score_changed and now - self.last_score_change_ts >= self.cfg.score_change_cooldown_seconds:
            self.state.update(team_a_score=stable_a, team_b_score=stable_b, match_status="live", ocr_debug=debug_payload)
            self.last_score_change_ts = now
            current = self.state.snapshot()

        self._evaluate_game_end(current, now, debug_payload)

    def _evaluate_game_end(self, current, now: float, debug_payload: dict) -> None:
        was_live = current.match_status in {"live", "game_final"}
        had_points = current.team_a_score > 0 or current.team_b_score > 0
        reset_like = current.team_a_score == 0 and current.team_b_score == 0

        if was_live and had_points and not reset_like:
            self.game_end_candidate_ts = now

        if self.game_end_candidate_ts and reset_like:
            if now - self.game_end_candidate_ts >= self.cfg.game_end_hold_seconds:
                self._finalize_game_once(current, debug_payload)
                self.game_end_candidate_ts = None

        if current.team_a_games >= current.target_games_to_win or current.team_b_games >= current.target_games_to_win:
            self.state.update(match_status="series_final", ocr_debug=debug_payload)

    def _finalize_game_once(self, current, debug_payload: dict) -> None:
        if current.current_game_number == self.last_increment_game_number + 1:
            return

        if current.team_a_score == current.team_b_score:
            self.state.update(match_status="game_final", ocr_debug=debug_payload)
            return

        winner = "a" if current.team_a_score > current.team_b_score else "b"
        if winner == "a":
            self.state.update(
                team_a_games=current.team_a_games + 1,
                team_a_score=0,
                team_b_score=0,
                game_timer="5:00",
                match_status="game_final",
                current_game_number=current.current_game_number + 1,
                ocr_debug=debug_payload,
            )
        else:
            self.state.update(
                team_b_games=current.team_b_games + 1,
                team_a_score=0,
                team_b_score=0,
                game_timer="5:00",
                match_status="game_final",
                current_game_number=current.current_game_number + 1,
                ocr_debug=debug_payload,
            )
        self.last_increment_game_number = current.current_game_number

    def _stable_value(self, values: deque):
        if len(values) < self.cfg.stabilize_frames:
            return None
        most_common, count = Counter(values).most_common(1)[0]
        if count < self.cfg.stabilize_frames:
            return None
        return most_common
