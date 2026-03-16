from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import mss
import numpy as np

from app.config import RegionsConfig


@dataclass
class CaptureResult:
    full_frame: np.ndarray
    team_a_crop: np.ndarray
    team_b_crop: np.ndarray


class ScreenCapturer:
    def __init__(self, regions: RegionsConfig) -> None:
        self.regions = regions
        self.sct = mss.mss()

    def grab(self) -> CaptureResult:
        scoreboard = self.regions.scoreboard.to_dict()
        raw = np.array(self.sct.grab(scoreboard))
        frame_bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

        a = self._crop(frame_bgr, self.regions.team_a_score)
        b = self._crop(frame_bgr, self.regions.team_b_score)
        return CaptureResult(full_frame=frame_bgr, team_a_crop=a, team_b_crop=b)

    @staticmethod
    def _crop(frame: np.ndarray, region: Any) -> np.ndarray:
        x1 = max(region.left, 0)
        y1 = max(region.top, 0)
        x2 = min(region.left + region.width, frame.shape[1])
        y2 = min(region.top + region.height, frame.shape[0])
        return frame[y1:y2, x1:x2].copy()
