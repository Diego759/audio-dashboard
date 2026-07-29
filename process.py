#!/usr/bin/env python3
"""
Mind Monitor / EEG Visualizer (Muse S Athena) -> Gateway dashboard pre-processor.

Cross-platform (Windows + macOS + Linux). Scans the `recordings/` folder next to
this script for `mindMonitor_*.zip` / `mindMonitor_*.csv` (phone Mind Monitor) and
`session_*.csv` (desktop EEG Visualizer) recordings, computes meditation /
Gateway-relevant metrics, and writes `dashboard_data.js` (+ a small
`eeg_index.js`) next to this script, where dashboard.html / index.html live.

Add a new tape:  drop its recording into `recordings/` and re-run:
    python3 process.py          (macOS/Linux)   or   python process.py  (Windows)
then refresh the dashboard in the browser.  A desktop `session_*.csv` needs to be
tied to a tape — the script ASKS you which one and remembers the answer in
session_tapes.json, so you never have to edit this file.  Pick a tape you already
recorded to add a second take of it.

Optional environment overrides (rarely needed):
    GATEWAY_LIBRARY     folder to write dashboard_data.js / eeg_index.js into
                        (default: this script's folder)
    GATEWAY_RECORDINGS  where to read recordings from; os.pathsep-separated list
                        (default: ./recordings next to this script)
"""

import csv, glob, io, json, math, os, re, statistics, sys, zipfile
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# Where the generated data is written — next to dashboard.html / index.html.
# In this repo that's the repo root (HERE). Override with GATEWAY_LIBRARY.
LIBRARY_DIR = os.environ.get("GATEWAY_LIBRARY") or HERE

# Where raw EEG recordings live. Default: ./recordings next to this script.
# Override / add more folders with GATEWAY_RECORDINGS (os.pathsep-separated).
RECORDINGS_DIRS = [p for p in (os.environ.get("GATEWAY_RECORDINGS")
                               or os.path.join(HERE, "recordings")).split(os.pathsep) if p]

# ---------------------------------------------------------------------------
# Labelling.  Three ways, in priority order:
#   1) SESSION_TAPES: pin ONE specific recording (by its file-id, the filename
#      without extension) to a tape.  This is how you keep MORE THAN ONE
#      recording of the same tape — pin each take here and they all show up as
#      separate takes of that tape.
#   2) SESSION_LABELS: pin a whole recording date (YYYY-MM-DD) to a tape.
#   3) TAPE_SEQUENCE: any recording NOT pinned above gets the next unclaimed
#      tape from this list by chronological recording order.
# So future tapes auto-label themselves the moment you drop them in & re-run,
# and repeat takes are a one-line pin.
#
# You do NOT need to edit this file to add a recording: just run the script and
# it will ASK which tape any new desktop `session_*.csv` belongs to, saving your
# answer to session_tapes.json (see PINS_FILE below).
# ---------------------------------------------------------------------------
SESSION_TAPES = {
    # EEG Visualizer captures.
    # (An earlier Orientation retake, session_20260721_182221, was deleted
    #  2026-07-23: the Muse BLE stream dropped ~15 min in and recorded nothing
    #  for the remaining ~17.5 min, so the "meditation depth" after that point
    #  was dead air, not real data.)
    "session_20260722_181311": "Wave 1 – Introduction to Focus 10",
    "session_20260723_182956": "Wave 1 – Orientation",
}

# Pins added interactively are stored here so you never have to edit code.
# Format: {"session_20260805_190000": "Wave 1 – Advanced Focus 10",
#          "session_20260722_095220": null}   <- null = ignore this file
PINS_FILE = os.path.join(HERE, "session_tapes.json")


def load_pins():
    """Built-in SESSION_TAPES merged with session_tapes.json (the file wins).

    A value of None/null means "permanently ignore this recording" (handy for
    a few-second test capture you don't want in the dashboard)."""
    pins = dict(SESSION_TAPES)
    try:
        with open(PINS_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict):
            pins.update(saved)
    except FileNotFoundError:
        pass
    except (ValueError, OSError) as exc:
        print(f"  (!) could not read {os.path.basename(PINS_FILE)}: {exc}")
    return pins


