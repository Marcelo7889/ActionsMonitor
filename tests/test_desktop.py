"""Unit tests for desktop.py — palette resolution and the XWayland decision.

Pure Python: no Qt, no real kdeglobals (each test writes its own into a temp
XDG_CONFIG_HOME), no dependence on the desktop the suite runs on.
"""

from __future__ import annotations

import pytest

import desktop
from status import ST_FAILURE, ST_SUCCESS

BREEZE_DARK = """\
[Colors:Button]
BackgroundNormal=41,44,48
ForegroundNormal=252,252,252

[Colors:Header]
BackgroundNormal=41,44,48
ForegroundNormal=252,252,252

[Colors:Selection]
BackgroundNormal=61,174,233
ForegroundNormal=252,252,252

[Colors:Tooltip]
BackgroundNormal=41,44,48
ForegroundNormal=252,252,252

[Colors:View]
BackgroundNormal=20,22,24
ForegroundInactive=161,169,177
ForegroundLink=29,153,243
ForegroundNegative=218,68,83
ForegroundNeutral=246,116,0
ForegroundNormal=252,252,252
ForegroundPositive=39,174,96
ForegroundVisited=155,89,182

[Colors:Window]
BackgroundNormal=32,35,38
DecorationFocus=61,174,233
DecorationHover=61,174,233
ForegroundInactive=161,169,177
ForegroundNormal=252,252,252

[Colors:Header][Inactive]
BackgroundNormal=32,35,38
"""

BREEZE_LIGHT_MIN = """\
[Colors:Window]
BackgroundNormal=239,240,241
ForegroundNormal=35,38,41
"""

KDE_WAYLAND = {
    "XDG_CURRENT_DESKTOP": "KDE",
    "XDG_SESSION_TYPE": "wayland",
    "WAYLAND_DISPLAY": "wayland-0",
    "DISPLAY": ":0",
}


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "linux")


def _kde_env(tmp_path, kdeglobals: str | None, **extra) -> dict:
    if kdeglobals is not None:
        (tmp_path / "kdeglobals").write_text(kdeglobals, encoding="utf-8")
    return {"XDG_CONFIG_HOME": str(tmp_path), "XDG_CURRENT_DESKTOP": "KDE", **extra}


def _no_config(tmp_path):
    return tmp_path / "missing-config.yaml"


# ---------------------------------------------------------------------------
# Palette shape
# ---------------------------------------------------------------------------
def test_brand_palette_is_the_historical_theme():
    assert desktop.BRAND["BG_DARK"] == "#1C1917"
    assert desktop.BRAND["FG_LINK"] == "#FBBF24"
    assert desktop.BRAND["STATUS"][ST_SUCCESS] == "#4ADE80"
    assert desktop.BRAND["LOGO_TINT"] is None


def test_suite_runs_on_brand_theme():
    # conftest pins ACTIONS_MONITOR_THEME=brand so screenshots are stable.
    import os
    if os.environ.get(desktop.THEME_ENV) != "brand":
        pytest.skip("suite deliberately run with another theme")
    import widgets
    assert widgets.THEME_NAME == "brand"
    assert widgets.BG_DARK == desktop.BRAND["BG_DARK"]


@pytest.mark.parametrize("scheme", [BREEZE_DARK, BREEZE_LIGHT_MIN, None])
def test_kde_palette_has_every_brand_role(tmp_path, scheme):
    name, palette, _ = desktop.resolve(
        "system", env=_kde_env(tmp_path, scheme), config_path=_no_config(tmp_path))
    assert name == "kde"
    assert set(palette) == set(desktop.BRAND)
    assert set(palette["STATUS"]) == set(desktop.BRAND["STATUS"])
    assert set(palette["SNOOZE_ICON"]) == set(desktop.BRAND["SNOOZE_ICON"])
    for key, value in palette.items():
        if key.startswith(("BADGE_", "REVIEW_", "STALE_", "MODE_")):
            assert len(value) == 2, key


# ---------------------------------------------------------------------------
# KDE colour scheme mapping
# ---------------------------------------------------------------------------
def test_breeze_dark_mapping(tmp_path):
    _, p, extras = desktop.resolve(
        "system", env=_kde_env(tmp_path, BREEZE_DARK), config_path=_no_config(tmp_path))
    assert p["IS_DARK"] is True
    assert p["BG_DARK"] == "#141618"        # View background
    assert p["BG_ROW"] == "#202326"         # Window background
    assert p["BG_HEADER"] == "#292C30"      # Header background
    assert p["FG_TEXT"] == "#FCFCFC"
    assert p["FG_LINK"] == "#3DAEE9"        # Plasma accent (DecorationFocus)
    assert p["STATUS"][ST_SUCCESS] == "#27AE60"
    assert p["STATUS"][ST_FAILURE] == "#DA4453"
    assert p["LOGO_TINT"] is None
    assert extras["icon_theme"] == "breeze-dark"
    assert (extras["font_family"], extras["font_size"]) == ("Noto Sans", 10.0)


def test_light_scheme_tints_logo_and_uses_light_icons(tmp_path):
    _, p, extras = desktop.resolve(
        "system", env=_kde_env(tmp_path, BREEZE_LIGHT_MIN), config_path=_no_config(tmp_path))
    assert p["IS_DARK"] is False
    assert p["LOGO_TINT"] is not None
    assert extras["icon_theme"] == "breeze"


