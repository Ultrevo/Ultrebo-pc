# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
# PyInstaller recipe. Build with:  pyinstaller --noconfirm --clean packaging/ultrebo.spec
import os
import re
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


def windows_version_file() -> str | None:
    """The details Windows shows under the exe's Properties > Details (name, company, version).

    An exe with none of these looks anonymous, which makes antivirus programs more suspicious of it.
    """
    if sys.platform != "win32":
        return None
    with open(os.path.join(root, "src", "ultrebo", "__init__.py"), encoding="utf-8") as f:
        version = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)
    numbers = (tuple(int(p) for p in re.findall(r"\d+", version)) + (0, 0, 0, 0))[:4]
    text = (
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([StringTable('040904B0', [\n"
        "      StringStruct('CompanyName', 'Ultrevo'),\n"
        "      StringStruct('FileDescription', 'Ultrebo - macro recorder and player'),\n"
        f"      StringStruct('FileVersion', '{version}'),\n"
        "      StringStruct('InternalName', 'Ultrebo'),\n"
        "      StringStruct('LegalCopyright', 'Copyright (C) 2026 Ultrevo. GPL-3.0'),\n"
        "      StringStruct('OriginalFilename', 'Ultrebo.exe'),\n"
        "      StringStruct('ProductName', 'Ultrebo'),\n"
        f"      StringStruct('ProductVersion', '{version}')])]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    )
    out = os.path.join(root, "build", "version_info.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return out


exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ultrebo",
    console=False,
    icon=icon,
    version=windows_version_file(),
    upx=False,  # packed programs are flagged far more often
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
