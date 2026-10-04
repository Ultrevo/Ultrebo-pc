# Third-party software

Ultrebo's downloadable builds bundle these open-source libraries. Each keeps its own licence.

| Library | Used for | Licence |
| --- | --- | --- |
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/) | The user interface | LGPL-3.0 |
| [pynput](https://github.com/moses-palmer/pynput) | Recording and sending mouse/keyboard input, global hotkeys | LGPL-3.0 |
| [OpenCV](https://opencv.org/) (`opencv-python-headless`) | Finding images on screen | Apache-2.0 |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) and its recognition models | Finding text on screen (runs offline) | Apache-2.0 |
| [ONNX Runtime](https://onnxruntime.ai/) | Running the text-recognition model | MIT |
| [mss](https://github.com/BoboTiG/python-mss) | Screen capture | MIT |
| [NumPy](https://numpy.org/) | Image arrays | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | Icon handling | HPND |
| [PyInstaller](https://pyinstaller.org/) | Packaging the builds | GPL-2.0 with a bootloader exception |

Because Qt for Python and pynput are LGPL, you may replace them with your own builds: Ultrebo's source is
available at <https://github.com/Ultrevo/Ultrebo-pc> and can be run directly with Python.
