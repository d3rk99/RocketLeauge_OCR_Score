from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import mss
import numpy as np

from app.config import Region, RegionsConfig


@dataclass
class CaptureResult:
    full_frame: np.ndarray
    team_a_crop: np.ndarray
    team_b_crop: np.ndarray
    timer_crop: np.ndarray


class ScreenCapturer:
    def __init__(self, regions: RegionsConfig) -> None:
        self.regions = regions
        self.sct = mss.mss()

    def grab(self) -> CaptureResult:
        # Capture each OCR region independently so config is explicitly split into:
        # 1) Team A score 2) Team B score 3) Game timer
        a = self._grab_region(self.regions.team_a_score)
        b = self._grab_region(self.regions.team_b_score)
        timer = self._grab_region(self.regions.game_timer)

        preview = self._grab_union_preview(
            [self.regions.team_a_score, self.regions.team_b_score, self.regions.game_timer]
        )
        return CaptureResult(full_frame=preview, team_a_crop=a, team_b_crop=b, timer_crop=timer)

    def _grab_region(self, region: Region) -> np.ndarray:
        raw = np.array(self.sct.grab(region.to_dict()))
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

    def _grab_union_preview(self, regions: list[Region]) -> np.ndarray:
        left = min(r.left for r in regions)
        top = min(r.top for r in regions)
        right = max(r.left + r.width for r in regions)
        bottom = max(r.top + r.height for r in regions)

        union = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        raw = np.array(self.sct.grab(union))
        frame = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

        for r, color in zip(regions, [(255, 100, 100), (100, 180, 255), (130, 255, 130)]):
            x1 = r.left - left
            y1 = r.top - top
            x2 = x1 + r.width
            y2 = y1 + r.height
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        return frame

    @staticmethod
    def _crop(frame: np.ndarray, region: Any) -> np.ndarray:
        x1 = max(region.left, 0)
        y1 = max(region.top, 0)
        x2 = min(region.left + region.width, frame.shape[1])
        y2 = min(region.top + region.height, frame.shape[0])
        return frame[y1:y2, x1:x2].copy()
