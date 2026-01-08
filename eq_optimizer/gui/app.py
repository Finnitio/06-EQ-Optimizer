from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
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

from eq_optimizer.manufacturer_store import ManufacturerRepository
from eq_optimizer.project_store import ProjectRecord, ProjectRepository
from .filter_tab import FilterTab


class MainWindow(QMainWindow):
    def __init__(self, project_repo: ProjectRepository, manufacturer_repo: ManufacturerRepository) -> None:
        super().__init__()
        self.setWindowTitle("EQ Optimizer")
        self.resize(1200, 750)

        self._repository = project_repo
        self._tabs = QTabWidget()
        self._project_tab = ProjectTab(project_repo)
        self._tabs.addTab(self._project_tab, "Project")
        self._filter_tab = FilterTab(manufacturer_repo)
        self._tabs.addTab(self._filter_tab, "Filters")
        self.setCentralWidget(self._tabs)


class ProjectTab(QWidget):
    def __init__(self, repository: ProjectRepository) -> None:
        super().__init__()
        self.repository = repository
        self._records: dict[str, ProjectRecord] = {}

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)

        self.list_widget = QListWidget()
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

        if self._records:
            index = 0
            if current_id:
                for row in range(self.list_widget.count()):
                    if self.list_widget.item(row).data(Qt.UserRole) == current_id:
                        index = row
                        break
            self.list_widget.setCurrentRow(index)
        else:
            self.detail_label.setText(
                "No projects found. Create one with the New button to start editing it inside the GUI."
            )

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
        try:
            record = self.repository.import_project(Path(file_path))
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
            path = self.repository.export_project(record.id, Path(destination))
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"Project saved to {path}.")

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
            self.detail_text.clear()
            return
        self.detail_label.setText(
            "\n".join(
                [
                    f"Name: {record.name}",
                    f"Stored at: {record.file_path}",
                    f"Updated: {record.updated_at}",
                    "",
                    "Detailed editing will be added in the following steps.",
                ]
            )
        )

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
    manufacturer_repo = ManufacturerRepository()
    window = MainWindow(project_repo, manufacturer_repo)
    window.show()

    if owns_app:
        app.exec()
