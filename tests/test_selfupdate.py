# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from ultrebo import selfupdate, updater
from ultrebo.selfupdate import InstallTarget, UpdateError
from ultrebo.updater import Asset, Update

PREFIX = updater.DOWNLOAD_PREFIX


def release(assets, tag="v0.2.0"):
    return json.dumps({"tag_name": tag, "html_url": "https://github.com/Ultrevo/Ultrebo-pc/releases/tag/" + tag, "assets": assets})


def asset_json(name="Ultrebo-v0.2.0-windows-x64.zip", url=None, digest="sha256:" + "a" * 64, size=1000):
    return {"name": name, "browser_download_url": url or PREFIX + "v0.2.0/" + name, "digest": digest, "size": size}


# ------------------------------------------------------------------ finding the right release file

def test_the_right_file_is_picked_for_each_system():
    assets = [asset_json("Ultrebo-v0.2.0-macos-intel.zip"), asset_json("Ultrebo-v0.2.0-windows-x64.zip"),
              asset_json("Ultrebo-v0.2.0-macos-apple-silicon.zip")]
    body = release(assets)
    assert updater.parse_release(body, "0.1.0", "windows-x64").asset.name.endswith("windows-x64.zip")
    assert updater.parse_release(body, "0.1.0", "macos-intel").asset.name.endswith("macos-intel.zip")
    assert updater.parse_release(body, "0.1.0", "macos-apple-silicon").asset.name.endswith("apple-silicon.zip")
    assert updater.parse_release(body, "0.1.0", None).asset is None  # a system with no build: release page only
    assert updater.parse_release(body, "0.1.0", "windows-x64").asset.sha256 == "a" * 64


@pytest.mark.parametrize("bad", [
    asset_json(url="https://evil.example/Ultrebo-v0.2.0-windows-x64.zip"),
    asset_json(url="http://github.com/Ultrevo/Ultrebo-pc/releases/download/v0/x-windows-x64.zip"),
    asset_json(url="https://github.com/someone-else/repo/releases/download/v0/Ultrebo-windows-x64.zip"),
    asset_json(digest="sha256:short"),
    asset_json(digest="md5:" + "a" * 32),
    asset_json(digest=None),
    asset_json(size=0),
    asset_json(size=updater.MAX_DOWNLOAD_BYTES + 1),
    asset_json(name="Ultrebo-v0.2.0-windows-x64.exe"),
])
def test_untrusted_or_incomplete_assets_mean_no_self_update(bad):
    update = updater.parse_release(release([bad]), "0.1.0", "windows-x64")
    assert update is not None and update.asset is None  # still told about the update, just not self-installed


def test_odd_asset_lists_are_ignored():
    for assets in (None, "x", [1, 2], [{"name": 3}]):
        body = json.dumps({"tag_name": "v0.2.0", "html_url": "https://github.com/Ultrevo/Ultrebo-pc/x", "assets": assets})
        assert updater.parse_release(body, "0.1.0", "windows-x64").asset is None


def test_platform_key(monkeypatch):
    cases = [("win32", "AMD64", "windows-x64"), ("win32", "ARM64", None), ("darwin", "arm64", "macos-apple-silicon"),
             ("darwin", "x86_64", "macos-intel"), ("linux", "x86_64", None)]
    for plat, machine, expected in cases:
        monkeypatch.setattr(sys, "platform", plat)
        monkeypatch.setattr(updater.platform, "machine", lambda m=machine: m)
        assert updater.platform_key() == expected


# --------------------------------------------------------------------------------- downloading

@pytest.fixture
def server(tmp_path):
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield tmp_path, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def make_asset(server, data=b"x" * 300_000, name="file.zip"):
    folder, base = server
    (folder / name).write_bytes(data)
    return Asset(name, f"{base}/{name}", hashlib.sha256(data).hexdigest(), len(data))


def test_download_checks_the_checksum(server, tmp_path):
    asset = make_asset(server)
    seen = []
    selfupdate.download(asset, tmp_path / "out.zip", lambda d, t: seen.append((d, t)))
    assert (tmp_path / "out.zip").read_bytes() == b"x" * 300_000
    assert seen[-1] == (300_000, 300_000)


