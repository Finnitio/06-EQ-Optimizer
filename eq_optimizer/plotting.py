from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FixedLocator, FuncFormatter, MultipleLocator

from .measurements import Response, compute_complex, compute_minimum_phase_angle
from .project import Way


def plot_ways(
    ways: Sequence[Way],
    responses: Sequence[Response],
    freq_grid: np.ndarray,
    save_path: Path | None,
    show_plot: bool = True,
) -> None:
    fig, (ax_mag, ax_phase_sum, ax_phase_ways) = plt.subplots(
        3, 1, figsize=(12, 10), sharex=True, height_ratios=[3, 1, 1]
    )
    summed = np.zeros_like(freq_grid, dtype=np.complex128)
    way_magnitudes: list[np.ndarray] = []
    way_complex: list[np.ndarray] = []
    display_min = 20.0
    display_max = 20_000.0
    display_ticks = np.array([20.0, 100.0, 1_000.0, 10_000.0, 20_000.0])

    for way, resp in zip(ways, responses):
        complex_resp = compute_complex(resp)
        summed += complex_resp
        ax_mag.semilogx(
            resp.frequency,
            resp.magnitude_db,
            label=way.name,
            color=way.color,
            linewidth=1.2,
        )
        way_magnitudes.append(resp.magnitude_db)
        way_complex.append(complex_resp)

    summed_db = 20.0 * np.log10(np.maximum(np.abs(summed), 1e-9))
    ax_mag.semilogx(freq_grid, summed_db, label="Sum", color="black", linewidth=2.0)
    ax_mag.set_ylabel("Magnitude [dB]")
    ax_mag.set_title("Three-Way Magnitude Response")
    ax_mag.grid(which="major", linestyle=":", linewidth=0.8, color="#666666")
    ax_mag.grid(which="minor", linestyle=":", linewidth=0.35, alpha=0.7, color="#999999")
    ax_mag.yaxis.set_major_locator(MultipleLocator(5))
    ax_mag.yaxis.set_minor_locator(MultipleLocator(1))
    ax_mag.legend()

    all_curves = list(way_magnitudes) + [summed_db]
    max_mag = max(np.max(curve) for curve in all_curves)
    top_limit = max_mag + 5.0
    visible_span = 50.0
    bottom_limit = top_limit - visible_span
    way_peaks = [np.max(curve) for curve in way_magnitudes]
    while any(peak < bottom_limit for peak in way_peaks):
        bottom_limit -= 10.0
    bottom_limit = 10.0 * np.floor(bottom_limit / 10.0)
    span_db = top_limit - bottom_limit
    ax_mag.set_ylim(bottom_limit, top_limit)

    decades = np.log10(display_max / display_min)
    top_axis_height_in = 6.0
    total_height = top_axis_height_in * 5.0 / 3.0  # height ratios [3,1,1]
    fig_width = max(12.0, decades * top_axis_height_in * 25.0 / span_db)
    fig.set_size_inches(fig_width, total_height, forward=True)

    phase_min = compute_minimum_phase_angle(freq_grid, summed_db, remove_delay=True)
    phase_deg = np.degrees(phase_min)
    phase_wrapped = ((phase_deg + 180.0) % 360.0) - 180.0
    ax_phase_sum.semilogx(
        freq_grid,
        phase_wrapped,
        color="black",
        linestyle="--",
        linewidth=1.5,
        label="Sum minimum phase",
    )
    ax_phase_sum.set_ylim(-180, 180)
    ax_phase_sum.set_yticks(np.arange(-180, 181, 60))
    ax_phase_sum.set_ylabel("Phase [deg]")
    ax_phase_sum.set_title("Minimum-Phase Sum")
    ax_phase_sum.grid(which="major", linestyle=":", linewidth=0.7, color="#666666")
    ax_phase_sum.yaxis.set_major_locator(MultipleLocator(60))
    ax_phase_sum.legend(loc="upper right")

    summed_mag = np.maximum(np.abs(summed), 1e-9)
    threshold = 0.10 * summed_mag
    for way, complex_resp, resp in zip(ways, way_complex, responses):
        way_mag = np.abs(complex_resp)
        mask = way_mag >= threshold
        phase_deg_full = ((np.degrees(resp.phase_rad) + 180.0) % 360.0) - 180.0
        strong_phase = np.where(mask, phase_deg_full, np.nan)
        weak_phase = np.where(~mask, phase_deg_full, np.nan)
        ax_phase_ways.semilogx(
            resp.frequency,
            strong_phase,
            color=way.color,
            linewidth=1.2,
            label=f"{way.name} phase",
        )
        ax_phase_ways.semilogx(
            resp.frequency,
            weak_phase,
            color=way.color,
            linewidth=0.6,
            linestyle="--",
            alpha=0.6,
        )
    ax_phase_ways.set_ylabel("Phase [deg]")
    ax_phase_ways.set_xlabel("Frequency [Hz]")
    ax_phase_ways.set_title("Per-Way Phase (visible when ≥25% of sum)")
    ax_phase_ways.set_ylim(-180, 180)
    ax_phase_ways.set_yticks(np.arange(-180, 181, 60))
    ax_phase_ways.grid(which="major", linestyle=":", linewidth=0.7, color="#666666")
    ax_phase_ways.yaxis.set_major_locator(MultipleLocator(60))
    ax_phase_ways.legend(loc="upper right")

    ax_mag.set_xlim(display_min, display_max)
    ax_phase_sum.set_xlim(display_min, display_max)
    ax_phase_ways.set_xlim(display_min, display_max)
    locator = FixedLocator(display_ticks)
    formatter = FuncFormatter(lambda value, _: f"{int(value):d}")
    ax_phase_sum.xaxis.set_major_locator(locator)
    ax_phase_sum.xaxis.set_major_formatter(formatter)
    ax_phase_ways.xaxis.set_major_locator(locator)
    ax_phase_ways.xaxis.set_major_formatter(formatter)

    fig.tight_layout()

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150)
        print(f"Saved plot to {save_path}")

    if show_plot:
        plt.show()
    else:
        plt.close()


