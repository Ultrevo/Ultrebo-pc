# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import io
import json
import threading
import time
import urllib.error

import cv2
import numpy as np
import pytest

from conftest import FakeInput, FakeScreen, wait_until, with_pattern
from ultrebo import notify, rulepack
from ultrebo.model import Macro, Step, StepType, WatchAction
from ultrebo.notify import Notifier
from ultrebo.runner import Runner
from ultrebo.store import MacroStore, Settings

HOOK = "https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyzABCDEF_-0123"


# ------------------------------------------------------------------ the address

@pytest.mark.parametrize("url", [
    HOOK,
    HOOK.replace("discord.com", "discordapp.com"),
    HOOK.replace("discord.com", "ptb.discord.com"),
    HOOK.replace("discord.com", "canary.discord.com"),
    HOOK.replace("/api/", "/api/v10/"),
    f"  {HOOK}  ",
])
def test_real_looking_webhooks_are_accepted(url):
    assert notify.is_valid_webhook(url)


@pytest.mark.parametrize("url", [
    "",
    "not a url",
    HOOK.replace("https", "http"),
    HOOK.replace("discord.com", "example.com"),
    HOOK.replace("discord.com", "discord.com.evil.example"),
    "https://evil.example/https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz",
    HOOK + "/extra",
    HOOK + "?thread_id=1",
    "https://discord.com/api/webhooks/abc/def",
])
def test_anything_else_is_refused_so_screenshots_never_go_elsewhere(url):
    assert not notify.is_valid_webhook(url)
    assert notify.post(url, "hi", None) == "That isn't a Discord webhook address."


# ------------------------------------------------------------------ the message

def test_message_names_cannot_ping_anyone_or_break_the_line():
    body, content_type = notify.build_body('Found "@everyone"\nsecond line', b"\xff\xd8jpegbytes\xff\xd9")
    boundary = content_type.split("boundary=")[1]
    text = body.decode("latin-1")
    assert text.count(f"--{boundary}") == 3 and text.endswith(f"--{boundary}--\r\n")
    payload = json.loads(text.split("\r\n\r\n")[1].split("\r\n--")[0])
    assert payload["allowed_mentions"] == {"parse": []}
    assert "\n" not in payload["content"] and "@everyone" in payload["content"]
    assert b'filename="screenshot.jpg"' in body and b"\xff\xd8jpegbytes\xff\xd9" in body


def test_a_message_without_a_screenshot_has_no_file_part():
    body, _ = notify.build_body("hello", None)
    assert b"files[0]" not in body and b"hello" in body


def test_clean_text_is_one_short_line():
    assert notify.clean_text("a\r\nb\tc\x00d") == "a b c d"
    assert len(notify.clean_text("x" * 5000, 50)) == 50


def test_screenshots_become_small_jpegs():
    image = np.random.default_rng(3).integers(0, 255, size=(1080, 1920, 3), dtype=np.uint8)
    data = notify.encode_screenshot(image)
    assert data[:2] == b"\xff\xd8"
    assert cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape == (1080, 1920, 3)
    huge = np.zeros((3000, 5000, 3), dtype=np.uint8)
    shape = cv2.imdecode(np.frombuffer(notify.encode_screenshot(huge), np.uint8), cv2.IMREAD_COLOR).shape
    assert max(shape[:2]) == notify.MAX_SIDE


# ------------------------------------------------------------------ talking to Discord

class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_post_sends_to_the_webhook_with_a_discord_style_user_agent(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None, context=None):
        seen["url"], seen["agent"], seen["type"] = request.full_url, request.get_header("User-agent"), request.get_header("Content-type")
        return _Response(b"")

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    assert notify.post(HOOK, "hi", b"\xff\xd8x") is None
    assert seen["url"] == HOOK
    assert seen["agent"].startswith("DiscordBot (")  # Discord turns away unnamed Python clients
    assert seen["type"].startswith("multipart/form-data; boundary=")


@pytest.mark.parametrize("code, words", [
    (404, "doesn't exist"), (401, "doesn't exist"), (429, "slow down"), (413, "too big"), (500, "error 500"),
])
def test_post_explains_what_went_wrong(monkeypatch, code, words):
    def fail(request, timeout=None, context=None):
        raise urllib.error.HTTPError(HOOK, code, "x", {}, None)

    monkeypatch.setattr(notify.urllib.request, "urlopen", fail)
    assert words in notify.post(HOOK, "hi", None)


def test_post_reports_being_offline(monkeypatch):
    def fail(request, timeout=None, context=None):
        raise OSError("no route")

    monkeypatch.setattr(notify.urllib.request, "urlopen", fail)
    assert "Couldn't reach Discord" in notify.post(HOOK, "hi", None)


