# Rocket League OCR Score Tracker (Windows-first)

A production-oriented starter project for broadcast operators who need a live Rocket League scoreboard feed from on-screen capture.

This tool:
- captures a configurable scoreboard region from your screen,
- reads score digits via OCR (EasyOCR or Tesseract),
- smooths noisy OCR output,
- tracks per-game and per-series progress with a simple state machine,
- writes canonical JSON to `data/match_state.json`, and
- powers an OBS-ready HTML overlay from that JSON.

---

## Repository structure

```text
app/
  main.py
  capture.py
  ocr.py
  state.py
  detector.py
  config.py
  logging_utils.py
overlay/
  index.html
  style.css
  overlay.js
config/
  regions.example.json
  settings.example.json
data/
  match_state.json
  score_reference/
    team_a/0..20/
    team_b/0..20/
scripts/
  install.bat
  run.bat
requirements.txt
.env.example
README.md
```

---

## Requirements

- Windows 10/11 (primary target)
- Python 3.11+
- A GPU is optional (EasyOCR can run CPU-only)
- Optional: Tesseract OCR installed system-wide if you choose the Tesseract backend

---

## Install

1. Open Command Prompt in project root.
2. Run:

```bat
scripts\install.bat
```

This script:
- detects Python 3.11+ (`py -3.11`, `py -3`, `py`, then `python`),
- attempts automatic Python 3.11 install with `winget` if Python is missing,
- creates `venv`, upgrades pip, and installs dependencies,
- if `nvidia-smi` is detected, attempts CUDA-enabled PyTorch install for EasyOCR GPU usage,
- prints Torch CUDA diagnostics (`torch.version.cuda`, `torch.cuda.is_available`, device count),
- checks if `tesseract` is on PATH and prints guidance.

`install.bat` and `run.bat` resolve paths relative to the repository root, so they work even when launched from outside the repo directory. `run.bat` launches with `python -m app.main` from the repo root to avoid import-path issues. Both scripts also pause on success and failure so the window stays open for confirmation/troubleshooting.

---

## Configuration

### 1) Copy config samples

```bat
copy config\regions.example.json config\regions.json
copy config\settings.example.json config\settings.json
copy .env.example .env
```

### 2) Edit capture coordinates (`config/regions.json`)

All coordinates are intentionally externalized (no hardcoded monitor resolution assumptions).

- `team_a_score`: **absolute** screen region for Team A (left score)
- `team_b_score`: **absolute** screen region for Team B (right score)
- `game_timer`: **absolute** screen region for the center game timer (e.g., `2:43`)

> Calibration is required for your HUD scale, game resolution, and observer layout.

### 3) Edit match settings (`config/settings.json`)

Set:
- `team_a_name`, `team_b_name`
- `series_type` (`bo3`, `bo5`, `bo7`)
- OCR and smoothing values (`min_ocr_confidence`, vote window, cooldown)
- preview/debug toggles

### 4) Optional environment overrides (`.env`)

- `OCR_ENGINE=easyocr` or `tesseract`
- `OCR_USE_GPU=auto|true|false` (EasyOCR only; `auto` enables GPU when CUDA is available)
- `OCR_AUTO_TORCH_CUDA=true|false` (attempt one-time CUDA Torch repair at app startup when NVIDIA is detected)
- `USE_REFERENCE_SCORES=true|false` (enable reference-template score matching before OCR)
- `REFERENCE_SCORE_MIN_CONFIDENCE=0.55` (template-match confidence threshold, 0-1)
- `TESSERACT_CMD` path if Tesseract is not on PATH
- `DEBUG_MODE`, `SHOW_PREVIEW`, `HOTKEYS_ENABLED`

---

## Run

Normal mode:

```bat
scripts\run.bat
```

Debug mode:

```bat
scripts\run.bat --debug
```

Debug mode saves preprocessed score crops into `debug_frames/` to help diagnose OCR failures.

When using EasyOCR, GPU usage is auto-detected by default. Set `OCR_USE_GPU=true` to force GPU (with CUDA), or `OCR_USE_GPU=false` to force CPU.
If logs still show CPU fallback, confirm `nvidia-smi` works and `torch.cuda.is_available = True` during `scripts\install.bat` output.
By default, the app also attempts a one-time startup repair (`OCR_AUTO_TORCH_CUDA=true`) to install CUDA PyTorch wheels when NVIDIA hardware is present.

### GUI control panel

The app now includes a Tk GUI that acts as an operator control panel and scoreboard utility.

- Launch GUI explicitly:

```bat
scripts\run.bat --gui
```

