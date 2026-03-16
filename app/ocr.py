from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import importlib
import logging
import os
import re
import subprocess
import sys
import time
import warnings

import cv2
import numpy as np


LOGGER = logging.getLogger("ocr")
CUDA_REPAIR_ATTEMPTED = False


@dataclass
class OCRResult:
    value: int | None
    confidence: float
    raw_text: str


@dataclass
class TimerOCRResult:
    timer: str | None
    confidence: float
    raw_text: str


class OCREngine(ABC):
    @abstractmethod
    def read_score(self, image: np.ndarray, side: str = "team_a") -> OCRResult:
        raise NotImplementedError

    @abstractmethod
    def read_timer(self, image: np.ndarray) -> TimerOCRResult:
        raise NotImplementedError


def _has_nvidia_gpu() -> bool:
    try:
        proc = subprocess.run(["nvidia-smi"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
        return proc.returncode == 0
    except Exception:
        return False


def _try_repair_torch_cuda() -> None:
    global CUDA_REPAIR_ATTEMPTED
    if CUDA_REPAIR_ATTEMPTED:
        return
    CUDA_REPAIR_ATTEMPTED = True

    auto_fix = os.getenv("OCR_AUTO_TORCH_CUDA", "true").strip().lower() in {"1", "true", "yes", "on"}
    if not auto_fix or not _has_nvidia_gpu():
        return

    LOGGER.warning("NVIDIA GPU detected but torch CUDA unavailable. Attempting one-time CUDA torch repair...")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "torch",
        "torchvision",
        "--index-url",
        "https://download.pytorch.org/whl/cu121",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0:
            LOGGER.warning("CUDA torch repair failed (exit=%s).", proc.returncode)
            return
        importlib.invalidate_caches()
        if "torch" in sys.modules:
            del sys.modules["torch"]
        LOGGER.info("CUDA torch repair command completed. Rechecking CUDA availability...")
    except Exception as exc:
        LOGGER.warning("CUDA torch repair attempt failed: %s", exc)


def resolve_easyocr_gpu(use_gpu: bool | None) -> bool:
    if use_gpu is not None:
        if use_gpu:
            try:
                import torch

                if torch.cuda.is_available():
                    LOGGER.info("EasyOCR GPU explicitly enabled (CUDA available).")
                    return True
                _try_repair_torch_cuda()
                import torch as torch_retry
                if torch_retry.cuda.is_available():
                    LOGGER.info("EasyOCR GPU enabled after CUDA torch repair.")
                    return True
                LOGGER.warning("EasyOCR GPU requested but CUDA is not available; falling back to CPU.")
                return False
            except Exception as exc:
                LOGGER.warning("EasyOCR GPU requested but torch CUDA check failed (%s); falling back to CPU.", exc)
                return False
        LOGGER.info("EasyOCR GPU explicitly disabled; using CPU.")
        return False

    try:
        import torch

        has_cuda = bool(torch.cuda.is_available())
        if not has_cuda:
            _try_repair_torch_cuda()
            import torch as torch_retry
            has_cuda = bool(torch_retry.cuda.is_available())
            torch = torch_retry

        LOGGER.info(
            "EasyOCR torch diagnostics: version=%s cuda_version=%s cuda_available=%s device_count=%s",
            getattr(torch, "__version__", "unknown"),
            getattr(getattr(torch, "version", None), "cuda", None),
            has_cuda,
            torch.cuda.device_count() if has_cuda else 0,
        )
        if has_cuda:
            LOGGER.info("EasyOCR auto GPU detection: CUDA available, enabling GPU.")
            return True
        LOGGER.warning("EasyOCR auto GPU detection: CUDA not available, using CPU.")
        return False
    except Exception as exc:
        LOGGER.warning("EasyOCR auto GPU detection failed (%s); using CPU.", exc)
        return False


class EasyOCREngine(OCREngine):
    def __init__(self, use_gpu: bool | None = None) -> None:
        import easyocr

        gpu = resolve_easyocr_gpu(use_gpu)
        if not gpu:
            warnings.filterwarnings(
                "ignore",
                message=".*pin_memory.*no accelerator is found.*",
                category=UserWarning,
            )
            logging.getLogger("easyocr.easyocr").setLevel(logging.ERROR)
        self.reader = easyocr.Reader(["en"], gpu=gpu)

    def read_score(self, image: np.ndarray, side: str = "team_a") -> OCRResult:
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

    def read_timer(self, image: np.ndarray) -> TimerOCRResult:
        out = self.reader.readtext(image, detail=1, paragraph=False, allowlist="0123456789:;.")
        if not out:
            return TimerOCRResult(timer=None, confidence=0.0, raw_text="")

        text_parts = []
        best_conf = 0.0
        for _, txt, conf in out:
            text_parts.append(txt)
            best_conf = max(best_conf, float(conf))

        cleaned = "".join(text_parts)
        timer = parse_game_timer_text(cleaned)
        return TimerOCRResult(timer=timer, confidence=best_conf, raw_text=cleaned)


class TesseractEngine(OCREngine):
    def __init__(self, tesseract_cmd: str | None = None) -> None:
        import pytesseract

        self.pytesseract = pytesseract
        if tesseract_cmd:
            self.pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def read_score(self, image: np.ndarray, side: str = "team_a") -> OCRResult:
        config = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
        text = self.pytesseract.image_to_string(image, config=config)
        data = self.pytesseract.image_to_data(image, config=config, output_type=self.pytesseract.Output.DICT)
        confs = _extract_tesseract_confidences(data)
        confidence = max(confs) if confs else 0.0
        value = parse_score_text(text)
        return OCRResult(value=value, confidence=confidence, raw_text=text.strip())

    def read_timer(self, image: np.ndarray) -> TimerOCRResult:
        config = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789:;."
        text = self.pytesseract.image_to_string(image, config=config)
        data = self.pytesseract.image_to_data(image, config=config, output_type=self.pytesseract.Output.DICT)
        confs = _extract_tesseract_confidences(data)
        confidence = max(confs) if confs else 0.0
        timer = parse_game_timer_text(text)
        return TimerOCRResult(timer=timer, confidence=confidence, raw_text=text.strip())


def _extract_tesseract_confidences(data: dict) -> list[float]:
    confs: list[float] = []
    for raw_conf in data.get("conf", []):
        try:
            c = float(raw_conf)
            if c >= 0:
                confs.append(c / 100.0)
        except Exception:
            continue
    return confs


def parse_score_text(text: str) -> int | None:
    digits = re.findall(r"\d+", text)
    if not digits:
        return None
    try:
        return int(digits[0])
    except ValueError:
        return None


def parse_game_timer_text(text: str) -> str | None:
    cleaned = text.replace(" ", "").strip()
    if not cleaned:
        return None

    # Normalize common OCR substitutions before parsing.
    normalized = cleaned.upper()
    normalized = normalized.replace("O", "0").replace("I", "1").replace("L", "1").replace("S", "5")

    # Preferred format: M:SS / MM:SS with tolerated separator variants.
    match = re.search(r"(\d{1,2})[:;\.\-](\d{2})", normalized)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        if seconds <= 59:
            return f"{minutes}:{seconds:02d}"

    # Fallback when OCR drops separator entirely (e.g. '257' => '2:57', '301' => '3:01').
    digits = re.sub(r"\D", "", normalized)
    if len(digits) == 3:
        minutes = int(digits[0])
        seconds = int(digits[1:])
        if seconds <= 59:
            return f"{minutes}:{seconds:02d}"
    if len(digits) == 4:
        minutes = int(digits[:2])
        seconds = int(digits[2:])
        if seconds <= 59:
            return f"{minutes}:{seconds:02d}"

    return None


def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    upscaled = cv2.resize(thresh, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    kernel = np.ones((2, 2), np.uint8)
    morph = cv2.morphologyEx(upscaled, cv2.MORPH_CLOSE, kernel)
    return morph


def preprocess_luma_mask(image: np.ndarray, luma_threshold: int) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, int(luma_threshold), 255, cv2.THRESH_BINARY)
    return mask


def build_engine(
    name: str,
    tesseract_cmd: str | None = None,
    easyocr_use_gpu: bool | None = None,
) -> OCREngine:
    normalized = name.lower().strip()
    if normalized == "easyocr":
        return EasyOCREngine(use_gpu=easyocr_use_gpu)
    if normalized == "tesseract":
        return TesseractEngine(tesseract_cmd=tesseract_cmd)
    raise ValueError(f"Unsupported OCR engine '{name}'")


def save_debug_crop(image: np.ndarray, output_dir: Path, prefix: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{prefix}_{int(time.time() * 1000)}.png"
    cv2.imwrite(str(path), image)
    return path