# ------------------------------------------------------------------ the background sender

class Recorder:
    def __init__(self, problem=None, block: threading.Event | None = None):
        self.sent, self.problem, self.block = [], problem, block

    def __call__(self, url, message, jpeg):
        if self.block is not None:
            self.block.wait(5)
        self.sent.append((url, message, jpeg))
        return self.problem


def make_notifier(sender, url=HOOK, clock=None, **kw):
    problems = []
    n = Notifier(lambda: url, on_problem=problems.append, sender=sender, clock=clock or time.monotonic, pause_s=0, **kw)
    return n, problems


IMAGE = np.zeros((20, 30, 3), dtype=np.uint8)


def test_a_queued_screenshot_is_sent_as_a_jpeg():
    rec = Recorder()
    n, problems = make_notifier(rec)
    assert n.send("a", "Found it", IMAGE)
    assert n.wait_until_sent()
    [(url, message, jpeg)] = rec.sent
    assert url == HOOK and message == "Found it" and jpeg[:2] == b"\xff\xd8" and problems == []


def test_nothing_is_sent_without_a_valid_webhook():
    rec = Recorder()
    for url in ("", "https://example.com/hook"):
        n, _ = make_notifier(rec, url=url)
        assert not n.configured() and not n.send("a", "x", IMAGE)
    assert rec.sent == []


def test_one_step_cannot_send_more_than_once_in_a_few_seconds():
    now = [100.0]
    rec = Recorder()
    n, _ = make_notifier(rec, clock=lambda: now[0], min_gap_s=5.0)
    assert n.send("claim", "1", IMAGE)
    assert not n.send("claim", "2", IMAGE)  # same step, too soon
    assert n.send("afk", "3", IMAGE)  # a different step is counted separately
    now[0] += 5.1
    assert n.send("claim", "4", IMAGE)
    assert n.wait_until_sent()
    assert sorted(m for _, m, _ in rec.sent) == ["1", "3", "4"]


def test_a_backed_up_queue_drops_screenshots_instead_of_growing():
    gate = threading.Event()
    rec = Recorder(block=gate)
    n, _ = make_notifier(rec, min_gap_s=0)
    results = [n.send(f"s{i}", str(i), IMAGE) for i in range(notify.MAX_WAITING + 3)]
    gate.set()
    assert n.wait_until_sent()
    assert results.count(False) >= 2 and len(rec.sent) <= notify.MAX_WAITING + 1


def test_problems_are_reported_and_later_sends_still_work():
    calls = []

    def sender(url, message, jpeg):
        calls.append(message)
        if message == "boom":
            raise RuntimeError("bad")
        return "Discord says no." if message == "no" else None

    n, problems = make_notifier(sender, min_gap_s=0)
    n.send("a", "no", IMAGE)
    n.send("b", "boom", IMAGE)
    n.send("c", "fine", IMAGE)
    assert n.wait_until_sent()
    assert calls == ["no", "boom", "fine"]
    assert problems[0] == "Discord says no." and "RuntimeError" in problems[1] and len(problems) == 2


# ------------------------------------------------------------------ settings, packs and the runner

def test_the_webhook_is_saved_in_settings_and_survives_unknown_keys(tmp_path):
    store = MacroStore(tmp_path)
    store.settings.webhook_url = HOOK
    store.save_settings()
    again = MacroStore(tmp_path)
    assert again.settings.webhook_url == HOOK
    assert Settings.from_dict({"webhook_url": 5}).webhook_url == ""
    assert "webhook_url" not in Settings.from_dict({"webhook_url": HOOK, "future": 1}).extra


def test_the_option_is_remembered_with_the_step():
    step = Step(type=StepType.IMAGE, template_file="a.png", notify=True)
    assert Step.from_dict(step.to_dict()).notify is True
    assert Step.from_dict({}).notify is False
    assert "Discord" in step.summary()


def test_shared_rule_packs_never_carry_or_switch_on_discord(tmp_path):
    store = MacroStore(tmp_path / "a")
    other = MacroStore(tmp_path / "b")
    macro = Macro(name="m", rules=[Step(type=StepType.TEXT, text="hi", watch=True, notify=True)])
    path = tmp_path / "x.ultrebo-rules"
    rulepack.export_pack(macro, store.templates_dir, path)
    import zipfile
    manifest = json.loads(zipfile.ZipFile(path).read("rules.json"))
    assert "notify" not in manifest["rules"][0]
    # and a pack that does say notify: true (made by hand) is still imported with it off
    manifest["rules"][0]["notify"] = True
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("rules.json", json.dumps(manifest))
    _, rules, _ = rulepack.read_pack(path, other.save_template_bytes, other.delete_template)
    assert rules[0].notify is False


