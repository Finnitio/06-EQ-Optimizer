# EQ Optimizer Objective

## Vision
- Deliver a Python-driven workflow that tunes a 3-way loudspeaker (Low / Mid / High) by optimizing IIR filters per way until the summed response follows a user-defined target (initially a flat line at a given SPL).
- The system acts as an interactive script: the user builds the scenario (ways, response files, filter blocks), inspects plots on demand, defines optimization freedoms, then launches an optimizer that reports visual progress every 5 seconds.
- Sessions must be pausable/resumable by snapshotting all assets (configs, source data, optimizer state) into a zip archive that can be reloaded later.

## Functional Scope
### Way & Measurement Management
- Create any number of "ways" (default 3) with names, gain offsets, and color coding.
- Attach a frequency-response file (CSV, TXT, or ARTA export) to each way; parser normalizes frequency (Hz) + magnitude (dB) pairs.
- Support phase traces so that summation can be complex (magnitude + phase) rather than magnitude-only.

### Filter Blocks (non-biquad parameterization)
- Each way holds an ordered list of IIR filter primitives described by physical parameters (type, f0, gain, Q/slope) rather than direct biquad coefficients.
- User may preset parameter values and min/max bounds so the optimizer knows which knobs are free vs. locked.
- Provide reusable filter templates (PEQ, shelving, all-pass, notch) stored as YAML/JSON snippets.

### Plotting & Monitoring
- Command `plot_now()` renders individual ways, applied filters, and the acoustic sum in a single Matplotlib figure.
- When optimization is running, refresh the plot every 5 seconds with current filter parameters and overlay target curve + error bands.
- Allow exporting figures (PNG/SVG) on demand for documentation.
- After each optimization run finishes (and on demand), emit a detailed list of the optimized filters per way (type, f0, gain, Q/slope, enabled status) so the final tuning recipe is explicitly documented—treat this report as essential before concluding a session.

### Target Definition & Cost Function
- Start with a linear target curve at a specified SPL (e.g., 90 dB) and allow future extensions (house curves, per-band weights).
- Cost function operates on log-frequency spacing, emphasizing the overlap region of the 3 ways; include configurable weighting and penalty on excessive boost/cut.

### Optimization Control
- User specifies:
  - Filter parameters that may vary (per way, per filter, per parameter).
  - Optimization algorithm (e.g., `scipy.optimize.least_squares`, `differential_evolution`, or `nevergrad` strategies) and number of passes/iterations.
  - Convergence / stop criteria (tolerance in dB RMS error, max runtime).
- Console commands: `start_opt()`, `pause_opt()`, `resume_opt()`, `stop_opt()`.
- Optimization loop emits status every 5 seconds (iteration, error metrics) alongside the plot refresh.

### Pause / Resume / Session Persistence
- `save_session("session-name.zip")` bundles:
  - Serialized project config (ways, filters, target, optimizer settings) in JSON/YAML.
  - Input measurement files and any derived data (resampled grids).
  - Latest optimizer state (parameter vector, algorithm-specific momentum, RNG state).
  - Log files and last generated plots.
- `load_session(zip_path)` recreates the working directory, restores optimizer objects, and resumes plotting timers.

## User Workflow (Happy Path)
1. Run `python optimizer_shell.py` to enter an interactive prompt.
2. `add_way name=L path=./measurements/woofer.csv color="#1f77b4" gain_db=0` (repeat for M/H).
3. `add_filter way=L type=peq f0=80 gain_db=0 q=1.2 free_params=[gain_db,q]` etc.
4. `plot_now()` to confirm baseline responses.
5. `set_target flat --level-db 90` (later allow custom curve files).
6. `opt_config algorithm="least_squares" passes=3 max_runtime=1200 weightings={"L":1,"M":1,"H":1}`.
7. `start_opt()` to launch optimization; observe auto-plots every 5 seconds. Use `plot_now()` any time for an immediate refresh.
8. `pause_opt()` when needed; optionally `save_session("woofer-tuning.zip")`.
9. At a later time, run `load_session("woofer-tuning.zip")`, then `resume_opt()`.

