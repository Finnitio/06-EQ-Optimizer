from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping


_DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "generic": {
        "description": "Default RBJ cookbook biquad formulas",
        "filters": {
            "peq": {"formula": "rbj"},
            "shelf": {"formula": "rbj"},
            "allpass": {"formula": "rbj"},
            "butterworth": {},
            "linkwitz-riley": {},
        },
    }
}


@dataclass(slots=True)
class ManufacturerProfile:
    name: str
    description: str
    filters: Mapping[str, Dict[str, Any]]

    def settings_for(self, filter_kind: str) -> Dict[str, Any]:
        return dict(self.filters.get(filter_kind, {}))


def load_manufacturer_profiles(path: Path | None) -> Dict[str, ManufacturerProfile]:
    raw_profiles: Dict[str, Dict[str, Any]] = dict(_DEFAULT_PROFILES)
    if path is not None and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        profiles = _normalize_profiles(data)
        if profiles:
            raw_profiles = profiles

    resolved: Dict[str, ManufacturerProfile] = {}
    for name, profile in raw_profiles.items():
        normalized_name = str(name).strip().lower()
        if not normalized_name:
            continue
        resolved[normalized_name] = ManufacturerProfile(
            name=normalized_name,
            description=profile.get("description", ""),
            filters=profile.get("filters", {}),
        )
    return resolved


def _normalize_profiles(data: Any) -> Dict[str, Dict[str, Any]] | None:
    if isinstance(data, dict):
        if "manufacturers" in data and isinstance(data["manufacturers"], list):
            return _from_list(data["manufacturers"])
        return {k.lower(): v for k, v in data.items()}
    if isinstance(data, list):
        return _from_list(data)
    return None


def _from_list(entries: list[Any]) -> Dict[str, Dict[str, Any]] | None:
    profiles: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        profiles[name.lower()] = {
            "description": entry.get("description", ""),
            "filters": entry.get("filters", {}),
        }
    return profiles or None