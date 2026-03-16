from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import re
import time

import cv2
import numpy as np


@dataclass
class OCRResult:
    value: int | None
    confidence: float
    raw_text: str


class OCREngine(ABC):
    @abstractmethod
    def read_score(self, image: np.ndarray) -> OCRResult:
        raise NotImplementedError


class EasyOCREngine(OCREngine):
    def __init__(self) -> None:
        import easyocr

        self.reader = easyocr.Reader(["en"], gpu=False)

    def read_score(self, image: np.ndarray) -> OCRResult:
        out = self.reader.readtext(image, detail=1, paragraph=False, allowlist="0123456789")
        if not out:
            return OCRResult(value=None, confidence=0.0, raw_text="")

        text_parts = []
        best_conf = 0.0
        for _, txt, conf in out:
            text_parts.append(txt)
            best_conf = max(best_conf, float(conf))

        cleaned = "".join(text_parts)
        value = parse_score_text(cleaned)
        return OCRResult(value=value, confidence=best_conf, raw_text=cleaned)


class TesseractEngine(OCREngine):
    def __init__(self, tesseract_cmd: str | None = None) -> None:
        import pytesseract

        self.pytesseract = pytesseract
        if tesseract_cmd:
            self.pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def read_score(self, image: np.ndarray) -> OCRResult:
        config = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
        text = self.pytesseract.image_to_string(image, config=config)
        data = self.pytesseract.image_to_data(image, config=config, output_type=self.pytesseract.Output.DICT)

        confs = []
        for raw_conf in data.get("conf", []):
            try:
                c = float(raw_conf)
                if c >= 0:
                    confs.append(c / 100.0)
            except Exception:
                continue

        confidence = max(confs) if confs else 0.0
        value = parse_score_text(text)
        return OCRResult(value=value, confidence=confidence, raw_text=text.strip())


def parse_score_text(text: str) -> int | None:
    digits = re.findall(r"\d+", text)
    if not digits:
        return None
    try:
        return int(digits[0])
    except ValueError:
        return None


def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    upscaled = cv2.resize(thresh, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    kernel = np.ones((2, 2), np.uint8)
    morph = cv2.morphologyEx(upscaled, cv2.MORPH_CLOSE, kernel)
    return morph


def build_engine(name: str, tesseract_cmd: str | None = None) -> OCREngine:
    normalized = name.lower().strip()
    if normalized == "easyocr":
        return EasyOCREngine()
    if normalized == "tesseract":
        return TesseractEngine(tesseract_cmd=tesseract_cmd)
    raise ValueError(f"Unsupported OCR engine '{name}'")


def save_debug_crop(image: np.ndarray, output_dir: Path, prefix: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{prefix}_{int(time.time() * 1000)}.png"
    cv2.imwrite(str(path), image)
    return path