- `scripts\run.bat` with no arguments starts in GUI mode by default.
- Use **Select Team A Region**, **Select Team B Region**, and **Select Timer Region** to calibrate the three OCR targets.
- Use **Toggle Region Borders** to show/hide visible boxes for all three OCR regions.
- Use the new **OCR Device + Performance** panel to pick **Auto / GPU / CPU**, view hardware detection status, and change **FPS** (poll rate).
- Use **Apply Device/FPS** to apply changes immediately (OCR auto-restarts if running).
- Use **Save as Default** to persist device/FPS into `config/settings.json`.
- Use **Start OCR / Stop OCR** and manual score/game controls directly in the GUI.
- Use **Save Regions** to write calibration to `config/regions.json`.

Both Windows batch scripts now pause on failures so the console stays open and you can read error messages before closing.

---

## Controls (fallback operations)

Manual controls are included because OCR is never perfect in production:

### Hotkeys (if enabled)
- `Ctrl+Alt+R` => reset current game score to `0-0`
- `Ctrl+Alt+1` => award a game win to Team A
- `Ctrl+Alt+2` => award a game win to Team B

### CLI commands (stdin)
While app is running, type one of:
- `reset` / `r`
- `award a` / `a`
- `award b` / `b`

---

## JSON output contract (`data/match_state.json`)

The app maintains and updates:

- `team_a_name`
- `team_b_name`
- `team_a_score`
- `team_b_score`
- `game_timer`
- `team_a_games`
- `team_b_games`
- `series_type` (`bo3|bo5|bo7`)
- `target_games_to_win` (auto-mapped: bo3→2, bo5→3, bo7→4)
- `current_game_number`
- `last_update`
- `match_status` (`idle|live|game_final|series_final`)
- `ocr_debug`

The detector includes debouncing, majority voting, confidence filtering, cooldown windows, and game-end safeguards to reduce double counting from flicker/replays.

---

## Overlay (OBS Browser Source)

Files are in `overlay/`:
- `index.html`
- `style.css`
- `overlay.js`

It displays:
- team names
- current live score
- live game timer
- games won in series
- best-of indicator
- status text

The style is transparent background and designed for 1920x1080 scenes.

### Loading in OBS

Option A (local file):
- Add **Browser Source**
- Check **Local file**
- Point to `overlay/index.html`
- Set width/height to 1920x1080

Option B (local hosting):

```bat
python -m http.server 8000
```

Then use `http://127.0.0.1:8000/overlay/index.html` in Browser Source.

`overlay.js` tries several JSON paths and handles missing/invalid state gracefully.

---


## Reference score training folders

A template-based score matcher is included to improve reliability when OCR struggles with stylized digits.

Folder layout (already scaffolded):

```text
data/score_reference/
  team_a/
    0/ 1/ 2/ ... 20/
  team_b/
    0/ 1/ 2/ ... 20/
```

How to use:
- Put one or more example images of each score into its numeric folder.
- Keep Team A examples in `team_a/<score>/` and Team B examples in `team_b/<score>/`.
- Crop images tightly to the score digit region for best matching.
- The app tries reference matching first, then falls back to OCR if no confident template match is found.

## OCR testing workflow

1. Start app with `--debug`.
2. Trigger scoreboard visibility in Rocket League observer view.
3. Inspect `debug_frames/` crops.
4. Adjust `regions.json` until crops tightly frame only score digits.
5. Tune `min_ocr_confidence`, `vote_window`, and `stabilize_frames`.

For first-time setup, test with static screenshots first (same HUD profile), then move to live capture.

---

## Known limitations

- OCR can fail with severe motion blur, compression, UI transitions, or unusual color themes.
- Game-end inference is heuristic without direct game API input.
- Global hotkeys may require elevated privileges depending on your environment.
- Browser security restrictions can affect local file reads in some OBS/browser combinations.

---

## Future roadmap

- Add template matching prior to OCR for stronger digit isolation.
- Add optional Rocket League data feed integration if available.
- Add per-tournament presets for region calibration.
- Add a lightweight local API/WebSocket for overlay updates.
- Add unit tests for detector state-machine edge cases.

---

## Next Steps

1. **Calibrate OCR regions for your scoreboard**
   - Copy `regions.example.json` to `regions.json`.
   - Use debug mode and iteratively tighten `team_a_score` / `team_b_score` crops.
   - Re-check after any Rocket League HUD scale/layout changes.

2. **Test with screenshots before live capture**
   - Capture multiple representative scoreboard screenshots.
   - Validate OCR preprocessing and confidence thresholds on these images first.
   - Move to live screen polling only after static OCR is stable.

3. **Improve reliability if OCR proves weak**
   - Add template matching anchors to lock scoreboard ROI before digit OCR.
   - Consider integrating game-state APIs/feeds where production environment permits.
   - Maintain manual operator controls as fail-safe even with automation.
