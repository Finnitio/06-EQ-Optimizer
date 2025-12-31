from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eq_optimizer import (
    FilterBlock,
    ManufacturerProfile,
    Project,
    load_manufacturer_profiles,
    plot_ways,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EQ optimizer prototype entry point")
    parser.add_argument("--input-dir", type=Path, default=Path("input"), help="Base folder for local measurement files (fallback when no config is found)")
    parser.add_argument("--tt-file", type=str, default="TT.frd", help="Bass way measurement file relative to --input-dir (fallback mode only)")
    parser.add_argument("--mt-file", type=str, default="MT.frd", help="Mid way measurement file (fallback mode only)")
    parser.add_argument("--ht-file", type=str, default="HT.frd", help="High way measurement file (fallback mode only)")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to the JSON project config. When omitted, the script auto-loads ./project.json if it exists.",
    )
    parser.add_argument("--save", type=Path, default=None, help="Optional path to save the generated plot (overrides auto naming)")
    parser.add_argument("--no-show", action="store_true", help="Skip showing the Matplotlib GUI (headless mode)")
    parser.add_argument("--points", type=int, default=2000, help="Number of log-spaced frequency samples")
    parser.add_argument(
        "--manufacturer-config",
        type=Path,
        default=None,
        help="Path to manufacturer biquad profiles; defaults to manufacturers.json next to the project config or in the working directory.",
    )
    return parser.parse_args(argv)


def run_cli(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    project, metadata = build_project(args)
    responses, freq_grid = project.resampled_responses(points=args.points)
    save_path = args.save or derive_default_output_path(project_name=metadata["name"])
    plot_ways(project.ways, responses, freq_grid, save_path, show_plot=not args.no_show)


def build_project(args: argparse.Namespace) -> tuple[Project, dict[str, str]]:
    default_base = args.input_dir.resolve()
    config_path = determine_config_path(args.config)
    manufacturer_config_path = determine_manufacturer_config_path(args.manufacturer_config, config_path)
    manufacturer_profiles = load_manufacturer_profiles(manufacturer_config_path)

    if config_path is not None:
        base_dir, ways, meta = load_project_config(config_path, fallback_base=default_base)
        manufacturer = select_manufacturer_profile(manufacturer_profiles, meta.get("manufacturer"))
        project = Project(base_dir=base_dir, sample_rate=meta["sample_rate"], manufacturer=manufacturer)
        for way in ways:
            project.add_way(way["name"], way["file"], color=way.get("color"), filters=way.get("filters"))
        return project, {"name": meta["name"], "manufacturer": manufacturer.name}

    manufacturer = select_manufacturer_profile(manufacturer_profiles, None)
    project = Project(base_dir=default_base, manufacturer=manufacturer)
    project.add_way("TT", args.tt_file, color="#2ca02c")
    project.add_way("MT", args.mt_file, color="#1f77b4")
    project.add_way("HT", args.ht_file, color="#ffbf00")
    return project, {"name": "default", "manufacturer": manufacturer.name}


def determine_config_path(user_path: Path | None) -> Path | None:
    if user_path is not None:
        if not user_path.exists():
            raise FileNotFoundError(f"Config file '{user_path}' does not exist")
        return user_path

    auto_path = Path("project.json")
    if auto_path.exists():
        return auto_path
    return None


def determine_manufacturer_config_path(user_path: Path | None, project_config: Path | None) -> Path | None:
    if user_path is not None:
        if not user_path.exists():
            raise FileNotFoundError(f"Manufacturer config '{user_path}' does not exist")
        return user_path

    candidates: list[Path] = []
    if project_config is not None:
        candidates.append(project_config.parent / "manufacturers.json")
    candidates.append(Path("manufacturers.json"))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_project_config(config_path: Path, fallback_base: Path) -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config file must be a JSON object containing at least a 'ways' array")

    ways_data = data.get("ways")
    if not ways_data:
        raise ValueError("Config file must define a non-empty 'ways' array")

    project_name = data.get("name") or config_path.stem
    sample_rate = float(data.get("sample_rate", 192000.0))
    manufacturer_name = str(data.get("manufacturer", "generic")).strip().lower() or "generic"
    base_dir_value = data.get("base_dir")
    if base_dir_value is None:
        base_dir = config_path.parent.resolve()
    else:
        base_dir = Path(base_dir_value)
        if not base_dir.is_absolute():
            base_dir = (config_path.parent / base_dir).resolve()

    normalized: list[dict[str, Any]] = []
    for entry in ways_data:
        if "name" not in entry or "file" not in entry:
            raise ValueError("Each way entry requires at least 'name' and 'file' fields")
        file_path = Path(entry["file"])
        if not file_path.is_absolute():
            file_path = (base_dir / file_path).resolve()
        filter_defs = [FilterBlock.from_dict(f) for f in entry.get("filters", [])]
        normalized.append(
            {
                "name": entry["name"],
                "file": file_path,
                "color": entry.get("color"),
                "filters": filter_defs,
            }
        )

    metadata = {"name": project_name, "sample_rate": sample_rate, "manufacturer": manufacturer_name}
    return base_dir, normalized, metadata


def select_manufacturer_profile(
    profiles: dict[str, ManufacturerProfile], desired: str | None
) -> ManufacturerProfile:
    if not profiles:
        raise ValueError("No manufacturer profiles available")

    lookup_name = (desired or "generic").strip().lower()
    if lookup_name in profiles:
        return profiles[lookup_name]

    available = ", ".join(sorted(profiles))
    raise ValueError(f"Unknown manufacturer '{desired}'. Available profiles: {available}")


def derive_default_output_path(project_name: str) -> Path:
    safe_name = project_name.strip().replace(" ", "_") or "project"
    output_dir = Path("output") / safe_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "plot.png"


if __name__ == "__main__":
    run_cli()