def test_missing_kdeglobals_falls_back_to_breeze_light(tmp_path):
    _, p, _ = desktop.resolve(
        "system", env=_kde_env(tmp_path, None), config_path=_no_config(tmp_path))
    assert p["BG_ROW"] == "#EFF0F1"
    assert p["IS_DARK"] is False


def test_font_and_explicit_icon_theme(tmp_path):
    scheme = BREEZE_DARK + "\n[General]\nfont=Inter,11,-1,5,400,0,0,0,0,0\n\n[Icons]\nTheme=Papirus-Dark\n"
    _, _, extras = desktop.resolve(
        "system", env=_kde_env(tmp_path, scheme), config_path=_no_config(tmp_path))
    assert extras["font_family"] == "Inter"
    assert extras["font_size"] == 11.0
    assert extras["icon_theme"] == "Papirus-Dark"


def test_garbage_colour_does_not_crash(tmp_path):
    scheme = "[Colors:Window]\nBackgroundNormal=not,a,colour\n"
    _, p, _ = desktop.resolve(
        "system", env=_kde_env(tmp_path, scheme), config_path=_no_config(tmp_path))
    assert p["BG_ROW"].startswith("#")


def test_badge_text_is_readable_on_solid_fills(tmp_path):
    _, p, _ = desktop.resolve(
        "system", env=_kde_env(tmp_path, BREEZE_DARK), config_path=_no_config(tmp_path))
    for key in ("BADGE_DRAFT", "BADGE_CONFLICT"):
        bg, fg = p[key]
        lighter, darker = sorted((desktop.luminance(bg), desktop.luminance(fg)), reverse=True)
        assert (lighter + 0.05) / (darker + 0.05) >= 3.0, key


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------
def test_auto_picks_kde_inside_plasma(tmp_path, linux):
    name, _, _ = desktop.resolve(
        "auto", env=_kde_env(tmp_path, BREEZE_DARK), config_path=_no_config(tmp_path))
    assert name == "kde"


def test_auto_picks_brand_outside_plasma(tmp_path, linux):
    env = {"XDG_CONFIG_HOME": str(tmp_path), "XDG_CURRENT_DESKTOP": "GNOME"}
    name, palette, extras = desktop.resolve("auto", env=env, config_path=_no_config(tmp_path))
    assert name == "brand"
    assert palette == desktop.BRAND
    assert extras == {}


def test_auto_is_brand_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    name, _, _ = desktop.resolve(
        "auto", env=_kde_env(tmp_path, BREEZE_DARK), config_path=_no_config(tmp_path))
    assert name == "brand"


def test_config_theme_brand_wins_over_plasma(tmp_path, linux):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("desktop:\n  theme: brand\n", encoding="utf-8")
    name, _, _ = desktop.resolve(env=_kde_env(tmp_path, BREEZE_DARK), config_path=cfg)
    assert name == "brand"


def test_env_override_wins_over_config(tmp_path, linux):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("desktop:\n  theme: brand\n", encoding="utf-8")
    env = _kde_env(tmp_path, BREEZE_DARK, ACTIONS_MONITOR_THEME="system")
    name, _, _ = desktop.resolve(env=env, config_path=cfg)
    assert name == "kde"


def test_unknown_mode_behaves_like_auto(tmp_path, linux):
    name, _, _ = desktop.resolve(
        "rainbow", env=_kde_env(tmp_path, BREEZE_DARK), config_path=_no_config(tmp_path))
    assert name == "kde"


@pytest.mark.parametrize("value,expected", [
    ("KDE", True), ("ubuntu:KDE", True), ("GNOME", False), ("", False),
])
def test_is_kde_session(value, expected):
    assert desktop.is_kde_session({"XDG_CURRENT_DESKTOP": value}) is expected


# ---------------------------------------------------------------------------
# XWayland decision
# ---------------------------------------------------------------------------
def test_xwayland_on_plasma_wayland(tmp_path, linux):
    assert desktop.wants_xwayland(dict(KDE_WAYLAND), _no_config(tmp_path)) is True


@pytest.mark.parametrize("override", [
    {"QT_QPA_PLATFORM": "wayland"},                         # user's explicit choice
    {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": ""},     # X11 session
    {"DISPLAY": ""},                                        # no XWayland server
    {"XDG_CURRENT_DESKTOP": "GNOME"},                       # auto = Plasma only
])
def test_xwayland_not_forced(tmp_path, linux, override):
    env = {**KDE_WAYLAND, **override}
    assert desktop.wants_xwayland(env, _no_config(tmp_path)) is False


@pytest.mark.parametrize("value,desktop_name,expected", [
    ("false", "KDE", False),
    ("true", "GNOME", True),
    ("auto", "KDE", True),
])
def test_xwayland_config(tmp_path, linux, value, desktop_name, expected):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"desktop:\n  xwayland: {value}\n", encoding="utf-8")
    env = {**KDE_WAYLAND, "XDG_CURRENT_DESKTOP": desktop_name}
    assert desktop.wants_xwayland(env, cfg) is expected


def test_xwayland_never_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    assert desktop.wants_xwayland(dict(KDE_WAYLAND), _no_config(tmp_path)) is False
