from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from eq_optimizer.filterset_store import FiltersetRepository
from eq_optimizer.project_store import ProjectRepository

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


class FilterTab(QWidget):
    """Minimal view with a filterset list on the left and the plot on the right."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        filterset_repository: FiltersetRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_repository = project_repository
        self.filterset_repository = filterset_repository
        self._active_project = None
        self._active_filter = "peq"
        self._build_ui()
        self._refresh_filtersets()
        self._update_filter_panel()
        self._update_plot()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # Left: filterset list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Filtersets"))
        self.filterset_list = QListWidget()
        self.filterset_list.itemSelectionChanged.connect(self._update_plot)
        left_layout.addWidget(self.filterset_list)

        refresh_row = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh_filtersets)
        refresh_row.addWidget(self.refresh_button)
        refresh_row.addStretch()
        left_layout.addLayout(refresh_row)

        splitter.addWidget(left_panel)

        # Right: preview only
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)

        preview_group = QGroupBox("Filter preview")
        preview_layout = QVBoxLayout(preview_group)
        header = QHBoxLayout()
        header.addWidget(QLabel("Preview sample rate"))
        self.sample_rate_combo = self._build_sample_rate_combo(_DEFAULT_SAMPLE_RATE, on_change=self._update_plot)
        header.addWidget(self.sample_rate_combo)
        header.addStretch()
        preview_layout.addLayout(header)

        self.figure = Figure(figsize=(6, 3.6))
        self.axes = self.figure.add_subplot(111)
        self.figure.subplots_adjust(bottom=0.18)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(260)
        preview_layout.addWidget(self.canvas)

        right_layout.addWidget(preview_group)

        # Filter selection buttons
        filter_group = QGroupBox("Filter parameters")
        filter_layout = QVBoxLayout(filter_group)
        
        button_row = QHBoxLayout()
        self.filter_button_group = QButtonGroup(self)
        self.filter_button_group.setExclusive(True)
        
        accent_style = (
            "QPushButton { border: 1px solid #0060df; border-radius: 4px; padding: 6px 12px; "
            "color: #0060df; background-color: transparent; } "
            "QPushButton:checked { background-color: #0060df; color: white; }"
        )
        
        for filter_name, label in [("peq", "PEQ"), ("shelf", "Shelf"), ("allpass", "Allpass"), 
                                    ("linkwitz-riley", "Linkwitz-Riley"), ("butterworth", "Butterworth")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(accent_style)
            btn.clicked.connect(lambda checked, f=filter_name: checked and self._on_filter_selected(f))
            self.filter_button_group.addButton(btn)
            button_row.addWidget(btn)
            if filter_name == "peq":
                btn.setChecked(True)
        button_row.addStretch()
        filter_layout.addLayout(button_row)
        
        # Stacked widget for filter parameters
        self.filter_params_stack = QStackedWidget()
        filter_layout.addWidget(self.filter_params_stack)
        
        # Build parameter panels for each filter
        self._build_peq_panel()
        self._build_shelf_panel()
        self._build_allpass_panel()
        self._build_linkwitz_riley_panel()
        self._build_butterworth_panel()
        
        right_layout.addWidget(filter_group)
        right_layout.addStretch()
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

    def set_active_project(self, record, payload) -> None:
        """Keep signature for caller; store and ignore for now."""
        self._active_project = record
        # No additional behaviour needed in this minimal view.

    def _build_sample_rate_combo(self, default_hz: float, on_change=None) -> QComboBox:
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
    def _format_sample_rate(value: float) -> str:
        display = value / 1000.0
        if abs(round(display) - display) < 1e-6:
            return f"{int(round(display))}k"
        rounded = round(display, 1)
        return f"{rounded:.1f}k"

    @staticmethod
    def _current_sample_rate(combo: QComboBox) -> float:
        data = combo.currentData()
        return float(data) if data is not None else _DEFAULT_SAMPLE_RATE

    def _refresh_filtersets(self) -> None:
        self.filterset_list.blockSignals(True)
        self.filterset_list.clear()
        try:
            records = sorted(self.filterset_repository.list_filtersets(), key=lambda r: r.name.lower())
        except Exception:
            records = []
        for record in records:
            item = QListWidgetItem(record.name)
            item.setData(Qt.UserRole, record.name)
            item.setToolTip(record.description)
            self.filterset_list.addItem(item)
        self.filterset_list.blockSignals(False)
        if self.filterset_list.count():
            self.filterset_list.setCurrentRow(0)

    def _update_plot(self) -> None:
        self.axes.clear()
        self.axes.set_xscale("log")
        self.axes.set_xlabel("Frequency [Hz]")
        self.axes.set_ylabel("Magnitude [dB]")
        self.axes.grid(True, which="both", linestyle=":", linewidth=0.6)

        freq = _PLOT_FREQ
        sample_rate = self._current_sample_rate(self.sample_rate_combo)
        
        # Load and plot sweep data if available
        sweep_path = self._get_current_sweep_path()
        if sweep_path:
            sweep_freq, sweep_mag = self._load_sweep_file(sweep_path)
            if sweep_freq is not None and sweep_mag is not None:
                self.axes.plot(sweep_freq, sweep_mag, label="Sweep", linewidth=1.5, 
                             color="#ff0000", alpha=0.8)
        
        # Calculate filter response based on active filter type
        gain = self._calculate_filter_response(freq, sample_rate)
        
        label = self._get_filter_label()
        self.axes.plot(freq, gain, label=label, linewidth=2)

        self.axes.legend(loc="best")
        self.canvas.draw_idle()

    def _on_filter_selected(self, filter_name: str) -> None:
        self._active_filter = filter_name
        self._update_filter_panel()
        self._update_plot()

    def _update_filter_panel(self) -> None:
        index_map = {"peq": 0, "shelf": 1, "allpass": 2, "linkwitz-riley": 3, "butterworth": 4}
        index = index_map.get(self._active_filter, 0)
        self.filter_params_stack.setCurrentIndex(index)

    def _build_peq_panel(self) -> None:
        panel = QWidget()
        layout = QFormLayout(panel)
        
        self.peq_freq = QDoubleSpinBox()
        self.peq_freq.setRange(10.0, 40000.0)
        self.peq_freq.setValue(1000.0)
        self.peq_freq.setDecimals(2)
        layout.addRow("Frequency (Hz):", self.peq_freq)
        
        self.peq_q = QDoubleSpinBox()
        self.peq_q.setRange(0.1, 20.0)
        self.peq_q.setValue(0.707)
        self.peq_q.setDecimals(3)
        layout.addRow("Q:", self.peq_q)
        
        self.peq_a = QDoubleSpinBox()
        self.peq_a.setRange(-36.0, 36.0)
        self.peq_a.setValue(3.0)
        self.peq_a.setDecimals(2)
        layout.addRow("A (dB):", self.peq_a)
        
        path_row = QHBoxLayout()
        self.peq_path = QLineEdit()
        self.peq_path.textChanged.connect(self._update_plot)
        path_browse = QPushButton("Browse")
        path_browse.clicked.connect(lambda: self._browse_sweep(self.peq_path))
        path_row.addWidget(self.peq_path)
        path_row.addWidget(path_browse)
        layout.addRow("Sweep path:", path_row)
        
        # Connect parameter changes to plot update
        self.peq_freq.valueChanged.connect(self._update_plot)
        self.peq_q.valueChanged.connect(self._update_plot)
        self.peq_a.valueChanged.connect(self._update_plot)
        
        self.filter_params_stack.addWidget(panel)

    def _build_shelf_panel(self) -> None:
        panel = QWidget()
        layout = QFormLayout(panel)
        
        self.shelf_freq = QDoubleSpinBox()
        self.shelf_freq.setRange(10.0, 40000.0)
        self.shelf_freq.setValue(1000.0)
        self.shelf_freq.setDecimals(2)
        layout.addRow("Frequency (Hz):", self.shelf_freq)
        
        self.shelf_q = QDoubleSpinBox()
        self.shelf_q.setRange(0.1, 20.0)
        self.shelf_q.setValue(0.707)
        self.shelf_q.setDecimals(3)
        layout.addRow("Q:", self.shelf_q)
        
        self.shelf_a = QDoubleSpinBox()
        self.shelf_a.setRange(-36.0, 36.0)
        self.shelf_a.setValue(3.0)
        self.shelf_a.setDecimals(2)
        layout.addRow("A (dB):", self.shelf_a)
        
        mode_row = QHBoxLayout()
        self.shelf_mode_group = QButtonGroup(self)
        self.shelf_low = QPushButton("Low Shelf")
        self.shelf_high = QPushButton("High Shelf")
        for btn in [self.shelf_low, self.shelf_high]:
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #0060df; border-radius: 4px; padding: 6px; "
                "color: #0060df; background-color: transparent; } "
                "QPushButton:checked { background-color: #0060df; color: white; }"
            )
            self.shelf_mode_group.addButton(btn)
            mode_row.addWidget(btn)
        self.shelf_low.setChecked(True)
        mode_row.addStretch()
        layout.addRow("Mode:", mode_row)
        
        path_row = QHBoxLayout()
        self.shelf_path = QLineEdit()
        self.shelf_path.textChanged.connect(self._update_plot)
        path_browse = QPushButton("Browse")
        path_browse.clicked.connect(lambda: self._browse_sweep(self.shelf_path))
        path_row.addWidget(self.shelf_path)
        path_row.addWidget(path_browse)
        layout.addRow("Sweep path:", path_row)
        
        # Connect parameter changes to plot update
        self.shelf_freq.valueChanged.connect(self._update_plot)
        self.shelf_q.valueChanged.connect(self._update_plot)
        self.shelf_a.valueChanged.connect(self._update_plot)
        self.shelf_low.clicked.connect(self._update_plot)
        self.shelf_high.clicked.connect(self._update_plot)
        
        self.filter_params_stack.addWidget(panel)

    def _build_allpass_panel(self) -> None:
        panel = QWidget()
        layout = QFormLayout(panel)
        
        self.allpass_freq = QDoubleSpinBox()
        self.allpass_freq.setRange(10.0, 40000.0)
        self.allpass_freq.setValue(1000.0)
        self.allpass_freq.setDecimals(2)
        layout.addRow("Frequency (Hz):", self.allpass_freq)
        
        self.allpass_q = QDoubleSpinBox()
        self.allpass_q.setRange(0.1, 20.0)
        self.allpass_q.setValue(0.707)
        self.allpass_q.setDecimals(3)
        layout.addRow("Q:", self.allpass_q)
        
        self.allpass_a = QDoubleSpinBox()
        self.allpass_a.setRange(-36.0, 36.0)
        self.allpass_a.setValue(3.0)
        self.allpass_a.setDecimals(2)
        layout.addRow("A (dB):", self.allpass_a)
        
        self.allpass_invert = QCheckBox("Invert")
        layout.addRow("", self.allpass_invert)
        
        path_row = QHBoxLayout()
        self.allpass_path = QLineEdit()
        self.allpass_path.textChanged.connect(self._update_plot)
        path_browse = QPushButton("Browse")
        path_browse.clicked.connect(lambda: self._browse_sweep(self.allpass_path))
        path_row.addWidget(self.allpass_path)
        path_row.addWidget(path_browse)
        layout.addRow("Sweep path:", path_row)
        
        # Connect parameter changes to plot update
        self.allpass_freq.valueChanged.connect(self._update_plot)
        self.allpass_q.valueChanged.connect(self._update_plot)
        self.allpass_a.valueChanged.connect(self._update_plot)
        self.allpass_invert.stateChanged.connect(self._update_plot)
        
        self.filter_params_stack.addWidget(panel)

    def _build_linkwitz_riley_panel(self) -> None:
        panel = QWidget()
        layout = QFormLayout(panel)
        
        self.lr_freq = QDoubleSpinBox()
        self.lr_freq.setRange(10.0, 40000.0)
        self.lr_freq.setValue(1000.0)
        self.lr_freq.setDecimals(2)
        layout.addRow("Frequency (Hz):", self.lr_freq)
        
        order_row = QHBoxLayout()
        self.lr_order_group = QButtonGroup(self)
        for order in [2, 4, 6, 8]:
            btn = QPushButton(str(order))
            btn.setCheckable(True)
            btn.setFixedWidth(40)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #0060df; border-radius: 4px; padding: 6px; "
                "color: #0060df; background-color: transparent; } "
                "QPushButton:checked { background-color: #0060df; color: white; }"
            )
            self.lr_order_group.addButton(btn, order)
            order_row.addWidget(btn)
        self.lr_order_group.button(4).setChecked(True)
        order_row.addStretch()
        layout.addRow("Order:", order_row)
        
        mode_row = QHBoxLayout()
        self.lr_mode_group = QButtonGroup(self)
        self.lr_lowpass = QPushButton("Lowpass")
        self.lr_highpass = QPushButton("Highpass")
        for btn in [self.lr_lowpass, self.lr_highpass]:
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #0060df; border-radius: 4px; padding: 6px; "
                "color: #0060df; background-color: transparent; } "
                "QPushButton:checked { background-color: #0060df; color: white; }"
            )
            self.lr_mode_group.addButton(btn)
            mode_row.addWidget(btn)
        self.lr_lowpass.setChecked(True)
        mode_row.addStretch()
        layout.addRow("Mode:", mode_row)
        
        path_row = QHBoxLayout()
        self.lr_path = QLineEdit()
        self.lr_path.textChanged.connect(self._update_plot)
        path_browse = QPushButton("Browse")
        path_browse.clicked.connect(lambda: self._browse_sweep(self.lr_path))
        path_row.addWidget(self.lr_path)
        path_row.addWidget(path_browse)
        layout.addRow("Sweep path:", path_row)
        
        # Connect parameter changes to plot update
        self.lr_freq.valueChanged.connect(self._update_plot)
        for btn in self.lr_order_group.buttons():
            btn.clicked.connect(self._update_plot)
        self.lr_lowpass.clicked.connect(self._update_plot)
        self.lr_highpass.clicked.connect(self._update_plot)
        
        self.filter_params_stack.addWidget(panel)

    def _build_butterworth_panel(self) -> None:
        panel = QWidget()
        layout = QFormLayout(panel)
        
        self.bw_freq = QDoubleSpinBox()
        self.bw_freq.setRange(10.0, 40000.0)
        self.bw_freq.setValue(1000.0)
        self.bw_freq.setDecimals(2)
        layout.addRow("Frequency (Hz):", self.bw_freq)
        
        order_row = QHBoxLayout()
        self.bw_order_group = QButtonGroup(self)
        for order in [1, 2, 3, 4, 5, 6, 7, 8]:
            btn = QPushButton(str(order))
            btn.setCheckable(True)
            btn.setFixedWidth(40)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #0060df; border-radius: 4px; padding: 6px; "
                "color: #0060df; background-color: transparent; } "
                "QPushButton:checked { background-color: #0060df; color: white; }"
            )
            self.bw_order_group.addButton(btn, order)
            order_row.addWidget(btn)
        self.bw_order_group.button(4).setChecked(True)
        order_row.addStretch()
        layout.addRow("Order:", order_row)
        
        mode_row = QHBoxLayout()
        self.bw_mode_group = QButtonGroup(self)
        self.bw_lowpass = QPushButton("Lowpass")
        self.bw_highpass = QPushButton("Highpass")
        for btn in [self.bw_lowpass, self.bw_highpass]:
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #0060df; border-radius: 4px; padding: 6px; "
                "color: #0060df; background-color: transparent; } "
                "QPushButton:checked { background-color: #0060df; color: white; }"
            )
            self.bw_mode_group.addButton(btn)
            mode_row.addWidget(btn)
        self.bw_lowpass.setChecked(True)
        mode_row.addStretch()
        layout.addRow("Mode:", mode_row)
        
        path_row = QHBoxLayout()
        self.bw_path = QLineEdit()
        self.bw_path.textChanged.connect(self._update_plot)
        path_browse = QPushButton("Browse")
        path_browse.clicked.connect(lambda: self._browse_sweep(self.bw_path))
        path_row.addWidget(self.bw_path)
        path_row.addWidget(path_browse)
        layout.addRow("Sweep path:", path_row)
        
        # Connect parameter changes to plot update
        self.bw_freq.valueChanged.connect(self._update_plot)
        for btn in self.bw_order_group.buttons():
            btn.clicked.connect(self._update_plot)
        self.bw_lowpass.clicked.connect(self._update_plot)
        self.bw_highpass.clicked.connect(self._update_plot)
        
        self.filter_params_stack.addWidget(panel)

    def _browse_sweep(self, line_edit: QLineEdit) -> None:
        from pathlib import Path
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select sweep file",
            str(Path.cwd()),
            "Sweep files (*.frd *.txt);;All files (*)",
        )
        if path:
            line_edit.setText(path)
    
    def _get_current_sweep_path(self) -> str:
        """Get the sweep path for the currently active filter."""
        if self._active_filter == "peq":
            return self.peq_path.text().strip()
        elif self._active_filter == "shelf":
            return self.shelf_path.text().strip()
        elif self._active_filter == "allpass":
            return self.allpass_path.text().strip()
        elif self._active_filter == "linkwitz-riley":
            return self.lr_path.text().strip()
        elif self._active_filter == "butterworth":
            return self.bw_path.text().strip()
        return ""
    
    def _get_selected_filterset_definition(self) -> dict:
        """Get the filter definition from the currently selected filterset."""
        item = self.filterset_list.currentItem()
        if not item:
            return {}
        
        filterset_name = item.data(Qt.UserRole)
        try:
            record = self.filterset_repository.get_entry(filterset_name)
            return record.filters.get(self._active_filter, {})
        except (KeyError, AttributeError):
            return {}
    
    def _load_sweep_file(self, file_path: str) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Load frequency and magnitude data from a sweep file (.frd or .txt)."""
        from pathlib import Path
        
        if not file_path or not Path(file_path).exists():
            return None, None
        
        try:
            freq_list = []
            mag_list = []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('*') or line.startswith('#'):
                        continue
                    
                    # Try to parse frequency and magnitude
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            freq = float(parts[0])
                            mag = float(parts[1])
                            freq_list.append(freq)
                            mag_list.append(mag)
                        except ValueError:
                            continue
            
            if freq_list and mag_list:
                return np.array(freq_list), np.array(mag_list)
        except Exception:
            pass
        
        return None, None
    
    def _calculate_filter_response(self, freq: np.ndarray, sample_rate: float) -> np.ndarray:
        """Calculate the magnitude response of the currently selected filter."""
        # Get the selected filterset to apply its constraints
        filterset_def = self._get_selected_filterset_definition()
        
        if self._active_filter == "peq":
            return self._calc_peq_response(freq, sample_rate, 
                                          self.peq_freq.value(), 
                                          self.peq_q.value(), 
                                          self.peq_a.value(),
                                          filterset_def)
        elif self._active_filter == "shelf":
            is_low_shelf = self.shelf_low.isChecked()
            return self._calc_shelf_response(freq, sample_rate,
                                            self.shelf_freq.value(),
                                            self.shelf_q.value(),
                                            self.shelf_a.value(),
                                            is_low_shelf,
                                            filterset_def)
        elif self._active_filter == "allpass":
            return self._calc_allpass_response(freq, sample_rate,
                                              self.allpass_freq.value(),
                                              self.allpass_q.value(),
                                              self.allpass_invert.isChecked(),
                                              filterset_def)
        elif self._active_filter == "linkwitz-riley":
            order = self.lr_order_group.checkedId()
            is_lowpass = self.lr_lowpass.isChecked()
            return self._calc_linkwitz_riley_response(freq, sample_rate,
                                                     self.lr_freq.value(),
                                                     order, is_lowpass)
        elif self._active_filter == "butterworth":
            order = self.bw_order_group.checkedId()
            is_lowpass = self.bw_lowpass.isChecked()
            return self._calc_butterworth_response(freq, sample_rate,
                                                  self.bw_freq.value(),
                                                  order, is_lowpass)
        return np.zeros_like(freq)
    
    def _calc_peq_response(self, freq: np.ndarray, fs: float, f0: float, q: float, 
                          gain_db: float, filterset_def: dict = None) -> np.ndarray:
        """Calculate parametric EQ (peaking filter) response."""
        # Apply filterset constraints if available
        if filterset_def:
            q_scale = filterset_def.get('q_scale', 1.0)
            q = q * q_scale
            
            q_min = filterset_def.get('q_min')
            q_max = filterset_def.get('q_max')
            if q_min is not None:
                q = max(q, q_min)
            if q_max is not None:
                q = min(q, q_max)
            
            gain_limit = filterset_def.get('gain_limit_db')
            if gain_limit is not None:
                gain_db = max(-gain_limit, min(gain_limit, gain_db))
        
        A = 10 ** (gain_db / 40.0)
        w0 = 2 * np.pi * f0 / fs
        alpha = np.sin(w0) / (2 * q)
        
        b0 = 1 + alpha * A
        b1 = -2 * np.cos(w0)
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha / A
        
        w = 2 * np.pi * freq / fs
        z = np.exp(1j * w)
        
        H = (b0 + b1 * z**(-1) + b2 * z**(-2)) / (a0 + a1 * z**(-1) + a2 * z**(-2))
        return 20 * np.log10(np.abs(H))
    
    def _calc_shelf_response(self, freq: np.ndarray, fs: float, f0: float, q: float, 
                            gain_db: float, is_low_shelf: bool, filterset_def: dict = None) -> np.ndarray:
        """Calculate shelving filter response."""
        # Apply filterset constraints if available
        if filterset_def:
            slope_scale = filterset_def.get('slope_scale', 1.0)
            q = q * slope_scale
            
            gain_limit = filterset_def.get('gain_limit_db')
            if gain_limit is not None:
                gain_db = max(-gain_limit, min(gain_limit, gain_db))
        
        A = 10 ** (gain_db / 40.0)
        w0 = 2 * np.pi * f0 / fs
        alpha = np.sin(w0) / (2 * q)
        
        if is_low_shelf:
            b0 = A * ((A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha)
            b1 = 2 * A * ((A - 1) - (A + 1) * np.cos(w0))
            b2 = A * ((A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha)
            a0 = (A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha
            a1 = -2 * ((A - 1) + (A + 1) * np.cos(w0))
            a2 = (A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha
        else:  # high shelf
            b0 = A * ((A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha)
            b1 = -2 * A * ((A - 1) + (A + 1) * np.cos(w0))
            b2 = A * ((A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha)
            a0 = (A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha
            a1 = 2 * ((A - 1) - (A + 1) * np.cos(w0))
            a2 = (A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha
        
        w = 2 * np.pi * freq / fs
        z = np.exp(1j * w)
        
        H = (b0 + b1 * z**(-1) + b2 * z**(-2)) / (a0 + a1 * z**(-1) + a2 * z**(-2))
        return 20 * np.log10(np.abs(H))
    
    def _calc_allpass_response(self, freq: np.ndarray, fs: float, f0: float, 
                               q: float, invert: bool, filterset_def: dict = None) -> np.ndarray:
        """Calculate allpass filter response (magnitude is flat, but included for completeness)."""
        # Allpass filters have unity magnitude response, so return 0 dB
        # Phase is affected by invert, but we're only showing magnitude here
        return np.zeros_like(freq)
    
    def _calc_linkwitz_riley_response(self, freq: np.ndarray, fs: float, f0: float, 
                                      order: int, is_lowpass: bool) -> np.ndarray:
        """Calculate Linkwitz-Riley crossover filter response."""
        # Linkwitz-Riley is Butterworth^2
        w0 = 2 * np.pi * f0
        w = 2 * np.pi * freq
        
        if is_lowpass:
            H = 1.0 / (1.0 + (w / w0) ** order)
        else:  # highpass
            H = (w / w0) ** order / (1.0 + (w / w0) ** order)
        
        return 20 * np.log10(np.maximum(H, 1e-10))
    
    def _calc_butterworth_response(self, freq: np.ndarray, fs: float, f0: float, 
                                   order: int, is_lowpass: bool) -> np.ndarray:
        """Calculate Butterworth filter response."""
        w0 = 2 * np.pi * f0
        w = 2 * np.pi * freq
        
        if is_lowpass:
            H = 1.0 / np.sqrt(1.0 + (w / w0) ** (2 * order))
        else:  # highpass
            H = 1.0 / np.sqrt(1.0 + (w0 / w) ** (2 * order))
        
        return 20 * np.log10(np.maximum(H, 1e-10))
    
    def _get_filter_label(self) -> str:
        """Generate a descriptive label for the current filter."""
        # Get filterset name
        filterset_name = ""
        if item := self.filterset_list.currentItem():
            filterset_name = f" [{item.text()}]"
        
        if self._active_filter == "peq":
            return f"PEQ{filterset_name}: {self.peq_freq.value():.1f} Hz, Q={self.peq_q.value():.2f}, A={self.peq_a.value():.1f} dB"
        elif self._active_filter == "shelf":
            shelf_type = "Low" if self.shelf_low.isChecked() else "High"
            return f"{shelf_type} Shelf{filterset_name}: {self.shelf_freq.value():.1f} Hz, Q={self.shelf_q.value():.2f}, A={self.shelf_a.value():.1f} dB"
        elif self._active_filter == "allpass":
            return f"Allpass{filterset_name}: {self.allpass_freq.value():.1f} Hz, Q={self.allpass_q.value():.2f}"
        elif self._active_filter == "linkwitz-riley":
            order = self.lr_order_group.checkedId()
            mode = "Lowpass" if self.lr_lowpass.isChecked() else "Highpass"
            return f"Linkwitz-Riley {order}{filterset_name}: {self.lr_freq.value():.1f} Hz, {mode}"
        elif self._active_filter == "butterworth":
            order = self.bw_order_group.checkedId()
            mode = "Lowpass" if self.bw_lowpass.isChecked() else "Highpass"
            return f"Butterworth {order}{filterset_name}: {self.bw_freq.value():.1f} Hz, {mode}"
        return "Filter"
