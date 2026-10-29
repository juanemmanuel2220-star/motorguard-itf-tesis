"""Aplicación Qt compartida por las pruebas (sin pantalla)."""

import os


def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