## Architecture Overview
- **Core packages**
  - `ways.py`: data classes (`Way`, `FilterBlock`, `FilterParamConstraint`).
  - `measurements.py`: loaders + resamplers for FR data, including smoothing options.
  - `filters.py`: conversions between user parameters and IIR coefficients via `scipy.signal` utilities.
  - `optimizer.py`: wraps selected optimization engines, exposes async-friendly interface for pause/resume.
  - `plotting.py`: Matplotlib routines for per-way, sum, and error curves; manages 5-second timer via `matplotlib.animation` or background thread.
  - `session.py`: serialization, zip packaging, integrity checks.
  - `shell.py`: REPL/CLI handling (cmd2 or textual for richer TUI).
- **Data Flow**
  1. Measurements resampled onto a shared log-frequency grid.
  2. Filters converted to magnitude/phase responses and applied per way.
  3. Ways summed (complex domain) to compute system response.
  4. Cost function compares system response to target, producing gradients/errors for optimizer.
  5. State (parameters + metadata) stored in a central `ProjectState` object for serialization.

## Optimization Strategy Details
- Default objective: minimize weighted RMS error between system response and target over 20 Hz – 20 kHz.
- Optional penalties: constrain boost/cut to ±12 dB, limit Q to prevent ultra-narrow filters, include smoothness penalty on parameter jumps between passes.
- Offer presets:
  - **Fast local**: `least_squares` with numeric Jacobian.
  - **Global coarse**: `differential_evolution` to find a basin, then hand off to local solver.
  - **Heuristic**: population-based search (e.g., CMA-ES via `cma` package) when filters interact strongly.
- Progress hook updates shared state every iteration so that the plotting thread can read consistent parameters.

## Plot Refresh Mechanism
- Use a background `threading.Timer` or `asyncio` task that wakes every 5 seconds while optimization is active.
- Each refresh regenerates per-way and summed FR data using the latest parameters, draws target + ± tolerance bands, and timestamps the figure.
- Provide a lightweight cache so identical plots (no parameter change) are skipped to save CPU.

## Session Zip Format (proposal)
```
project/
  config.yaml             # ways, filters, optimizer config
  data/
    measurements/*.csv    # original files
    grid.pkl              # resampled frequency grid
  state/
    optimizer.pkl         # algorithm-specific state dict
    parameters.json       # current parameter vector
  logs/
    events.log            # textual history
  plots/
    latest.png
```
- Use `zipfile` with CRC to ensure integrity; include manifest version for forward compatibility.

## CLI / Scripting Commands (Draft)
| Command | Purpose |
| --- | --- |
| `add_way name path [gain_db] [color]` | Register a way and link its measurement file. |
| `add_filter way type param=value ... [free=param1,param2]` | Append a filter block with optional free parameters. |
| `plot_now [--sum-only]` | Force immediate plot generation. |
| `set_target flat --level-db X` or `set_target file path` | Define the optimization goal. |
| `opt_config key=value ...` | Choose algorithm, passes, tolerances, runtime. |
| `start_opt` / `pause_opt` / `resume_opt` / `stop_opt` | Control optimizer lifecycle. |
| `save_session path.zip` / `load_session path.zip` | Persist or restore the full project state. |

## Non-Functional Requirements
- Runs on Windows/macOS/Linux with Python ≥3.10.
- Matplotlib backend should fall back to Agg when no display is available.
- Ensure thread-safe access to shared state between optimizer and plotting timers.
- Logging via `structlog` or `logging` module with timestamps for reproducibility.

## Next Steps
1. Scaffold the Python project (poetry or uv) with the modules listed above.
2. Define data classes and serialization schema (`pydantic` or `dataclasses` + marshmallow).
3. Implement measurement ingestion + shared frequency grid generation.
4. Prototype filter parameter → biquad conversion and magnitude/phase evaluation.
5. Stub optimizer wrapper with fake updates to verify the 5-second plotting loop.
6. Implement session save/load pipeline and validate zip integrity.
7. Author unit tests for cost function, serialization, and pause/resume logic.
