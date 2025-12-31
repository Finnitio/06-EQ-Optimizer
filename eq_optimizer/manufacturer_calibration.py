from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.optimize import least_squares

from .filters import FilterBlock, design_filter_response
from .measurements import Response, load_frd


@dataclass(slots=True)
class ReferenceSettings:
    """Reference values used while fitting the calibration sweeps."""

    freq_hz: float = 1000.0
    gain_db: float = 3.0
    q: float = 0.707
    shelf_slope: float = 0.707


@dataclass(slots=True)
class SweepFiles:
    peq: Path
    allpass: Path
    shelf: Path

    def paths(self) -> Iterable[Path]:
        return (self.peq, self.allpass, self.shelf)


@dataclass(slots=True)
class _ParameterSpec:
    name: str
    initial: float
    lower: float
    upper: float


def calibrate_manufacturer_profile(
    name: str,
    sweep_dir: Path,
    peq_file: str,
    allpass_file: str,
    shelf_file: str,
    sample_rate: float,
    reference: ReferenceSettings | None = None,
) -> dict[str, Any]:
    """Create a manufacturer entry by fitting three second-order sweeps."""

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Manufacturer name must not be empty")

    ref = reference or ReferenceSettings()
    sweeps = SweepFiles(
        peq=(sweep_dir / peq_file).resolve(),
        allpass=(sweep_dir / allpass_file).resolve(),
        shelf=(sweep_dir / shelf_file).resolve(),
    )

    for path in sweeps.paths():
        if not path.exists():
            raise FileNotFoundError(f"Missing calibration sweep: {path}")

    responses = {
        "peq": load_frd(sweeps.peq),
        "allpass": load_frd(sweeps.allpass),
        "shelf": load_frd(sweeps.shelf),
    }

    filters = {
        "peq": _calibrate_peq(responses["peq"], sample_rate, ref),
        "allpass": _calibrate_allpass(responses["allpass"], sample_rate, ref),
        "shelf": _calibrate_shelf(responses["shelf"], sample_rate, ref),
    }

    description = (
        "Auto-calibrated from 2nd-order PEQ/All-pass/Shelf sweeps "
        f"({sweeps.peq.name}, {sweeps.allpass.name}, {sweeps.shelf.name}) "
        f"with {ref.gain_db} dB, Q={ref.q}, f={ref.freq_hz} Hz."
    )

    return {"name": clean_name, "description": description, "filters": filters}


def persist_manufacturer_profile(entry: dict[str, Any], path: Path) -> Path:
    """Insert or update the given manufacturer entry in *path*."""

    container, structure = _load_existing_config(path)
    _upsert_entry(container, structure, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(container, indent=2), encoding="utf-8")
    return path


def _load_existing_config(path: Path) -> tuple[Any, str]:
    if not path or not path.exists():
        return ({"manufacturers": []}, "wrapped_list")

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("manufacturers"), list):
        return data, "wrapped_list"
    if isinstance(data, list):
        return data, "list"
    if isinstance(data, dict):
        return data, "dict"
    raise ValueError("Unsupported manufacturer config format")


def _upsert_entry(container: Any, structure: str, entry: dict[str, Any]) -> None:
    name = str(entry.get("name", "")).strip()
    if not name:
        raise ValueError("Manufacturer entry requires a 'name' field")
    key = name.lower()

    if structure == "wrapped_list":
        _upsert_into_list(container["manufacturers"], entry, key)
    elif structure == "list":
        _upsert_into_list(container, entry, key)
    elif structure == "dict":
        container[key] = entry
    else:
        raise ValueError(f"Unsupported config structure '{structure}'")


def _upsert_into_list(items: list[dict[str, Any]], entry: dict[str, Any], key: str) -> None:
    for idx, candidate in enumerate(items):
        cand_name = str(candidate.get("name", "")).strip().lower()
        if cand_name == key:
            items[idx] = entry
            return
    items.append(entry)


