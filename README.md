# EQ Optimizer Scratchpad

This repo now ships with a GUI shell that manages EQ projects and a legacy CLI for the existing plotting and calibration workflows. The `input/*.frd` fixtures, default `project.json`, and plotting helpers are still available beneath the new application layer.

## Quick start
1. Install Python 3.12 (or newer) and the dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```
2. Launch the GUI:
   ```powershell
   python main.py
   ```
   The window opens with the **Project** tab so you can create/import/export/delete project configs. All managed projects are stored under `project_store/` (override via `--project-store`).
3. Pick a project and continue with the planned workflow tabs as they are added. You can still hand-edit individual JSON files under `project_store/` or import existing configs at any time.

`main.py` now launches the GUI by default. Pass `--cli` when you want to fall back to the command-line interface covered below.

## Project tab (GUI)
- Lists every managed project stored in `project_store/`
- **New:** builds a copy of the default template (TT/MT/HT) and lists it immediately
- **Import:** adds any `project.json`-style file into the catalog; the file contents are copied into the store so the originals stay untouched
- **Export:** copies the selected project to a destination of your choice (use the `.eqproj` extension to keep things separate)
- **Delete:** removes the selected project from the catalog and deletes its managed copy
- Detail pane: shows metadata about the managed file; the JSON itself stays hidden because every setting will be editable within upcoming GUI tabs.

## Filter tab (GUI)
- **Manufacturer list:** mirrors `manufacturers.json`, with create/import/export/delete actions.
- **Filter palette:** add PEQ, low shelves (high shelves reuse the same coefficients), phase blocks, and Butterworth/Linkwitz-Riley low-pass sections (6–48 dB/oct) directly into the selected manufacturer profile.
- **Single filter per type:** each button activates one canonical block (default 1 kHz, $Q=0.707$, $A=3$ dB) so manufacturers stay aligned with the calibration assumptions.
- **Parameter editor & preview:** tweak frequency, Q/slope, and gain below the live plot to see each block’s magnitude response instantly; when a calibration sweep (PEQ, all-pass, shelf, or low-pass) is linked, its FRD trace is shown automatically while the matching filter button is active.
- **Calibration panel:** point to PEQ/all-pass/shelf sweeps (`.txt`/`.frd`) and optionally add dedicated low-pass sweeps (Butterworth & Linkwitz-Riley, order-selectable) before running the solver to update the manufacturer scaling factors without leaving the app.

## Script options
| Flag | Description |
| --- | --- |
| `--input-dir PATH` | Folder that contains `TT.frd`, `MT.frd`, `HT.frd` (default: `input`). |
| `--tt-file NAME` / `--mt-file NAME` / `--ht-file NAME` | Alternative filenames for the bass, mid, or tweeter ways (used only when no config file is provided/found). |
| `--config PATH` | Path to a JSON config (defaults to `project.json` when present). |
| `--save PATH` | Override the auto-generated output path (`output/<project_name>/plot.png`). |
| `--no-show` | Do not open the GUI window (useful for automated runs or remote sessions). |
| `--points N` | Number of log-spaced frequency samples for interpolation (default: 2000). |
| `--manufacturer-config PATH` | Path to the manufacturer profile file (defaults to `manufacturers.json` next to the project file or in the working directory). |
| `--add-manufacturer NAME` / `-addmanufacturer NAME` | Fit a manufacturer profile from `peq.txt`, `allpass.txt`, and `lowshelf.txt` sweeps (second-order filters) and update the manufacturer config instead of plotting. |
| `--calibration-sample-rate HZ` | Override the sample rate used while fitting the sweeps (paired with `--add-manufacturer`, default 192000 Hz). |
| `--peq-sweep FILE`, `--allpass-sweep FILE`, `--shelf-sweep FILE` | Override the sweep filenames relative to `--input-dir` when using `--add-manufacturer`. |
| `--lowpass-bw-sweep FILE` / `--lowpass-bw-order N` | Optional Butterworth low-pass sweep and its order for `--add-manufacturer`. |
| `--lowpass-lr-sweep FILE` / `--lowpass-lr-order N` | Optional Linkwitz-Riley low-pass sweep (even-order) for `--add-manufacturer`. |
| `--test` | Generate `test.png` that compares the summed response against the VituixFR measurement (see below) instead of the default multi-way plot. |
| `--vituix-file FILE` | Use an alternate FRD file for `--test` (defaults to `input/VituixFR.txt`). |
| `--export-sum FILE` | Write the summed response to an FRD file (full grid by default, trimmed to 20–20 kHz when used with `--test`). |
| `--cli` | Execute the legacy CLI instead of launching the GUI. |
| `--project-store PATH` | Override the GUI project catalog folder (default: `project_store/`). |

### Legacy CLI mode
Run any of the historical commands by combining `--cli` with the flags above, e.g.:

```powershell
python main.py --cli --config project.json --no-show
```

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
- Run `python main.py --add-manufacturer hypex` to estimate scale factors for `peq`, `shelf`, and `allpass` filters from the measured sweeps located under `input/` (`peq.txt`, `allpass.txt`, and `lowshelf.txt` by default). All three sweeps must represent **second-order** sections configured for 3 dB, $Q = 0.707$, and $f = 1000$ Hz; this also covers both low and high shelves because the manufacturer profile scales the shared shelf block.
- Provide optional Butterworth or Linkwitz-Riley low-pass sweeps with `--lowpass-bw-sweep somefile.frd` and/or `--lowpass-lr-sweep otherfile.frd`. Pair them with `--lowpass-bw-order N` or `--lowpass-lr-order N` (even numbers only for Linkwitz-Riley) to tell the solver which order the hardware sweep represents; the GUI exposes the same inputs inside the calibration panel.
- Use `--peq-sweep`, `--allpass-sweep`, or `--shelf-sweep` to point at alternative sweep filenames, and `--calibration-sample-rate` to match the DSP’s internal rate if it differs from the default 192 kHz. The command reuses `--manufacturer-config` to decide which JSON file should be updated (creating it when necessary) and overwrites existing entries with the same name.

### Test comparison mode
- Run `python main.py --test` once you have placed `VituixFR.txt` (standard FRD columns) in the `input/` folder. The command loads the configured project, sums all filtered ways, resamples the Vituix measurement to the shared frequency grid, trims both traces to 20 Hz–20 kHz, and writes `output/<project_name>/test.png`.
- The figure overlays the magnitude traces of the summed response and the Vituix measurement, centers the vertical scale around the average magnitude of both curves (±5 dB), and shows a paired phase plot where both traces are wrapped to ±180°. Pass `--vituix-file some/other.frd` to compare against a different reference sweep and `--no-show` when you only need the PNG file.
- Add `--export-sum output/<project_name>/sum.frd` when you want the same trimmed summed response (20–20 kHz) written as an FRD file for comparison inside VituixCAD or other tools. Without `--test`, the export covers the full interpolation grid.

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
