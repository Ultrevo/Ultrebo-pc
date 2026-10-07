# Ultrebo for desktop

[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

**Website:** https://ultrevo.github.io/Ultrebo/  -  **Discord:** https://discord.gg/mAKGfaAWWW  -  **Android version:** https://github.com/Ultrevo/Ultrebo

Ultrebo records your **mouse clicks, drags, scrolling and key presses**, lets you edit every step, and replays them in a loop.
It can also **look for a picture or for words on your screen** and react to them. It is built for repetitive game
tasks such as tower-defense farming, and works with any program on Windows and macOS.

- **Record** your mouse and keyboard with the pauses between them, then edit each step: position, wait, repeat, on/off, and a test button for each one.
- **The list order is the run order.** Select a step, type the position you want in **Move to #** and press Enter (or click Move).
- **Select several steps at once** by dragging over them, or Shift-click / Ctrl-click (Ctrl+A selects all). Delete, Duplicate and Move work on everything selected; the Delete key removes them too.
- **Two run modes.** *Sequence* runs everything in order, looped. *Reactive* runs only the first step in the list whose condition is met.
- **Find image.** Drag a box over your screen to pick a picture and Ultrebo clicks it whenever it appears.
- **Find text.** Type words such as `I'm here`. Ultrebo reads the screen on your computer and clicks them when they show up.
- **Rules.** Always-watching detections that handle pop-ups while your macro runs. Add as many as you like.
- **Global hotkeys** that work while a game has focus: **F8** starts/stops, **F9** records (changeable in Settings).
- **Private.** No accounts, no ads, no tracking. Your macros and screenshots stay on your computer.

> **Use responsibly.** Many games forbid automation in their terms of service and may suspend accounts that use it.
> Ultrebo does not hide itself or avoid detection. You are responsible for how you use it.

## Download

Get the latest build from the [Releases page](../../releases/latest):

| System | File |
| --- | --- |
| Windows 10 / 11 | `Ultrebo-v…-windows-x64.zip` |
| macOS, Apple silicon (M1 and newer) | `Ultrebo-v…-macos-apple-silicon.zip` |
| macOS, Intel | `Ultrebo-v…-macos-intel.zip` (not always available) |

### Windows

1. Unzip the file anywhere (for example your Desktop) and open the `Ultrebo` folder.
2. Double-click `Ultrebo.exe`.
3. Windows may show **"Windows protected your PC"** because the app isn't signed with a paid certificate. Click
   **More info**, then **Run anyway**. Some antivirus programs also flag any program that records keyboard and mouse
   input; Ultrebo only records while you press Record, and its source code is public.
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

Not packaged yet. It can run from source on X11 (see [MAINTAINING.md](MAINTAINING.md)); Wayland blocks the kind of input control Ultrebo needs.

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
- **Then start the macro over from the first step** makes the macro go back to step 1 as soon as this step is found (and clicked), instead of carrying on to the next step. It doesn't use up one of your loops. Only used in Sequence mode.

### Rules

Open a macro's **Rules** tab to make always-watching detections. A rule looks for an image or for words and checks the screen
in the background for the whole run, even while your steps are busy. When its target appears:

- **Pause, then carry on:** the main macro pauses between actions, the rule clicks the target (if you left that on), waits the time you set, and the macro continues.
- **Restart macro from the start:** the macro stops, the rule (optionally) clicks, waits, then the macro starts again from step 1.

You can have as many rules as you like in one macro. **If two rules are on screen at the same moment, the one nearer the top of the list
is handled first**; use Up and Down to reorder. The other is handled right after if it is still showing.
A macro with only rules just sits and watches until you stop it. *Settings > Look at the screen every* controls how often the screen is checked.

#### Mouse wiggle

Some games, such as Roblox, only notice the mouse when they see it move, not when the cursor is placed straight onto a spot. So when a rule clicks, Ultrebo
glides the mouse to the target and wiggles it very slightly first. It's on by default; untick **Move the mouse a little before clicking** in a rule if you don't
want it.

On Windows, Ultrebo moves the mouse with real mouse input (not just by placing the cursor), because some games ignore a cursor that was only placed. If a game still doesn't react to the cursor, tell us on Discord which game and what happened.

#### Groups

If several rules are really the same thing, such as three pictures of one pop-up, put them in a **group** (**Groups...** on the Rules tab, then pick the group in each
rule). As soon as one rule in a group is found, the whole group stops being checked. By default that lasts until the macro stops; set a number of seconds
for a pop-up that comes back now and then, and the group starts looking again after that long. Tick **Start checking again when the macro restarts** to have a group wake up on its own whenever the macro restarts: it finishes a loop and starts over (Sequence mode), or a rule set to restart the macro does it. In Reactive mode only a restarting rule counts, because a cycle isn't a restart. Rules with no group are unaffected. Groups are shared along with the rules.

#### Sharing rules with other players

Set your rules up once, then share them: on the **Rules** tab click **Share > Export these rules to a file**. That makes one
`.ultrebo-rules` file (with the pictures inside) in Ultrebo's **Rule packs** folder; **Share > Open the rule packs folder** shows it. Send it to
anyone. They open their own macro's Rules tab and use **Share > Import rules from a file**, and the rules are added at the bottom of their list.

- **Text rules** work on any screen. **Picture rules** match best when the other player has the same screen size and game window size, so they may
  need to pick a picture again.
- The search area isn't shared, because it belongs to one screen.
- Rule packs from the phone version can't be used on a computer, and the other way round.
- **Only import rule packs from people you trust, and check what each rule does:** rules click things on your screen.

Macros made with an older version, where a step was marked "always watching", are converted into rules automatically.

### Screenshots to Discord

Want to know when something is found while you're away? Add a **Discord webhook** and tick **Send a screenshot to Discord when found** on any
Find image or Find text step, or on a rule. Each time it is found, Ultrebo posts a screenshot of the monitor it is watching, with a short message such as
`Ultrebo found "Victory" in "Farm"`, to your channel.

1. In Discord open your channel's **Settings > Integrations > Webhooks > New Webhook** and choose **Copy Webhook URL**.
2. In Ultrebo open **Settings**, paste it into **Discord webhook** and click **Send test** to check it works.

- A step sends at most one screenshot every few seconds, so a rule that keeps matching won't flood the channel. Sending happens in the background and never slows the macro down.
- **Keep the webhook address private:** anyone who has it can post in that channel. It is saved only on your computer and is never included in a shared rules file. Importing rules never turns this on.
- The screenshot shows the whole watched monitor, so it can include anything on screen at that moment.
- If a macro has this ticked but no webhook is set, Ultrebo tells you instead of starting.

## Updating

When a newer version is out, Ultrebo shows an **Update available** message when it opens. Click **Update now**: it downloads the new version
from this project's GitHub release, checks it against GitHub's published checksum, closes, swaps the new files in and opens again. Your macros and
settings are kept, because they're stored separately.

- If Ultrebo is installed somewhere it can't write to (for example `Program Files`), the message offers the release page instead. Download the zip and replace the folder yourself.
- **On a Mac you may need to switch Accessibility, Input Monitoring and Screen Recording back on** after an update, because macOS treats the new, unsigned app as a different program.
- Versions before 0.1.1 only tell you about updates. If you have 0.1.0, download the new version once by hand; after that, Update now works.
- Switch the check off in *Settings*.

## Troubleshooting

### Windows Security says the file contains a virus

Ultrebo isn't code-signed yet, and it records and sends mouse and keyboard input, which can make Windows Security's automatic detection guess wrong about a new program.
If it blocks or deletes `Ultrebo.exe` (for example *Behavior:Win32/DefenseEvasion.A!ml*), it is a false alarm, but check you have the real file first:

1. Download only from this project's [Releases](../../releases) page. Compare the zip's checksum with the `.sha256` file next to it (PowerShell: `Get-FileHash <zip> -Algorithm SHA256`).
2. Make an empty folder such as `C:\Ultrebo`, then add it under **Windows Security > Virus & threat protection > Manage settings > Exclusions > Add an exclusion > Folder**.
3. Unzip into that folder and run `Ultrebo.exe`.

You can also upload the zip to [VirusTotal](https://www.virustotal.com) for a second opinion, or report the false alarm to Microsoft at <https://www.microsoft.com/wdsi/filesubmission>.
The code is open and the downloads are built by GitHub from it, so you can read exactly what runs.

| Problem | Fix |
| --- | --- |
| Something didn't save, or a button did nothing | Look for `error.log` in Ultrebo's data folder (`%APPDATA%\Ultrebo` on Windows) and send it to us on Discord. Ultrebo also tells you if it can't write your macros to disk. |
| F8 (or the record hotkey) does nothing | Each press shows a small notice over the screen: *Running...*, *Stopped*, or *Can't start: why*. **If no notice appears, Windows isn't passing the key to Ultrebo.** That happens when the game or another program runs **as administrator** and Ultrebo doesn't: right-click Ultrebo and choose *Run as administrator*. You can also pick a different key in *Settings*. |
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
Network use: the optional update check against GitHub (switch it off in *Settings*), downloading the new version if you click **Update now**, and, only if you
set a Discord webhook and tick the option on a step or rule, sending a screenshot to that webhook when it is found.

**Recording captures every key you press until you stop it**, so don't type passwords while recording.

## Community and support

Questions, bug reports or ideas? Join the [Discord server](https://discord.gg/mAKGfaAWWW) and open a support ticket, or open an
[issue](../../issues) on GitHub.

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
