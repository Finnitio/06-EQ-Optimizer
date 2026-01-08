from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from eq_optimizer.filters import FilterBlock, design_filter_response
from eq_optimizer.manufacturer_calibration import calibrate_manufacturer_profile
from eq_optimizer.manufacturer_store import ManufacturerRecord, ManufacturerRepository
from eq_optimizer.manufacturers import ManufacturerProfile
from eq_optimizer.measurements import Response, load_frd, resample_response


_PLOT_FREQ = np.logspace(np.log10(20.0), np.log10(20_000.0), 1200)
_DEFAULT_SAMPLE_RATE = 192000.0
_SAMPLE_RATE_CHOICES: list[tuple[str, float]] = [
    ("44.1k", 44_100.0),
    ("48k", 48_000.0),
    ("88.2k", 88_200.0),
    ("96k", 96_000.0),
    ("176.4k", 176_400.0),
    ("192k", 192_000.0),
]
@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    minimum: float
    maximum: float
    step: float
    decimals: int = 2
    kind: str = "float"


@dataclass(frozen=True)
class BlockTemplate:
    key: str
    title: str
    block_type: str
    defaults: dict[str, float]
    static_params: dict[str, Any]
    fields: list[ParamSpec]

    @property
    def block_id(self) -> str:
        return f"template-{self.key}"


class ManufacturerDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New manufacturer")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._name_edit = QLineEdit()
        self._desc_edit = QLineEdit()
        form.addRow("Name", self._name_edit)
        form.addRow("Description", self._desc_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def name_value(self) -> str:
        return self._name_edit.text().strip()

    def description_value(self) -> str:
        return self._desc_edit.text().strip()


BLOCK_TEMPLATES: list[BlockTemplate] = [
    BlockTemplate(
        key="peq",
        title="PEQ",
        block_type="peq",
        defaults={"f0": 1000.0, "q": 0.707, "gain_db": 3.0},
        static_params={},
        fields=[
            ParamSpec("f0", "Center freq (Hz)", 10.0, 40_000.0, 10.0, 2),
            ParamSpec("q", "Q", 0.1, 20.0, 0.1, 3),
            ParamSpec("gain_db", "Gain (dB)", -36.0, 36.0, 0.5, 2),
        ],
    ),
    BlockTemplate(
        key="shelf_low",
        title="Low shelf",
        block_type="shelf",
        defaults={"freq": 1000.0, "slope": 0.707, "gain_db": 3.0},
        static_params={"mode": "low"},
        fields=[
            ParamSpec("freq", "Corner freq (Hz)", 10.0, 40_000.0, 10.0, 2),
            ParamSpec("slope", "Slope", 0.1, 4.0, 0.05, 3),
            ParamSpec("gain_db", "Gain (dB)", -36.0, 36.0, 0.5, 2),
        ],
    ),
    BlockTemplate(
        key="allpass",
        title="All-pass",
        block_type="phase",
        defaults={"freq": 1000.0, "q": 0.707},
        static_params={},
        fields=[
            ParamSpec("freq", "Center freq (Hz)", 10.0, 40_000.0, 10.0, 2),
            ParamSpec("q", "Q", 0.1, 20.0, 0.1, 3),
        ],
    ),
    BlockTemplate(
        key="lowpass",
        title="Low-pass",
        block_type="linkwitz-riley",
        defaults={"freq": 1000.0},
        static_params={"mode": "lowpass"},
        fields=[
            ParamSpec("freq", "Cutoff (Hz)", 10.0, 40_000.0, 10.0, 2),
        ],
    ),
]
TEMPLATE_BY_KEY = {template.key: template for template in BLOCK_TEMPLATES}
PASS_TEMPLATE_KEYS = {"lowpass"}


class FilterTab(QWidget):
    def __init__(self, repository: ManufacturerRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self._records: dict[str, ManufacturerRecord] = {}
        self._current_manufacturer: Optional[str] = None
        self._current_block_key: Optional[str] = None
        self._suspend_updates = False
        self.param_widgets: dict[str, QWidget] = {}
        self._calibration_inputs: dict[str, QLineEdit] = {}
        self._calibration_cache: dict[str, tuple[str, Response]] = {}

        self._build_ui()
        self._wire_events()
        self._refresh_manufacturers()

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.manufacturer_list = QListWidget()
        left_layout.addWidget(self.manufacturer_list)

        button_row = QHBoxLayout()
        self.new_button = QPushButton("New")
        self.import_button = QPushButton("Import")
        self.export_button = QPushButton("Export")
        self.delete_button = QPushButton("Delete")
        self.refresh_button = QPushButton("Refresh")
        for button in (
            self.new_button,
            self.import_button,
            self.export_button,
            self.delete_button,
            self.refresh_button,
        ):
            button_row.addWidget(button)
        button_row.addStretch()
        left_layout.addLayout(button_row)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 0, 0, 0)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self.block_button_group = QButtonGroup(self)
        self.block_button_group.setExclusive(True)
        palette_layout = QGridLayout()
        palette_layout.setHorizontalSpacing(6)
        palette_layout.setVerticalSpacing(6)
        self.block_buttons: dict[str, QPushButton] = {}
        for index, template in enumerate(BLOCK_TEMPLATES):
            button = QPushButton(template.title)
            button.setCheckable(True)
            button.setStyleSheet(
                "QPushButton { padding: 6px; }\n"
                "QPushButton:checked { background-color: #0060df; color: white; }"
            )
            self.block_button_group.addButton(button)
            self.block_buttons[template.key] = button
            palette_layout.addWidget(button, index // 4, index % 4)
        right_layout.addLayout(palette_layout)

        pass_layout = QHBoxLayout()
        pass_layout.addWidget(QLabel("Pass filter type:"))
        self.pass_type_combo = QComboBox()
        self.pass_type_combo.addItems(["Linkwitz-Riley", "Butterworth"])
        self.pass_type_combo.setCurrentIndex(0)
        pass_layout.addWidget(self.pass_type_combo)
        pass_layout.addSpacing(12)
        pass_layout.addWidget(QLabel("Order:"))
        self.pass_order_combo = QComboBox()
        self.pass_order_combo.addItems(["2", "4", "6", "8", "10", "12"])
        self.pass_order_combo.setCurrentText("4")
        pass_layout.addWidget(self.pass_order_combo)
        pass_layout.addStretch()
        right_layout.addLayout(pass_layout)

        self.param_group = QGroupBox("Filter parameters")
        param_layout = QVBoxLayout(self.param_group)
        self.block_status = QLabel("Select a filter button to edit its canonical block.")
        self.block_status.setWordWrap(True)
        param_layout.addWidget(self.block_status)
        self.param_form = QFormLayout()
        param_layout.addLayout(self.param_form)
        self.reset_button = QPushButton("Reset defaults")
        param_layout.addWidget(self.reset_button, alignment=Qt.AlignLeft)
        self.param_group.setEnabled(False)
        right_layout.addWidget(self.param_group)

        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel("Preview sample rate"))
        self.sample_rate_combo = self._build_sample_rate_combo(_DEFAULT_SAMPLE_RATE, on_change=self._update_plot)
        sample_row.addWidget(self.sample_rate_combo)
        sample_row.addStretch()
        right_layout.addLayout(sample_row)

        self.figure = Figure(figsize=(6, 4))
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(250)
        right_layout.addWidget(self.canvas, stretch=1)

        self.calibration_group = QGroupBox("Calibration sweeps")
        calib_form = QFormLayout(self.calibration_group)
        self.peq_path = self._add_calibration_row(calib_form, "peq", "PEQ", "Select PEQ sweep")
        self.allpass_path = self._add_calibration_row(calib_form, "allpass", "All-pass", "Select all-pass sweep")
        self.shelf_path = self._add_calibration_row(calib_form, "shelf", "Low shelf", "Select shelf sweep")
        bw_orders = list(range(2, 13))
        lr_orders = [2, 4, 6, 8, 10, 12]
        self.lowpass_bw_path, self.lowpass_bw_order = self._add_lowpass_calibration_row(
            calib_form,
            key="lowpass_bw",
            label="Low-pass (Butterworth)",
            caption="Select Butterworth low-pass sweep",
            order_values=bw_orders,
            default_order=4,
        )
        self.lowpass_lr_path, self.lowpass_lr_order = self._add_lowpass_calibration_row(
            calib_form,
            key="lowpass_lr",
            label="Low-pass (Linkwitz-Riley)",
            caption="Select Linkwitz-Riley low-pass sweep",
            order_values=lr_orders,
            default_order=4,
        )
        self.cal_sample_rate_combo = self._build_sample_rate_combo(_DEFAULT_SAMPLE_RATE)
        calib_form.addRow("Sample rate", self.cal_sample_rate_combo)
        self.calibrate_button = QPushButton("Run calibration")
        calib_form.addRow("", self.calibrate_button)
        right_layout.addWidget(self.calibration_group)

    def _wrap_file_row(self, line_edit: QLineEdit, button: QPushButton) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        return container

    def _add_calibration_row(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        caption: str,
    ) -> QLineEdit:
        line_edit = QLineEdit()
        button = QPushButton("Browse")
        button.clicked.connect(lambda: self._browse_file(line_edit, caption))
        line_edit.textChanged.connect(lambda _: self._calibration_path_changed(key))
        form.addRow(label, self._wrap_file_row(line_edit, button))
        self._calibration_inputs[key] = line_edit
        return line_edit

    def _add_lowpass_calibration_row(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        caption: str,
        order_values: list[int],
        default_order: int,
    ) -> tuple[QLineEdit, QComboBox]:
        line_edit = QLineEdit()
        button = QPushButton("Browse")
        button.clicked.connect(lambda: self._browse_file(line_edit, caption))
        line_edit.textChanged.connect(lambda _: self._calibration_path_changed(key))
        order_combo = QComboBox()
        for value in order_values:
            order_combo.addItem(str(value), value)
        if default_order in order_values:
            order_combo.setCurrentIndex(order_values.index(default_order))
        order_label = QLabel("Order")
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        layout.addSpacing(8)
        layout.addWidget(order_label)
        layout.addWidget(order_combo)
        form.addRow(label, row)
        self._calibration_inputs[key] = line_edit
        return line_edit, order_combo

    def _build_sample_rate_combo(self, default_hz: float, on_change: Callable[[], None] | None = None) -> QComboBox:
        combo = QComboBox()
        for label, value in _SAMPLE_RATE_CHOICES:
            combo.addItem(label, value)
        self._select_sample_rate(combo, default_hz)
        if on_change is not None:
            combo.currentIndexChanged.connect(lambda _: on_change())
        return combo

    def _select_sample_rate(self, combo: QComboBox, target_hz: float) -> None:
        for index in range(combo.count()):
            data = combo.itemData(index)
            if data is None:
                continue
            if abs(float(data) - target_hz) < 1e-3:
                combo.setCurrentIndex(index)
                return
        combo.addItem(self._format_sample_rate(target_hz), target_hz)
        combo.setCurrentIndex(combo.count() - 1)

    @staticmethod
    def _current_sample_rate(combo: QComboBox) -> float:
        data = combo.currentData()
        return float(data) if data is not None else _DEFAULT_SAMPLE_RATE

    @staticmethod
    def _format_sample_rate(value: float) -> str:
        display = value / 1000.0
        if abs(round(display) - display) < 1e-6:
            return f"{int(round(display))}k"
        rounded = round(display, 1)
        return f"{rounded:.1f}k"

    def _wire_events(self) -> None:
        self.manufacturer_list.itemSelectionChanged.connect(self._on_manufacturer_selected)
        self.new_button.clicked.connect(self._create_manufacturer)
        self.import_button.clicked.connect(self._import_manufacturer)
        self.export_button.clicked.connect(self._export_manufacturer)
        self.delete_button.clicked.connect(self._delete_manufacturer)
        self.refresh_button.clicked.connect(self._refresh_manufacturers)
        self.reset_button.clicked.connect(self._reset_parameters)
        self.pass_type_combo.currentTextChanged.connect(self._pass_controls_changed)
        self.pass_order_combo.currentTextChanged.connect(self._pass_controls_changed)
        self.calibrate_button.clicked.connect(self._run_calibration)
        for key, button in self.block_buttons.items():
            button.clicked.connect(lambda checked, k=key: self._on_block_clicked(k, checked))

    # ------------------------------------------------------------------
    # Manufacturer management
    # ------------------------------------------------------------------
    def _refresh_manufacturers(self, select_name: Optional[str] = None) -> None:
        try:
            records = sorted(self.repository.list_manufacturers(), key=lambda r: r.name.lower())
        except Exception as exc:
            QMessageBox.critical(self, "Load manufacturers", str(exc))
            return
        self._records = {record.name: record for record in records}
        desired = select_name or self._current_manufacturer
        self.manufacturer_list.blockSignals(True)
        self.manufacturer_list.clear()
        for record in records:
            item = QListWidgetItem(record.name)
            item.setData(Qt.UserRole, record.name)
            item.setToolTip(record.description)
            self.manufacturer_list.addItem(item)
            if record.name == desired:
                self.manufacturer_list.setCurrentItem(item)
        self.manufacturer_list.blockSignals(False)
        if desired and desired in self._records:
            self._current_manufacturer = desired
            self._update_selection_state()
        elif records:
            self.manufacturer_list.setCurrentRow(0)
        else:
            self._current_manufacturer = None
            self._current_block_key = None
            self._update_selection_state()

    def _create_manufacturer(self) -> None:
        dialog = ManufacturerDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.name_value()
        if not name:
            QMessageBox.warning(self, "Invalid name", "Manufacturer name cannot be empty.")
            return
        try:
            record = self.repository.create_manufacturer(name, dialog.description_value())
        except Exception as exc:
            QMessageBox.critical(self, "Create manufacturer", str(exc))
            return
        self._refresh_manufacturers(record.name)

    def _import_manufacturer(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import manufacturers",
            str(Path.cwd()),
            "Manufacturer profiles (*.json *.eqmf);;All files (*)",
        )
        if not path:
            return
        try:
            imported = self.repository.import_file(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        names = ", ".join(record.name for record in imported)
        QMessageBox.information(self, "Import complete", f"Imported: {names}")
        self._refresh_manufacturers()

    def _export_manufacturer(self) -> None:
        record = self._current_record()
        if not record:
            QMessageBox.information(self, "Select manufacturer", "Choose a manufacturer to export.")
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Export manufacturer",
            str(Path.cwd() / f"{record.name}.eqmf"),
            "Manufacturer profile (*.eqmf);;JSON (*.json);;All files (*)",
        )
        if not destination:
            return
        try:
            path = self.repository.export_manufacturer(record.name, Path(destination))
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Export complete", f"Written to {path}")

    def _delete_manufacturer(self) -> None:
        record = self._current_record()
        if not record:
            QMessageBox.information(self, "Select manufacturer", "Choose a manufacturer to delete.")
            return
        confirm = QMessageBox.question(
            self,
            "Delete manufacturer",
            f"Delete '{record.name}'? This removes the stored profile.",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.repository.delete_manufacturer(record.name)
        except Exception as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self._refresh_manufacturers()

    def _on_manufacturer_selected(self) -> None:
        item = self.manufacturer_list.currentItem()
        self._current_manufacturer = item.data(Qt.UserRole) if item else None
        self._update_selection_state()

    def _update_selection_state(self) -> None:
        record = self._current_record()
        has_record = record is not None
        for button in self.block_buttons.values():
            button.setEnabled(has_record)
            if not has_record:
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
        self.param_group.setEnabled(False)
        self.block_status.setText("Select a filter button to edit its canonical block.")
        self.calibrate_button.setEnabled(has_record)
        self.pass_type_combo.setEnabled(has_record)
        self.pass_order_combo.setEnabled(has_record)
        if not has_record:
            self._current_block_key = None
            self._update_plot()
            return
        default_key = self._current_block_key or "peq"
        if default_key in self.block_buttons:
            self.block_buttons[default_key].setChecked(True)
            self._select_block(default_key)

    def _current_record(self) -> Optional[ManufacturerRecord]:
        if not self._current_manufacturer:
            return None
        return self._records.get(self._current_manufacturer)

    def _reload_record(self, name: str) -> None:
        try:
            record = self.repository.get_entry(name)
        except Exception:
            return
        self._records[name] = record

    # ------------------------------------------------------------------
    # Block editing
    # ------------------------------------------------------------------
    def _on_block_clicked(self, key: str, checked: bool) -> None:
        if checked:
            self._select_block(key)

    def _select_block(self, key: str) -> None:
        record = self._current_record()
        template = TEMPLATE_BY_KEY.get(key)
        if not record or not template:
            return
        block = self._ensure_block(record, template)
        if block is None:
            return
        self._current_block_key = key
        self._build_param_fields(template, block)
        self.param_group.setEnabled(True)
        self.block_status.setText(f"Editing {template.title} for {record.name}.")
        self._update_plot()

    def _pass_controls_changed(self) -> None:
        if self._current_block_key not in PASS_TEMPLATE_KEYS:
            return
        record = self._current_record()
        if not record:
            return
        template = TEMPLATE_BY_KEY.get(self._current_block_key or "")
        if not template:
            return
        block = self._ensure_block(record, template)
        if block:
            self._update_plot()

    def _ensure_block(self, record: ManufacturerRecord, template: BlockTemplate) -> Optional[dict[str, Any]]:
        block = self._find_block(record, template)
        if block is None:
            payload = {
                "id": template.block_id,
                "type": template.block_type,
                "params": self._initial_params(template),
            }
            if template.key in PASS_TEMPLATE_KEYS:
                self._apply_pass_filter_metadata(payload, template)
            try:
                block = self.repository.replace_block(record.name, payload)
            except Exception as exc:
                QMessageBox.critical(self, "Create filter block", str(exc))
                return None
            self._reload_record(record.name)
            block = self._find_block(self._records[record.name], template)
        elif template.key in PASS_TEMPLATE_KEYS:
            updated = self._apply_pass_filter_metadata(block, template)
            if updated:
                try:
                    self.repository.replace_block(record.name, block)
                except Exception as exc:
                    QMessageBox.critical(self, "Update filter block", str(exc))
                    return None
                self._reload_record(record.name)
                block = self._find_block(self._records[record.name], template)
        return block

    def _selected_pass_type(self) -> str:
        text = self.pass_type_combo.currentText().strip().lower()
        return "linkwitz-riley" if "linkwitz" in text else "butterworth"

    def _selected_pass_order(self) -> int:
        try:
            return int(self.pass_order_combo.currentText())
        except ValueError:
            return 4

    def _apply_pass_filter_metadata(self, block: dict[str, Any], template: BlockTemplate) -> bool:
        if template.key not in PASS_TEMPLATE_KEYS:
            return False
        desired_type = self._selected_pass_type()
        desired_order = self._selected_pass_order()
        desired_mode = "lowpass"
        params = block.setdefault("params", {})
        changed = False
        if block.get("type") != desired_type:
            block["type"] = desired_type
            changed = True
        if params.get("mode") != desired_mode:
            params["mode"] = desired_mode
            changed = True
        if params.get("order") != desired_order:
            params["order"] = desired_order
            changed = True
        if "freq" not in params:
            params["freq"] = template.defaults.get("freq", 1000.0)
            changed = True
        return changed

    def _initial_params(self, template: BlockTemplate) -> dict[str, float]:
        params = dict(template.static_params)
        params.update(template.defaults)
        return params

    def _find_block(self, record: ManufacturerRecord, template: BlockTemplate) -> Optional[dict[str, Any]]:
        for block in record.blocks:
            if block.get("id") == template.block_id:
                params = block.setdefault("params", {})
                for key, value in template.static_params.items():
                    params[key] = value
                return block
        for block in record.blocks:
            block_id = str(block.get("id") or "")
            if not block_id.startswith("template-"):
                continue
            if block.get("type") != template.block_type:
                continue
            params = block.get("params", {})
            if all(params.get(k) == v for k, v in template.static_params.items()):
                return block
        return None

    def _build_param_fields(self, template: BlockTemplate, block: dict[str, Any]) -> None:
        while self.param_form.rowCount():
            self.param_form.removeRow(0)
        self.param_widgets: dict[str, QWidget] = {}
        self._suspend_updates = True
        params = self._initial_params(template)
        params.update(block.get("params", {}))
        for spec in template.fields:
            widget: QWidget
            if spec.kind == "int":
                spin = QSpinBox()
                spin.setRange(int(spec.minimum), int(spec.maximum))
                spin.setSingleStep(max(1, int(spec.step)))
                spin.valueChanged.connect(self._on_param_changed)
                widget = spin
            else:
                dbl = QDoubleSpinBox()
                dbl.setRange(spec.minimum, spec.maximum)
                dbl.setSingleStep(spec.step)
                dbl.setDecimals(spec.decimals)
                dbl.valueChanged.connect(self._on_param_changed)
                widget = dbl
            value = params.get(spec.key, template.defaults.get(spec.key, 0.0))
            if isinstance(widget, QSpinBox):
                widget.setValue(int(round(value)))
            else:
                widget.setValue(float(value))
            self.param_form.addRow(spec.label, widget)
            self.param_widgets[spec.key] = widget
        self._suspend_updates = False

    def _on_param_changed(self, _: float) -> None:
        if self._suspend_updates:
            return
        self._persist_current_block()

    def _reset_parameters(self) -> None:
        template = TEMPLATE_BY_KEY.get(self._current_block_key or "")
        record = self._current_record()
        if not record or not template:
            return
        block = self._ensure_block(record, template)
        if not block:
            return
        block["params"] = self._initial_params(template)
        if template.key in PASS_TEMPLATE_KEYS:
            self._apply_pass_filter_metadata(block, template)
        try:
            self.repository.replace_block(record.name, block)
        except Exception as exc:
            QMessageBox.critical(self, "Reset block", str(exc))
            return
        self._reload_record(record.name)
        self._build_param_fields(template, block)
        self._update_plot()

    def _persist_current_block(self) -> None:
        record = self._current_record()
        template = TEMPLATE_BY_KEY.get(self._current_block_key or "")
        if not record or not template:
            return
        block = self._ensure_block(record, template)
        if not block:
            return
        params = dict(template.static_params)
        for key, widget in self.param_widgets.items():
            if isinstance(widget, QSpinBox):
                params[key] = int(widget.value())
            elif isinstance(widget, QDoubleSpinBox):
                params[key] = float(widget.value())
        block["params"] = params
        if template.key in PASS_TEMPLATE_KEYS:
            self._apply_pass_filter_metadata(block, template)
        try:
            self.repository.replace_block(record.name, block)
        except Exception as exc:
            QMessageBox.critical(self, "Update block", str(exc))
            return
        self._reload_record(record.name)
        self._update_plot()

    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------
    def _update_plot(self) -> None:
        self.axes.clear()
        self.axes.set_xscale("log")
        self.axes.set_xlabel("Frequency [Hz]")
        show_phase = self._current_block_key == "allpass"
        self.axes.set_ylabel("Phase [deg]" if show_phase else "Magnitude [dB]")
        self.axes.grid(True, which="both", linestyle=":", linewidth=0.6)
        block = self._current_block_dict()
        profile = self._current_profile()
        sample_rate = self._current_sample_rate(self.sample_rate_combo)
        if block:
            try:
                response = design_filter_response(
                    FilterBlock(kind=block.get("type", ""), params=block.get("params", {})),
                    _PLOT_FREQ,
                    sample_rate,
                    profile,
                )
                if show_phase:
                    phase_deg = np.degrees(np.unwrap(np.angle(response)))
                    wrapped = ((phase_deg + 180.0) % 360.0) - 180.0
                    self.axes.semilogx(_PLOT_FREQ, wrapped, color="#0060df", linewidth=1.6, label="Filter phase")
                    self.axes.set_ylim(-200.0, 200.0)
                else:
                    magnitude = 20.0 * np.log10(np.maximum(np.abs(response), 1e-9))
                    self.axes.semilogx(_PLOT_FREQ, magnitude, color="#0060df", linewidth=1.6, label="Filter")
            except Exception as exc:
                self.axes.text(0.5, 0.5, f"Plot error\n{exc}", ha="center", va="center", transform=self.axes.transAxes)
        measurement_entry = self._calibration_measurement_for_block(self._current_block_key or "")
        if measurement_entry:
            measurement, label = measurement_entry
            resampled = resample_response(measurement, _PLOT_FREQ)
            if show_phase:
                phase_deg = np.degrees(resampled.phase_rad)
                wrapped = ((phase_deg + 180.0) % 360.0) - 180.0
                self.axes.semilogx(
                    resampled.frequency,
                    wrapped,
                    linestyle="--",
                    linewidth=1.2,
                    color="#ff7f0e",
                    label=f"{label} (sweep)",
                )
            else:
                self.axes.semilogx(
                    resampled.frequency,
                    resampled.magnitude_db,
                    linestyle="--",
                    linewidth=1.2,
                    color="#ff7f0e",
                    label=f"{label} (sweep)",
                )
        if self.axes.has_data():
            self.axes.legend(loc="best")
        else:
            self.axes.text(0.5, 0.5, "Select a filter to preview", ha="center", va="center", transform=self.axes.transAxes)
        self.canvas.draw_idle()

    def _current_block_dict(self) -> Optional[dict[str, Any]]:
        record = self._current_record()
        template = TEMPLATE_BY_KEY.get(self._current_block_key or "")
        if not record or not template:
            return None
        return self._find_block(record, template)

    def _current_profile(self) -> ManufacturerProfile | None:
        record = self._current_record()
        if not record:
            return None
        return ManufacturerProfile(name=record.name, description=record.description, filters=record.filters)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def _browse_file(self, line_edit: QLineEdit, caption: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            caption,
            str(Path.cwd()),
            "Sweeps (*.frd *.txt);;All files (*)",
        )
        if path:
            line_edit.setText(path)
        else:
            self._update_plot()

    def _calibration_path_changed(self, key: str) -> None:
        self._calibration_cache.pop(key, None)
        path = self._calibration_inputs.get(key)
        if not path:
            return
        text = path.text().strip()
        candidate = Path(text) if text else None
        if candidate and candidate.exists():
            self._load_calibration_response(key, text)
        self._update_plot()

    def _calibration_measurement_for_block(self, block_key: str) -> Optional[tuple[Response, str]]:
        mapping = {
            "peq": "peq",
            "allpass": "allpass",
            "shelf_low": "shelf",
        }
        if block_key == "lowpass":
            cal_key = "lowpass_lr" if self._selected_pass_type() == "linkwitz-riley" else "lowpass_bw"
        else:
            cal_key = mapping.get(block_key)
        if not cal_key:
            return None
        line_edit = self._calibration_inputs.get(cal_key)
        if not line_edit:
            return None
        path_text = line_edit.text().strip()
        if not path_text:
            return None
        response = self._load_calibration_response(cal_key, path_text)
        if response is None:
            return None
        return response, Path(path_text).name

    def _load_calibration_response(self, cal_key: str, path_text: str) -> Optional[Response]:
        cached = self._calibration_cache.get(cal_key)
        if cached and cached[0] == path_text:
            return cached[1]
        candidate = Path(path_text)
        if not candidate.exists():
            self._calibration_cache.pop(cal_key, None)
            return None
        try:
            response = load_frd(candidate)
        except Exception as exc:
            QMessageBox.warning(self, "Load sweep", f"Unable to read {candidate.name}: {exc}")
            self._calibration_cache.pop(cal_key, None)
            return None
        self._calibration_cache[cal_key] = (path_text, response)
        return response

    def _run_calibration(self) -> None:
        record = self._current_record()
        if not record:
            QMessageBox.information(self, "Select manufacturer", "Choose a manufacturer first.")
            return
        paths = {
            "peq": Path(self.peq_path.text().strip()),
            "allpass": Path(self.allpass_path.text().strip()),
            "shelf": Path(self.shelf_path.text().strip()),
        }
        missing_core = [key for key, path in paths.items() if not path.exists()]
        if missing_core:
            QMessageBox.warning(
                self,
                "Missing sweeps",
                "Select existing PEQ, all-pass, and low-shelf files before calibrating.",
            )
            return

        lowpass_rows = [
            ("butterworth", "Butterworth low-pass", self.lowpass_bw_path, self.lowpass_bw_order),
            ("linkwitz-riley", "Linkwitz-Riley low-pass", self.lowpass_lr_path, self.lowpass_lr_order),
        ]
        optional_lowpass: list[tuple[str, Path, int]] = []
        for kind, label, line_edit, order_combo in lowpass_rows:
            text = line_edit.text().strip()
            if not text:
                continue
            candidate = Path(text)
            if not candidate.exists():
                QMessageBox.warning(self, "Missing sweeps", f"Select an existing file for {label}.")
                return
            order_value = order_combo.currentData()
            if order_value is None:
                order_value = order_combo.currentText()
            optional_lowpass.append((kind, candidate, int(order_value)))

        directories = {path.parent for path in paths.values()}
        directories.update(spec_path.parent for _, spec_path, _ in optional_lowpass)
        if len(directories) != 1:
            QMessageBox.warning(self, "Sweep locations", "Place every sweep inside the same folder.")
            return
        sweep_dir = directories.pop()
        lowpass_specs = [(kind, spec_path.name, order) for kind, spec_path, order in optional_lowpass]
        try:
            entry = calibrate_manufacturer_profile(
                name=record.name,
                sweep_dir=sweep_dir,
                peq_file=paths["peq"].name,
                allpass_file=paths["allpass"].name,
                shelf_file=paths["shelf"].name,
                sample_rate=self._current_sample_rate(self.cal_sample_rate_combo),
                lowpass_specs=lowpass_specs or None,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Calibration failed", str(exc))
            return
        merged_filters = dict(record.filters)
        merged_filters.update(entry.get("filters", {}))
        updated = ManufacturerRecord(
            name=entry.get("name", record.name),
            description=entry.get("description", record.description),
            filters=merged_filters,
            blocks=record.blocks,
        )
        try:
            self.repository.save_entry(updated)
        except Exception as exc:
            QMessageBox.critical(self, "Persist calibration", str(exc))
            return
        QMessageBox.information(self, "Calibration complete", f"Updated manufacturer '{updated.name}'.")
        self._refresh_manufacturers(updated.name)
