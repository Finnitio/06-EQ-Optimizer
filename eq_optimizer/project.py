from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import numpy as np

_NAMED_COLORS = {
    "green": "#2ca02c",
    "grün": "#2ca02c",
    "gruen": "#2ca02c",
    "blue": "#1f77b4",
    "blau": "#1f77b4",
    "red": "#d62728",
    "rot": "#d62728",
    "yellow": "#ffbf00",
    "gelb": "#ffbf00",
    "orange": "#ff7f0e",
    "purple": "#9467bd",
    "violet": "#9467bd",
    "violett": "#9467bd",
    "magenta": "#e377c2",
    "pink": "#e377c2",
    "teal": "#17becf",
    "cyan": "#17becf",
    "türkis": "#17becf",
    "turkis": "#17becf",
    "white": "#ffffff",
    "weiß": "#ffffff",
    "weiss": "#ffffff",
    "black": "#000000",
    "schwarz": "#000000",
    "grey": "#7f7f7f",
    "gray": "#7f7f7f",
    "grau": "#7f7f7f",
}

from .filters import FilterBlock, apply_filter_chain
from .measurements import Response, build_common_grid, load_frd, resample_response


@dataclass
class Way:
    name: str
    file_path: Path
    color: str = "#1f77b4"
    filters: List[FilterBlock] = field(default_factory=list)


@dataclass
class Project:
    base_dir: Path = Path(".")
    sample_rate: float = 192000.0
    ways: List[Way] = field(default_factory=list)

    def add_way(
        self,
        name: str,
        file_path: Path | str,
        color: str | None = None,
        filters: List[FilterBlock] | None = None,
    ) -> None:
        path = Path(file_path)
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()
        self.ways.append(
            Way(
                name=name,
                file_path=path,
                color=normalize_color(color, len(self.ways)),
                filters=list(filters or []),
            )
        )

    def load_responses(self) -> list[Response]:
        if not self.ways:
            raise ValueError("No ways configured. Add at least one Way before loading responses.")
        return [load_frd(way.file_path) for way in self.ways]

    def resampled_responses(self, points: int = 2000) -> tuple[list[Response], np.ndarray]:
        responses = self.load_responses()
        freq_grid = build_common_grid(responses, points=points)
        resampled: list[Response] = []
        for way, resp in zip(self.ways, responses):
            resampled_resp = resample_response(resp, freq_grid)
            filtered = apply_filter_chain(resampled_resp, way.filters, self.sample_rate)
            resampled.append(filtered)
        return resampled, freq_grid


def default_color(index: int) -> str:
    palette = [
        "#2ca02c",  # green
        "#1f77b4",  # blue
        "#ffbf00",  # yellow
        "#ff7f0e",  # orange
        "#9467bd",  # purple
        "#17becf",  # teal
    ]
    return palette[index % len(palette)]


def normalize_color(raw_value: str | None, index: int) -> str:
    if not raw_value:
        return default_color(index)

    value = raw_value.strip()
    lower = value.lower()
    if lower in _NAMED_COLORS:
        return _NAMED_COLORS[lower]

    if lower.startswith("#"):
        hex_part = lower[1:]
        if len(hex_part) in {3, 6} and all(c in "0123456789abcdef" for c in hex_part):
            return lower
    elif len(lower) in {3, 6} and all(c in "0123456789abcdef" for c in lower):
        return f"#{lower}"

    raise ValueError(
        f"Unknown color value '{value}'. Provide a hex code (e.g. #1f77b4) or a supported name such as 'blau', 'grün', 'red', 'blue'."
    )
