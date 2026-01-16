from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QInputDialog,
)

from eq_optimizer.filters import FilterBlock
from eq_optimizer.manufacturers import ManufacturerProfile
from eq_optimizer.plotting import render_way_plots
from eq_optimizer.project import Project, normalize_color
from eq_optimizer.project_store import ProjectRepository
from eq_optimizer.filterset_store import FiltersetRepository


class SystemTab(QWidget):
    def __init__(
        self,
        project_repository: ProjectRepository,
        filterset_repository: FiltersetRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_repo = project_repository
        self._filterset_repo = filterset_repository
        self._current_record = None
        self._current_payload: dict[str, Any] | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        filterset_row = QHBoxLayout()
        filterset_row.addWidget(QLabel("Filterset:"))
        self.filterset_combo = QComboBox()
        self.filterset_combo.currentIndexChanged.connect(self._on_filterset_changed)
        filterset_row.addWidget(self.filterset_combo, 1)
        left_layout.addLayout(filterset_row)

        ways_group = QGroupBox("Ways")
        ways_outer_layout = QVBoxLayout(ways_group)
        ways_splitter = QSplitter(Qt.Horizontal)
        
        ways_list_widget = QWidget()
        ways_list_layout = QVBoxLayout(ways_list_widget)
        ways_list_layout.setContentsMargins(0, 0, 0, 0)
        self.ways_list = QListWidget()
        self.ways_list.itemSelectionChanged.connect(self._sync_blocks_list)
        self.ways_list.itemSelectionChanged.connect(self._update_way_params)
        ways_list_layout.addWidget(self.ways_list)

        ways_buttons = QHBoxLayout()
        add_way_btn = QPushButton("Add")
        remove_way_btn = QPushButton("Remove")
        add_way_btn.clicked.connect(self._add_way)
        remove_way_btn.clicked.connect(self._remove_way)
        ways_buttons.addWidget(add_way_btn)
        ways_buttons.addWidget(remove_way_btn)
        ways_buttons.addStretch()
        ways_list_layout.addLayout(ways_buttons)

        path_row = QHBoxLayout()
        self.way_path_edit = QLineEdit()
        self.way_path_edit.setPlaceholderText("Pfad zur Messdatei")
        self.way_path_edit.editingFinished.connect(self._apply_way_path_edit)
        self.way_path_button = QPushButton("Browse")
        self.way_path_button.clicked.connect(self._browse_way_file)
        path_row.addWidget(self.way_path_edit, stretch=1)
        path_row.addWidget(self.way_path_button)
        ways_list_layout.addLayout(path_row)
        ways_splitter.addWidget(ways_list_widget)
        
        way_params_widget = QWidget()
        way_params_layout = QVBoxLayout(way_params_widget)
        way_params_layout.setContentsMargins(8, 0, 0, 0)
        
        self.way_params_form = QFormLayout()
        way_params_layout.addLayout(self.way_params_form)
        way_params_layout.addStretch()
        ways_splitter.addWidget(way_params_widget)
        
        ways_splitter.setStretchFactor(0, 1)
        ways_splitter.setStretchFactor(1, 1)
        ways_outer_layout.addWidget(ways_splitter)
        left_layout.addWidget(ways_group, 1)

        blocks_group = QGroupBox("Filter Blocks")
        blocks_outer_layout = QVBoxLayout(blocks_group)
        blocks_splitter = QSplitter(Qt.Horizontal)
        
        blocks_list_widget = QWidget()
        blocks_list_layout = QVBoxLayout(blocks_list_widget)
        blocks_list_layout.setContentsMargins(0, 0, 0, 0)
        self.blocks_list = QListWidget()
        self.blocks_list.itemSelectionChanged.connect(self._update_filter_params)
        blocks_list_layout.addWidget(self.blocks_list)
        block_buttons = QHBoxLayout()
        add_block_btn = QPushButton("Add")
        remove_block_btn = QPushButton("Remove")
        add_block_btn.clicked.connect(self._add_filter_block)
        remove_block_btn.clicked.connect(self._remove_filter_block)
        block_buttons.addWidget(add_block_btn)
        block_buttons.addWidget(remove_block_btn)
        block_buttons.addStretch()
        blocks_list_layout.addLayout(block_buttons)
        blocks_splitter.addWidget(blocks_list_widget)
        
        params_widget = QWidget()
        params_layout = QVBoxLayout(params_widget)
        params_layout.setContentsMargins(8, 0, 0, 0)
        
        self.params_enabled_check = QCheckBox("Enabled")
        self.params_enabled_check.setChecked(True)
        self.params_enabled_check.stateChanged.connect(self._on_param_changed)
        params_layout.addWidget(self.params_enabled_check)
        
        self.params_form = QFormLayout()
        params_layout.addLayout(self.params_form)
        params_layout.addStretch()
        blocks_splitter.addWidget(params_widget)
        
        blocks_splitter.setStretchFactor(0, 1)
        blocks_splitter.setStretchFactor(1, 1)
        blocks_outer_layout.addWidget(blocks_splitter)
        left_layout.addWidget(blocks_group, 2)

        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self.figure = Figure(figsize=(7, 5))
        self.ax_mag, self.ax_phase_sum, self.ax_phase_ways = self.figure.subplots(
            3, 1, sharex=True, height_ratios=[3, 1, 1]
        )
        self.canvas = FigureCanvas(self.figure)
        right_layout.addWidget(self.canvas)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        self._update_way_path_field()

    # ------------------------------------------------------------------
    def set_active_project(self, record, payload) -> None:
        self._current_record = record
        self._current_payload = payload if payload is not None else None
        self._populate_filterset_combo()
        self._refresh_lists()
        self._draw_plot()

    def _refresh_lists(self) -> None:
        self.ways_list.clear()
        ways = self._current_payload.get("ways", []) if self._current_payload else []
        for entry in ways:
            item = QListWidgetItem(entry.get("name", "Unbenannt"))
            item.setData(Qt.UserRole, entry)
            self.ways_list.addItem(item)
        if self.ways_list.count():
            self.ways_list.setCurrentRow(0)
        else:
            self.blocks_list.clear()
            self._update_way_path_field()

    def _populate_filterset_combo(self) -> None:
        self.filterset_combo.blockSignals(True)
        self.filterset_combo.clear()
        try:
            records = sorted(self._filterset_repo.list_filtersets(), key=lambda r: r.name.lower())
        except Exception:
            records = []
        for record in records:
            self.filterset_combo.addItem(record.name, record.name)
        current_filterset = self._current_payload.get("filterset", "generic") if self._current_payload else "generic"
        index = self.filterset_combo.findData(current_filterset)
        if index >= 0:
            self.filterset_combo.setCurrentIndex(index)
        self.filterset_combo.blockSignals(False)

    def _on_filterset_changed(self) -> None:
        if not self._current_payload:
            return
        selected = self.filterset_combo.currentData()
        if selected:
            self._current_payload["filterset"] = selected
            self._persist_project()
            self._draw_plot()

    def _sync_blocks_list(self) -> None:
        self.blocks_list.clear()
        entry = self._selected_way_entry()
        if not entry:
            self._update_way_path_field()
            self._update_filter_params()
            return
        filters = entry.get("filters", [])
        type_counts = {}
        for block in filters:
            block_type = block.get("type", "?")
            type_counts[block_type] = type_counts.get(block_type, 0) + 1
            text = self._format_block(block, type_counts[block_type])
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, block)
            self.blocks_list.addItem(item)
        self._update_way_path_field()
        self._update_filter_params()
    
    def _update_way_params(self) -> None:
        # Clear existing parameter widgets
        while self.way_params_form.rowCount() > 0:
            self.way_params_form.removeRow(0)
        
        entry = self._selected_way_entry()
        if not entry:
            return
        
        # Delay parameter
        delay_spin = QDoubleSpinBox()
        delay_spin.setRange(0.0, 100.0)
        delay_spin.setDecimals(3)
        delay_spin.setSingleStep(0.1)
        delay_spin.setSuffix(" ms")
        delay_spin.setValue(entry.get("delay_ms", 0.0))
        delay_spin.setProperty("way_param_key", "delay_ms")
        delay_spin.valueChanged.connect(self._on_way_param_changed)
        self.way_params_form.addRow("Delay", delay_spin)
        
        # Gain parameter
        gain_spin = QDoubleSpinBox()
        gain_spin.setRange(-24.0, 24.0)
        gain_spin.setDecimals(2)
        gain_spin.setSingleStep(0.1)
        gain_spin.setSuffix(" dB")
        gain_spin.setValue(entry.get("gain_db", 0.0))
        gain_spin.setProperty("way_param_key", "gain_db")
        gain_spin.valueChanged.connect(self._on_way_param_changed)
        self.way_params_form.addRow("Gain", gain_spin)
        
        # Invert parameter
        invert_check = QCheckBox()
        invert_check.setChecked(entry.get("invert", False))
        invert_check.setProperty("way_param_key", "invert")
        invert_check.stateChanged.connect(self._on_way_param_changed)
        self.way_params_form.addRow("Invert", invert_check)
    
    def _on_way_param_changed(self) -> None:
        way_idx = self._selected_way_index()
        if way_idx is None or not self._current_payload:
            return
        
        ways = self._current_payload.get("ways", [])
        if not (0 <= way_idx < len(ways)):
            return
        
        way_entry = ways[way_idx]
        
        # Update all way parameter values
        for i in range(self.way_params_form.rowCount()):
            widget = self.way_params_form.itemAt(i, QFormLayout.FieldRole).widget()
            if widget and widget.property("way_param_key"):
                key = widget.property("way_param_key")
                if isinstance(widget, QDoubleSpinBox):
                    way_entry[key] = widget.value()
                elif isinstance(widget, QCheckBox):
                    way_entry[key] = widget.isChecked()
        
        self._persist_project()
        self._draw_plot()
    
    def _update_filter_params(self) -> None:
        # Clear existing parameter widgets
        while self.params_form.rowCount() > 0:
            self.params_form.removeRow(0)
        
        block_item = self.blocks_list.currentItem()
        if not block_item:
            self.params_enabled_check.setEnabled(False)
            return
        
        block = block_item.data(Qt.UserRole)
        if not block:
            self.params_enabled_check.setEnabled(False)
            return
        
        self.params_enabled_check.setEnabled(True)
        params = block.get("params", {})
        enabled = params.get("enabled", True)
        self.params_enabled_check.blockSignals(True)
        self.params_enabled_check.setChecked(enabled)
        self.params_enabled_check.blockSignals(False)
        
        filter_type = block.get("type", "")
        self._build_param_widgets(filter_type, params)
    
    def _build_param_widgets(self, filter_type: str, params: dict[str, Any]) -> None:
        if filter_type == "peq":
            self._add_param_spin("freq", "Frequency [Hz]", params.get("freq", 1000.0), 20.0, 20000.0)
            self._add_param_spin("q", "Q", params.get("q", 0.707), 0.1, 20.0)
            self._add_param_spin("gain_db", "Gain [dB]", params.get("gain_db", 0.0), -24.0, 24.0)
        elif filter_type == "shelf":
            self._add_mode_combo(params.get("mode", "low"))
            self._add_param_spin("freq", "Frequency [Hz]", params.get("freq", 1000.0), 20.0, 20000.0)
            self._add_param_spin("gain_db", "Gain [dB]", params.get("gain_db", 0.0), -24.0, 24.0)
            self._add_param_spin("slope", "Slope", params.get("slope", 0.707), 0.1, 4.0)
        elif filter_type == "allpass":
            self._add_param_spin("freq", "Frequency [Hz]", params.get("freq", 1000.0), 20.0, 20000.0)
            self._add_param_spin("q", "Q", params.get("q", 0.707), 0.1, 20.0)
        elif filter_type in ["linkwitz-riley", "butterworth"]:
            self._add_mode_combo(params.get("mode", "lowpass"))
            self._add_param_spin("freq", "Frequency [Hz]", params.get("freq", 1000.0), 20.0, 20000.0)
            self._add_order_spin(params.get("order", 4))
    
    def _add_param_spin(self, key: str, label: str, value: float, min_val: float, max_val: float) -> None:
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setDecimals(3)
        spin.setSingleStep(0.1 if "gain" in key or key == "q" or key == "slope" else 10.0)
        spin.setValue(float(value))
        spin.setProperty("param_key", key)
        spin.valueChanged.connect(self._on_param_changed)
        self.params_form.addRow(label, spin)
    
    def _add_mode_combo(self, current_mode: str) -> None:
        combo = QComboBox()
        combo.addItems(["lowpass", "highpass", "low", "high"])
        index = combo.findText(current_mode)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.setProperty("param_key", "mode")
        combo.currentTextChanged.connect(self._on_param_changed)
        self.params_form.addRow("Mode", combo)
    
    def _add_order_spin(self, value: int) -> None:
        spin = QSpinBox()
        spin.setRange(1, 12)
        spin.setValue(int(value))
        spin.setProperty("param_key", "order")
        spin.valueChanged.connect(self._on_param_changed)
        self.params_form.addRow("Order", spin)
    
    def _on_param_changed(self) -> None:
        way_idx = self._selected_way_index()
        if way_idx is None or not self._current_payload:
            return
        
        block_item = self.blocks_list.currentItem()
        if not block_item:
            return
        
        block_idx = self.blocks_list.row(block_item)
        filters = self._current_payload.get("ways", [])[way_idx].get("filters", [])
        if not (0 <= block_idx < len(filters)):
            return
        
        block = filters[block_idx]
        params = block.setdefault("params", {})
        
        # Update enabled state
        params["enabled"] = self.params_enabled_check.isChecked()
        
        # Update all parameter values
        for i in range(self.params_form.rowCount()):
            widget = self.params_form.itemAt(i, QFormLayout.FieldRole).widget()
            if widget and widget.property("param_key"):
                key = widget.property("param_key")
                if isinstance(widget, QDoubleSpinBox):
                    params[key] = widget.value()
                elif isinstance(widget, QSpinBox):
                    params[key] = widget.value()
                elif isinstance(widget, QComboBox):
                    params[key] = widget.currentText()
        
        # Update list display - rebuild to get correct numbering
        self._sync_blocks_list()
        self.blocks_list.setCurrentRow(block_idx)
        
        self._persist_project()
        self._draw_plot()

    # ------------------------------------------------------------------
    def _selected_way_index(self) -> Optional[int]:
        item = self.ways_list.currentItem()
        if not item:
            return None
        return self.ways_list.row(item)

    def _selected_way_entry(self) -> Optional[dict[str, Any]]:
        idx = self._selected_way_index()
        if idx is None or not self._current_payload:
            return None
        ways = self._current_payload.get("ways", [])
        if 0 <= idx < len(ways):
            return ways[idx]
        return None

    def _add_way(self) -> None:
        if not self._current_record or self._current_payload is None:
            QMessageBox.information(self, "Kein Projekt", "Bitte zuerst ein Projekt auswählen.")
            return
        name, ok = QInputDialog.getText(self, "Neuer Weg", "Name")
        if not ok or not name.strip():
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "FRD-Datei wählen",
            str(Path.cwd()),
            "Messdateien (*.frd *.txt);;Alle Dateien (*)",
        )
        if not file_path:
            return
        stored_path = self._normalize_path(Path(file_path))
        ways = self._current_payload.setdefault("ways", [])
        color = normalize_color(None, len(ways))
        ways.append(
            {
                "name": name.strip(),
                "file": stored_path,
                "color": color,
                "filters": [],
            }
        )
        self._persist_project()
        self._refresh_lists()
        self._draw_plot()

    def _remove_way(self) -> None:
        idx = self._selected_way_index()
        if idx is None or not self._current_payload:
            return
        ways = self._current_payload.get("ways", [])
        if not (0 <= idx < len(ways)):
            return
        del ways[idx]
        self._persist_project()
        self._refresh_lists()
        self._draw_plot()

    def _add_filter_block(self) -> None:
        if not self._current_payload:
            QMessageBox.information(self, "Kein Projekt", "Bitte zuerst ein Projekt auswählen.")
            return
        idx = self._selected_way_index()
        if idx is None:
            QMessageBox.information(self, "Kein Weg", "Bitte zuerst einen Weg auswählen.")
            return
        dialog = FilterBlockDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        block = dialog.block_data
        ways = self._current_payload.get("ways", [])
        ways[idx].setdefault("filters", []).append(block)
        self._persist_project()
        self._sync_blocks_list()
        self._draw_plot()

    def _remove_filter_block(self) -> None:
        idx = self._selected_way_index()
        if idx is None or not self._current_payload:
            return
        block_item = self.blocks_list.currentItem()
        if not block_item:
            return
        block_idx = self.blocks_list.row(block_item)
        filters = self._current_payload.get("ways", [])[idx].get("filters", [])
        if 0 <= block_idx < len(filters):
            del filters[block_idx]
            self._persist_project()
            self._sync_blocks_list()
            self._draw_plot()

    def _apply_way_path_edit(self) -> None:
        if not self._current_payload:
            return
        entry = self._selected_way_entry()
        if not entry:
            return
        new_path = self.way_path_edit.text().strip()
        if new_path == entry.get("file", ""):
            return
        entry["file"] = new_path
        self._persist_project()
        self._draw_plot()

    def _browse_way_file(self) -> None:
        entry = self._selected_way_entry()
        if not entry:
            QMessageBox.information(self, "Kein Weg", "Bitte zuerst einen Weg auswählen.")
            return
        initial_dir = self._resolve_initial_dir(entry.get("file") or "")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "FRD-Datei wählen",
            initial_dir,
            "Messdateien (*.frd *.txt);;Alle Dateien (*)",
        )
        if not file_path:
            return
        normalized = self._normalize_path(Path(file_path))
        self.way_path_edit.setText(normalized)
        self._apply_way_path_edit()

    def _resolve_initial_dir(self, start_path: str) -> str:
        if not start_path:
            return str(Path.cwd())
        candidate = Path(start_path)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        if candidate.is_dir():
            return str(candidate)
        return str(candidate.parent)

    def _update_way_path_field(self) -> None:
        entry = self._selected_way_entry()
        enabled = entry is not None
        self.way_path_edit.blockSignals(True)
        self.way_path_edit.setText(entry.get("file", "") if entry else "")
        self.way_path_edit.setEnabled(enabled)
        self.way_path_button.setEnabled(enabled)
        self.way_path_edit.blockSignals(False)

    # ------------------------------------------------------------------
    def _persist_project(self) -> None:
        if not self._current_record or self._current_payload is None:
            return
        updated = self._project_repo.update_project_payload(self._current_record.id, self._current_payload)
        self._current_record = updated

    def _draw_plot(self) -> None:
        for ax in (self.ax_mag, self.ax_phase_sum, self.ax_phase_ways):
            ax.clear()

        if not self._current_payload or not self._current_payload.get("ways"):
            self.ax_mag.text(0.5, 0.5, "Keine Wege verfügbar", ha="center", va="center")
            self.canvas.draw_idle()
            return

        try:
            project = self._build_project_model()
            responses, freq_grid = project.resampled_responses(points=1600)
        except Exception as exc:
            self.ax_mag.text(0.5, 0.5, f"Plotfehler: {exc}", ha="center", va="center")
            self.canvas.draw_idle()
            return

        render_way_plots(
            self.ax_mag,
            self.ax_phase_sum,
            self.ax_phase_ways,
            project.ways,
            responses,
            freq_grid,
            figure=self.figure,
        )
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _build_project_model(self) -> Project:
        payload = self._current_payload or {}
        project = Project(
            base_dir=Path.cwd(),
            sample_rate=float(payload.get("sample_rate", 192000.0)),
        )
        filterset_name = payload.get("filterset") or payload.get("manufacturer")
        project.manufacturer = self._load_manufacturer(filterset_name)
        for index, entry in enumerate(payload.get("ways", [])):
            block_defs = [FilterBlock.from_dict(block) for block in entry.get("filters", [])]
            project.add_way(
                entry.get("name", f"Weg {index + 1}"),
                entry.get("file", ""),
                entry.get("color"),
                block_defs,
                gain_db=entry.get("gain_db"),
                delay_ms=entry.get("delay_ms"),
                invert=entry.get("invert"),
            )
        return project

    def _load_manufacturer(self, filterset_name: str | None) -> ManufacturerProfile | None:
        if not filterset_name:
            return None
        try:
            record = self._filterset_repo.get_entry(filterset_name)
        except KeyError:
            return None
        return ManufacturerProfile(
            name=record.name,
            description=record.description,
            filters=record.filters,
        )

    def _normalize_path(self, path: Path) -> str:
        path = path.resolve()
        workspace = Path.cwd().resolve()
        try:
            relative = path.relative_to(workspace)
            return relative.as_posix()
        except ValueError:
            return path.as_posix()

    def _format_block(self, block: dict[str, Any], number: int) -> str:
        block_type = block.get("type", "?").upper()
        params = block.get("params", {})
        freq = params.get("freq") or params.get("f0") or params.get("fc")
        if freq is not None:
            return f"{block_type} {number} @ {freq:.0f} Hz"
        return f"{block_type} {number}"


class FilterBlockDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Filter Block")
        self.block_data: dict[str, Any] | None = None
        self.selected_type: str | None = None
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select Filter Type:"))

        button_style = (
            "QPushButton { border: 1px solid #0060df; border-radius: 4px; padding: 12px 20px; "
            "color: #0060df; background-color: transparent; font-size: 11pt; } "
            "QPushButton:hover { background-color: #e0f0ff; }"
        )

        filters = [
            ("peq", "Parametric EQ", {"freq": 1000.0, "q": 0.707, "gain_db": 0.0}),
            ("shelf", "Shelf", {"mode": "low", "freq": 1000.0, "gain_db": 0.0, "slope": 0.707}),
            ("allpass", "All-Pass", {"freq": 1000.0, "q": 0.707}),
            ("linkwitz-riley", "Linkwitz-Riley", {"mode": "lowpass", "freq": 1000.0, "order": 4}),
            ("butterworth", "Butterworth", {"mode": "lowpass", "freq": 1000.0, "order": 4}),
        ]

        for filter_type, label, default_params in filters:
            btn = QPushButton(label)
            btn.setStyleSheet(button_style)
            btn.clicked.connect(lambda checked, ft=filter_type, dp=default_params: self._select_filter(ft, dp))
            layout.addWidget(btn)

        layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def _select_filter(self, filter_type: str, default_params: dict[str, Any]) -> None:
        self.block_data = {"type": filter_type, "params": default_params}
        self.accept()