def plot_sum_vs_reference(
    sum_response: Response,
    reference_response: Response,
    save_path: Path,
    show_plot: bool = False,
) -> None:
    fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(10, 7), sharex=True, height_ratios=[3, 1.5])

    freq = sum_response.frequency
    ref_freq = reference_response.frequency
    if freq.shape != ref_freq.shape or np.any(freq != ref_freq):
        raise ValueError("Sum and reference responses must share the same frequency grid")

    ax_mag.semilogx(freq, sum_response.magnitude_db, label="Sum", color="#111111", linewidth=1.8)
    ax_mag.semilogx(freq, reference_response.magnitude_db, label="Vituix FR", color="#d62728", linewidth=1.4)
    ax_mag.set_ylabel("Magnitude [dB]")
    ax_mag.grid(which="both", linestyle=":", linewidth=0.8, alpha=0.8)
    ax_mag.legend(loc="best")

    all_mag = np.concatenate([sum_response.magnitude_db, reference_response.magnitude_db])
    avg_mag = float(np.mean(all_mag))
    y_min = avg_mag - 5.0
    y_max = avg_mag + 5.0
    if y_max <= y_min:
        y_max = y_min + 10.0
    ax_mag.set_ylim(y_min, y_max)
    ax_mag.yaxis.set_major_locator(MultipleLocator(1))
    ax_mag.yaxis.set_minor_locator(MultipleLocator(0.5))

    def _wrap_phase(rad: np.ndarray) -> np.ndarray:
        deg = np.degrees(rad)
        return ((deg + 180.0) % 360.0) - 180.0

    ax_phase.semilogx(freq, _wrap_phase(sum_response.phase_rad), label="Sum phase", color="#111111", linewidth=1.5)
    ax_phase.semilogx(freq, _wrap_phase(reference_response.phase_rad), label="Vituix phase", color="#d62728", linewidth=1.2)
    ax_phase.set_ylabel("Phase [deg]")
    ax_phase.set_xlabel("Frequency [Hz]")
    ax_phase.set_ylim(-180, 180)
    ax_phase.set_yticks(np.arange(-180, 181, 60))
    ax_phase.grid(which="both", linestyle=":", linewidth=0.7, alpha=0.8)
    ax_phase.legend(loc="best")

    xmin = float(freq.min())
    xmax = float(freq.max())
    ax_mag.set_xlim(xmin, xmax)
    ax_phase.set_xlim(xmin, xmax)

    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=150)
    print(f"Saved comparison plot to {save_path}")

    if show_plot:
        plt.show()
    else:
        plt.close()
