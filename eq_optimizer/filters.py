from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
from scipy import signal

from .measurements import Response, compute_complex
from .manufacturers import ManufacturerProfile


@dataclass
class FilterBlock:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FilterBlock":
        if "type" not in data:
            raise ValueError("Filter definition must contain a 'type' field")
        kind = str(data["type"]).lower()
        params = {k: v for k, v in data.items() if k != "type"}
        return cls(kind=kind, params=params)


def apply_filter_chain(
    response: Response,
    filters: Iterable[FilterBlock],
    sample_rate: float,
    manufacturer: ManufacturerProfile | None = None,
) -> Response:
    filters_list = list(filters)
    if not filters_list:
        return response

    freq = response.frequency
    complex_resp = compute_complex(response)

    for block in filters_list:
        h = design_filter_response(block, freq, sample_rate, manufacturer)
        complex_resp *= h

    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(complex_resp), 1e-12))
    phase_rad = np.unwrap(np.angle(complex_resp))
    return Response(frequency=freq, magnitude_db=magnitude_db, phase_rad=phase_rad)


def design_filter_response(
    block: FilterBlock,
    freq_hz: np.ndarray,
    sample_rate: float,
    manufacturer: ManufacturerProfile | None = None,
) -> np.ndarray:
    kind = block.kind
    params = _merge_params(block, manufacturer)

    if not bool(params.get("enabled", True)):
        return np.ones_like(freq_hz, dtype=np.complex128)

    if kind == "butterworth":
        return _design_butterworth(params, freq_hz, sample_rate)
    if kind in {"linkwitz-riley", "lr"}:
        return _design_linkwitz_riley(params, freq_hz, sample_rate)
    if kind in {"peq", "peaking"}:
        return _design_peq(params, freq_hz, sample_rate)
    if kind in {"shelf", "shelving"}:
        return _design_shelf(params, freq_hz, sample_rate)
    if kind in {"phase", "allpass"}:
        return _design_allpass(params, freq_hz, sample_rate)
    if kind in {"gain", "gain_db", "gain-db"}:
        return _design_gain(params, freq_hz)
    if kind in {"delay", "delay_us", "delay-µs"}:
        return _design_delay(params, freq_hz)

    raise ValueError(f"Unsupported filter type: {kind}")


