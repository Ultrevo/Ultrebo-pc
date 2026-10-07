# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Updates Ultrebo to the latest release by itself.

It downloads this computer's release file from the project's GitHub release, checks it against the
SHA-256 checksum GitHub publishes, unpacks it next to the installed app, then starts a small helper
that waits for Ultrebo to close, swaps the new files in and opens Ultrebo again. Macros and settings
live in a separate folder and are never touched. Anything unexpected means "don't self-update": the
interface falls back to opening the release page.
"""
from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .updater import MAX_DOWNLOAD_BYTES, Asset, Update, ssl_context

WINDOWS_EXE = "Ultrebo.exe"
MAC_APP = "Ultrebo.app"
MAC_BINARY = "Contents/MacOS/Ultrebo"


class UpdateError(Exception):
    """The update could not be installed. The message is safe to show to the user."""


@dataclass(frozen=True)
class InstallTarget:
    kind: str  # "windows" or "mac"
    path: Path  # the Ultrebo folder (Windows) or Ultrebo.app (Mac)


@dataclass(frozen=True)
class PreparedUpdate:
    kind: str
    staged: Path  # the new Ultrebo folder / Ultrebo.app, unpacked and checked
    staging_dir: Path
    target: Path


def install_target() -> InstallTarget | None:
    """Where the running app is installed, or None when it can't update itself (running from source,
    or installed somewhere this user can't write to)."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "win32":
        folder = exe.parent
        if exe.name.lower() == WINDOWS_EXE.lower() and os.access(folder, os.W_OK) and os.access(folder.parent, os.W_OK):
            return InstallTarget("windows", folder)
    elif sys.platform == "darwin":
        bundle = exe.parents[2] if len(exe.parents) > 2 else None
        if bundle is not None and bundle.suffix == ".app" and os.access(bundle.parent, os.W_OK) and os.access(bundle, os.W_OK):
            return InstallTarget("mac", bundle)
    return None


def can_update(update: Update) -> bool:
    return update.asset is not None and install_target() is not None


def download(
    asset: Asset,
    dest: Path,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    timeout: float = 30.0,
) -> None:
    """Download the release file to `dest` and check it against its published SHA-256."""
    request = urllib.request.Request(asset.url, headers={"User-Agent": "Ultrebo"})
    digest = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response, open(dest, "wb") as out:
            limit = asset.size or MAX_DOWNLOAD_BYTES
            total = asset.size or int(response.headers.get("Content-Length") or 0)
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateError("The update was cancelled.")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > limit:
                    raise UpdateError("The downloaded file is larger than expected, so it was thrown away.")
                digest.update(chunk)
                out.write(chunk)
                if progress is not None:
                    progress(done, total or done)
    except UpdateError:
        raise
    except Exception as e:  # noqa: BLE001
        raise UpdateError(f"The download failed: {e}") from e
    if (asset.size and done != asset.size) or digest.hexdigest() != asset.sha256:
        raise UpdateError("The downloaded file didn't match its checksum, so it was thrown away. Please try again.")


def _unpack(zip_path: Path, into: Path, kind: str) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "mac":
            # zipfile would drop the permissions and links a Mac app needs, so use the system tool.
            subprocess.run(["ditto", "-x", "-k", str(zip_path), str(into)], check=True, capture_output=True, timeout=300)
            staged, marker = into / MAC_APP, MAC_BINARY
        else:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(into)  # refuses paths that climb out of the folder
            staged, marker = into / "Ultrebo", WINDOWS_EXE
    except Exception as e:  # noqa: BLE001
        raise UpdateError(f"The update file could not be unpacked: {e}") from e
    if not (staged / marker).exists():
        raise UpdateError("The update file doesn't look like Ultrebo, so it was not installed.")
    return staged