def save_pin(key, tape):
    """Persist one recording -> tape assignment (tape=None means ignore)."""
    saved = {}
    try:
        with open(PINS_FILE, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            saved = loaded
    except (FileNotFoundError, ValueError, OSError):
        pass
    saved[key] = tape
    with open(PINS_FILE, "w", encoding="utf-8") as fh:
        json.dump(saved, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

SESSION_LABELS = {
    "2026-05-26": ("Wave 1 – Orientation", 1),
    "2026-05-27": ("Wave 1 – Introduction to Focus 10", 2),
    "2026-05-28": ("Wave 1 – Advanced Focus 10", 3),
}

# Gateway Experience tapes in listening order.
# Wave 1 "Discovery" then Wave 2 "Threshold" (standard Monroe sequence — adjust
# the Wave 2 names if your album order differs).
WAVE1_SEQUENCE = [
    "Wave 1 – Orientation",
    "Wave 1 – Introduction to Focus 10",
    "Wave 1 – Advanced Focus 10",
    "Wave 1 – Release and Recharge",
    "Wave 1 – Exploration of Sleep",
    "Wave 1 – Free Flow 10",
]
WAVE2_SEQUENCE = [
    "Wave 2 – Introduction to Focus 12",
    "Wave 2 – Problem Solving",
    "Wave 2 – One-Month Patterning",
    "Wave 2 – Color Breathing",
    "Wave 2 – Energy Bar Tool",
    "Wave 2 – Living Body Map",
]
TAPE_SEQUENCE = WAVE1_SEQUENCE + WAVE2_SEQUENCE

# Maps each tape label to its episode number `n` in the Gateway Library's
# data.js, so the dashboard can deep-link to the exact recording and the
# library can badge tapes you've recorded. (Confirmed against data.js.)
EPISODE_N = {
    "Wave 1 – Orientation": 2,
    "Wave 1 – Introduction to Focus 10": 3,
    "Wave 1 – Advanced Focus 10": 4,
    "Wave 1 – Release and Recharge": 5,
    "Wave 1 – Exploration of Sleep": 6,
    "Wave 1 – Free Flow 10": 7,
    "Wave 2 – Introduction to Focus 12": 8,
    "Wave 2 – Problem Solving": 9,
    "Wave 2 – One-Month Patterning": 195,
    "Wave 2 – Color Breathing": 10,
    "Wave 2 – Energy Bar Tool": 11,
    "Wave 2 – Living Body Map": 12,
}

CHANNELS = ["TP9", "AF7", "AF8", "TP10"]
BANDS = ["Delta", "Theta", "Alpha", "Beta", "Gamma"]
LEFT = ["TP9", "AF7"]
RIGHT = ["AF8", "TP10"]


def parse_ts(s):
    # Mind Monitor:            "2026-05-26 10:08:04.579"  (space separator)
    # older EEG Visualizer:    "2026-07-21T18:22:21.445"  (ISO 'T' separator)
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError("unrecognised timestamp: " + s)


def fnum(s):
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# Older EEG Visualizer builds wrote signal quality as words rather than 1/2/4.
_HSI_WORDS = {"good": 1, "ok": 2, "okay": 2, "medium": 2, "fair": 2,
              "bad": 4, "poor": 4, "none": 4, "off": 4}


def hsi_bucket(raw):
    """Muse signal quality -> 1 (good) / 2 (ok) / 4 (poor).

    Handles the numeric HSI written by Mind Monitor and current EEG Visualizer
    builds, and the older EEG Visualizer word form ('good'/'ok'/'bad')."""
    if raw is None or raw == "":
        return None
    v = fnum(raw)
    if v is not None:
        return 1 if v <= 1 else (2 if v < 4 else 4)
    return _HSI_WORDS.get(str(raw).strip().lower())


def lin(bel):
    """Mind Monitor band columns are log10 power (Bels) -> linear power."""
    return 10.0 ** bel


def band_is_relative(path):
    """Two apps write the band columns in DIFFERENT units:

      * Mind Monitor (phone): log10 absolute band power in Bels -> often
        negative, per-channel 5-band sums vary widely.  Needs 10^x.
      * EEG Visualizer (desktop): already-normalised RELATIVE band powers ->
        all >= 0, each channel's 5 bands sum to 1.  Must NOT be 10^x'd.

    Applying 10^x to the already-relative values squashes every band toward
    ~20% (10^x is near-flat for small x), which is exactly what made the
    desktop recordings look nothing like the phone ones.  Detect the format so
    each recording is handled correctly."""
    checked = votes_rel = 0
    for row in iter_rows(path):
        sums, neg, ok = [], False, True
        for c in CHANNELS:
            tot = 0.0
            for band in BANDS:
                v = fnum(row.get(f"{band}_{c}"))
                if v is None:
                    ok = False
                    break
                if v < 0:
                    neg = True
                tot += v
            if not ok:
                break
            sums.append(tot)
        if not ok or not sums or max(sums) <= 0.01:   # skip blank/leading-zero rows
            continue
        checked += 1
        if not neg and all(0.95 <= s <= 1.05 for s in sums):
            votes_rel += 1
        if checked >= 20:
            break
    return checked > 0 and votes_rel >= 0.8 * checked


def iter_rows(path):
    """Yield csv.DictReader rows from a .csv or the .csv inside a .zip."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                yield from csv.DictReader(text)
    else:
        with open(path, newline="", encoding="utf-8") as fh:
            yield from csv.DictReader(fh)


def collect_sources(pins):
    """Return (sources, unassigned).

    `sources` is a list of (key, path) preferring .csv over .zip for the same
    recording.  `unassigned` lists desktop session_*.csv files that have no pin
    yet — main() offers to assign those interactively.

    Scans every folder in RECORDINGS_DIRS (plus an optional `extracted/`
    subfolder of each) for phone `mindMonitor_*` files and desktop
    `session_*.csv` files."""
    found = {}
    unassigned = []
    for base in RECORDINGS_DIRS:
        for path in glob.glob(os.path.join(base, "mindMonitor_*.csv")) + \
                    glob.glob(os.path.join(base, "extracted", "mindMonitor_*.csv")) + \
                    glob.glob(os.path.join(base, "mindMonitor_*.zip")):
            key = os.path.splitext(os.path.basename(path))[0]
            # prefer csv if both exist
            if key in found and found[key].lower().endswith(".csv"):
                continue
            found[key] = path

        # EEG Visualizer for Muse writes session_*.csv.  Only pick up the ones
        # assigned to a tape — this keeps stray test-capture files (e.g. a
        # few-second synthetic run) out of the dashboard.  Anything unassigned
        # is reported rather than silently skipped.
        for path in sorted(glob.glob(os.path.join(base, "session_*.csv"))):
            key = os.path.splitext(os.path.basename(path))[0]
            if key in pins:
                if pins[key]:                     # None => explicitly ignored
                    found.setdefault(key, path)
            elif not any(k == key for k, _ in unassigned):
                unassigned.append((key, path))

    return sorted(found.items(), key=lambda kv: kv[0]), unassigned


def describe_recording(path):
    """One-line 'what is this file' summary to help identify a new recording."""
    try:
        first = last = None
        n = 0
        for row in iter_rows(path):
            ts = row.get("TimeStamp")
            if not ts:
                continue
            if first is None:
                first = ts
            last = ts
            n += 1
        if first is None:
            return "empty / unreadable"
        mins = (parse_ts(last) - parse_ts(first)).total_seconds() / 60.0
        return f"recorded {parse_ts(first).strftime('%Y-%m-%d %H:%M')}, {mins:.0f} min, {n} rows"
    except Exception as exc:                       # never block on a bad file
        return f"(could not read: {exc})"


# Shorthands people actually type for the tape titles.
_TAPE_ALIASES = {r"\bintro\b": "introduction", r"\brelease & recharge\b": "release and recharge",
                 r"\bff10\b": "free flow 10", r"\bebt\b": "energy bar tool"}


def _norm_tape(s):
    """Loose form for comparing tape names: lowercase, any dash -> '-', tidy space."""
    s = s.strip().lower()
    for dash in ("—", "–", "--"):        # em dash, en dash, double hyphen
        s = s.replace(dash, "-")
    for pat, repl in _TAPE_ALIASES.items():
        s = re.sub(pat, repl, s)
    return " ".join(s.split())


def _loose_tape(s):
    """As _norm_tape but dashes become spaces, so 'one month' == 'One-Month'."""
    return " ".join(_norm_tape(s).replace("-", " ").split())


def resolve_tape_name(text):
    """Turn typed text into a canonical tape name from TAPE_SEQUENCE.

    Forgiving about the en-dash (typing a plain '-' is fine), about common
    shorthands ("intro to focus 10"), and about typing only the short title, so
    "orientation", "Wave 1 - Orientation" and "Wave 1 – Orientation" all resolve
    to the canonical label.

    Returns (canonical_name, candidates).  If canonical_name is None, either
    nothing matched (candidates empty) or it was ambiguous (candidates lists the
    possibilities)."""
    want, want_loose = _norm_tape(text), _loose_tape(text)
    if not want:
        return None, []

    # 1) full-name match
    for tape in TAPE_SEQUENCE:
        if _norm_tape(tape) == want or _loose_tape(tape) == want_loose:
            return tape, []

    # 2) match on the short title after the "Wave N - " prefix
    exact, partial = [], []
    for tape in TAPE_SEQUENCE:
        short = _norm_tape(tape).split("-", 1)[-1].strip()
        short_loose = " ".join(short.replace("-", " ").split())
        if want in (short,) or want_loose == short_loose:
            exact.append(tape)
        elif want in _norm_tape(tape) or want_loose in _loose_tape(tape):
            partial.append(tape)
    hits = exact or partial
    if len(hits) == 1:
        return hits[0], []
    return None, hits


def assign_unassigned(unassigned):
    """Ask which tape each new desktop recording belongs to; save the answers.

    Runs only on an interactive terminal.  Otherwise it prints instructions and
    leaves the files out of the dashboard (unchanged, safe default)."""
    interactive = sys.stdin is not None and sys.stdin.isatty()

    print()
    print("Found %d new recording(s) not yet assigned to a tape:" % len(unassigned))
    for key, path in unassigned:
        print(f"  - {key}.csv  ({describe_recording(path)})")

    if not interactive:
        print()
        print("Not running in an interactive terminal, so they were skipped.")
        print("Run `python3 process.py` from a terminal to assign them, or add")
        print(f"them to {os.path.basename(PINS_FILE)} manually, e.g.:")
        print('  { "%s": "%s" }' % (unassigned[0][0], TAPE_SEQUENCE[0]))
        return False

    changed = False
    for key, path in unassigned:
        print()
        print(f"Which tape is  {key}.csv  ({describe_recording(path)})?")
        for i, tape in enumerate(TAPE_SEQUENCE, 1):
            print(f"  {i:2d}) {tape}")
        print("   t) enter the tape name")
        print("   s) skip for now (ask again next time)")
        print("   x) ignore this file permanently (e.g. a test capture)")

        while True:
            try:
                ans = input("Enter a number, t, s, or x: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nSkipped.")
                return changed
            if ans == "s":
                break
            if ans == "x":
                save_pin(key, None)
                print(f"  -> ignoring {key}.csv from now on.")
                changed = True
                break
            if ans == "t":
                tape = prompt_tape_name()
                if tape is None:            # cancelled -> back to the menu
                    print("  (cancelled)")
                    continue
                save_pin(key, tape)
                print(f"  -> {key}.csv = {tape}")
                changed = True
                break
            if ans.isdigit() and 1 <= int(ans) <= len(TAPE_SEQUENCE):
                tape = TAPE_SEQUENCE[int(ans) - 1]
                save_pin(key, tape)
                print(f"  -> {key}.csv = {tape}")
                changed = True
                break
            print("  Sorry, didn't get that.")
    return changed


def prompt_tape_name():
    """Ask the user to type a tape name.  Returns a name, or None to cancel.

    Typed text is matched against the known tapes so the canonical label (with
    its en-dash) is stored — that's what links a session to its Library episode
    and its guide.  A name that matches nothing can still be used, but the
    consequences are spelled out first."""
    while True:
        try:
            raw = input("  Tape name (blank to cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not raw:
            return None

        tape, candidates = resolve_tape_name(raw)
        if tape:
            if _norm_tape(tape) != _norm_tape(raw):
                print(f"  Matched known tape: {tape}")
            return tape

        if candidates:
            print("  That matches several tapes — please be more specific:")
            for c in candidates:
                print(f"    - {c}")
            continue

        # Not a known tape: allow it, but say what won't work.
        print(f'  "{raw}" is not one of the standard Wave 1/2 tapes.')
        print("  It will still be analysed, but it won't link to a Library tape")
        print("  or show that tape's guide/checklist.")
        try:
            ok = input("  Use this name anyway? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if ok in ("y", "yes"):
            return raw


def moving_avg(xs, win):
    out = []
    q = []
    s = 0.0
    for x in xs:
        q.append(x)
        s += x
        if len(q) > win:
            s -= q.pop(0)
        out.append(s / len(q))
    return out


def process(path):
    samples = []          # one per band row
    events = []           # (sec_from_start, type)
    hsi_counts = {1: 0, 2: 0, 4: 0}
    start = None
    batteries = []
    is_rel = band_is_relative(path)   # relative-power vs log-power band columns

    for row in iter_rows(path):
        ts_raw = row.get("TimeStamp")
        if not ts_raw:
            continue
        ts = parse_ts(ts_raw)
        if start is None:
            start = ts
        sec = (ts - start).total_seconds()

        elem = row.get("Elements") or ""
        if "blink" in elem:
            events.append((sec, "blink"))
        elif "jaw_clench" in elem:
            events.append((sec, "jaw"))

        b = fnum(row.get("Battery"))
        if b is not None:
            batteries.append(b)

        # signal quality (numeric 1/2/4 or older word form good/ok/bad)
        for c in CHANNELS:
            key = hsi_bucket(row.get(f"HSI_{c}"))
            if key is not None:
                hsi_counts[key] = hsi_counts.get(key, 0) + 1

        # only rows carrying band power form timeline samples
        if not row.get("Alpha_TP9"):
            continue

        # linear power per band, summed across channels; also per-channel for asymmetry
        band_lin = {}
        ok = True
        chan_band = {}
        for band in BANDS:
            tot = 0.0
            for c in CHANNELS:
                v = fnum(row.get(f"{band}_{c}"))
                if v is None:
                    ok = False
                    break
                p = v if is_rel else lin(v)   # desktop app values are already linear/relative
                chan_band[(band, c)] = p
                tot += p
            if not ok:
                break
            band_lin[band] = tot
        if not ok:
            continue

        total = sum(band_lin.values())
        if total <= 0:
            continue
        rel = {band: band_lin[band] / total for band in BANDS}

        # hemispheric alpha (linear) for symmetry + frontal asymmetry
        a_left = sum(chan_band[("Alpha", c)] for c in LEFT)
        a_right = sum(chan_band[("Alpha", c)] for c in RIGHT)
        faa = math.log(chan_band[("Alpha", "AF8")]) - math.log(chan_band[("Alpha", "AF7")])

        hr = fnum(row.get("Heart_Rate"))
        if hr is not None and hr <= 0:
            hr = None

        ax = fnum(row.get("Accelerometer_X")) or 0.0
        ay = fnum(row.get("Accelerometer_Y")) or 0.0
        az = fnum(row.get("Accelerometer_Z")) or 0.0
        accel_mag = math.sqrt(ax * ax + ay * ay + az * az)

        samples.append({
            "t": round(sec, 2),
            "delta": round(rel["Delta"], 4),
            "theta": round(rel["Theta"], 4),
            "alpha": round(rel["Alpha"], 4),
            "beta": round(rel["Beta"], 4),
            "gamma": round(rel["Gamma"], 4),
            "hr": round(hr, 1) if hr is not None else None,
            "accel": round(accel_mag, 4),
            "faa": round(faa, 4),
            "a_left": a_left,
            "a_right": a_right,
        })

    if not samples:
        return None

    # movement = sample-to-sample change in accel magnitude (stillness proxy)
    accel_series = [s["accel"] for s in samples]
    mv = [0.0] + [abs(accel_series[i] - accel_series[i - 1]) for i in range(1, len(accel_series))]
    for s, m in zip(samples, mv):
        s["move"] = round(m, 4)
        del s["accel"]

    # hemispheric alpha symmetry: 1 - |L-R|/(L+R)  (1 = perfectly balanced)
    for s in samples:
        l, r = s.pop("a_left"), s.pop("a_right")
        s["sym"] = round(1 - abs(l - r) / (l + r), 4) if (l + r) > 0 else None

    # derived ratios + smoothed series for display
    def col(name):
        return [s[name] for s in samples]

    n = len(samples)
    duration_min = samples[-1]["t"] / 60.0

    hr_vals = [s["hr"] for s in samples if s["hr"] is not None]

    # session summary
    summary = {
        "n": n,
        "duration_min": round(duration_min, 1),
        "rel_mean": {b: round(statistics.mean(col(b)), 4) for b in
                     ["delta", "theta", "alpha", "beta", "gamma"]},
        "hr_mean": round(statistics.mean(hr_vals), 1) if hr_vals else None,
        "hr_min": round(min(hr_vals), 0) if hr_vals else None,
        "hr_max": round(max(hr_vals), 0) if hr_vals else None,
        "sym_mean": round(statistics.mean([s["sym"] for s in samples if s["sym"] is not None]), 3),
        "move_mean": round(statistics.mean(col("move")), 4),
        "stillness_pct": round(100.0 * sum(1 for m in col("move") if m < 0.02) / n, 1),
        "blink_count": sum(1 for _, t in events if t == "blink"),
        "jaw_count": sum(1 for _, t in events if t == "jaw"),
        "battery_start": round(batteries[0], 1) if batteries else None,
        "battery_end": round(batteries[-1], 1) if batteries else None,
    }
    qtot = sum(hsi_counts.values()) or 1
    summary["signal_good_pct"] = round(100.0 * hsi_counts.get(1, 0) / qtot, 1)
    summary["hsi_counts"] = hsi_counts

    # theta/beta and alpha/theta ratios; meditation depth = theta+alpha relative
    for s in samples:
        s["tbr"] = round(s["theta"] / s["beta"], 3) if s["beta"] > 0 else None
        s["depth"] = round(s["theta"] + s["alpha"], 4)
    summary["tbr_mean"] = round(statistics.mean([s["tbr"] for s in samples if s["tbr"]]), 3)
    summary["depth_mean"] = round(statistics.mean(col("depth")), 4)

    return {
        "date": start.strftime("%Y-%m-%d"),   # from the data, not the filename
        "band_format": "relative" if is_rel else "log",
        "samples": samples,
        "events": events,
        "summary": summary,
    }


def main():
    # Labels carry the en-dash; make console output UTF-8 so it can't crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    pins = load_pins()
    sources, unassigned = collect_sources(pins)

    # A new desktop recording needs to be tied to a tape — ask, don't skip.
    if unassigned:
        if assign_unassigned(unassigned):
            pins = load_pins()
            sources, unassigned = collect_sources(pins)
        print()

    if not sources:
        print("No recordings found in:", ", ".join(RECORDINGS_DIRS))
        print("Drop mindMonitor_*.zip/.csv or session_*.csv files there and re-run.")
        return

    sessions = []
    for key, path in sources:
        print("Processing", os.path.basename(path), "...")
        data = process(path)
        if not data:
            print("  (no band data, skipped)")
            continue
        # Tape assignment priority:
        #   1) pins[key]            - per-recording pin (this is what lets one
        #                             tape hold more than one take)
        #   2) SESSION_LABELS[date] - legacy per-date pin
        #   3) positional fallback  - assigned after sorting, below
        label = pins.get(key)
        if not label:
            label = SESSION_LABELS.get(data["date"], (None,))[0]
        sessions.append({
            "id": key,
            "label": label,            # explicit pin, or None -> filled below
            "file": os.path.basename(path),
            **data,                    # date, samples, events, summary
        })

    # chronological order = listening order
    sessions.sort(key=lambda s: (s["date"], s["id"]))

    # Positional fallback: each un-pinned recording gets the next tape in the
    # standard sequence that no pin has already claimed.  Claiming this way means
    # adding an extra take of an already-labelled tape never shifts the labels
    # of the auto-labelled recordings.
    claimed = {s["label"] for s in sessions if s["label"]}
    remaining = [t for t in TAPE_SEQUENCE if t not in claimed]
    ri = 0
    for s in sessions:
        if not s["label"]:
            s["label"] = remaining[ri] if ri < len(remaining) else f"Session ({s['date']})"
            ri += 1

    # Number the takes within each tape (take 1, 2, ... by date) so the same
    # audio can carry more than one recording.
    groups = defaultdict(list)
    for s in sessions:
        groups[s["label"]].append(s)
    for grp in groups.values():
        grp.sort(key=lambda s: (s["date"], s["id"]))
        for k, s in enumerate(grp, 1):
            s["take"] = k
            s["takes_total"] = len(grp)

    for i, s in enumerate(sessions):
        s["order"] = i + 1
        s["episode_n"] = EPISODE_N.get(s["label"])   # library episode, or None

    # Where to write generated data: the Library folder (combined app home) if
    # it exists, else fall back to HERE so the tool still works standalone.
    out_dir = LIBRARY_DIR if os.path.isdir(LIBRARY_DIR) else HERE

    out = os.path.join(out_dir, "dashboard_data.js")
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "sessions": sessions}
    with open(out, "w", encoding="utf-8") as f:
        f.write("window.GATEWAY_DATA = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")

    # Tiny index the Library reads to badge tapes you've recorded (keyed by
    # episode number) — avoids loading the full dashboard_data.js there.
    # Headline fields describe the most recent take (kept flat for the badge);
    # `takes` is the count and `all` lists every take of that tape.
    def brief(s):
        sm = s["summary"]
        return {"id": s["id"], "date": s["date"], "take": s.get("take", 1),
                "depth": sm["depth_mean"], "hr": sm["hr_mean"],
                "signal": sm["signal_good_pct"], "dur": sm["duration_min"]}

    by_ep = defaultdict(list)
    for s in sessions:
        if s.get("episode_n"):
            by_ep[s["episode_n"]].append(s)

    eeg_index = {}
    for n, grp in by_ep.items():
        grp = sorted(grp, key=lambda s: s.get("take", 1))
        latest = grp[-1]                       # most recent take is the headline
        entry = brief(latest)
        entry["label"] = latest["label"]
        entry["takes"] = len(grp)
        entry["all"] = [brief(s) for s in grp]
        eeg_index[str(n)] = entry
    idx_path = os.path.join(out_dir, "eeg_index.js")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write("window.EEG_INDEX = ")
        json.dump(eeg_index, f, separators=(",", ":"))
        f.write(";\n")

    kb = os.path.getsize(out) / 1024
    print(f"\nWrote {out} ({kb:.0f} KB) with {len(sessions)} session(s).")
    print(f"Wrote {idx_path} ({len(eeg_index)} tapes linked).")
    for s in sessions:
        sm = s["summary"]
        ep = s.get("episode_n")
        take = f" [take {s['take']}/{s['takes_total']}]" if s.get("takes_total", 1) > 1 else ""
        fmt = "" if s.get("band_format") == "log" else f" ({s['band_format']} bands)"
        print(f"  - {s['label']}{take}{fmt}: {sm['duration_min']} min, "
              f"HR~{sm['hr_mean']}, signal {sm['signal_good_pct']}% good, "
              f"alpha {sm['rel_mean']['alpha']*100:.0f}% / theta {sm['rel_mean']['theta']*100:.0f}%"
              f"{'  -> tape #'+str(ep) if ep else ''}")


if __name__ == "__main__":
    main()
