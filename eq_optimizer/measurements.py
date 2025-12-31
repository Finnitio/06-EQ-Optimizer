from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np


@dataclass
class Response:
    frequency: np.ndarray
    magnitude_db: np.ndarray
    phase_rad: np.ndarray


def load_frd(path: Path) -> Response:
    """Load an FRD file containing frequency (Hz), magnitude (dB), phase (deg)."""
    freqs: list[float] = []
    mags: list[float] = []
    phases_deg: list[float] = []

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("*", ";", "#")):
                continue
            parts = stripped.split()
            if len(parts) < 3:
                continue
            f, m, p = parts[:3]
            try:
                freqs.append(float(f))
                mags.append(float(m))
                phases_deg.append(float(p))
            except ValueError:
                continue

    if not freqs:
        raise ValueError(f"No FRD data found in {path}")

    freq_arr = np.asarray(freqs)
    sort_idx = np.argsort(freq_arr)
    freq_arr = freq_arr[sort_idx]
    mag_arr = np.asarray(mags)[sort_idx]
    phase_deg_arr = np.asarray(phases_deg)[sort_idx]
    phase_rad_arr = np.unwrap(np.deg2rad(phase_deg_arr))

    return Response(frequency=freq_arr, magnitude_db=mag_arr, phase_rad=phase_rad_arr)


def write_frd(response: Response, path: Path, include_header: bool = True) -> None:
    """Persist a response as frequency/magnitude/phase triplets in FRD format."""
    freq = np.asarray(response.frequency)
    mag = np.asarray(response.magnitude_db)
    phase_deg = np.degrees(np.asarray(response.phase_rad))
    if freq.shape != mag.shape or freq.shape != phase_deg.shape:
        raise ValueError("Response arrays must share the same shape before exporting to FRD")

    destination = Path(path)
    if destination.parent:
        destination.parent.mkdir(parents=True, exist_ok=True)

    header = "* Frequency[Hz]\tMagnitude[dB]\tPhase[deg]\n"
    with destination.open("w", encoding="ascii") as handle:
        if include_header:
            handle.write(header)
        for f_val, mag_db, phase in zip(freq, mag, phase_deg):
            handle.write(f"{f_val:.6f}\t{mag_db:.6f}\t{phase:.6f}\n")


def build_common_grid(responses: Sequence[Response], points: int = 2000) -> np.ndarray:
    min_freqs = [resp.frequency.min() for resp in responses]
    max_freqs = [resp.frequency.max() for resp in responses]
    low = max(min_freqs)
    high = min(max_freqs)
    if low <= 0 or high <= low:
        raise ValueError("Unable to determine overlapping frequency range between responses")
    return np.logspace(math.log10(low), math.log10(high), points)


def resample_response(response: Response, target_freqs: np.ndarray) -> Response:
    source_freqs = response.frequency
    mag = response.magnitude_db
    phase = response.phase_rad
    x_src = np.log10(source_freqs)
    x_tgt = np.log10(target_freqs)
    mag_interp = np.interp(x_tgt, x_src, mag)
    phase_interp = np.interp(x_tgt, x_src, phase)
    return Response(frequency=target_freqs, magnitude_db=mag_interp, phase_rad=phase_interp)


def compute_complex(response: Response) -> np.ndarray:
    mag_lin = np.power(10.0, response.magnitude_db / 20.0)
    return mag_lin * np.exp(1j * response.phase_rad)


def estimate_minimum_phase_response(response: Response, remove_delay: bool = True) -> Response:
    """Approximate the minimum-phase version of a response using a Hilbert transform."""
    phase = compute_minimum_phase_angle(response.frequency, response.magnitude_db, remove_delay=remove_delay)
    return Response(
        frequency=response.frequency.copy(),
        magnitude_db=response.magnitude_db.copy(),
        phase_rad=phase,
    )


def compute_minimum_phase_angle(
    frequency: np.ndarray,
    magnitude_db: np.ndarray,
    remove_delay: bool = True,
) -> np.ndarray:
    mag_lin = np.power(10.0, magnitude_db / 20.0)
    log_mag = np.log(np.maximum(mag_lin, 1e-12))
    hilbert = _hilbert_transform(log_mag)
    phase = -hilbert
    if remove_delay:
        # Remove best-fit linear phase (constant group delay / excess phase)
        poly = np.polyfit(frequency, phase, 1)
        phase -= np.polyval(poly, frequency)
    else:
        phase -= phase[-1]
    return phase


def _hilbert_transform(x: np.ndarray) -> np.ndarray:
    n = x.size
    spectrum = np.fft.fft(x)
    h = np.zeros(n)
    if n % 2 == 0:
        h[0] = h[n // 2] = 1
        h[1 : n // 2] = 2
    else:
        h[0] = 1
        h[1 : (n + 1) // 2] = 2
    analytic = np.fft.ifft(spectrum * h)
    return np.imag(analytic)
