"""Desktop-environment integration — colour palette, font and icon theme.

Pure-data module (no Qt / PIL imports), resolved once at import time so the
palette constants that `widgets.py` / `icons.py` / `settings_ui.py` bake into
their stylesheets already carry the right colours.

Two palettes exist:

- ``brand`` — the warm stone/amber dark theme the app ships with (default on
  Windows / macOS / non-KDE Linux). Values here are the historical literals.
- ``kde`` — derived from the user's KDE Plasma colour scheme
  (``~/.config/kdeglobals``) so the window follows Breeze / Breeze Dark /
  any custom scheme, the Plasma accent colour, the system UI font and the
  Breeze icon theme. Semantic colours (success / failure / warnings) come
  from the scheme's Positive / Negative / Neutral roles.

The choice is ``desktop.theme`` in ``config.yaml`` (``auto`` | ``brand`` |
``system``) or the ``ACTIONS_MONITOR_THEME`` env var, which wins. ``auto``
picks ``kde`` inside a Plasma session and ``brand`` elsewhere. The theme is
read once at startup — changing it needs a restart.

This module also decides whether to run under XWayland on Plasma Wayland
(`wants_xwayland`): xdg-shell gives Wayland clients no "you were minimised"
notification, so minimise-to-tray only works through XWayland.

Like the other extracted modules it never imports from ``main``; the config
path is computed with the same rule as ``main._APP_DIR``.
"""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Mapping, Optional

from status import (
    ST_CANCELLED,
    ST_FAILURE,
    ST_QUEUED,
    ST_RUNNING,
    ST_SKIPPED,
    ST_SUCCESS,
    ST_UNKNOWN,
)

THEME_ENV = "ACTIONS_MONITOR_THEME"
THEME_MODES = ("auto", "brand", "system")

Colour = str
Pair = tuple[str, str]  # (background, foreground) of a badge / chip

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def _rgb(colour: Colour) -> tuple[int, int, int]:
    c = colour.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _hex(r: float, g: float, b: float) -> Colour:
    clamp = lambda v: max(0, min(255, round(v)))
    return f"#{clamp(r):02X}{clamp(g):02X}{clamp(b):02X}"