def _calibrate_peq(response: Response, sample_rate: float, reference: ReferenceSettings) -> dict[str, float]:
    specs = [
        _ParameterSpec("f0", reference.freq_hz, reference.freq_hz * 0.25, reference.freq_hz * 4.0),
        _ParameterSpec("gain_db", reference.gain_db, max(0.1, reference.gain_db * 0.25), reference.gain_db * 4.0),
        _ParameterSpec("q", reference.q, 0.1, 12.0),
    ]
    result = _fit_section("peq", response, sample_rate, specs, mag_weight=1.0, phase_weight=0.05)
    return {
        "formula": "cookbook",
        "freq_scale": _scale(result["f0"], reference.freq_hz),
        "gain_scale": _scale(result["gain_db"], reference.gain_db),
        "q_scale": _scale(result["q"], reference.q),
    }


def _calibrate_allpass(response: Response, sample_rate: float, reference: ReferenceSettings) -> dict[str, float]:
    specs = [
        _ParameterSpec("freq", reference.freq_hz, reference.freq_hz * 0.25, reference.freq_hz * 4.0),
        _ParameterSpec("q", reference.q, 0.1, 12.0),
    ]
    result = _fit_section("phase", response, sample_rate, specs, mag_weight=0.05, phase_weight=1.0)
    return {
        "formula": "cookbook",
        "freq_scale": _scale(result["freq"], reference.freq_hz),
        "q_scale": _scale(result["q"], reference.q),
    }


def _calibrate_shelf(response: Response, sample_rate: float, reference: ReferenceSettings) -> dict[str, float]:
    specs = [
        _ParameterSpec("freq", reference.freq_hz, reference.freq_hz * 0.25, reference.freq_hz * 4.0),
        _ParameterSpec("gain_db", reference.gain_db, max(0.1, reference.gain_db * 0.25), reference.gain_db * 6.0),
        _ParameterSpec("slope", reference.shelf_slope, 0.1, 4.0),
    ]
    result = _fit_section("shelf", response, sample_rate, specs, extra={"mode": "low"}, mag_weight=1.0, phase_weight=0.05)
    return {
        "formula": "cookbook",
        "freq_scale": _scale(result["freq"], reference.freq_hz),
        "gain_scale": _scale(result["gain_db"], reference.gain_db),
        "slope_scale": _scale(result["slope"], reference.shelf_slope),
    }


def _fit_section(
    kind: str,
    response: Response,
    sample_rate: float,
    specs: list[_ParameterSpec],
    extra: dict[str, Any] | None = None,
    mag_weight: float = 1.0,
    phase_weight: float = 0.1,
) -> dict[str, float]:
    freq = response.frequency
    if freq.size == 0:
        raise ValueError("Calibration sweep must contain frequency data")
    max_freq = float(freq.max())
    if sample_rate <= 2.1 * max_freq:
        raise ValueError(
            f"Sample rate {sample_rate:.1f} Hz is insufficient for sweep up to {max_freq:.1f} Hz"
        )

    measured_mag = response.magnitude_db
    measured_phase = response.phase_rad

    names = [spec.name for spec in specs]
    x0 = np.array([spec.initial for spec in specs], dtype=float)
    lower = np.array([spec.lower for spec in specs], dtype=float)
    upper = np.array([spec.upper for spec in specs], dtype=float)

    def residuals(vec: np.ndarray) -> np.ndarray:
        params = dict(extra or {})
        params.update({name: float(value) for name, value in zip(names, vec)})
        block = FilterBlock(kind=kind, params=params)
        prediction = design_filter_response(block, freq, sample_rate)
        pred_mag = 20.0 * np.log10(np.maximum(np.abs(prediction), 1e-12))
        pred_phase = np.unwrap(np.angle(prediction))
        mag_error = (pred_mag - measured_mag) * (mag_weight if mag_weight else 0.0)
        phase_error = (pred_phase - measured_phase) * (phase_weight if phase_weight else 0.0)
        return np.concatenate([mag_error, phase_error])

    result = least_squares(residuals, x0, bounds=(lower, upper), loss="soft_l1", max_nfev=400)
    if not result.success:
        raise RuntimeError(f"Unable to fit {kind} sweep: {result.message}")
    return {name: float(value) for name, value in zip(names, result.x)}


def _scale(value: float, reference: float) -> float:
    if abs(reference) < 1e-9:
        return 1.0
    ratio = value / reference
    return float(np.round(ratio, 6))
