# Rocket League OCR Score Tracker (Windows-first)

This project captures Rocket League HUD regions and writes `data/match_state.json` for an OBS browser overlay.

## What it does now

- Captures **3 separate regions**:
  1. Team A score (left)
  2. Team B score (right)
  3. Game timer
- Uses a **luma mask** (high-contrast black/white) for score tracking.
- Uses **pixel-change counts** (not score-digit OCR) to increment score by +1 when enough pixels flip between frames.
- Detects game end when **both score regions have no white pixels for 50ms**.
- Awards a game win to higher score, resets score to `0-0`, and waits for white pixels to return before tracking next game.
- Still OCRs the timer region (EasyOCR/Tesseract).
- Writes overlay state JSON consumed by `overlay/index.html`.

## Project layout

```text
app/
  main.py
  capture.py
  ocr.py
  detector.py
  state.py
  config.py
  gui.py
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
scripts/
  install.bat
  run.bat
requirements.txt
.env.example
```

## Install (Windows)

```bat
scripts\install.bat
```

The installer keeps the window open on success/failure so you can read output.

## Run

```bat
scripts\run.bat
```

Default run mode is GUI.

## GUI highlights

- Region selectors for Team A / Team B / Timer.
- Toggle border overlays to confirm capture locations.
- OCR device chooser (Auto/GPU/CPU).
- FPS control.
- **Luma threshold control** (slider + spinbox).
- **Live Team A/Team B/Timer previews** to tune regions and threshold.
- Start/Stop OCR worker and manual score/game controls.
- GUI preview rendering is now main-thread-safe to avoid Tk freezes/"Not Responding" when OCR is running.

## Config

Copy sample files:

```bat
copy config\regions.example.json config\regions.json
copy config\settings.example.json config\settings.json
copy .env.example .env
```

`settings.json` now includes:

- `luma_threshold`
- `white_pixel_min_count`
- `pixel_change_count_threshold`
- `score_increment_cooldown_ms`
- `game_end_no_white_ms`

## Overlay

Load `overlay/index.html` as OBS Browser Source (local file) or host with:

```bat
python -m http.server 8000
```

Then use `http://127.0.0.1:8000/overlay/index.html`.


## Terminal error reporting (new)

The app now logs explicit terminal errors for common failure scenarios instead of failing silently.

Implemented scenarios:
- Invalid OCR region dimensions/positions at startup (negative coordinates or non-positive width/height).
- Empty frame/crop capture (often caused by bad region coordinates or display capture problems).
- OCR worker startup failures (engine init/capture backend failures).
- OCR processing loop failures (timer OCR backend errors, detector/runtime exceptions).

Behavior:
- First failures are logged immediately with stack traces.
- Repeated failures are throttled to avoid terminal spam, but still continue retrying.
- GUI also shows latest worker error text in the control panel.

## Next Steps

1. **Calibrate OCR regions**
   - Use GUI region tools and border toggle.
   - Confirm Team A is left score region and Team B is right score region.
   - Save to `config/regions.json`.

2. **Test with screenshots before live capture**
   - Take static screenshots/crops of scoreboard states.
   - Tune `luma_threshold` using GUI preview until only white score glyphs remain.
   - Validate score increments and game-end behavior in controlled playback.

3. **Improve reliability later**
   - Add optional template matching for score-change event validation.
   - Add Rocket League game-state APIs (e.g., BakkesMod plugin feeds) if available.
   - Blend timer OCR confidence with extra temporal smoothing.