def test_wrong_checksum_size_or_cancel_are_refused(server, tmp_path):
    good = make_asset(server)
    with pytest.raises(UpdateError, match="checksum"):
        selfupdate.download(Asset(good.name, good.url, "0" * 64, good.size), tmp_path / "a.zip")
    with pytest.raises(UpdateError, match="larger than expected"):
        selfupdate.download(Asset(good.name, good.url, good.sha256, good.size - 10), tmp_path / "b.zip")
    with pytest.raises(UpdateError, match="checksum"):
        selfupdate.download(Asset(good.name, good.url, good.sha256, good.size + 10), tmp_path / "c.zip")
    with pytest.raises(UpdateError, match="cancelled"):
        selfupdate.download(good, tmp_path / "d.zip", cancelled=lambda: True)
    with pytest.raises(UpdateError, match="download failed"):
        selfupdate.download(Asset("x.zip", "http://127.0.0.1:9/x.zip", "0" * 64, 5), tmp_path / "e.zip", timeout=1)


# ------------------------------------------------------------------------------------ unpacking

def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def test_unpack_windows_zip(tmp_path):
    z = make_zip(tmp_path / "u.zip", {"Ultrebo/Ultrebo.exe": b"new", "Ultrebo/_internal/lib.dll": b"dll"})
    staged = selfupdate._unpack(z, tmp_path / "stage", "windows")
    assert (staged / "Ultrebo.exe").read_bytes() == b"new" and (staged / "_internal" / "lib.dll").exists()


def test_unpack_refuses_files_that_are_not_ultrebo_and_path_tricks(tmp_path):
    with pytest.raises(UpdateError, match="doesn't look like Ultrebo"):
        selfupdate._unpack(make_zip(tmp_path / "a.zip", {"Other/readme.txt": b"x"}), tmp_path / "s1", "windows")
    with pytest.raises(UpdateError, match="could not be unpacked"):
        selfupdate._unpack(tmp_path / "missing.zip", tmp_path / "s2", "windows")
    tricky = make_zip(tmp_path / "t.zip", {"Ultrebo/Ultrebo.exe": b"x", "../escaped.txt": b"bad"})
    selfupdate._unpack(tricky, tmp_path / "s3", "windows")
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path.parent / "escaped.txt").exists()


def test_prepare_downloads_checks_and_unpacks(server, tmp_path, monkeypatch):
    folder, base = server
    zip_path = make_zip(folder / "Ultrebo-v0.2.0-windows-x64.zip", {"Ultrebo/Ultrebo.exe": b"new"})
    data = zip_path.read_bytes()
    asset = Asset(zip_path.name, f"{base}/{zip_path.name}", hashlib.sha256(data).hexdigest(), len(data))
    install = tmp_path / "installed" / "Ultrebo"
    install.mkdir(parents=True)
    monkeypatch.setattr(selfupdate, "install_target", lambda: InstallTarget("windows", install))
    prepared = selfupdate.prepare(Update("0.2.0", "https://github.com/x", asset))
    assert (prepared.staged / "Ultrebo.exe").read_bytes() == b"new" and prepared.target == install
    assert prepared.kind == "windows"

    bad = Asset(asset.name, asset.url, "0" * 64, asset.size)
    with pytest.raises(UpdateError):
        selfupdate.prepare(Update("0.2.0", "u", bad))


def test_prepare_refuses_without_an_asset_or_install(monkeypatch):
    monkeypatch.setattr(selfupdate, "install_target", lambda: None)
    with pytest.raises(UpdateError, match="can't update itself"):
        selfupdate.prepare(Update("0.2.0", "u", Asset("a.zip", "u", "0" * 64, 5)))
    assert selfupdate.can_update(Update("0.2.0", "u")) is False


def test_running_from_source_never_self_updates():
    assert selfupdate.install_target() is None  # not a frozen build


# ---------------------------------------------------------- the helper that swaps the files in

def finished_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def build_tree(tmp_path, bundle_name):
    target = tmp_path / "install" / bundle_name
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old")
    (target / "keep.txt").write_text("old version of a shared file")
    staging = tmp_path / "install" / ".ultrebo-update-x"
    staged = staging / bundle_name
    staged.mkdir(parents=True)
    (staged / "keep.txt").write_text("new version")
    (staged / "added.txt").write_text("new")
    return target, staging, staged