class FakeNotifier:
    def __init__(self, configured=True):
        self._configured, self.sent = configured, []

    def configured(self):
        return self._configured

    def send(self, key, message, image):
        self.sent.append((key, message, image))
        return True


def runner_with(templates_dir, frame, notifier):
    inp = FakeInput()
    r = Runner(inp, FakeScreen(lambda: frame), None, templates_dir, on_status=lambda s: None, on_error=print, notifier=notifier)
    return r, inp


def finished(r):
    return wait_until(lambda: not r.running, timeout=6)


def test_a_step_that_asked_for_it_sends_the_screenshot_it_found_the_image_in(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    note = FakeNotifier()
    r, inp = runner_with(templates_dir, frame, note)
    step = Step(type=StepType.IMAGE, template_file="button.png", name="Claim", notify=True, delay_after_ms=5, timeout_ms=800)
    assert r.start(Macro(name="Farm", loops=1, steps=[step])) is None
    assert finished(r)
    [(key, message, image)] = note.sent
    assert key == step.id and message == 'Ultrebo found "Claim" in "Farm"'
    assert image.shape == frame.shape and (image == frame).all()
    assert len(inp.clicks()) == 1


def test_steps_without_the_option_send_nothing(templates_dir, blank, pattern):
    note = FakeNotifier()
    r, _ = runner_with(templates_dir, with_pattern(blank, pattern), note)
    r.start(Macro(loops=1, steps=[Step(type=StepType.IMAGE, template_file="button.png", delay_after_ms=5)]))
    assert finished(r)
    assert note.sent == []


def test_a_rule_sends_when_it_is_seen(templates_dir, blank, pattern):
    note = FakeNotifier()
    r, _ = runner_with(templates_dir, with_pattern(blank, pattern), note)
    rule = Step(type=StepType.IMAGE, template_file="button.png", watch=True, notify=True, name="Pop-up", delay_after_ms=20,
                on_seen=WatchAction.CONTINUE)
    r.start(Macro(name="Farm", rules=[rule]))
    assert wait_until(lambda: len(note.sent) >= 1)
    r.stop()
    assert note.sent[0][1] == 'Ultrebo found "Pop-up" in "Farm"'


def test_a_macro_wanting_discord_will_not_start_without_a_webhook(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    step = Step(type=StepType.IMAGE, template_file="button.png", name="Claim", notify=True)
    for notifier in (None, FakeNotifier(configured=False)):
        r, _ = runner_with(templates_dir, frame, notifier)
        error = r.start(Macro(loops=1, steps=[step]))
        assert error and "Claim" in error and "Discord webhook" in error and not r.running
    r, _ = runner_with(templates_dir, frame, FakeNotifier())
    assert r.start(Macro(loops=1, steps=[step])) is None
    assert finished(r)


# ------------------------------------------------------------------ the Settings window

def _close(qapp, dialog):
    from PySide6.QtCore import QEvent

    dialog.deleteLater()  # a top-level dialog left for garbage collection can crash Qt at exit
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_settings_window_saves_and_clears_the_webhook(qapp):
    from ultrebo.ui.dialogs import SettingsDialog

    settings = Settings()
    dialog = SettingsDialog(settings, None, None)
    dialog.webhook.setText(f"  {HOOK} ")
    dialog._save()
    assert settings.webhook_url == HOOK
    dialog.webhook.setText("")
    dialog._save()
    assert settings.webhook_url == ""
    _close(qapp, dialog)


def test_settings_window_refuses_a_wrong_address(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from ultrebo.ui.dialogs import SettingsDialog

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    settings = Settings()
    dialog = SettingsDialog(settings, None, None)
    dialog.webhook.setText("https://example.com/hook")
    dialog._save()
    assert settings.webhook_url == "" and "Discord webhook" in warnings[-1]
    _close(qapp, dialog)


def test_the_test_button_reports_what_discord_said(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from ultrebo.ui import dialogs

    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(("warning", a[2])))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(("info", a[2])))
    monkeypatch.setattr(dialogs, "post", lambda url, message, jpeg: None)
    dialog = dialogs.SettingsDialog(Settings(), None, None)
    dialog.webhook.setText(HOOK)
    dialog._send_test()
    assert wait_until(lambda: (qapp.processEvents(), bool(shown))[1])
    assert shown[-1][0] == "info" and dialog.webhook_test.isEnabled()
    monkeypatch.setattr(dialogs, "post", lambda url, message, jpeg: "Discord says no.")
    dialog._send_test()
    assert wait_until(lambda: (qapp.processEvents(), len(shown) == 2)[1])
    assert shown[-1] == ("warning", "Discord says no.")
    _close(qapp, dialog)
