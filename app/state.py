from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import threading

from app.config import MatchConfig, target_games_to_win


@dataclass
class MatchState:
    team_a_name: str
    team_b_name: str
    team_a_score: int
    team_b_score: int
    game_timer: str
    team_a_games: int
    team_b_games: int
    series_type: str
    target_games_to_win: int
    current_game_number: int
    last_update: str
    match_status: str
    ocr_debug: dict


class StateManager:
    def __init__(self, path: Path, match_cfg: MatchConfig) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_or_create(match_cfg)

    def _load_or_create(self, match_cfg: MatchConfig) -> MatchState:
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if "game_timer" not in payload:
                    payload["game_timer"] = "5:00"
                return MatchState(**payload)
            except Exception:
                pass

        now = _utc_now()
        return MatchState(
            team_a_name=match_cfg.team_a_name,
            team_b_name=match_cfg.team_b_name,
            team_a_score=0,
            team_b_score=0,
            game_timer="5:00",
            team_a_games=0,
            team_b_games=0,
            series_type=match_cfg.series_type,
            target_games_to_win=target_games_to_win(match_cfg.series_type),
            current_game_number=1,
            last_update=now,
            match_status="idle",
            ocr_debug={},
        )

    def snapshot(self) -> MatchState:
        with self.lock:
            return MatchState(**asdict(self.state))

    def update(self, **changes) -> MatchState:
        with self.lock:
            for key, value in changes.items():
                setattr(self.state, key, value)
            self.state.last_update = _utc_now()
            self._persist_locked()
            return MatchState(**asdict(self.state))

    def reset_current_game_score(self) -> MatchState:
        return self.update(team_a_score=0, team_b_score=0, game_timer="5:00", match_status="idle")

    def award_game(self, side: str) -> MatchState:
        current = self.snapshot()
        if side == "a":
            games = current.team_a_games + 1
            return self.update(team_a_games=games, team_a_score=0, team_b_score=0, game_timer="5:00", current_game_number=current.current_game_number + 1)
        if side == "b":
            games = current.team_b_games + 1
            return self.update(team_b_games=games, team_a_score=0, team_b_score=0, game_timer="5:00", current_game_number=current.current_game_number + 1)
        raise ValueError("side must be 'a' or 'b'")

    def _persist_locked(self) -> None:
        payload = asdict(self.state)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(self.path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
