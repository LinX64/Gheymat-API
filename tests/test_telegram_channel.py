import datetime
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("telegram_channel", ROOT / "tools/telegram_channel.py")
channel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(channel)


def without_urls(text):
    return re.sub(r"https://\S+", "", text)


def test_every_text_fits_telegram_limits(monkeypatch):
    for live in ("", "1"):
        monkeypatch.setenv("TELEGRAM_ANDROID_LIVE", live)
        channel.check_lengths()


def test_no_rate_numbers_in_any_text(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ANDROID_LIVE", "1")
    for name, text in channel.check_lengths().items():
        digits = re.findall(r"[0-9۰-۹]+", without_urls(text))
        assert all(d == "۱۳۹۷" for d in digits), (name, digits)


def test_rotation_shows_every_post_once_per_cycle():
    pool = len(channel.POSTS) + 1
    day = datetime.date(2026, 11, 23)
    seen = []
    while len(seen) < pool:
        if day.weekday() in (0, 2, 5):
            seen.append(channel.post_index(day))
        day += datetime.timedelta(days=1)
    assert sorted(seen) == list(range(pool))


def test_android_link_only_when_live(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ANDROID_LIVE", "")
    assert "play.google.com" not in channel.welcome()
    monkeypatch.setenv("TELEGRAM_ANDROID_LIVE", "1")
    assert "play.google.com" in channel.welcome()
    assert "play.google.com" in channel.description()


def test_workflow_pins_actions_and_keeps_token_in_env():
    text = (ROOT / ".github/workflows/telegram-channel.yml").read_text()
    for use in re.findall(r"uses:\s*(\S+)", text):
        assert re.search(r"@[0-9a-f]{40}$", use), use
    assert "secrets.TELEGRAM_BOT_TOKEN" in text
    assert "${{ inputs" not in text.split("run:")[1].splitlines()[0]


def test_channel_photo_is_a_png():
    data = Path(channel.ICON).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) < 10 * 1024 * 1024