def _merge_params(block: FilterBlock, manufacturer: ManufacturerProfile | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if manufacturer is not None:
        merged.update(manufacturer.settings_for(block.kind))
    merged.update(block.params)
    return merged


def _design_butterworth(params: dict[str, Any], freq_hz: np.ndarray, sample_rate: float) -> np.ndarray:
    order = int(params.get("order", 2))
    mode = params.get("mode", "lowpass").lower()
    wn = _extract_normalized_cutoff(params, sample_rate, mode)
    b, a = signal.butter(order, wn, btype=mode, analog=False, output="ba")
    return _freq_response(b, a, freq_hz, sample_rate)


def _design_linkwitz_riley(params: dict[str, Any], freq_hz: np.ndarray, sample_rate: float) -> np.ndarray:
    order = int(params.get("order", 4))
    if order % 2 != 0:
        raise ValueError("Linkwitz-Riley order must be an even number")
    mode = params.get("mode", "lowpass").lower()
    wn = _extract_normalized_cutoff(params, sample_rate, mode)
    base_order = order // 2
    b, a = signal.butter(base_order, wn, btype=mode, analog=False, output="ba")
    h = _freq_response(b, a, freq_hz, sample_rate)
    return h * h


def _design_peq(params: dict[str, Any], freq_hz: np.ndarray, sample_rate: float) -> np.ndarray:
    f0 = float(params.get("f0") or params.get("freq") or params.get("fc"))
    f0 = f0 * float(params.get("freq_scale", 1.0)) + float(params.get("freq_offset_hz", params.get("freq_offset", 0.0)))
    if f0 <= 0:
        raise ValueError("Parametric EQ requires a positive center frequency")

    q = float(params.get("q", 1.0)) * float(params.get("q_scale", 1.0))
    q = _clamp(q, params.get("q_min"), params.get("q_max"))
    gain_db = float(params.get("gain_db", 0.0))
    gain_db = gain_db * float(params.get("gain_scale", 1.0)) + float(params.get("gain_offset_db", 0.0))
    gain_limit = params.get("gain_limit_db")
    if gain_limit is not None:
        limit = abs(float(gain_limit))
        gain_db = _clamp(gain_db, -limit, limit)
    b, a = _biquad_peq(f0, q, gain_db, sample_rate)
    return _freq_response(b, a, freq_hz, sample_rate)


def _design_shelf(params: dict[str, Any], freq_hz: np.ndarray, sample_rate: float) -> np.ndarray:
    mode = params.get("mode", "low").lower()
    freq0 = float(params.get("freq") or params.get("f0") or params.get("fc"))
    freq0 = freq0 * float(params.get("freq_scale", 1.0)) + float(params.get("freq_offset_hz", params.get("freq_offset", 0.0)))
    if freq0 <= 0:
        raise ValueError("Shelf filter requires a positive corner frequency")

    gain_db = float(params.get("gain_db", 0.0))
    gain_db = gain_db * float(params.get("gain_scale", 1.0)) + float(params.get("gain_offset_db", 0.0))
    gain_limit = params.get("gain_limit_db")
    if gain_limit is not None:
        limit = abs(float(gain_limit))
        gain_db = _clamp(gain_db, -limit, limit)
    slope = float(params.get("slope", params.get("s", 1.0))) * float(params.get("slope_scale", 1.0))
    slope = _clamp(slope, params.get("slope_min"), params.get("slope_max"))
    b, a = _biquad_shelf(freq0, gain_db, slope, sample_rate, mode)
    return _freq_response(b, a, freq_hz, sample_rate)


def _design_allpass(params: dict[str, Any], freq_hz: np.ndarray, sample_rate: float) -> np.ndarray:
    freq0 = float(params.get("freq") or params.get("f0") or params.get("fc"))
    freq0 = freq0 * float(params.get("freq_scale", 1.0)) + float(params.get("freq_offset_hz", params.get("freq_offset", 0.0)))
    if freq0 <= 0:
        raise ValueError("All-pass filter requires a positive center frequency")
    q = float(params.get("q", 0.707)) * float(params.get("q_scale", 1.0))
    q = _clamp(q, params.get("q_min"), params.get("q_max"))
    b, a = _biquad_allpass(freq0, q, sample_rate)
    return _freq_response(b, a, freq_hz, sample_rate)


def _design_gain(params: dict[str, Any], freq_hz: np.ndarray) -> np.ndarray:
    if "gain_db" not in params:
        raise ValueError("Gain filter requires 'gain_db'")
    gain_db = float(params.get("gain_db", 0.0))
    gain = 10 ** (gain_db / 20.0)
    return np.full(freq_hz.shape, gain, dtype=np.complex128)


def _design_delay(params: dict[str, Any], freq_hz: np.ndarray) -> np.ndarray:
    delay_us = params.get("delay_us")
    if delay_us is None:
        delay_us = params.get("us")
    if delay_us is None:
        delay_us = params.get("microseconds")
    if delay_us is None:
        raise ValueError("Delay filter requires 'delay_us'")
    delay_s = (float(delay_us) + float(params.get("delay_offset_us", 0.0))) * 1e-6
    phase = -2.0j * np.pi * freq_hz * delay_s
    return np.exp(phase)


def _extract_normalized_cutoff(params: dict[str, Any], sample_rate: float, mode: str) -> Any:
    nyquist = sample_rate / 2.0
    if mode in {"lowpass", "highpass"}:
        freq = params.get("freq") or params.get("f0") or params.get("fc")
        if freq is None:
            raise ValueError("Filter definition missing 'freq' for Butterworth/LR")
        wn = float(freq) / nyquist
        if not 0 < wn < 1:
            raise ValueError("Cutoff frequency must be within (0, Nyquist)")
        return wn
    if mode in {"bandpass", "bandstop"}:
        freqs = params.get("freqs") or params.get("band")
        if not freqs or len(freqs) != 2:
            raise ValueError("Band filters require a 'freqs' array with [low, high]")
        wn = [float(freqs[0]) / nyquist, float(freqs[1]) / nyquist]
        if not 0 < wn[0] < wn[1] < 1:
            raise ValueError("Band frequencies must lie within (0, Nyquist)")
        return wn
    raise ValueError(f"Unsupported Butterworth/LR mode: {mode}")


def _freq_response(b: np.ndarray, a: np.ndarray, freq_hz: np.ndarray, sample_rate: float) -> np.ndarray:
    nyquist = sample_rate / 2.0
    max_freq = freq_hz.max()
    if max_freq >= nyquist:
        raise ValueError(
            f"Frequency grid ({max_freq:.1f} Hz max) exceeds Nyquist ({nyquist:.1f} Hz). "
            "Increase sample_rate in project config."
        )
    w = 2.0 * np.pi * freq_hz / sample_rate
    _, h = signal.freqz(b, a, worN=w)
    return h


def _biquad_peq(f0: float, q: float, gain_db: float, sample_rate: float) -> tuple[np.ndarray, np.ndarray]:
    w0 = 2.0 * np.pi * f0 / sample_rate
    alpha = np.sin(w0) / (2.0 * q)
    a = 10 ** (gain_db / 40.0)
    b0 = 1 + alpha * a
    b1 = -2 * np.cos(w0)
    b2 = 1 - alpha * a
    a0 = 1 + alpha / a
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha / a
    b = np.array([b0, b1, b2]) / a0
    a = np.array([1.0, a1 / a0, a2 / a0])
    return b, a


def _biquad_shelf(
    f0: float,
    gain_db: float,
    slope: float,
    sample_rate: float,
    mode: str,
) -> tuple[np.ndarray, np.ndarray]:
    w0 = 2.0 * np.pi * f0 / sample_rate
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    a = 10 ** (gain_db / 40.0)
    alpha = sin_w0 / 2.0 * np.sqrt((a + 1 / a) * (1 / slope - 1) + 2)
    beta = 2 * np.sqrt(a) * alpha

    if mode == "low":
        b0 = a * ((a + 1) - (a - 1) * cos_w0 + beta)
        b1 = 2 * a * ((a - 1) - (a + 1) * cos_w0)
        b2 = a * ((a + 1) - (a - 1) * cos_w0 - beta)
        a0 = (a + 1) + (a - 1) * cos_w0 + beta
        a1 = -2 * ((a - 1) + (a + 1) * cos_w0)
        a2 = (a + 1) + (a - 1) * cos_w0 - beta
    elif mode == "high":
        b0 = a * ((a + 1) + (a - 1) * cos_w0 + beta)
        b1 = -2 * a * ((a - 1) + (a + 1) * cos_w0)
        b2 = a * ((a + 1) + (a - 1) * cos_w0 - beta)
        a0 = (a + 1) - (a - 1) * cos_w0 + beta
        a1 = 2 * ((a - 1) - (a + 1) * cos_w0)
        a2 = (a + 1) - (a - 1) * cos_w0 - beta
    else:
        raise ValueError("Shelf mode must be 'low' or 'high'")

    b = np.array([b0, b1, b2]) / a0
    a = np.array([1.0, a1 / a0, a2 / a0])
    return b, a


def _biquad_allpass(f0: float, q: float, sample_rate: float) -> tuple[np.ndarray, np.ndarray]:
    w0 = 2.0 * np.pi * f0 / sample_rate
    alpha = np.sin(w0) / (2.0 * q)
    b0 = 1 - alpha
    b1 = -2 * np.cos(w0)
    b2 = 1 + alpha
    a0 = 1 + alpha
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha
    b = np.array([b0, b1, b2]) / a0
    a = np.array([1.0, a1 / a0, a2 / a0])
    return b, a


def _clamp(value: float, min_value: Any | None, max_value: Any | None) -> float:
    if min_value is not None:
        value = max(value, float(min_value))
    if max_value is not None:
        value = min(value, float(max_value))
    return value
