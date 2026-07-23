# Gateway Meditation Dashboard

An offline dashboard for reviewing **Muse S Athena** EEG recordings made while
listening to the Monroe **Gateway Experience** tapes, plus a browser for the tape
library. Everything runs locally in your web browser — no server account, no
internet, no build step.

- **My Sessions** (`dashboard.html`) — per-recording brain-state analysis:
  relative band power, meditation depth (θ+α), theta/beta ratio, hemispheric
  alpha symmetry, frontal alpha asymmetry, heart rate, stillness, signal
  quality — plus a "compare takes" overlay when a tape has more than one
  recording, and a "compare all sessions" progress view.
- **Library** (`index.html`) — browse the tapes, read the Hemi-Sync frequency
  analysis, and jump straight to the EEG for any tape you've recorded.

> **Note:** the audio files are **not** in this repo, so the "▶ Listen" buttons
> and the in-page player won't play anything. The analysis and browsing UI work
> fully without them.

## Requirements

- **Python 3** (any recent 3.x) — used only to (a) serve the files and
  (b) regenerate the data. Check with `python3 --version`.
- Any modern web browser.

## Run it (view the dashboard)

**macOS** — double-click **`serve.command`** in Finder
(first time: right-click → Open to clear Gatekeeper). It starts a local server
and opens the Library.

**Windows** — double-click **`serve.bat`**.

**Any OS, from a terminal:**

```bash
cd gateway-dashboard
python3 -m http.server 8768
# then open http://localhost:8768/index.html
```

(Opening the `.html` files directly with `file://` will **not** work — the pages
load their data via `<script src>`, which browsers block over `file://`. Use the
local server above.)

## Regenerate the data from recordings

The dashboard reads two generated files, `dashboard_data.js` and `eeg_index.js`,
which are built from the raw EEG recordings in **`recordings/`**. To rebuild them
(e.g. after adding a new recording):

```bash
cd gateway-dashboard
python3 process.py
```

Then refresh the browser.

### Adding a new recording

1. Drop the recording into **`recordings/`**:
   - **Phone Mind Monitor** → `mindMonitor_*.zip` (or `.csv`). Auto-labelled to
     the next tape in sequence by its recording date.
   - **Desktop EEG Visualizer for Muse** → `session_*.csv`. These must be
     **pinned** to a tape (see next step) — that's also how you keep more than
     one take of the same tape.
2. If it's a `session_*.csv`, add one line to `SESSION_TAPES` near the top of
   `process.py`, keyed by the filename without extension, e.g.:
   ```python
   SESSION_TAPES = {
       "session_20260722_181311": "Wave 1 – Introduction to Focus 10",
       "session_20260805_190000": "Wave 1 – Advanced Focus 10",  # new take
   }
   ```
3. Re-run `python3 process.py` and refresh.

### Optional environment overrides

- `GATEWAY_RECORDINGS` — read recordings from a different folder (or several,
  separated by `:` on macOS/Linux, `;` on Windows) instead of `./recordings`.
- `GATEWAY_LIBRARY` — write `dashboard_data.js` / `eeg_index.js` somewhere other
  than the repo root.

## Two apps, two data formats (important)

Recordings come from two different apps that store band power **differently**, and
`process.py` handles each correctly:

| | Phone **Mind Monitor** | Desktop **EEG Visualizer** |
|---|---|---|
| Band columns | log₁₀ absolute power (Bels) | already-normalised relative power |
| Sampling | ~1 sample/sec | ~1 sample / 5–8 sec (BLE-limited) |

Because the two apps compute bands with different algorithms, **compare
phone-to-phone and desktop-to-desktop** — the absolute band percentages are not
directly comparable across apps (Mind Monitor's gamma in particular runs very
hot). Each session in the dashboard is tagged with its `band_format`.

## Files

```
dashboard.html      My Sessions analysis UI
index.html          Library / tape browser
Manual.html         Visual Hemi-Sync explainer
process.py          builds dashboard_data.js + eeg_index.js from recordings/
recordings/         raw EEG (mindMonitor_*.zip, session_*.csv)
chart.umd.min.js    Chart.js (vendored, offline)
data.js             tape metadata          transcripts.js  tape transcripts
frequencies.js      Hemi-Sync freq analysis (_freq/*.png)
dashboard_data.js   generated: full per-session timeline (git-ignored? no, kept)
eeg_index.js        generated: per-tape summary the Library badges read
_art/ _freq/ _manual/   images
```

Personal recordings and Gateway materials — keep this repository **private**.
