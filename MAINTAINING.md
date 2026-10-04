# Maintaining Ultrebo (desktop)

Notes for the maintainer. Not needed to use the app.

## Running from source

```
git clone https://github.com/Ultrevo/Ultrebo-pc
cd Ultrebo-pc
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pip uninstall -y opencv-python && pip install --force-reinstall --no-deps opencv-python-headless
python -m ultrebo
python -m pytest
```

On Linux it runs from source on X11 (Wayland blocks the kind of input control Ultrebo needs); there is no packaged Linux build.

```
src/ultrebo/
  model.py      Macro, Step and rule data (saved as JSON)
  runner.py     Sequence/reactive loops and the rules watcher
  recorder.py   Turns recorded input into steps
  imagematch.py, textmatch.py, ocr.py   Finding pictures and words on the screen
  inputs.py, screen.py, monitors.py, hotkeys.py   Mouse/keyboard, screenshots, monitor choice, global hotkeys
  ui/           The Qt interface
packaging/      PyInstaller recipe
```

## Building the app

```
pip install pyinstaller
pyinstaller --noconfirm --clean packaging/ultrebo.spec
dist/Ultrebo/Ultrebo --selftest        # checks image and text recognition work in the build
```

Every push also builds Windows and macOS test builds on GitHub: open the run under **Actions** and download the
**Ultrebo-test-build** artifacts.

## Releasing

On GitHub, **Releases > Draft a new release**, create a tag such as `v0.1.0`, **Publish**. The *Release builds* workflow
runs the tests, builds the Windows and macOS apps and attaches them to that release. The tag becomes the version.

The builds are unsigned. For fewer warnings, sign the Windows build (for example with [SignPath](https://signpath.org/),
free for open source) and notarise the Mac build with an Apple Developer ID.