def prepare(
    update: Update,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> PreparedUpdate:
    """Download, verify and unpack the update. Nothing about the installed app changes yet."""
    target = install_target()
    if update.asset is None or target is None:
        raise UpdateError("This copy of Ultrebo can't update itself. Download the new version from the release page.")
    downloads = Path(tempfile.mkdtemp(prefix="ultrebo-download-"))
    # On a Mac the new app is unpacked beside the old one so it can be swapped in with one rename.
    parent = target.path.parent if target.kind == "mac" else Path(tempfile.gettempdir())
    staging = Path(tempfile.mkdtemp(prefix=".ultrebo-update-", dir=parent))
    try:
        zip_path = downloads / update.asset.name
        download(update.asset, zip_path, progress, cancelled)
        staged = _unpack(zip_path, staging, target.kind)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(downloads, ignore_errors=True)
    return PreparedUpdate(target.kind, staged, staging, target.path)


# ---------------------------------------------------------------------------------------------- helper

def windows_script(
    pid: int, staged: Path, target: Path, staging: Path, log: Path, relaunch: str, grace_s: int = 20
) -> str:
    # Every line is run as it is reached (no parenthesised blocks), so the counters below really count.
    # The Windows tools are named in full: on a PC with Git installed, a bare `find` can be Git's own, which is a
    # different program and made this script think Ultrebo had already closed.
    return f"""@echo off
setlocal
title Updating Ultrebo
echo Updating Ultrebo... please wait. It opens again by itself in a moment.
echo Please don't open Ultrebo yourself until then.
echo %date% %time% waiting for Ultrebo to close> "{log}"
set "PID={pid}"
set /a tries=0
:wait
"%SystemRoot%\\System32\\tasklist.exe" /FI "PID eq %PID%" /NH 2>nul | "%SystemRoot%\\System32\\find.exe" "%PID%" >nul
if errorlevel 1 goto copy
set /a tries+=1
if %tries% GTR {grace_s} goto kill
"%SystemRoot%\\System32\\ping.exe" -n 2 127.0.0.1 >nul
goto wait
:kill
echo %date% %time% Ultrebo did not close by itself, closing it>> "{log}"
"%SystemRoot%\\System32\\taskkill.exe" /F /PID %PID% >nul 2>&1
"%SystemRoot%\\System32\\ping.exe" -n 3 127.0.0.1 >nul
:copy
echo %date% %time% copying the new files>> "{log}"
"%SystemRoot%\\System32\\ping.exe" -n 2 127.0.0.1 >nul
set /a attempts=0
:again
set /a attempts+=1
"%SystemRoot%\\System32\\robocopy.exe" "{staged}" "{target}" /E /R:10 /W:1 /NFL /NDL /NJH /NJS /NP >> "{log}" 2>&1
if %ERRORLEVEL% LSS 8 goto copied
echo %date% %time% copy attempt %attempts% failed>> "{log}"
if %attempts% LSS 4 goto again
echo.
echo The new files could not be copied in (something was still using the old ones).
echo Ultrebo will open again as the old version. Download the new version from the release page instead.
echo The update log is here: {log}
echo %date% %time% UPDATE FAILED>> "{log}"
"%SystemRoot%\\System32\\ping.exe" -n 8 127.0.0.1 >nul
goto launch
:copied
echo %date% %time% update installed>> "{log}"
:launch
{relaunch}
rmdir /S /Q "{staging}" >nul 2>&1
"""


def mac_script(pid: int, staged: Path, target: Path, staging: Path, log: Path, relaunch: str) -> str:
    q = shlex.quote
    return f"""#!/bin/bash
PID={pid}
n=0
while kill -0 "$PID" 2>/dev/null; do
  sleep 0.5
  n=$((n+1))
  [ "$n" -gt 240 ] && break
done
sleep 1
OLD={q(str(target) + ".ultrebo-old")}
rm -rf "$OLD"
if mv {q(str(target))} "$OLD"; then
  if mv {q(str(staged))} {q(str(target))}; then
    rm -rf "$OLD"
  else
    mv "$OLD" {q(str(target))}
    echo "The new version could not be moved into place." >> {q(str(log))}
  fi
else
  echo "The old version could not be moved aside." >> {q(str(log))}
fi
xattr -dr com.apple.quarantine {q(str(target))} 2>/dev/null
{relaunch}
rm -rf {q(str(staging))}
"""


def clean_old_leftovers(max_age_s: float = 86400.0) -> int:
    """Delete update folders that earlier attempts left in the temp folder (each holds a whole unpacked copy)."""
    root = Path(tempfile.gettempdir())
    removed = 0
    for pattern in (".ultrebo-update-*", "ultrebo-download-*"):
        try:
            found = list(root.glob(pattern))
        except OSError:
            continue
        for folder in found:
            try:
                if folder.is_dir() and time.time() - folder.stat().st_mtime > max_age_s:
                    shutil.rmtree(folder, ignore_errors=True)
                    removed += 1
            except OSError:
                pass
    return removed


def last_update_problem(max_age_s: float = 1800.0) -> str | None:
    """If the update helper recently reported that it couldn't install the new files, say so (once)."""
    log = Path(tempfile.gettempdir()) / "ultrebo-update.log"
    try:
        if time.time() - log.stat().st_mtime > max_age_s:
            return None
        text = log.read_text(encoding="utf-8", errors="replace")
        if "UPDATE FAILED" not in text:
            return None
        log.replace(log.with_suffix(".seen.log"))  # only tell them once
    except OSError:
        return None
    return (
        "The last update could not be installed, so this is still the old version. "
        "Some files were probably still in use. Please download the new version from the release page "
        f"and unzip it over this one.\n\nThe update log is at:\n{log}"
    )


def apply(prepared: PreparedUpdate) -> None:
    """Start the helper that swaps the new version in once this process has exited, then reopens Ultrebo.

    The caller must close the app right after this returns."""
    log = Path(tempfile.gettempdir()) / "ultrebo-update.log"
    pid = os.getpid()
    if prepared.kind == "windows":
        relaunch = f'start "" "{prepared.target / WINDOWS_EXE}"'
        text = windows_script(pid, prepared.staged, prepared.target, prepared.staging_dir, log, relaunch)
        script = prepared.staging_dir / "update.bat"
        script.write_text(text, encoding="utf-8")
        # A small window of its own, so there is something on screen saying the update is being installed.
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        # The script lives in the staging folder, which it deletes last, so run a copy from the temp folder.
        runner = Path(tempfile.gettempdir()) / f"ultrebo-update-{pid}.bat"
        shutil.copyfile(script, runner)
        subprocess.Popen(["cmd", "/c", str(runner)], creationflags=flags, close_fds=True)
    else:
        relaunch = f"open -n {shlex.quote(str(prepared.target))}"
        text = mac_script(pid, prepared.staged, prepared.target, prepared.staging_dir, log, relaunch)
        runner = Path(tempfile.gettempdir()) / f"ultrebo-update-{pid}.sh"
        runner.write_text(text, encoding="utf-8")
        runner.chmod(0o700)
        subprocess.Popen(["/bin/bash", str(runner)], start_new_session=True, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