def wait_for(path, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not path.exists():
        time.sleep(0.1)
    return path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the Mac helper is a bash script")
def test_mac_helper_swaps_the_app_and_reopens_it(tmp_path):
    target, staging, staged = build_tree(tmp_path, "Ultrebo.app")
    marker = tmp_path / "relaunched"
    script = tmp_path / "update.sh"
    script.write_text(selfupdate.mac_script(finished_pid(), staged, target, staging, tmp_path / "log.txt", f"touch {marker}"))
    subprocess.run(["/bin/bash", str(script)], check=True, timeout=30)
    assert wait_for(marker)
    assert (target / "added.txt").exists() and (target / "keep.txt").read_text() == "new version"
    assert not (target / "old.txt").exists()  # a whole-app swap, like replacing it by hand
    assert not (tmp_path / "install" / "Ultrebo.app.ultrebo-old").exists() and not staging.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the Mac helper is a bash script")
def test_mac_helper_puts_the_old_app_back_if_the_swap_fails(tmp_path):
    target, staging, staged = build_tree(tmp_path, "Ultrebo.app")
    marker, log = tmp_path / "relaunched", tmp_path / "log.txt"
    script = tmp_path / "update.sh"
    missing = tmp_path / "does-not-exist"
    script.write_text(selfupdate.mac_script(finished_pid(), missing, target, staging, log, f"touch {marker}"))
    subprocess.run(["/bin/bash", str(script)], check=True, timeout=30)
    assert (target / "old.txt").read_text() == "old"  # untouched
    assert "could not be moved into place" in log.read_text() and wait_for(marker)


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows helper is a batch file")
def test_windows_helper_copies_the_new_files_over_and_reopens(tmp_path):
    target, staging, staged = build_tree(tmp_path, "Ultrebo")
    marker = tmp_path / "relaunched.txt"
    script = tmp_path / "update.bat"
    script.write_text(selfupdate.windows_script(finished_pid(), staged, target, staging, tmp_path / "log.txt", f'echo done > "{marker}"'))
    subprocess.run(["cmd", "/c", str(script)], check=True, timeout=60)
    assert wait_for(marker)
    assert (target / "added.txt").exists() and (target / "keep.txt").read_text() == "new version"
    assert (target / "old.txt").exists()  # files are copied over the old ones, nothing is deleted
    assert not staging.exists()


# ------------------------------------------------------------------ the update check explains itself

def test_check_detailed_reports_what_it_found_or_why_it_failed(monkeypatch):
    class Reply:
        status = 200

        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    body = release([asset_json()])
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: Reply(body))
    monkeypatch.setattr(updater, "platform_key", lambda: "windows-x64")
    result = updater.check_detailed("0.1.0")
    assert result.error is None and result.latest == "0.2.0" and result.update.version == "0.2.0"
    assert updater.check_detailed("0.2.0").update is None and updater.check_detailed("0.2.0").latest == "0.2.0"
    assert updater.check("0.1.0").version == "0.2.0"

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: Reply("not json"))
    assert "not what Ultrebo expected" in updater.check_detailed("0.1.0").error

    def boom(*a, **k):
        raise OSError("certificate verify failed")

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    result = updater.check_detailed("0.1.0")
    assert result.update is None and "certificate verify failed" in result.error
    assert updater.check("0.1.0") is None  # the quiet version still never raises


def test_check_update_command_line_reports_ok_and_failures(monkeypatch, tmp_path, capsys):
    from ultrebo import app

    fine = updater.CheckResult(Update("0.2.0", "https://github.com/x", Asset("a.zip", PREFIX + "a.zip", "a" * 64, 5)), "0.2.0")
    monkeypatch.setattr(updater, "check_detailed", lambda v: fine)
    monkeypatch.setattr(updater, "platform_key", lambda: "windows-x64")
    report = tmp_path / "r.txt"
    assert app.check_update_cli(report) == 0 and "ok latest=0.2.0 download=a.zip" in report.read_text()

    monkeypatch.setattr(updater, "check_detailed", lambda v: updater.CheckResult(None, error="OSError: no route"))
    assert app.check_update_cli(None) == 1 and "FAILED OSError: no route" in capsys.readouterr().out

    no_download = updater.CheckResult(Update("0.2.0", "https://github.com/x"), "0.2.0")
    monkeypatch.setattr(updater, "check_detailed", lambda v: no_download)
    assert app.check_update_cli(None) == 1 and "no download for windows-x64" in capsys.readouterr().out