def mix(a: Colour, b: Colour, t: float) -> Colour:
    """Linear blend: ``t=0`` → *a*, ``t=1`` → *b*."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


def luminance(colour: Colour) -> float:
    """WCAG relative luminance (0 = black, 1 = white)."""
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(colour)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def is_dark(colour: Colour) -> bool:
    return luminance(colour) < 0.4


def on_colour(colour: Colour) -> Colour:
    """Readable text colour (white or near-black) on a solid *colour* fill."""
    return "#FFFFFF" if luminance(colour) < 0.45 else "#1B1E20"


# ---------------------------------------------------------------------------
# Brand palette — the historical literals, unchanged
# ---------------------------------------------------------------------------
BRAND: dict[str, object] = {
    # Surfaces
    "BG_DARK":         "#1C1917",  # window / page (stone-900)
    "BG_HEADER":       "#1C1917",  # header bar
    "BG_ROW":          "#262220",  # card row fill
    "BG_ROW_ALT":      "#262220",  # kept for import compat
    "BG_ROW_HOVER":    "#2C2825",
    "BG_ROW_SNOOZED":  "#221F1D",
    "BG_FOOTER":       "#232020",
    "BG_INPUT":        "#262220",
    "BG_CODE":         "#171412",  # YAML editor / preview
    "BG_TOOLTIP":      "#292524",
    "BG_HOVER":        "#292524",  # icon-button hover, selected nav item
    "BG_HOVER_STRONG": "#33302D",  # snooze-button hover, secondary button
    "BG_SELECTED":     "#4A3728",  # menu selection, row blink
    "BG_CHIP":         "#3D3530",  # neutral badge / chip, disabled button
    "BG_CHIP_DIM":     "#2C2825",  # badges on a snoozed row
    # Lines
    "BORDER":          "#33302D",
    "BORDER_SUBTLE":   "#292524",
    "BORDER_STRONG":   "#57534E",  # checkbox outline
    "BORDER_INPUT":    "#3B3734",
    "BORDER_POPUP":    "#44403C",
    # Text
    "FG_TEXT":         "#E7E5E4",  # stone-200
    "FG_TITLE":        "#F5F5F4",  # stone-100
    "FG_MUTED":        "#A8A29E",  # stone-400
    "FG_FAINT":        "#78716C",  # stone-500
    "FG_DIM":          "#57534E",  # hints, snoozed titles
    "FG_DIMMER":       "#44403C",  # snoozed meta text
    "FG_LINK":         "#FBBF24",  # amber-400 — primary accent
    "FG_LINK_HOVER":   "#F59E0B",  # amber-500
    "FG_ON_ACCENT":    "#1C1917",  # text on an FG_LINK fill
    "FG_SUCCESS":      "#4ADE80",
    "FG_ERROR":        "#F87171",
    "ACCENT":          "#292524",  # stone-800 (plain buttons)
    "ACCENT_DIM":      "#3F3B38",  # accent bar of a snoozed row
    # Badges — (background, foreground)
    "BADGE_PREFIX":     ("#3D3530", "#FBBF24"),
    "BADGE_DRAFT":      ("#92400E", "#FEF3C7"),
    "BADGE_CONFLICT":   ("#7F1D1D", "#FEE2E2"),
    "BADGE_UNRESOLVED": ("#4A1D1D", "#FCA5A5"),
    "BADGE_JIRA":       ("#302830", "#A78BFA"),
    "BADGE_SNOOZED":    ("#3D3530", "#A8A29E"),
    "BADGE_DIM":        ("#2C2825", "#57534E"),
    "REVIEW_APPROVED":  ("#1C3A2A", "#4ADE80"),
    "REVIEW_CHANGES":   ("#3A1C1C", "#F87171"),
    "REVIEW_COMMENTED": ("#1C2A3A", "#60A5FA"),
    "REVIEW_PENDING":   ("#3D3530", "#FBBF24"),
    "STALE_SLIGHT":     ("#3D3520", "#EAB308"),
    "STALE_MODERATE":   ("#3A2A1C", "#F97316"),
    "STALE_VERY":       ("#3A1C1C", "#EF4444"),
    "MODE_BRANCH":      ("#33302D", "#A8A29E"),
    "MODE_PR":          ("#3D3530", "#FBBF24"),
    "MODE_ACTOR":       ("#1C2A3A", "#60A5FA"),
    "MODE_URL":         ("#302830", "#A78BFA"),
    # Status → accent bar / dot / text colour
    "STATUS": {
        ST_UNKNOWN:   "#A8A29E",
        ST_QUEUED:    "#FBBF24",
        ST_RUNNING:   "#FBBF24",
        ST_SUCCESS:   "#4ADE80",
        ST_FAILURE:   "#F87171",
        ST_CANCELLED: "#A8A29E",
        ST_SKIPPED:   "#A8A29E",
    },
    # Status → icon circle fill (white glyph on top)
    "STATUS_FILL": {
        ST_UNKNOWN:   "#8C857F",
        ST_QUEUED:    "#CA8A04",
        ST_RUNNING:   "#CA8A04",
        ST_SUCCESS:   "#22994D",
        ST_FAILURE:   "#C53030",
        ST_CANCELLED: "#8C857F",
        ST_SKIPPED:   "#8C857F",
    },
    # Snooze bell button — state → (circle fill, glyph, slashed)
    "SNOOZE_ICON": {
        "normal":       ("#3D3530", "#A8A29E", False),
        "hover":        ("#4A3728", "#FBBF24", False),
        "active":       ("#92400E", "#FEF3C7", True),
        "active_hover": ("#78350F", "#FFFFFF", True),
    },
    # Checkbox tick glyph (drawn on an FG_LINK fill)
    "CHECK_GLYPH":   "#FFFFFF",
    # Recolour the white WizX20 wordmark (None = keep the brand artwork)
    "LOGO_TINT":     None,
    "IS_DARK":       True,
}

# ---------------------------------------------------------------------------
# KDE Plasma colour scheme
# ---------------------------------------------------------------------------
# Breeze (light) defaults — what KDE itself assumes when kdeglobals lacks a key.
_BREEZE_DEFAULTS: dict[str, dict[str, str]] = {
    "Window":    {"BackgroundNormal": "239,240,241", "ForegroundNormal": "35,38,41",
                  "ForegroundInactive": "112,125,138"},
    "View":      {"BackgroundNormal": "255,255,255", "ForegroundNormal": "35,38,41",
                  "ForegroundInactive": "112,125,138"},
    "Button":    {"BackgroundNormal": "252,252,252", "ForegroundNormal": "35,38,41"},
    "Selection": {"BackgroundNormal": "61,174,233", "ForegroundNormal": "255,255,255"},
    "Tooltip":   {"BackgroundNormal": "247,247,247", "ForegroundNormal": "35,38,41"},
    "Header":    {"BackgroundNormal": "222,224,226", "ForegroundNormal": "35,38,41"},
    "_roles":    {"ForegroundLink": "41,128,185", "ForegroundVisited": "155,89,182",
                  "ForegroundNegative": "218,68,83", "ForegroundNeutral": "246,116,0",
                  "ForegroundPositive": "39,174,96", "DecorationFocus": "61,174,233",
                  "DecorationHover": "147,206,233"},
}


def is_kde_session(env: Optional[Mapping[str, str]] = None) -> bool:
    """True inside a KDE Plasma session (any version, X11 or Wayland)."""
    env = os.environ if env is None else env
    desktops = env.get("XDG_CURRENT_DESKTOP", "") + ":" + env.get("XDG_SESSION_DESKTOP", "")
    return ("KDE" in desktops.upper().split(":")
            or env.get("KDE_FULL_SESSION", "").lower() == "true")


def kdeglobals_path(env: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "kdeglobals"


def read_kdeglobals(path: Path) -> Optional[configparser.ConfigParser]:
    """Parse kdeglobals (KConfig INI). Returns None when absent/unreadable."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # KConfig keys are case-sensitive
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            parser.read_file(fh)
    except (OSError, configparser.Error):
        return None
    return parser


