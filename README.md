# EQ Optimizer Scratchpad

This repo now ships with a GUI shell that manages EQ projects. The historical plotting/calibration helpers (`input/*.frd`, default `project.json`, etc.) still live beneath the new application layer, but everything is driven from the GUI.

## Quick start
1. Install Python 3.12 (or newer) and the dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```
2. Launch the GUI:
   ```powershell
   python main.py
   ```
   The window opens with the **Project** tab so you can create/import/export/delete project configs. All managed projects are stored under `project_store/` (adjust the path passed to `launch_gui` in `main.py` if you prefer a different location).
3. Pick a project and continue with the planned workflow tabs as they are added. You can still hand-edit individual JSON files under `project_store/` or import existing configs at any time.

`main.py` now launches the GUI by default, and the legacy CLI has been removed.

## Project tab (GUI)
- Lists every managed project stored in `project_store/`
- **New:** builds a copy of the default template (TT/MT/HT) and lists it immediately
- **Import:** adds any `project.json`-style file into the catalog; the file contents are copied into the store so the originals stay untouched
- **Export:** copies the selected project to a destination of your choice (use the `.eqproj` extension to keep things separate)
- **Delete:** removes the selected project from the catalog and deletes its managed copy
- Detail pane: shows metadata about the managed file; the JSON itself stays hidden because every setting will be editable within upcoming GUI tabs.

## Filter tab (GUI)
- **Project-aware filtersets:** the tab follows the project selected on the *Project* page, automatically loading the linked manufacturer entry and disabling edits when no project is active. Exported projects always bundle the referenced filterset so collaborators inherit the same calibration data.
- **Filter palette:** add PEQ, Shelf, All-pass, and Crossover blocks directly into the active project’s filterset. Shelf and crossover mode buttons stay left-aligned with compact “Low / High” toggles, and the filter-type chooser now uses buttons so you can flip between Linkwitz-Riley and Butterworth instantly.
- **Per-type order controls:** order is selected via buttons (up to 8th order, Linkwitz-Riley restricted to even values) and the UI remembers separate orders/modes for each topology, so you can prepare low/high-pass sweeps for both types at once.
- **Parameter editor & preview:** tweak frequency, Q/slope, gain, topology, and order to see each block’s response immediately. Selecting a calibration sweep automatically focuses the matching filter and overlays the FRD trace so you can verify the fit without extra clicks.
- **Calibration panel:** point to any subset of PEQ/All-pass/Shelf sweeps and optionally add individual Butterworth/Linkwitz-Riley crossover sweeps (each with its own frequency, order, and mode). Only the provided sweeps are recalibrated; existing coefficients remain untouched.


## Config file structure (`project.json`)
The default `project.json` already matches the TT/MT/HT files in `input/`. Adjust it as needed:

```json
{
   "name": "three_way_baseline",
   "sample_rate": 192000,
   "manufacturer": "generic",
   "ways": [
      {
         "name": "TT",
         "file": "input/TT.frd",

      ### Manufacturer profiles (`manufacturers.json`)
      - The main config’s `manufacturer` field selects one of the profiles defined in `manufacturers.json` (either the copy next to the project file or the default at the repo root). When omitted it falls back to the built-in `generic` RBJ cookbook formulas.
      - Each profile entry looks like this:
        ```json
        {
           "name": "minidsp",
           "description": "MiniDSP-style presets",
           "filters": {
              "peq": { "gain_limit_db": 12, "q_min": 0.2, "q_max": 20 },
              "shelf": { "gain_limit_db": 12, "slope_scale": 0.9 },
              "allpass": { "q_scale": 0.95 }
           }
        }
        ```
      - Filter-specific dictionaries are merged with each block’s parameters before designing the biquad. This makes it easy to enforce gain/Q limits, scale slopes, or tweak default formulas per manufacturer. Set `enabled: false` to globally bypass a filter type for a given profile.
         "color": "green",
         "filters": [
            { "type": "linkwitz-riley", "mode": "lowpass", "order": 4, "freq": 350 },
            { "type": "peq", "f0": 80, "gain_db": 3, "q": 1.2 }
         ]
      },
      {
         "name": "MT",
         "file": "input/MT.frd",
         "color": "blue",
         "filters": [
            { "type": "linkwitz-riley", "mode": "highpass", "order": 4, "freq": 320 },
            { "type": "butterworth", "mode": "lowpass", "order": 4, "freq": 2500 }
         ]
      },
      {
         "name": "HT",
         "file": "input/HT.frd",
         "color": "red",
         "filters": [
            { "type": "linkwitz-riley", "mode": "highpass", "order": 4, "freq": 2400 },
            { "type": "phase", "f0": 4500, "q": 0.8 }
         ]
      }
   ]
}
```

Relative paths inside `ways[].file` are resolved against the config file’s directory. The optional `name` field drives the output folder naming (`output/<name>/plot.png`), and the optional `sample_rate` controls how digital filters are evaluated (defaults to 192 kHz so the 20 kHz band is well below Nyquist). The `color` field accepts either hex codes (e.g. `#1f77b4`) or the built-in English/German names (`blau`, `blue`, `grün`, `green`, `rot`, `red`, etc.); any unknown name raises a clear error at load time.

