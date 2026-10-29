"""
Sistema de diseño y hojas de estilo QSS para la estación MotorGuard-ITF.
Basado en principios de diseño de alta legibilidad, estética Dark Mission-Control y contraste WCAG AA.
"""

# Paleta de colores Dark Theme
COLOR_BG_DARK = "#090d16"          # Fondo de ventana principal
COLOR_SURFACE = "#131b2e"          # Tarjetas y paneles
COLOR_SURFACE_ALT = "#1c263f"      # Superficie elevada / hover
COLOR_BORDER = "#283556"           # Bordes sutiles
COLOR_TEXT_PRIMARY = "#f8fafc"     # Texto principal de alto contraste
COLOR_TEXT_MUTED = "#94a3b8"       # Texto secundario / etiquetas
COLOR_ACCENT = "#38bdf8"           # Acento cian primario

# Semáforos y estados
COLOR_SUCCESS = "#10b981"          # Verde normal
COLOR_WARNING = "#f59e0b"          # Amarillo transición
COLOR_DANGER = "#ef4444"           # Rojo falla ITF
COLOR_PURPLE = "#8b5cf6"           # Púrpura calibración

DARK_STYLESHEET = """
QMainWindow {
    background-color: #090d16;
    color: #f8fafc;
    font-family: 'Segoe UI', 'Ubuntu', 'Helvetica Neue', sans-serif;
}

QWidget {
    background-color: #090d16;
    color: #f8fafc;
    font-size: 13px;
}

QGroupBox {
    background-color: #131b2e;
    border: 1px solid #283556;
    border-radius: 8px;
    margin-top: 24px;
    padding: 12px;
    font-weight: 600;
    font-size: 13px;
    color: #38bdf8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 4px;
    padding: 2px 8px;
    background-color: #1c263f;
    border: 1px solid #283556;
    border-radius: 4px;
    color: #38bdf8;
}

/* Botones genéricos */
QPushButton {
    background-color: #1c263f;
    border: 1px solid #283556;
    border-radius: 6px;
    color: #f8fafc;
    padding: 7px 14px;
    font-weight: 500;
    font-size: 13px;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #283556;
    border-color: #38bdf8;
}

QPushButton:pressed {
    background-color: #0f172a;
}

QPushButton:disabled {
    background-color: #131b2e;
    color: #475569;
    border-color: #1e293b;
}

/* Botones semánticos especiales */
QPushButton#btn_carga {
    background-color: #1d4ed8;
    border-color: #3b82f6;
    font-weight: 600;
}
QPushButton#btn_carga:hover {
    background-color: #2563eb;
}

QPushButton#btn_falla {
    background-color: #c2410c;
    border-color: #ea580c;
    font-weight: 600;
}
QPushButton#btn_falla:hover {
    background-color: #ea580c;
}

QPushButton#btn_severidad {
    background-color: #b91c1c;
    border-color: #dc2626;
    font-weight: 600;
}
QPushButton#btn_severidad:hover {
    background-color: #dc2626;
}

QPushButton#btn_sano {
    background-color: #047857;
    border-color: #059669;
    font-weight: 600;
}
QPushButton#btn_sano:hover {
    background-color: #059669;
}

QPushButton#btn_baseline {
    background-color: #6d28d9;
    border-color: #7c3aed;
    font-weight: 600;
}
QPushButton#btn_baseline:hover {
    background-color: #7c3aed;
}

QPushButton#btn_record {
    background-color: #991b1b;
    border-color: #ef4444;
    font-weight: 600;
}
QPushButton#btn_record:hover {
    background-color: #dc2626;
}

QPushButton#btn_stop_record {
    background-color: #334155;
    border-color: #64748b;
    font-weight: 600;
}

/* ComboBox */
QComboBox {
    background-color: #1c263f;
    border: 1px solid #283556;
    border-radius: 6px;
    padding: 6px 12px;
    color: #f8fafc;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #38bdf8;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #283556;
}

QComboBox QAbstractItemView {
    background-color: #131b2e;
    border: 1px solid #283556;
    selection-background-color: #283556;
    color: #f8fafc;
    padding: 4px;
}

/* Tablas */
QTableWidget {
    background-color: #131b2e;
    gridline-color: #1e293b;
    border: 1px solid #283556;
    border-radius: 6px;
    color: #f8fafc;
    font-size: 12px;
    selection-background-color: #1c263f;
}

QHeaderView::section {
    background-color: #1c263f;
    color: #94a3b8;
    padding: 6px;
    border: 1px solid #283556;
    font-weight: 600;
    font-size: 12px;
}

/* Barras de progreso */
QProgressBar {
    border: 1px solid #283556;
    border-radius: 4px;
    background-color: #131b2e;
    text-align: center;
    color: #f8fafc;
    font-size: 11px;
    height: 16px;
}

QProgressBar::chunk {
    background-color: #8b5cf6;
    border-radius: 3px;
}

/* Barra de estado */
QStatusBar {
    background-color: #0f172a;
    border-top: 1px solid #1e293b;
    color: #94a3b8;
    font-size: 12px;
}

/* Badges y Labels especiales */
QLabel#lbl_motor_on {
    background-color: #064e3b;
    color: #34d399;
    border: 1px solid #059669;
    border-radius: 12px;
    padding: 4px 12px;
    font-weight: 700;
    font-size: 12px;
}

QLabel#lbl_motor_off {
    background-color: #1e293b;
    color: #94a3b8;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 4px 12px;
    font-weight: 700;
    font-size: 12px;
}

QLabel#lbl_hw_connected {
    background-color: #064e3b;
    color: #34d399;
    border: 1px solid #059669;
    border-radius: 12px;
    padding: 4px 12px;
    font-weight: 700;
    font-size: 12px;
}

QLabel#lbl_hw_disconnected {
    background-color: #451a03;
    color: #f59e0b;
    border: 1px solid #b45309;
    border-radius: 12px;
    padding: 4px 12px;
    font-weight: 700;
    font-size: 12px;
}
"""
