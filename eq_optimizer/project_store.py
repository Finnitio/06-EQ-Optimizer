from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid


@dataclass(slots=True)
class ProjectRecord:
    """Metadata describing a stored project entry."""

    id: str
    name: str
    file_path: Path
    created_at: str
    updated_at: str


_DEFAULT_TEMPLATE = {
    "name": "New Project",
    "sample_rate": 192000,
    "filterset": "generic",
    "ways": [
        {
            "name": "TT",
            "file": "input/TT.frd",
            "color": "#2ca02c",
            "filters": [],
        },
        {
            "name": "MT",
            "file": "input/MT.frd",
            "color": "#1f77b4",
            "filters": [],
        },
        {
            "name": "HT",
            "file": "input/HT.frd",
            "color": "#ffbf00",
            "filters": [],
        },
    ],
}


def default_project_payload(name: str | None = None) -> dict[str, Any]:
    payload = json.loads(json.dumps(_DEFAULT_TEMPLATE))
    payload["name"] = (name or _DEFAULT_TEMPLATE["name"]).strip() or _DEFAULT_TEMPLATE["name"]
    return payload


class ProjectRepository:
    """Simple JSON-backed project catalog."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self.storage_dir = (storage_dir or Path("project_store")).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.storage_dir / "index.json"
        self.prefs_path = self.storage_dir / "prefs.json"
        if not self.index_path.exists():
            self._write_index({"projects": []})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_projects(self) -> list[ProjectRecord]:
        return [self._entry_to_record(entry) for entry in self._read_index().get("projects", [])]

    def get_record(self, record_id: str) -> ProjectRecord:
        for record in self.list_projects():
            if record.id == record_id:
                return record
        raise KeyError(f"Project '{record_id}' not found")

    def create_project(self, name: str | None = None, template: dict[str, Any] | None = None) -> ProjectRecord:
        payload = json.loads(json.dumps(template or default_project_payload(name)))
        payload["name"] = (name or payload.get("name", "New Project")).strip() or "New Project"
        return self._store_payload(payload)

    def import_project(self, source_file: Path, override_name: str | None = None) -> ProjectRecord:
        source_file = source_file.expanduser().resolve()
        if not source_file.exists():
            raise FileNotFoundError(f"Import source '{source_file}' does not exist")
        payload = json.loads(source_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "ways" not in payload:
            raise ValueError("Invalid project file: expected JSON object with 'ways' field")
        if override_name:
            payload["name"] = override_name
        elif not payload.get("name"):
            payload["name"] = source_file.stem
        return self._store_payload(payload)

    def store_payload(self, payload: dict[str, Any]) -> ProjectRecord:
        """Persist *payload* inside the project catalog and return its record."""

        return self._store_payload(json.loads(json.dumps(payload)))

    def export_project(self, record_id: str, destination: Path) -> Path:
        record = self.get_record(record_id)
        destination = destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(record.file_path.read_text(encoding="utf-8"), encoding="utf-8")
        return destination

    def load_payload(self, record_id: str) -> dict[str, Any]:
        record = self.get_record(record_id)
        if not record.file_path.exists():
            raise FileNotFoundError(f"Stored project '{record_id}' payload is missing at {record.file_path}")
        data = json.loads(record.file_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Stored project payload must be a JSON object")
        return data

    def update_project_payload(self, record_id: str, payload: dict[str, Any]) -> ProjectRecord:
        record = self.get_record(record_id)
        record.file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        updated_name = payload.get("name", record.name)
        self._update_index_entry(record_id, name=updated_name)
        return self.get_record(record_id)

    def delete_project(self, record_id: str) -> None:
        entries = self._read_index().get("projects", [])
        remaining = [entry for entry in entries if entry["id"] != record_id]
        if len(remaining) == len(entries):
            raise KeyError(f"Project '{record_id}' not found")
        record = next(entry for entry in entries if entry["id"] == record_id)
        payload_path = self.storage_dir / record["file"]
        if payload_path.exists():
            payload_path.unlink()
        self._write_index({"projects": remaining})

    def refresh_names(self) -> None:
        entries = self._read_index().get("projects", [])
        dirty = False
        for entry in entries:
            payload_path = self.storage_dir / entry["file"]
            if payload_path.exists():
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                name = payload.get("name")
                if name and name != entry.get("name"):
                    entry["name"] = name
                    entry["updated_at"] = _timestamp()
                    dirty = True
        if dirty:
            self._write_index({"projects": entries})

    def get_last_selected_project_id(self) -> str | None:
        prefs = self._read_prefs()
        value = prefs.get("last_selected_project_id")
        return str(value) if value else None

    def set_last_selected_project_id(self, record_id: str | None) -> None:
        prefs = self._read_prefs()
        if record_id:
            prefs["last_selected_project_id"] = record_id
        else:
            prefs.pop("last_selected_project_id", None)
        self._write_prefs(prefs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _store_payload(self, payload: dict[str, Any]) -> ProjectRecord:
        record_id = uuid.uuid4().hex
        filename = f"{record_id}.json"
        payload_path = self.storage_dir / filename
        payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        record = {
            "id": record_id,
            "name": payload.get("name", "Project"),
            "file": filename,
            "created_at": _timestamp(),
            "updated_at": _timestamp(),
        }
        entries = self._read_index().get("projects", [])
        entries.append(record)
        self._write_index({"projects": entries})
        return self._entry_to_record(record)

    def _entry_to_record(self, entry: dict[str, Any]) -> ProjectRecord:
        return ProjectRecord(
            id=entry["id"],
            name=entry.get("name", "Project"),
            file_path=(self.storage_dir / entry["file"]).resolve(),
            created_at=entry.get("created_at", ""),
            updated_at=entry.get("updated_at", ""),
        )

    def _read_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"projects": []}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _write_index(self, data: dict[str, Any]) -> None:
        self.index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _update_index_entry(self, record_id: str, **updates: Any) -> None:
        entries = self._read_index().get("projects", [])
        modified = False
        for entry in entries:
            if entry.get("id") == record_id:
                entry.update(updates)
                entry["updated_at"] = _timestamp()
                modified = True
                break
        if modified:
            self._write_index({"projects": entries})

    def _read_prefs(self) -> dict[str, Any]:
        if not self.prefs_path.exists():
            return {}
        try:
            return json.loads(self.prefs_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_prefs(self, data: dict[str, Any]) -> None:
        self.prefs_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