def _kde_colour(cfg: Optional[configparser.ConfigParser], group: str, key: str) -> Colour:
    raw = None
    if cfg is not None and cfg.has_section(f"Colors:{group}"):
        raw = cfg.get(f"Colors:{group}", key, fallback=None)
    if not raw:
        raw = (_BREEZE_DEFAULTS.get(group, {}).get(key)
               or _BREEZE_DEFAULTS["_roles"].get(key)
               or _BREEZE_DEFAULTS["Window"].get(key))
        if raw is None and key == "ForegroundInactive":
            raw = _BREEZE_DEFAULTS["Window"]["ForegroundInactive"]
    try:
        parts = [int(p.strip()) for p in raw.split(",")[:3]]
        return _hex(*parts)
    except (AttributeError, ValueError, TypeError):
        return "#FF00FF"  # visibly wrong rather than crashing at import


def kde_font(cfg: Optional[configparser.ConfigParser]) -> tuple[str, float]:
    """(family, point size) of the Plasma "General" font — Noto Sans 10 default."""
    raw = cfg.get("General", "font", fallback="") if cfg is not None else ""
    parts = [p.strip() for p in raw.split(",")]
    family = parts[0] if parts and parts[0] else "Noto Sans"
    try:
        size = float(parts[1]) if len(parts) > 1 and float(parts[1]) > 0 else 10.0
    except ValueError:
        size = 10.0
    return family, size


def kde_icon_theme(cfg: Optional[configparser.ConfigParser], dark: bool) -> str:
    """Icon theme name. Qt's plain loader doesn't recolour Breeze SVGs the way
    KIconLoader does, so swap to the matching dark variant on dark schemes."""
    theme = cfg.get("Icons", "Theme", fallback="") if cfg is not None else ""
    theme = theme.strip() or "breeze"
    if dark and theme == "breeze":
        theme = "breeze-dark"
    elif not dark and theme == "breeze-dark":
        theme = "breeze"
    return theme


