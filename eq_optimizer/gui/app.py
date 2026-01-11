from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from eq_optimizer.filterset_store import FiltersetRecord, FiltersetRepository
from eq_optimizer.project_store import ProjectRecord, ProjectRepository
from .filter_tab import FilterTab


class MainWindow(QMainWindow):
    def __init__(self, project_repo: ProjectRepository, filterset_repo: FiltersetRepository) -> None:
        super().__init__()
        self.setWindowTitle("EQ Optimizer")
        self.resize(1200, 750)

        self._repository = project_repo
        self._tabs = QTabWidget()
        self._project_tab = ProjectTab(project_repo, filterset_repo)
        self._tabs.addTab(self._project_tab, "Project")
        self._filter_tab = FilterTab(project_repo, filterset_repo)
        self._project_tab.projectSelected.connect(self._filter_tab.set_active_project)
        self._project_tab.publish_selection()
        self._tabs.addTab(self._filter_tab, "Filtersets")
        self.setCentralWidget(self._tabs)


class ProjectTab(QWidget):
    projectSelected = Signal(object, object)

    def __init__(self, repository: ProjectRepository, filterset_repo: FiltersetRepository) -> None:
        super().__init__()
        self.repository = repository
        self.filterset_repo = filterset_repo
        self._records: dict[str, ProjectRecord] = {}

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget::item:selected { background-color: #0060df; color: white; }"
        )
        self.list_widget.itemSelectionChanged.connect(self._update_details)
        list_layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        self.new_button = QPushButton("New")
        self.import_button = QPushButton("Import")
        self.export_button = QPushButton("Export")
        self.delete_button = QPushButton("Delete")
        self.refresh_button = QPushButton("Refresh")
        for widget in (
            self.new_button,
            self.import_button,
            self.export_button,
            self.delete_button,
            self.refresh_button,
        ):
            button_row.addWidget(widget)
        button_row.addStretch()
        list_layout.addLayout(button_row)

        splitter.addWidget(list_container)

        detail_container = QWidget()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_label = QLabel("Select a project to view details.")
        self.detail_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_label)
        splitter.addWidget(detail_container)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

        self.new_button.clicked.connect(self._create_project)
        self.import_button.clicked.connect(self._import_project)
        self.export_button.clicked.connect(self._export_project)
        self.delete_button.clicked.connect(self._delete_project)
        self.refresh_button.clicked.connect(self.refresh_projects)

        self.refresh_projects()

    def publish_selection(self) -> None:
        """Re-emit the current selection so late listeners stay in sync."""

        self._update_details()

    # ------------------------------------------------------------------
    def refresh_projects(self) -> None:
        try:
            self.repository.refresh_names()
        except Exception as exc:  # pragma: no cover - defensive
            QMessageBox.warning(self, "Refresh failed", str(exc))
        records = sorted(self.repository.list_projects(), key=lambda r: r.updated_at, reverse=True)
        current_id: Optional[str] = None
        if current_item := self.list_widget.currentItem():
            current_id = current_item.data(Qt.UserRole)

        self.list_widget.clear()
        self._records = {record.id: record for record in records}
        for record in records:
            item = QListWidgetItem(record.name)
            item.setData(Qt.UserRole, record.id)
            item.setToolTip(str(record.file_path))
            self.list_widget.addItem(item)

        preferred_id = current_id or self.repository.get_last_selected_project_id()
        target_row = self._row_for_record_id(preferred_id)
        if target_row is None and self.list_widget.count():
            target_row = 0

        if target_row is not None:
            self.list_widget.setCurrentRow(target_row)
        else:
            self.list_widget.clearSelection()
        if not self._records:
            self.detail_label.setText(
                "No projects found. Create one with the New button to start editing it inside the GUI."
            )
        self._update_details()

    # ------------------------------------------------------------------
    def _create_project(self) -> None:
        dialog = ProjectNameDialog(self, title="Create Project")
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            record = self.repository.create_project(dialog.project_name())
        except Exception as exc:
            QMessageBox.critical(self, "Create failed", str(exc))
            return
        self.refresh_projects()
        self._select_record(record.id)

    def _import_project(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import project",
            str(Path.cwd()),
            "EQ Optimizer Project (*.json *.eqproj);;JSON files (*.json);;All files (*)",
        )
        if not file_path:
            return
        source_path = Path(file_path)
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", f"Unable to read project file: {exc}")
            return
        if not isinstance(payload, dict) or "ways" not in payload:
            QMessageBox.critical(self, "Import failed", "Project file must be a JSON object containing 'ways'.")
            return

        filterset_snapshot = payload.pop("filterset", None)
        try:
            if filterset_snapshot:
                self._handle_imported_filterset(filterset_snapshot)
            record = self.repository.store_payload(payload)
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        QMessageBox.information(self, "Imported", f"Added project '{record.name}'.")
        self.refresh_projects()
        self._select_record(record.id)

    def _export_project(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Select project", "Choose a project to export.")
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Export project",
            str(Path.cwd() / f"{record.name}.eqproj"),
            "EQ Optimizer Project (*.eqproj);;JSON files (*.json);;All files (*)",
        )
        if not destination:
            return
        try:
            payload = self.repository.load_payload(record.id)
            snapshot = self._snapshot_filterset(payload)
            if snapshot:
                payload["filterset"] = snapshot
            destination_path = Path(destination)
            destination_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"Project saved to {destination}.")

    def _delete_project(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Select project", "Choose a project to delete.")
            return
        confirm = QMessageBox.question(
            self,
            "Delete project",
            f"Delete '{record.name}'? This removes it from the local catalog.",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.repository.delete_project(record.id)
        except Exception as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self.refresh_projects()

    def _update_details(self) -> None:
        record = self._selected_record()
        if not record:
            self.detail_label.setText("Select a project to view details.")
            self.projectSelected.emit(None, None)
            return
        try:
            payload = self.repository.load_payload(record.id)
        except Exception as exc:
            self.detail_label.setText(f"Unable to load project: {exc}")
            self.projectSelected.emit(None, None)
            return
        self.repository.set_last_selected_project_id(record.id)
        filterset = payload.get("filterset", "generic")
        self.detail_label.setText(
            "\n".join(
                [
                    f"Name: {record.name}",
                    f"Stored at: {record.file_path}",
                    f"Updated: {record.updated_at}",
                    f"Filterset: {filterset}",
                    "",
                    "Detailed editing will be added in the following steps.",
                ]
            )
        )
        self.projectSelected.emit(record, payload)

    def _selected_record(self) -> Optional[ProjectRecord]:
        item = self.list_widget.currentItem()
        if not item:
            return None
        record_id = item.data(Qt.UserRole)
        return self._records.get(record_id)

    def _select_record(self, record_id: str) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.UserRole) == record_id:
                self.list_widget.setCurrentRow(row)
                break

    def _row_for_record_id(self, record_id: Optional[str]) -> Optional[int]:
        if not record_id:
            return None
        for row in range(self.list_widget.count()):
            if self.list_widget.item(row).data(Qt.UserRole) == record_id:
                return row
        return None

    def _handle_imported_filterset(self, snapshot: dict[str, Any]) -> None:
        name = str(snapshot.get("name", "")).strip()
        if not name:
            return
        incoming = FiltersetRecord(
            name=name,
            description=snapshot.get("description", ""),
            filters=dict(snapshot.get("filters", {})),
            blocks=list(snapshot.get("blocks", [])),
        )
        try:
            existing = self.filterset_repo.get_entry(name)
        except KeyError:
            self.filterset_repo.save_entry(incoming)
            return

        differences = self._format_filter_differences(existing.filters, incoming.filters)
        message = QMessageBox(self)
        message.setWindowTitle("Filterset conflict")
        message.setIcon(QMessageBox.Question)
        message.setText(
            f"Filterset '{name}' already exists. Keep the existing definition or replace it with the imported one?"
        )
        if differences:
            message.setInformativeText("Differences found in: " + ", ".join(sorted(differences)))
            details = []
            for key in sorted(differences):
                details.append(f"[{key}] Existing: {json.dumps(existing.filters.get(key), indent=2)}")
                details.append(f"[{key}] Imported: {json.dumps(incoming.filters.get(key), indent=2)}")
            message.setDetailedText("\n".join(details))
        replace_button = message.addButton("Replace", QMessageBox.AcceptRole)
        keep_button = message.addButton("Keep existing", QMessageBox.RejectRole)
        message.setDefaultButton(keep_button)
        message.exec()
        if message.clickedButton() is replace_button:
            self.filterset_repo.save_entry(incoming)

    @staticmethod
    def _format_filter_differences(existing: dict[str, Any], incoming: dict[str, Any]) -> set[str]:
        differing: set[str] = set()
        for key in set(existing).union(incoming):
            if existing.get(key) != incoming.get(key):
                differing.add(key)
        return differing

    def _snapshot_filterset(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        filterset_name = str(payload.get("filterset", "")).strip()
        if not filterset_name:
            return None
        try:
            record = self.filterset_repo.get_entry(filterset_name)
        except KeyError:
            return None
        return {
            "name": record.name,
            "description": record.description,
            "filters": record.filters,
            "blocks": record.blocks,
        }


class ProjectNameDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, title: str = "Project name") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("My Project")
        form.addRow("Name", self._name_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def project_name(self) -> Optional[str]:
        return self._name_edit.text().strip() or None


def launch_gui(storage_dir: Path | None = None) -> None:
    app = QApplication.instance()
    owns_app = False
    if app is None:
        app = QApplication(sys.argv)
        owns_app = True

    project_repo = ProjectRepository(storage_dir)
    filterset_repo = FiltersetRepository()
    window = MainWindow(project_repo, filterset_repo)
    window.show()

    if owns_app:
        app.exec()
