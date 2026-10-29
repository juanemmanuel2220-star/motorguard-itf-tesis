# Receta de PyInstaller para el paquete autónomo (se ejecuta dentro del contenedor de construcción, con el
# código montado en /src). Solo entran los módulos de la app nueva: las pruebas, las herramientas y el código
# anterior quedan fuera.
# -*- mode: python ; coding: utf-8 -*-

SRC = "/src/motorguard_dashboard"

a = Analysis(
    [f"{SRC}/app.py"],
    pathex=["/src"],
    datas=[(f"{SRC}/ui/fuentes", "motorguard_dashboard/ui/fuentes"),
           (f"{SRC}/ui/recursos", "motorguard_dashboard/ui/recursos"),
           (f"{SRC}/rag/datos", "motorguard_dashboard/rag/datos")],       # extracto de resultados de la tesis
    hiddenimports=["PySide6.QtSvg", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtDBus",
                   # keyring elige su backend por entry points: se incluyen explícitamente
                   "keyring.backends.SecretService", "keyring.backends.chainer", "keyring.backends.fail",
                   "keyring.backends.null"],
    excludes=["tkinter", "matplotlib", "PIL", "IPython",
              "motorguard_dashboard.tests", "motorguard_dashboard.herramientas",
              "motorguard_dashboard.acquisition", "motorguard_dashboard.processing", "motorguard_dashboard.core",
              "motorguard_dashboard.ui.widgets", "motorguard_dashboard.ui.main_window", "motorguard_dashboard.ui.styles",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="motorguard-itf", console=False,
          strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="motorguard-itf")
