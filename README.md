# Ultrebo for desktop

[![CI](https://github.com/Ultrevo/Ultrebo-pc/actions/workflows/ci.yml/badge.svg)](https://github.com/Ultrevo/Ultrebo-pc/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

**Website:** https://ultrevo.github.io/Ultrebo/  -  **Discord:** https://discord.gg/mAKGfaAWWW  -  **Android version:** https://github.com/Ultrevo/Ultrebo

Ultrebo records your **mouse clicks, drags, scrolling and key presses**, lets you edit every step, and replays them in a loop.
It can also **look for a picture or for words on your screen** and react to them. It is built for repetitive game
tasks such as tower-defense farming, and works with any program on Windows and macOS.

- **Record** your input with the pauses between it, then edit each step: position, wait, repeat, priority, on/off, test one step.
- **Priority order.** Lower number runs first; reorder with Up and Down.
- **Two run modes.** *Sequence* runs everything in order, looped. *Reactive* runs only the highest-priority step whose condition is met.
- **Find image.** Drag a box over your screen to pick a picture; Ultrebo clicks it whenever it appears.
- **Find text.** Type words such as `I'm here`; Ultrebo reads the screen (offline) and clicks them when they show up.
- **Pop-up watcher.** Steps marked *Always watching* check the screen in the background while your macro runs. When one
  appears the macro can **pause and carry on**, or **restart from the first step**.
- **Global hotkeys** that work while a game has focus: **F8** starts/stops, **F9** records (changeable in Settings).
- **Private.** No accounts, no analytics. Macros and screenshots stay on your computer. The only network use is an
  optional check on GitHub for a newer version.

> **Use responsibly.** Many games forbid automation in their terms of service and may suspend accounts that use it.
> Ultrebo does not hide itself or avoid detection. You are responsible for how you use it.

## Download

Get the latest build from the [Releases page](../../releases/latest):

| System | File |
| --- | --- |
| Windows 10 / 11 | `Ultrebo-v…-windows-x64.zip` |
| macOS, Apple silicon (M1 and newer) | `Ultrebo-v…-macos-apple-silicon.zip` |
| macOS, Intel | `Ultrebo-v…-macos-intel.zip` (if listed) |

### Windows

1. Unzip the file anywhere (for example your Desktop) and open the `Ultrebo` folder.
2. Double-click `Ultrebo.exe`.
3. Windows may show **"Windows protected your PC"** because the app isn't signed with a paid certificate. Click
   **More info**, then **Run anyway**. Some antivirus programs also flag any program that records keyboard and mouse
   input; Ultrebo only records while you press Record, and its [source code](.) is public.
4. If a game ignores Ultrebo's clicks, right-click `Ultrebo.exe` and choose **Run as administrator**. Windows blocks
   input into programs that run at a higher level than the one sending it.

### macOS

1. Unzip, drag **Ultrebo** into your **Applications** folder, then **right-click it and choose Open** (the first time
   only). If macOS says it can't verify the app: **System Settings > Privacy & Security > Open Anyway**.
   Advanced alternative: `xattr -dr com.apple.quarantine /Applications/Ultrebo.app`
2. macOS asks for three permissions before an app may control or watch your computer. Ultrebo's **Get started**
   card shows what is missing, with a button for each. In **System Settings > Privacy & Security** switch Ultrebo on under:
   - **Accessibility** (to click and press keys),
   - **Input Monitoring** (to record, and for the hotkeys),
   - **Screen Recording** (only for image and text steps).
3. Quit and reopen Ultrebo after switching permissions on.

### Linux

Not packaged yet. It runs from source on X11 (see below); Wayland blocks the kind of input control Ultrebo needs.

## Quick start

1. Click **New** to make a macro.
2. Click **Add step > Record inputs** (or press **F9**). The window minimises. Do the clicks and key presses you want
   in your game, then press **F9** again. They appear as steps.
3. Double-click a step to change it. Use **Test** to run just that step.
4. Press **F8** (or **Start**) to run the macro. Press **F8** again to stop. **F8** is your safety brake, so
   check it works before you leave a macro running.

Tips: play in **windowed mode**, and don't move or resize the game window between recording and running,
because clicks are recorded as screen positions.

### Several monitors

Image and text steps watch one monitor at a time. Choose it in **Settings > Monitor to watch** (use **Show numbers** to see which
is which). *Pick image from screen* shows that monitor too. Clicks and drags use the exact screen position you recorded, so keep
your game on the monitor you chose, and re-record if you move it.

### Find image and Find text

- **Find image:** *Add step > Find image*, then **Pick image from screen**. Ultrebo hides its window and shows your screen;
  drag a box around the button or icon. Crop tightly around something distinctive. Raise the match threshold if it clicks the wrong
  thing; lower it if it misses.
- **Find text:** *Add step > Find text* and type the words. Capital letters, spaces and punctuation are ignored. *Match strictness* controls
  how many misread letters are forgiven (0.8 allows about one wrong letter in six). It reads Latin letters and numbers (English and similar).
- **Search area:** for either, you can pick a smaller area of the screen to search. It's faster and more accurate.
- **Click it when found** can be switched off to make a step that only *waits* for something to appear.

### Pop-up watcher

Turn on **Always watching** for an image or text step. It checks the screen in the background for the whole run, even
while your other steps are busy. When its target appears:

- **Pause, then carry on:** the main macro pauses between actions, the watcher clicks the target, waits the time you set, and the macro continues.
- **Restart macro from the start:** the macro stops, the watcher (optionally) clicks, waits, then the macro starts again from step 1.

A macro with only watchers just sits and watches until you stop it. *Settings > Look at the screen every* controls how often the screen is checked.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Clicks land in the wrong place | Don't move or resize the game window after recording. On Windows, keep display scaling the same as when you recorded. Re-record if in doubt. |
| A game ignores the clicks (Windows) | Run Ultrebo as administrator. Some games with anti-cheat block simulated input entirely; nothing here works around that. |
| Nothing happens on a Mac | Check Accessibility and Input Monitoring are on for Ultrebo, then restart it. |
| Image is never found | Re-pick it, lower the threshold (try 0.75), and make sure you recorded it at the same window size. |
| Text is never found | Lower *Match strictness* (try 0.7), or use *Find image* for stylised game fonts. |
| Hotkeys do nothing | Pick different keys in *Settings*; on a Mac check Input Monitoring. |
| The computer gets busy | Make *Look at the screen every* longer (for example 2000 ms) and use a search area. |

## Privacy

Everything runs on your computer. Macros and cropped images are stored in your user folder
(`%APPDATA%\Ultrebo` on Windows, `~/Library/Application Support/Ultrebo` on a Mac). Screenshots are examined in memory and thrown away;
the only picture saved is the box you crop. Text recognition (RapidOCR) is bundled and runs offline.
The one network request is the optional update check against GitHub (switch it off in *Settings*).

**Recording captures every key you press until you stop it**, so don't type passwords while recording.

## Run from source

```
git clone https://github.com/Ultrevo/Ultrebo-pc
cd Ultrebo-pc
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pip uninstall -y opencv-python && pip install --force-reinstall --no-deps opencv-python-headless
python -m ultrebo
python -m pytest
```

Build a downloadable app yourself with `pip install pyinstaller && pyinstaller --noconfirm --clean packaging/ultrebo.spec`.

```
src/ultrebo/
  model.py      Macro and Step data (saved as JSON)
  runner.py     Sequence/reactive loops and the pop-up watcher
  recorder.py   Turns recorded input into steps
  imagematch.py, textmatch.py, ocr.py   Finding pictures and words on the screen
  inputs.py, screen.py, hotkeys.py      Mouse/keyboard, screenshots, global hotkeys
  ui/           The Qt interface
```

## Releasing (maintainers)

On GitHub, **Releases > Draft a new release**, create a tag such as `v0.1.0`, **Publish**. The *Release builds* workflow runs the tests,
builds the Windows and macOS apps and attaches them to that release. The builds are unsigned: for fewer warnings, sign the
Windows build (for example with [SignPath](https://signpath.org/), free for open source) and notarise the Mac build with an Apple Developer ID.

## Support Ultrebo

Ultrebo is free. If it saves you time you can optionally chip in, on the **Ethereum network** (ETH, or USDT/USDC on Ethereum):

```
0x108484e1744Fd6ED22288411B9596390E76CD5b2
```

Double-check the address and the network before sending; crypto payments can't be reversed. There is no obligation, and nothing is locked behind it.

## License and credits

[GPL-3.0](LICENSE), copyright (C) 2026 Ultrevo. Anyone may use, study and modify this program, but copies and modified
versions must stay open source under the same licence and keep the copyright notice. Bundled libraries are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Ultrebo is designed, directed, tested and maintained by Ultrevo. Much of the code was written with the help of an
AI assistant (Claude, by Anthropic).