def kde_palette(cfg: Optional[configparser.ConfigParser]) -> dict[str, object]:
    """Map a KDE colour scheme onto the app's palette roles."""
    c = lambda group, key: _kde_colour(cfg, group, key)

    win_bg, win_fg = c("Window", "BackgroundNormal"), c("Window", "ForegroundNormal")
    win_inactive = c("Window", "ForegroundInactive")
    view_bg, view_fg = c("View", "BackgroundNormal"), c("View", "ForegroundNormal")
    btn_bg = c("Button", "BackgroundNormal")
    sel_bg, sel_fg = c("Selection", "BackgroundNormal"), c("Selection", "ForegroundNormal")
    tip_bg = c("Tooltip", "BackgroundNormal")
    header_bg = c("Header", "BackgroundNormal")
    accent = c("Window", "DecorationFocus")
    hover = c("Window", "DecorationHover")
    link = c("View", "ForegroundLink")
    visited = c("View", "ForegroundVisited")
    positive = c("View", "ForegroundPositive")
    negative = c("View", "ForegroundNegative")
    neutral = c("View", "ForegroundNeutral")
    dark = is_dark(win_bg)

    def tint(fg: Colour, strength: float = 0.18) -> Pair:
        return (mix(view_bg, fg, strength), fg)

    def solid(fill: Colour) -> Pair:
        return (fill, on_colour(fill))

    # Inactive grey reads poorly under a white glyph on dark schemes — deepen it.
    grey_fill = mix(win_inactive, "#000000", 0.25 if dark else 0.0)
    shade = lambda col: mix(col, "#000000", 0.08)

    faint = mix(win_inactive, view_bg, 0.25)
    dim = mix(win_inactive, view_bg, 0.45)
    chip = mix(view_bg, win_fg, 0.09)

    return {
        "BG_DARK":         view_bg,
        "BG_HEADER":       header_bg,
        "BG_ROW":          win_bg,
        "BG_ROW_ALT":      win_bg,
        "BG_ROW_HOVER":    mix(win_bg, hover, 0.14),
        "BG_ROW_SNOOZED":  mix(win_bg, view_bg, 0.55),
        "BG_FOOTER":       header_bg,
        "BG_INPUT":        view_bg,
        "BG_CODE":         view_bg,
        "BG_TOOLTIP":      tip_bg,
        "BG_HOVER":        mix(header_bg, hover, 0.22),
        "BG_HOVER_STRONG": mix(win_bg, hover, 0.28),
        "BG_SELECTED":     mix(view_bg, sel_bg, 0.35),
        "BG_CHIP":         chip,
        "BG_CHIP_DIM":     mix(view_bg, win_fg, 0.05),
        "BORDER":          mix(win_bg, win_fg, 0.14),
        "BORDER_SUBTLE":   mix(win_bg, win_fg, 0.09),
        "BORDER_STRONG":   mix(view_bg, view_fg, 0.35),
        "BORDER_INPUT":    mix(view_bg, view_fg, 0.22),
        "BORDER_POPUP":    mix(tip_bg, win_fg, 0.20),
        "FG_TEXT":         win_fg,
        "FG_TITLE":        view_fg,
        "FG_MUTED":        win_inactive,
        "FG_FAINT":        faint,
        "FG_DIM":          dim,
        "FG_DIMMER":       mix(win_inactive, view_bg, 0.60),
        "FG_LINK":         accent,
        "FG_LINK_HOVER":   mix(accent, win_fg, 0.25),
        "FG_ON_ACCENT":    sel_fg if luminance(accent) < 0.6 else on_colour(accent),
        "FG_SUCCESS":      positive,
        "FG_ERROR":        negative,
        "ACCENT":          btn_bg,
        "ACCENT_DIM":      mix(win_bg, win_fg, 0.18),
        "BADGE_PREFIX":     tint(accent),
        "BADGE_DRAFT":      solid(shade(neutral)),
        "BADGE_CONFLICT":   solid(shade(negative)),
        "BADGE_UNRESOLVED": tint(negative, 0.22),
        "BADGE_JIRA":       tint(visited),
        "BADGE_SNOOZED":    (chip, win_inactive),
        "BADGE_DIM":        (mix(view_bg, win_fg, 0.05), dim),
        "REVIEW_APPROVED":  tint(positive),
        "REVIEW_CHANGES":   tint(negative),
        "REVIEW_COMMENTED": tint(link),
        "REVIEW_PENDING":   tint(neutral),
        "STALE_SLIGHT":     (mix(view_bg, neutral, 0.10), mix(neutral, win_fg, 0.30)),
        "STALE_MODERATE":   tint(neutral, 0.22),
        "STALE_VERY":       tint(negative, 0.22),
        "MODE_BRANCH":      (chip, win_inactive),
        "MODE_PR":          tint(accent),
        "MODE_ACTOR":       tint(link),
        "MODE_URL":         tint(visited),
        "STATUS": {
            ST_UNKNOWN:   win_inactive,
            ST_QUEUED:    neutral,
            ST_RUNNING:   neutral,
            ST_SUCCESS:   positive,
            ST_FAILURE:   negative,
            ST_CANCELLED: win_inactive,
            ST_SKIPPED:   win_inactive,
        },
        "STATUS_FILL": {
            ST_UNKNOWN:   grey_fill,
            ST_QUEUED:    shade(neutral),
            ST_RUNNING:   shade(neutral),
            ST_SUCCESS:   shade(positive),
            ST_FAILURE:   shade(negative),
            ST_CANCELLED: grey_fill,
            ST_SKIPPED:   grey_fill,
        },
        "SNOOZE_ICON": {
            "normal":       (chip, win_inactive, False),
            "hover":        (mix(view_bg, sel_bg, 0.30), accent, False),
            "active":       (shade(neutral), on_colour(neutral), True),
            "active_hover": (mix(neutral, "#000000", 0.25), "#FFFFFF", True),
        },
        "CHECK_GLYPH":   sel_fg if luminance(accent) < 0.6 else on_colour(accent),
        "LOGO_TINT":     None if dark else view_fg,
        "IS_DARK":       dark,
    }


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def _default_config_path() -> Path:
    # Same rule as main._APP_DIR — duplicated to keep this module main-free.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config.yaml"
    return Path(__file__).resolve().parent.parent / "config.yaml"


