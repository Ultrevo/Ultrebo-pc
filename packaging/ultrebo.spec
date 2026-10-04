# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
# PyInstaller recipe. Build with:  pyinstaller --noconfirm --clean packaging/ultrebo.spec
import os
import sys

from PyInstaller.utils.hooks import collect_all

here = SPECPATH  # noqa: F821 - provided by PyInstaller
root = os.path.abspath(os.path.join(here, ".."))
assets = os.path.join(root, "src", "ultrebo", "assets")

datas = [(assets, "ultrebo/assets")]
binaries = []
hiddenimports = []
for package in ("rapidocr_onnxruntime", "onnxruntime"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

if sys.platform == "win32":
    hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32"]
elif sys.platform == "darwin":
    hiddenimports += ["pynput.keyboard._darwin", "pynput.mouse._darwin"]
else:
    hiddenimports += ["pynput.keyboard._xorg", "pynput.mouse._xorg"]

a = Analysis(  # noqa: F821
    [os.path.join(here, "launcher.py")],
    pathex=[os.path.join(root, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick"],
)
pyz = PYZ(a.pure)  # noqa: F821

icon = os.path.join(assets, "icon.ico" if sys.platform == "win32" else "icon.png")
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ultrebo",
    console=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Ultrebo")  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="Ultrebo.app",
        icon=os.path.join(assets, "icon.png"),
        bundle_identifier="com.ultrevo.ultrebo",
        info_plist={
            "CFBundleName": "Ultrebo",
            "CFBundleDisplayName": "Ultrebo",
            "NSHighResolutionCapable": True,
            "NSScreenCaptureUsageDescription": "Ultrebo looks at the screen to find images and text for your macros.",
        },
    )
