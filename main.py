from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from eq_optimizer import (
    FilterBlock,
    ManufacturerProfile,
    Project,
    Response,
    load_frd,
    load_manufacturer_profiles,
    plot_sum_vs_reference,
    plot_ways,
    resample_response,
)
from eq_optimizer.manufacturer_calibration import (
    calibrate_manufacturer_profile,
    persist_manufacturer_profile,
)
from eq_optimizer.measurements import compute_complex


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
    parser.add_argument(
        "--add-manufacturer",
        "-addmanufacturer",
        dest="add_manufacturer",
        type=str,
        default=None,
        help="Calibrate a manufacturer profile from peq/allpass/shelf sweeps instead of plotting a project.",
    )
    parser.add_argument(
        "--calibration-sample-rate",
        type=float,
        default=192000.0,
        help="Sample rate used when fitting calibration sweeps (only relevant with --add-manufacturer).",
    )
    parser.add_argument(
        "--peq-sweep",
        type=str,
        default="peq.txt",
        help="PEQ sweep filename relative to --input-dir when using --add-manufacturer.",
    )
    parser.add_argument(
        "--allpass-sweep",
        type=str,
        default="allpass.txt",
        help="All-pass sweep filename relative to --input-dir when using --add-manufacturer.",
    )
    parser.add_argument(
        "--shelf-sweep",
        type=str,
        default="lowshelf.txt",
        help="Low-shelf sweep filename relative to --input-dir when using --add-manufacturer.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Generate test.png comparing the summed response with the VituixFR measurement instead of the standard plot.",
    )
    parser.add_argument(
        "--vituix-file",
        type=Path,
        default=Path("VituixFR.txt"),
        help="Path to the Vituix FRD file (relative to --input-dir when not absolute) used with --test.",
    )
    return parser.parse_args(argv)


def run_cli(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.add_manufacturer:
        run_manufacturer_calibration(args)
        return
    if args.test:
        run_test_mode(args)
        return
    project, metadata = build_project(args)
    responses, freq_grid = project.resampled_responses(points=args.points)
    save_path = args.save or derive_default_output_path(project_name=metadata["name"])
    plot_ways(project.ways, responses, freq_grid, save_path, show_plot=not args.no_show)


def run_manufacturer_calibration(args: argparse.Namespace) -> None:
    config_path = determine_config_path(args.config)
    manufacturer_config_path = determine_manufacturer_config_path(args.manufacturer_config, config_path)
    if manufacturer_config_path is None:
        manufacturer_config_path = Path("manufacturers.json")

    profile = calibrate_manufacturer_profile(
        name=args.add_manufacturer,
        sweep_dir=args.input_dir.resolve(),
        peq_file=args.peq_sweep,
        allpass_file=args.allpass_sweep,
        shelf_file=args.shelf_sweep,
        sample_rate=float(args.calibration_sample_rate),
    )
    persist_manufacturer_profile(profile, manufacturer_config_path)
    print(f"Stored manufacturer '{profile['name']}' in {manufacturer_config_path}")


def run_test_mode(args: argparse.Namespace) -> None:
    project, metadata = build_project(args)
    responses, freq_grid = project.resampled_responses(points=args.points)
    sum_response = build_sum_response(responses)

    vituix_path = args.vituix_file
    if not vituix_path.is_absolute():
        vituix_path = (args.input_dir / vituix_path).resolve()
    if not vituix_path.exists():
        raise FileNotFoundError(f"Vituix FR file '{vituix_path}' does not exist")

    vituix_response = load_frd(vituix_path)
    reference = resample_response(vituix_response, sum_response.frequency)

    trimmed_sum, trimmed_reference = trim_frequency_window(sum_response, reference, 20.0, 20_000.0)
    project_output_path = derive_default_output_path(metadata["name"]).with_name("test.png")

    plot_sum_vs_reference(trimmed_sum, trimmed_reference, save_path=project_output_path, show_plot=not args.no_show)


def build_sum_response(responses: list[Response]) -> Response:
    if not responses:
        raise ValueError("At least one response is required to compute the sum")
    freq = responses[0].frequency
    summed = np.zeros(freq.shape, dtype=np.complex128)
    for response in responses:
        if not np.array_equal(response.frequency, freq):
            raise ValueError("Responses must share the same frequency grid")
        summed += compute_complex(response)
    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(summed), 1e-12))
    phase_rad = np.unwrap(np.angle(summed))
    return Response(frequency=freq, magnitude_db=magnitude_db, phase_rad=phase_rad)


def trim_frequency_window(
    sum_response: Response,
    reference_response: Response,
    fmin: float,
    fmax: float,
) -> tuple[Response, Response]:
    freq = sum_response.frequency
    if freq.shape != reference_response.frequency.shape or np.any(freq != reference_response.frequency):
        raise ValueError("Responses must share identical frequency grids before trimming")
    mask = (freq >= fmin) & (freq <= fmax)
    if not np.any(mask):
        raise ValueError("Frequency window does not overlap with response data")

    def slice_response(resp: Response) -> Response:
        return Response(
            frequency=resp.frequency[mask],
            magnitude_db=resp.magnitude_db[mask],
            phase_rad=resp.phase_rad[mask],
        )

    return slice_response(sum_response), slice_response(reference_response)


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