def read_desktop_config(config_path: Optional[Path] = None) -> dict:
    """The ``desktop:`` block of config.yaml (empty dict on any problem).

    Read straight from disk because the palette must be known before Qt
    widgets are built — long before ``ConfigManager`` loads."""
    path = config_path or _default_config_path()
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        block = data.get("desktop") if isinstance(data, dict) else None
        return block if isinstance(block, dict) else {}
    except Exception:
        return {}


def resolve(mode: Optional[str] = None, *,
            env: Optional[Mapping[str, str]] = None,
            config_path: Optional[Path] = None) -> tuple[str, dict[str, object], dict[str, object]]:
    """Return ``(name, palette, extras)``.

    *name* is ``"brand"`` or ``"kde"``; *extras* carries the font family /
    size and icon theme for the Qt side (empty for brand)."""
    env = os.environ if env is None else env
    if mode is None:
        mode = (env.get(THEME_ENV) or "").strip().lower() or None
    if mode is None:
        mode = str(read_desktop_config(config_path).get("theme", "auto")).strip().lower()
    if mode not in THEME_MODES:
        mode = "auto"

    use_kde = mode == "system" or (mode == "auto" and sys.platform.startswith("linux")
                                   and is_kde_session(env))
    if not use_kde:
        return "brand", dict(BRAND), {}

    cfg = read_kdeglobals(kdeglobals_path(env))
    palette = kde_palette(cfg)
    family, size = kde_font(cfg)
    extras = {
        "font_family": family,
        "font_size": size,
        "icon_theme": kde_icon_theme(cfg, bool(palette["IS_DARK"])),
    }
    return "kde", palette, extras


def wants_xwayland(env: Optional[Mapping[str, str]] = None,
                   config_path: Optional[Path] = None) -> bool:
    """Whether to force Qt's ``xcb`` platform (XWayland) before QApplication.

    Under native Wayland, KWin minimises a window without telling the client
    (xdg-shell has no minimised state), so "minimise to tray" can't work; under
    XWayland the ``_NET_WM_STATE_HIDDEN`` change arrives as a normal
    ``WindowMinimized`` event. Only applies to Plasma Wayland sessions, never
    overrides an explicit ``QT_QPA_PLATFORM``, and ``desktop.xwayland: false``
    opts out (``true`` forces it on any Wayland session)."""
    env = os.environ if env is None else env
    if not sys.platform.startswith("linux") or env.get("QT_QPA_PLATFORM"):
        return False
    if env.get("XDG_SESSION_TYPE", "").lower() != "wayland" and not env.get("WAYLAND_DISPLAY"):
        return False
    if not env.get("DISPLAY"):  # no XWayland server to talk to
        return False
    setting = read_desktop_config(config_path).get("xwayland", "auto")
    if isinstance(setting, bool):
        return setting
    if str(setting).strip().lower() in ("false", "no", "off", "0"):
        return False
    if str(setting).strip().lower() in ("true", "yes", "on", "1"):
        return True
    return is_kde_session(env)


THEME_NAME, PALETTE, EXTRAS = resolve()
