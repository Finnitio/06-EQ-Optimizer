# EQ Optimizer Scratchpad

This repo currently contains the TT/MT/HT measurement files (`input/*.frd`), a default config file (`project.json`), and a helper script to visualize the three ways together with their summed response.

## Quick start
1. Install Python 3.12 (or newer) and the dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```
2. Edit `project.json` if you need to point to different measurement files, rename/color the ways, or switch the `manufacturer` profile used for the biquad math. The default file already references `input/TT.frd`, `input/MT.frd`, and `input/HT.frd` with the requested green/blue/yellow colors.
3. Generate the plot via the main entry point. By default the figure is saved under `output/<project_name>/plot.png` where `<project_name>` comes from the config (see below). Use `--save` only if you want to override that path. Example:
   ```powershell
   python main.py
   ```

`main.py` automatically loads `project.json` if it exists. You only need the `--tt-file`/`--mt-file`/`--ht-file` overrides when deliberately running without a config file. (`plot_three_way.py` still exists as a thin wrapper for backwards compatibility, but all new functionality lives in `main.py`.)

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
| `--test` | Generate `test.png` that compares the summed response against the VituixFR measurement (see below) instead of the default multi-way plot. |
| `--vituix-file FILE` | Use an alternate FRD file for `--test` (defaults to `input/VituixFR.txt`). |

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
- Use `--peq-sweep`, `--allpass-sweep`, or `--shelf-sweep` to point at alternative sweep filenames, and `--calibration-sample-rate` to match the DSP’s internal rate if it differs from the default 192 kHz. The command reuses `--manufacturer-config` to decide which JSON file should be updated (creating it when necessary) and overwrites existing entries with the same name.

### Test comparison mode
- Run `python main.py --test` once you have placed `VituixFR.txt` (standard FRD columns) in the `input/` folder. The command loads the configured project, sums all filtered ways, resamples the Vituix measurement to the shared frequency grid, trims both traces to 20 Hz–20 kHz, and writes `output/<project_name>/test.png`.
- The figure overlays the magnitude traces of the summed response and the Vituix measurement, centers the vertical scale around the average magnitude of both curves (±5 dB), and shows a paired phase plot where both traces are wrapped to ±180°. Pass `--vituix-file some/other.frd` to compare against a different reference sweep and `--no-show` when you only need the PNG file.

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
