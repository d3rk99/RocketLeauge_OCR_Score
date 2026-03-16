from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
DEBUG_DIR = ROOT_DIR / "debug_frames"


@dataclass
class Region:
    top: int
    left: int
    width: int
    height: int

    @classmethod
    def from_dict(cls, value: dict) -> "Region":
        return cls(
            top=int(value["top"]),
            left=int(value["left"]),
            width=int(value["width"]),
            height=int(value["height"]),
        )

    def to_dict(self) -> dict:
        return {
            "top": self.top,
            "left": self.left,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class AppConfig:
    fps: int
    min_ocr_confidence: float
    vote_window: int
    stabilize_frames: int
    score_change_cooldown_seconds: float
    game_end_hold_seconds: float
    overlay_state_path: Path
    engine: str
    tesseract_cmd: str | None
    debug_mode: bool
    show_preview: bool
    hotkeys_enabled: bool


@dataclass
class RegionsConfig:
    scoreboard: Region
    team_a_score: Region
    team_b_score: Region


@dataclass
class MatchConfig:
    team_a_name: str
    team_b_name: str
    series_type: str


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _series_target(series_type: str) -> int:
    mapping = {"bo3": 2, "bo5": 3, "bo7": 4}
    if series_type not in mapping:
        raise ValueError(f"Invalid series_type '{series_type}', expected one of {tuple(mapping)}")
    return mapping[series_type]


def load_configs() -> tuple[AppConfig, RegionsConfig, MatchConfig]:
    load_dotenv(ROOT_DIR / ".env")

    settings_data = _read_json(CONFIG_DIR / "settings.json") if (CONFIG_DIR / "settings.json").exists() else _read_json(CONFIG_DIR / "settings.example.json")
    regions_data = _read_json(CONFIG_DIR / "regions.json") if (CONFIG_DIR / "regions.json").exists() else _read_json(CONFIG_DIR / "regions.example.json")

    app_cfg = AppConfig(
        fps=int(settings_data.get("fps", 8)),
        min_ocr_confidence=float(settings_data.get("min_ocr_confidence", 0.55)),
        vote_window=int(settings_data.get("vote_window", 7)),
        stabilize_frames=int(settings_data.get("stabilize_frames", 3)),
        score_change_cooldown_seconds=float(settings_data.get("score_change_cooldown_seconds", 1.0)),
        game_end_hold_seconds=float(settings_data.get("game_end_hold_seconds", 2.0)),
        overlay_state_path=ROOT_DIR / settings_data.get("overlay_state_path", "data/match_state.json"),
        engine=os.getenv("OCR_ENGINE", settings_data.get("ocr_engine", "easyocr")),
        tesseract_cmd=os.getenv("TESSERACT_CMD", settings_data.get("tesseract_cmd")),
        debug_mode=str(os.getenv("DEBUG_MODE", settings_data.get("debug_mode", False))).lower() in ("1", "true", "yes", "on"),
        show_preview=str(os.getenv("SHOW_PREVIEW", settings_data.get("show_preview", False))).lower() in ("1", "true", "yes", "on"),
        hotkeys_enabled=str(os.getenv("HOTKEYS_ENABLED", settings_data.get("hotkeys_enabled", True))).lower() in ("1", "true", "yes", "on"),
    )

    regions_cfg = RegionsConfig(
        scoreboard=Region.from_dict(regions_data["scoreboard"]),
        team_a_score=Region.from_dict(regions_data["team_a_score"]),
        team_b_score=Region.from_dict(regions_data["team_b_score"]),
    )

    match_cfg = MatchConfig(
        team_a_name=settings_data.get("team_a_name", "Team Alpha"),
        team_b_name=settings_data.get("team_b_name", "Team Bravo"),
        series_type=settings_data.get("series_type", "bo5"),
    )

    _series_target(match_cfg.series_type)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    return app_cfg, regions_cfg, match_cfg


def target_games_to_win(series_type: str) -> int:
    return _series_target(series_type)
