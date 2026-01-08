from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

_DEFAULT_MANUFACTURER = {
    "name": "generic",
    "description": "Default RBJ cookbook biquad formulas",
    "filters": {
        "peq": {"formula": "rbj"},
        "shelf": {"formula": "rbj"},
        "allpass": {"formula": "rbj"},
        "butterworth": {},
        "linkwitz-riley": {},
    },
    "blocks": [],
}


@dataclass(slots=True)
class ManufacturerRecord:
    name: str
    description: str
    filters: dict[str, Any] = field(default_factory=dict)
    blocks: list[dict[str, Any]] = field(default_factory=list)


class ManufacturerRepository:
    """Lightweight helper that manages manufacturers.json entries."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.path = (config_path or Path("manufacturers.json")).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_entries([json.loads(json.dumps(_DEFAULT_MANUFACTURER))])

    # ------------------------------------------------------------------
    # High-level CRUD
    # ------------------------------------------------------------------
    def list_manufacturers(self) -> list[ManufacturerRecord]:
        return [self._entry_to_record(entry) for entry in self._read_entries()]

    def get_entry(self, name: str) -> ManufacturerRecord:
        entry = self._find_entry(name)
        if entry is None:
            raise KeyError(f"Manufacturer '{name}' not found")
        return self._entry_to_record(entry)

    def create_manufacturer(self, name: str, description: str = "") -> ManufacturerRecord:
        normalized = self._sanitize(name)
        if not normalized:
            raise ValueError("Manufacturer name must not be empty")
        entries = self._read_entries()
        if self._find_entry(normalized, entries) is not None:
            raise ValueError(f"Manufacturer '{normalized}' already exists")
        entry = {
            "name": normalized,
            "description": description.strip(),
            "filters": {},
            "blocks": [],
        }
        entries.append(entry)
        self._write_entries(entries)
        return self._entry_to_record(entry)

    def delete_manufacturer(self, name: str) -> None:
        key = self._sanitize(name)
        entries = self._read_entries()
        filtered = [entry for entry in entries if self._sanitize(entry.get("name")) != key]
        if len(filtered) == len(entries):
            raise KeyError(f"Manufacturer '{name}' not found")
        if not filtered:
            filtered = [json.loads(json.dumps(_DEFAULT_MANUFACTURER))]
        self._write_entries(filtered)

    def import_file(self, source: Path) -> list[ManufacturerRecord]:
        source = source.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Import file '{source}' does not exist")
        payload = json.loads(source.read_text(encoding="utf-8"))
        new_entries = self._coerce_to_entries(payload)
        if not new_entries:
            raise ValueError("Import file does not describe any manufacturers")
        existing = self._read_entries()
        imported: list[ManufacturerRecord] = []
        for entry in new_entries:
            normalized = self._sanitize(entry.get("name"))
            if not normalized:
                continue
            entry["name"] = normalized
            entry.setdefault("filters", {})
            entry.setdefault("blocks", [])
            current = self._find_entry(normalized, existing)
            if current is None:
                existing.append(entry)
            else:
                blocks = entry.get("blocks") or current.get("blocks") or []
                entry["blocks"] = blocks
                current.update(entry)
            imported.append(self._entry_to_record(entry))
        self._write_entries(existing)
        return imported

    def export_manufacturer(self, name: str, destination: Path) -> Path:
        entry = self._find_entry(name)
        if entry is None:
            raise KeyError(f"Manufacturer '{name}' not found")
        destination = destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {"manufacturers": [entry]}
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination

    def save_entry(self, record: ManufacturerRecord) -> ManufacturerRecord:
        entries = self._read_entries()
        normalized = self._sanitize(record.name)
        entry = {
            "name": normalized,
            "description": record.description,
            "filters": record.filters,
            "blocks": record.blocks,
        }
        if not normalized:
            raise ValueError("Manufacturer name must not be empty")
        for idx, candidate in enumerate(entries):
            if self._sanitize(candidate.get("name")) == normalized:
                entries[idx] = entry
                self._write_entries(entries)
                return record
        entries.append(entry)
        self._write_entries(entries)
        return record

    # ------------------------------------------------------------------
    # Filter block helpers
    # ------------------------------------------------------------------
    def list_blocks(self, manufacturer: str) -> list[dict[str, Any]]:
        entry = self._find_entry(manufacturer)
        if entry is None:
            raise KeyError(f"Manufacturer '{manufacturer}' not found")
        return list(entry.get("blocks", []))

    def add_block(self, manufacturer: str, block: dict[str, Any]) -> dict[str, Any]:
        entries = self._read_entries()
        entry = self._require_entry(entries, manufacturer)
        new_block = self._normalize_block(block)
        entry.setdefault("blocks", []).append(new_block)
        self._write_entries(entries)
        return new_block

    def update_block(self, manufacturer: str, block_id: str, params: dict[str, Any]) -> dict[str, Any]:
        entries = self._read_entries()
        entry = self._require_entry(entries, manufacturer)
        blocks = entry.setdefault("blocks", [])
        for block in blocks:
            if block.get("id") == block_id:
                block.setdefault("params", {}).update(params)
                self._write_entries(entries)
                return block
        raise KeyError(f"Filter '{block_id}' not found for manufacturer '{manufacturer}'")

    def replace_block(self, manufacturer: str, block: dict[str, Any]) -> dict[str, Any]:
        entries = self._read_entries()
        entry = self._require_entry(entries, manufacturer)
        blocks = entry.setdefault("blocks", [])
        updated = self._normalize_block(block)
        for idx, existing in enumerate(blocks):
            if existing.get("id") == updated["id"]:
                blocks[idx] = updated
                break
        else:
            blocks.append(updated)
        self._write_entries(entries)
        return updated

    def delete_block(self, manufacturer: str, block_id: str) -> None:
        entries = self._read_entries()
        entry = self._require_entry(entries, manufacturer)
        blocks = entry.setdefault("blocks", [])
        filtered = [block for block in blocks if block.get("id") != block_id]
        if len(filtered) == len(blocks):
            raise KeyError(f"Filter '{block_id}' not found for manufacturer '{manufacturer}'")
        entry["blocks"] = filtered
        self._write_entries(entries)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _read_entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return [json.loads(json.dumps(_DEFAULT_MANUFACTURER))]
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return self._coerce_to_entries(data)

    def _write_entries(self, entries: Iterable[dict[str, Any]]) -> None:
        safe_entries = [self._normalize_entry(entry) for entry in entries]
        payload = {"manufacturers": safe_entries}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _coerce_to_entries(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            if isinstance(data.get("manufacturers"), list):
                entries = data["manufacturers"]
            else:
                entries = []
                for name, value in data.items():
                    if not isinstance(value, dict):
                        continue
                    entry = dict(value)
                    entry.setdefault("name", name)
                    entries.append(entry)
        elif isinstance(data, list):
            entries = list(data)
        else:
            raise ValueError("Unsupported manufacturer config format")
        normalized = [self._normalize_entry(entry) for entry in entries if entry.get("name")]
        return normalized or [json.loads(json.dumps(_DEFAULT_MANUFACTURER))]

    def _normalize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "name": self._sanitize(entry.get("name")),
            "description": entry.get("description", ""),
            "filters": entry.get("filters", {}) or {},
            "blocks": entry.get("blocks", []) or [],
        }
        valid_blocks = []
        for block in normalized["blocks"]:
            try:
                valid_blocks.append(self._normalize_block(block))
            except Exception:
                continue
        normalized["blocks"] = valid_blocks
        return normalized

    def _normalize_block(self, block: dict[str, Any]) -> dict[str, Any]:
        block_type = str(block.get("type", "")).strip().lower()
        if not block_type:
            raise ValueError("Filter block requires a 'type' field")
        normalized = {
            "id": block.get("id") or uuid.uuid4().hex,
            "type": block_type,
            "params": dict(block.get("params", {})),
        }
        return normalized

    def _find_entry(self, name: str, entries: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        entries = entries or self._read_entries()
        key = self._sanitize(name)
        for entry in entries:
            if self._sanitize(entry.get("name")) == key:
                return entry
        return None

    def _require_entry(self, entries: list[dict[str, Any]], name: str) -> dict[str, Any]:
        entry = self._find_entry(name, entries)
        if entry is None:
            raise KeyError(f"Manufacturer '{name}' not found")
        return entry

    def _entry_to_record(self, entry: dict[str, Any]) -> ManufacturerRecord:
        return ManufacturerRecord(
            name=entry.get("name", ""),
            description=entry.get("description", ""),
            filters=dict(entry.get("filters", {})),
            blocks=list(entry.get("blocks", [])),
        )

    @staticmethod
    def _sanitize(name: Any) -> str:
        return str(name or "").strip()