### Calibrating manufacturer profiles
- Pick a project, switch to the **Filters** tab, and browse to whichever sweeps you captured. You can refresh individual sections (PEQ, all-pass, shelf, or either crossover) independently—only the provided files are re-fit, and the remaining coefficients stay untouched.
- Each crossover sweep row has its own frequency, order buttons (up to 8th, with Linkwitz-Riley restricted to even numbers), and “Low/High” toggle. This allows you to calibrate a Butterworth low-pass and a Linkwitz-Riley high-pass in one pass even if their orders differ.
- Keep every sweep inside the same folder; the calibration dialog enforces this so the relative file names stored inside the project remain valid for collaborators.
- After running **Run calibration**, the updated filterset is stored in `manufacturers.json`, linked to the active project, and the project export will embed the new coefficients so they cannot get lost when the `.eqproj` file is shared.

### Filters array (per way)
- `type`: one of `butterworth`, `linkwitz-riley`/`lr`, `peq`, `shelf`, or `phase` (all-pass).
   - New utility blocks: `gain` (constant gain in dB) and `delay` (time offset in µs).
- Butterworth / Linkwitz-Riley specific keys:
   - `mode`: `lowpass`, `highpass`, `bandpass`, or `bandstop` (LR requires low/high pass with even `order`).
   - `order`: integer filter order.
   - `freq` (single cutoff) or `freqs: [low, high]` for band filters.
- `peq`: `f0`, `gain_db`, `q`.
- `shelf`: `mode` (`low`/`high`), `freq`, `gain_db`, optional `slope`.
- `phase`: shorthand for a unity-gain all-pass biquad; provide `f0` and `q`.
- `gain`: requires `gain_db` (positive or negative) and simply scales the way before summation.
- `delay`: provide `delay_us` (microseconds). The block applies `e^{-j 2\pi f \cdot delay}` to shift the phase without touching magnitude.

Filters are evaluated in order and multiplied into each way’s measured response before plotting, so you can describe full crossover stacks straight from the config file.

## What the plot shows
- Individual magnitudes for TT, MT, and HT (using the colors green, blue, and yellow)
- A black curve representing the complex sum of the three ways
- A dedicated **minimum-phase** axis beneath the magnitude plot (dashed black), derived via Hilbert transform with best-fit delay removed, then wrapped to 0–360° for easy reading with a legend entry labeled "Sum minimum phase"
- A third phase panel (also wrapped to 0–360°) plotting each way's absolute phase. Segments where a way contributes ≥10 % of the sum appear as solid lines; quieter sections fade into thin dashed traces for context
- Log-frequency axis with a dense grid in the overlapping region shared by all three FRD files
- Magnitude axis enforces a **25 dB per decade pixel ratio** while locking the display to 20 Hz–20 kHz with a 50 dB window (+5 dB headroom); if a way would fall outside the frame, the lower bound expands in **10 dB steps** but the aspect is recomputed so each decade still matches 25 dB in pixel height
- View is focused on the classic **20 Hz – 20 kHz** band with fixed log ticks at 20, 100, 1k, 10k, and 20k Hz for quick reference

You can now treat this script as the baseline for connecting the measurement files to the planned optimizer shell. Later, the same data structures can be extended with filter blocks, targets, and optimization controls described in `objective.md`.
