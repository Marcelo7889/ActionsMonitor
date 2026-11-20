"""Workflow row widget + colour palette + tiny QLabel subclasses.

UI-only module. Imports `pollers` for `WorkflowState` / status constants and
`icons` for the pre-rendered status / snooze pixmaps. main.py re-imports the
colour constants from here so existing call sites in MainWindow keep working.
"""

from __future__ import annotations

import platform
import webbrowser
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QSizePolicy, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap

from icons import _reviewer_icon_b64, _snooze_qpixmaps, _status_qpixmaps
from pollers import (
    ST_CANCELLED,
    ST_FAILURE,
    ST_QUEUED,
    ST_RUNNING,
    ST_SKIPPED,
    ST_SUCCESS,
    ST_UNKNOWN,
    WorkflowState,
    _format_age,
)

IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# Colour palette — brand warm dark theme, or the KDE Plasma colour scheme
# (resolved once at import by `desktop.py`; see its docstring)
# ---------------------------------------------------------------------------
import desktop as _desktop

_P = _desktop.PALETTE
THEME_NAME = _desktop.THEME_NAME   # "brand" | "kde"

BG_DARK         = _P["BG_DARK"]          # window / page
BG_HEADER       = _P["BG_HEADER"]        # header bar
BG_ROW          = _P["BG_ROW"]           # card row fill (design v2)
BG_ROW_ALT      = _P["BG_ROW_ALT"]       # kept for import compat — rows are uniform cards now
BG_ROW_HOVER    = _P["BG_ROW_HOVER"]     # card hover
BG_ROW_SNOOZED  = _P["BG_ROW_SNOOZED"]   # dimmed card for snoozed rows
BG_FOOTER       = _P["BG_FOOTER"]        # footer bar
BG_INPUT        = _P["BG_INPUT"]         # line edits / combos
BG_CODE         = _P["BG_CODE"]          # YAML editor / preview
BG_TOOLTIP      = _P["BG_TOOLTIP"]
BG_HOVER        = _P["BG_HOVER"]         # icon-button hover, selected nav item
BG_HOVER_STRONG = _P["BG_HOVER_STRONG"]  # snooze-button hover, secondary buttons
BG_SELECTED     = _P["BG_SELECTED"]      # menu selection, row blink
BG_CHIP         = _P["BG_CHIP"]          # neutral chip / disabled button
BORDER          = _P["BORDER"]           # hairlines / separators
BORDER_SUBTLE   = _P["BORDER_SUBTLE"]
BORDER_STRONG   = _P["BORDER_STRONG"]    # checkbox outline
BORDER_INPUT    = _P["BORDER_INPUT"]
BORDER_POPUP    = _P["BORDER_POPUP"]     # tooltip / menu frame
FG_TEXT         = _P["FG_TEXT"]
FG_TITLE        = _P["FG_TITLE"]         # row titles / headings
FG_MUTED        = _P["FG_MUTED"]
FG_FAINT        = _P["FG_FAINT"]         # secondary meta text
FG_DIM          = _P["FG_DIM"]           # hints, snoozed titles
FG_DIMMER       = _P["FG_DIMMER"]        # snoozed meta text
FG_LINK         = _P["FG_LINK"]          # primary accent (amber / Plasma accent)
FG_LINK_HOVER   = _P["FG_LINK_HOVER"]
FG_ON_ACCENT    = _P["FG_ON_ACCENT"]     # text on an FG_LINK fill
FG_SUCCESS      = _P["FG_SUCCESS"]
FG_ERROR        = _P["FG_ERROR"]
ACCENT          = _P["ACCENT"]           # plain buttons
ACCENT_DIM      = _P["ACCENT_DIM"]       # accent bar of a snoozed row
IS_DARK_THEME   = bool(_P["IS_DARK"])

# Badges — (background, foreground)
BADGE_PREFIX     = _P["BADGE_PREFIX"]
BADGE_DRAFT      = _P["BADGE_DRAFT"]
BADGE_CONFLICT   = _P["BADGE_CONFLICT"]
BADGE_UNRESOLVED = _P["BADGE_UNRESOLVED"]
BADGE_JIRA       = _P["BADGE_JIRA"]
BADGE_SNOOZED    = _P["BADGE_SNOOZED"]
BADGE_DIM        = _P["BADGE_DIM"]       # any badge on a snoozed row

if THEME_NAME == "kde":
    UI_FONT = _desktop.EXTRAS.get("font_family", "Noto Sans")
else:
    UI_FONT = "Segoe UI" if IS_WINDOWS else "DejaVu Sans"

COLOUR = dict(_P["STATUS"])

STATUS_LABEL = {
    ST_UNKNOWN:  "Unknown",
    ST_QUEUED:   "Queued",
    ST_RUNNING:  "Running…",
    ST_SUCCESS:  "Success",
    ST_FAILURE:  "Failed",
    ST_CANCELLED:"Cancelled",
    ST_SKIPPED:  "Skipped",
}

# Review status badge config: state → (label, bg_colour, fg_colour)
_REVIEW_BADGE_CFG = {
    "approved":          ("APPROVED",          *_P["REVIEW_APPROVED"]),
    "changes_requested": ("CHANGES REQUESTED", *_P["REVIEW_CHANGES"]),
    "commented":         ("IN REVIEW",         *_P["REVIEW_COMMENTED"]),
    "pending":           ("REVIEW PENDING",    *_P["REVIEW_PENDING"]),
}

# Staleness badge config: level → (bg_colour, fg_colour)
_STALENESS_BADGE_CFG = {
    "slightly_stale":   _P["STALE_SLIGHT"],
    "moderately_stale": _P["STALE_MODERATE"],
    "very_stale":       _P["STALE_VERY"],
}


class _ClickableLabel(QLabel):
    """QLabel that opens a URL on click and shows a hand cursor."""
    def __init__(self, *args, url_fn=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._url_fn = url_fn
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._url_fn:
            url = self._url_fn()
            if url:
                webbrowser.open(url)


class _TitleLabel(_ClickableLabel):
    """ClickableLabel with a preferred-min width — sizeHint is `max(natural, MIN)`
    so short titles look balanced; minimumSizeHint stays small so the label can
    shrink and wrap when the window narrows."""

    PREFERRED_MIN = 450

    def sizeHint(self):
        sh = super().sizeHint()
        return QSize(max(sh.width(), self.PREFERRED_MIN), sh.height())


def _link_css(color: str, size: int, hover: str = FG_LINK) -> str:
    """Stylesheet for a clickable label: base color + amber hover via :hover pseudo-state."""
    return (f"QLabel {{ color: {color}; font-size: {size}px; }} "
            f"QLabel:hover {{ color: {hover}; text-decoration: underline; }}")


def _make_badge(text: str, bg: str, fg: str, bold: bool = False) -> QLabel:
    """Create a small badge label with styled background."""
    lbl = QLabel(text)
    weight = "bold" if bold else "normal"
    lbl.setStyleSheet(
        f"background-color: {bg}; color: {fg}; font-size: 10px; font-weight: {weight}; "
        f"padding: 2px 6px; border-radius: 3px;"
    )
    lbl.setVisible(False)
    return lbl


class WorkflowRow(QWidget):

    def __init__(self, parent: QWidget, wid: int, state: WorkflowState, alt: bool,
                 jira_base_url: str = "", sub_key: Optional[str] = None,
                 snooze_cb: Optional[callable] = None):
        super().__init__(parent)
        self.wid = wid
        self._sub_key = sub_key
        self._state = state
        self._jira_base_url = jira_base_url
        self._snooze_cb = snooze_cb
        self._snoozed = False
        self._icon_opacity: Optional[QGraphicsOpacityEffect] = None
        self._bg = BG_ROW_ALT if alt else BG_ROW
        # Qt only auto-enables styled backgrounds for exact-QWidget instances;
        # without this the `WorkflowRow { background-color }` QSS (zebra
        # striping, blink-on-focus) never paints on this subclass.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_right_click)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left accent bar — inset pill (design v2: 3px wide, 2px radius,
        # 6px from the card edge, 2px vertical inset)
        accent_wrap = QWidget()
        accent_layout = QVBoxLayout(accent_wrap)
        accent_layout.setContentsMargins(6, 2, 0, 2)
        accent_layout.setSpacing(0)
        self._accent = QFrame()
        self._accent.setFixedWidth(3)
        self._accent.setStyleSheet(
            f"background-color: {COLOUR[state.status]}; border-radius: 2px;")
        accent_layout.addWidget(self._accent)
        main_layout.addWidget(accent_wrap)

        # Left column: icon + snooze
        left_col = QVBoxLayout()
        left_col.setContentsMargins(12, 8, 10, 4)
        left_col.setSpacing(4)

        self._icon_lbl = QLabel()
        pixmap = _status_qpixmaps.get(state.status, _status_qpixmaps.get(ST_UNKNOWN))
        self._icon_lbl.setPixmap(pixmap)
        self._icon_lbl.setFixedSize(22, 22)
        left_col.addWidget(self._icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        main_layout.addLayout(left_col)

        # Centre column
        centre = QVBoxLayout()
        centre.setContentsMargins(0, 8, 0, 6)
        centre.setSpacing(0)

        # PR title row: title (left) + target arrow (right) — PR mode only.
        pr_title_row = QHBoxLayout()
        pr_title_row.setContentsMargins(0, 0, 0, 0)
        pr_title_row.setSpacing(0)

        self._pr_title_lbl = _TitleLabel(
            url_fn=lambda: self._state.pr_url)
        # PR titles are user-controlled text — never let QLabel auto-detect
        # them as rich text (a title containing <table> etc. would be parsed).
        self._pr_title_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._pr_title_lbl.setStyleSheet(_link_css(FG_TITLE, 13))
        self._pr_title_lbl.setToolTip("Open PR on GitHub")
        self._pr_title_lbl.setMinimumWidth(0)
        self._pr_title_lbl.setWordWrap(True)
        pr_title_row.addWidget(self._pr_title_lbl, 0)

        pr_title_row.addSpacing(20)

        # Target label — PR-mode only; the `→ target` suffix links to the branch tree.
        self._target_lbl = _ClickableLabel(url_fn=self._target_url)
        self._target_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._target_lbl.setStyleSheet(_link_css(FG_MUTED, 11))
        self._target_lbl.setToolTip("Open target branch on GitHub")
        self._target_lbl.setMinimumWidth(0)
        self._target_lbl.setWordWrap(False)
        self._target_lbl.setVisible(False)
        # Branch/target labels stay content-sized; trailing stretch absorbs
        # extra width so the subtitle stays flush-left next to the title.
        pr_title_row.addWidget(self._target_lbl, 0)
        pr_title_row.addStretch(1)

        self._pr_title_widget = QWidget()
        self._pr_title_widget.setLayout(pr_title_row)
        self._pr_title_widget.setVisible(False)
        centre.addWidget(self._pr_title_widget)

        # Top row: name + branch
        self._top_row = QHBoxLayout()
        self._top_row.setContentsMargins(0, 0, 0, 0)
        self._top_row.setSpacing(0)

        self._name_lbl = _TitleLabel(state.name, url_fn=self._name_url)
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._name_lbl.setStyleSheet(_link_css(FG_TITLE, 13))
        self._name_lbl.setMinimumWidth(0)
        self._name_lbl.setWordWrap(True)
        self._top_row.addWidget(self._name_lbl, 0)

        # Toggleable 20px gap between name and branch — hidden in PR mode
        # (name hidden) so the branch slug aligns flush-left with the title.
        self._name_branch_gap = QWidget()
        self._name_branch_gap.setFixedWidth(20)
        self._top_row.addWidget(self._name_branch_gap)

        # Branch label — in PR mode shows `#PR  branch-slug` and links to
        # the latest run; in branch/actor mode shows the branch and links
        # to the branch tree.
        self._branch_lbl = _ClickableLabel(url_fn=self._branch_url)
        self._branch_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._branch_lbl.setStyleSheet(_link_css(FG_MUTED, 11))
        self._branch_lbl.setToolTip("Open branch on GitHub")
        self._branch_lbl.setMinimumWidth(0)
        self._branch_lbl.setWordWrap(False)
        self._branch_lbl.setVisible(False)
        # Both labels sized to content; trailing stretch absorbs extra width
        # so the subtitle stays flush-left next to the title.
        self._top_row.addWidget(self._branch_lbl, 0)

        self._top_row.addStretch(1)
        centre.addLayout(self._top_row)

        # Badge row
        badge_layout = QHBoxLayout()
        badge_layout.setContentsMargins(0, 2, 0, 0)
        badge_layout.setSpacing(4)

        self._prefix_lbl = _make_badge("", *BADGE_PREFIX)
        badge_layout.addWidget(self._prefix_lbl)

        self._draft_lbl = _make_badge("DRAFT", *BADGE_DRAFT, bold=True)
        badge_layout.addWidget(self._draft_lbl)

        self._conflict_lbl = _make_badge("\u26A0 CONFLICT", *BADGE_CONFLICT, bold=True)
        self._conflict_lbl.setToolTip("This PR has merge conflicts that must be resolved")
        badge_layout.addWidget(self._conflict_lbl)

        self._unresolved_lbl = _make_badge("", *BADGE_UNRESOLVED, bold=True)
        self._unresolved_lbl.setToolTip("Unresolved review threads on this PR")
        badge_layout.addWidget(self._unresolved_lbl)

        self._jira_lbl = _make_badge("", *BADGE_JIRA)
        self._jira_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._jira_lbl.mousePressEvent = lambda e: self._open_jira()
        badge_layout.addWidget(self._jira_lbl)

        self._review_lbl = _make_badge("", *_P["REVIEW_PENDING"])
        self._review_lbl.setTextFormat(Qt.RichText)
        badge_layout.addWidget(self._review_lbl)

        self._stale_lbl = _make_badge("", *_P["STALE_SLIGHT"], bold=True)
        badge_layout.addWidget(self._stale_lbl)

        self._snooze_lbl = _make_badge("SNOOZED", *BADGE_SNOOZED, bold=True)
        badge_layout.addWidget(self._snooze_lbl)

        badge_layout.addStretch()
        self._badge_widget = QWidget()
        self._badge_widget.setLayout(badge_layout)
        self._badge_widget.setVisible(False)
        centre.addWidget(self._badge_widget)

        # Status info line — clickable, opens the latest run instance.
        self._info_lbl = _ClickableLabel(url_fn=lambda: self._state.run_url or self._state.url)
        self._info_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._info_lbl.setStyleSheet(_link_css(FG_MUTED, 11))
        self._info_lbl.setToolTip("Open latest run on GitHub")
        self._info_lbl.setMinimumWidth(0)
        self._info_lbl.setWordWrap(True)
        centre.addWidget(self._info_lbl)

        main_layout.addLayout(centre, 1)

        # Right column: poll rate + compact snooze button
        right_col = QHBoxLayout()
        right_col.setContentsMargins(4, 10, 12, 0)
        right_col.setSpacing(4)

        self._poll_lbl = QLabel()
        self._poll_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
        self._poll_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        right_col.addWidget(self._poll_lbl)

        self._snooze_btn = QLabel()
        self._snooze_btn.setPixmap(_snooze_qpixmaps.get("normal", QPixmap()))
        self._snooze_btn.setFixedSize(24, 24)
        self._snooze_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._snooze_btn.setStyleSheet(
            "QLabel { border-radius: 6px; } "
            f"QLabel:hover {{ background-color: {BG_HOVER_STRONG}; }}")
        self._snooze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._snooze_btn.setToolTip("Snooze - pause polling, dim the row, mute notifications")
        self._snooze_btn.mousePressEvent = lambda e: self._toggle_snooze()
        self._snooze_btn.enterEvent = lambda e: self._snooze_hover_enter()
        self._snooze_btn.leaveEvent = lambda e: self._snooze_hover_leave()
        right_col.addWidget(self._snooze_btn, 0, Qt.AlignmentFlag.AlignTop)

        right_wrap = QWidget()
        right_wrap.setLayout(right_col)
        right_wrap.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        main_layout.addWidget(right_wrap)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._apply_background()
        self._update_labels()

    # The app-wide `QWidget { background-color: BG_DARK }` rule would paint
    # dark patches behind the row's child containers (badge row, right column,
    # spacer widgets) on top of the card fill — force descendants transparent.
    # Widget-level styles (accent bar, badges, snooze hover) still win.
    _CHILD_RESET = "WorkflowRow QWidget { background-color: transparent; }"

    def _apply_background(self):
        hover = self._bg if self._snoozed else BG_ROW_HOVER
        self.setStyleSheet(
            f"WorkflowRow {{ background-color: {self._bg}; border-radius: 6px; }} "
            f"WorkflowRow:hover {{ background-color: {hover}; }} "
            + self._CHILD_RESET
        )

    def paint_bg(self, colour: str):
        """Temporarily flood the card with `colour` (blink-on-focus). Call
        `_apply_background()` to restore the normal fill."""
        self.setStyleSheet(
            f"WorkflowRow {{ background-color: {colour}; border-radius: 6px; }} "
            + self._CHILD_RESET
        )

    def _set_accent(self, colour: str):
        self._accent.setStyleSheet(
            f"background-color: {colour}; border-radius: 2px;")

    def _name_url(self) -> Optional[str]:
        s = self._state
        # Name label opens workflow overview when available; falls back to the
        # latest run, then to the configured URL.
        return s.workflow_url or s.run_url or s.url

    def _branch_url(self) -> Optional[str]:
        s = self._state
        # In PR mode the branch label carries `#PR  branch-slug` and points at
        # the latest run; the target label handles the branch link. In
        # branch/actor mode there is no split, so it stays as the branch link.
        if s.pr_number:
            return s.run_url or s.url
        return s.branch_url or s.run_url or s.url

    def _target_url(self) -> Optional[str]:
        s = self._state
        # The label displays the PR *target* branch — link there, not to the
        # head branch (branch_url is always built from the head branch).
        return s.target_url or s.branch_url or s.run_url or s.url

    def _on_right_click(self, pos):
        if self._snooze_cb:
            self._snooze_cb((self.wid, self._sub_key), self.mapToGlobal(pos))

    def _toggle_snooze(self):
        if self._snooze_cb:
            self._snooze_cb((self.wid, self._sub_key), None)

    def _snooze_hover_enter(self):
        key = "active_hover" if self._snoozed else "hover"
        pm = _snooze_qpixmaps.get(key)
        if pm:
            self._snooze_btn.setPixmap(pm)

    def _snooze_hover_leave(self):
        key = "active" if self._snoozed else "normal"
        pm = _snooze_qpixmaps.get(key)
        if pm:
            self._snooze_btn.setPixmap(pm)

    def set_snoozed(self, snoozed: bool):
        self._snoozed = snoozed
        self._snooze_btn.setToolTip(
            "Unsnooze - resume polling and notifications" if snoozed
            else "Snooze - pause polling, dim the row, mute notifications")
        dim_text = FG_DIM
        dim_muted = FG_DIMMER
        if snoozed:
            self._bg = BG_ROW_SNOOZED
            self._set_accent(ACCENT_DIM)
            self._info_lbl.setStyleSheet(_link_css(dim_muted, 11))
            self._name_lbl.setStyleSheet(_link_css(dim_text, 13))
            self._poll_lbl.setStyleSheet(f"color: {dim_muted}; font-size: 11px;")
            self._branch_lbl.setStyleSheet(_link_css(dim_muted, 11))
            self._target_lbl.setStyleSheet(_link_css(dim_muted, 11))
            self._pr_title_lbl.setStyleSheet(_link_css(dim_text, 13))
            if self._icon_opacity is None:
                self._icon_opacity = QGraphicsOpacityEffect(self._icon_lbl)
                self._icon_lbl.setGraphicsEffect(self._icon_opacity)
            self._icon_opacity.setOpacity(0.35)
        else:
            self._bg = BG_ROW
            self._set_accent(COLOUR.get(self._state.status, COLOUR[ST_UNKNOWN]))
            # Status may have changed while snoozed (update() skips the icon
            # when snoozed) — refresh the pixmap so icon and accent agree.
            self._icon_lbl.setPixmap(
                _status_qpixmaps.get(self._state.status, _status_qpixmaps.get(ST_UNKNOWN)))
            self._info_lbl.setStyleSheet(_link_css(FG_MUTED, 11))
            self._name_lbl.setStyleSheet(_link_css(FG_TITLE, 13))
            self._poll_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
            self._branch_lbl.setStyleSheet(_link_css(FG_MUTED, 11))
            self._target_lbl.setStyleSheet(_link_css(FG_MUTED, 11))
            self._pr_title_lbl.setStyleSheet(_link_css(FG_TITLE, 13))
            if self._icon_opacity is not None:
                self._icon_opacity.setOpacity(1.0)
        self._apply_background()
        self._restyle_static_badges()
        self._update_labels()

    def _badge_css(self, bg: str, fg: str, bold: bool = False) -> str:
        if self._snoozed:
            bg, fg = BADGE_DIM
        weight = "bold" if bold else "normal"
        return (f"background-color: {bg}; color: {fg}; font-size: 10px; "
                f"font-weight: {weight}; padding: 2px 6px; border-radius: 3px;")

    def _restyle_static_badges(self):
        self._prefix_lbl.setStyleSheet(self._badge_css(*BADGE_PREFIX))
        self._draft_lbl.setStyleSheet(self._badge_css(*BADGE_DRAFT, bold=True))
        self._conflict_lbl.setStyleSheet(self._badge_css(*BADGE_CONFLICT, bold=True))
        self._unresolved_lbl.setStyleSheet(self._badge_css(*BADGE_UNRESOLVED, bold=True))
        self._jira_lbl.setStyleSheet(self._badge_css(*BADGE_JIRA))

    def _open_jira(self):
        if self._jira_base_url and self._state.jira_key:
            webbrowser.open(f"{self._jira_base_url.rstrip('/')}/browse/{self._state.jira_key}")

    def update(self, state: WorkflowState, poll_rate: int, jira_base_url: str = ""):
        self._state = state
        self._jira_base_url = jira_base_url or self._jira_base_url
        if not self._snoozed:
            self._set_accent(COLOUR.get(state.status, COLOUR[ST_UNKNOWN]))
            pixmap = _status_qpixmaps.get(state.status, _status_qpixmaps.get(ST_UNKNOWN))
            self._icon_lbl.setPixmap(pixmap)
        self._poll_lbl.setText(f"{poll_rate}s")
        self._update_labels()

    def _update_labels(self):
        s = self._state
        status_txt = STATUS_LABEL.get(s.status, s.status)
        if s.error:
            status_txt = f"Error: {s.error}"
        elif s.run_number:
            status_txt = f"{status_txt} - run #{s.run_number}"
            if s.started_at:
                try:
                    dt = datetime.fromisoformat(s.started_at.replace("Z", "+00:00"))
                    dt_local = dt.astimezone()
                    status_txt += f"  ({dt_local.strftime('%d %b %H:%M')})"
                except Exception:
                    pass

        self._info_lbl.setText(status_txt)
        # Failed / errored runs get a red info line (design v2); everything
        # else stays muted. Snoozed rows keep their dimmed style.
        if not self._snoozed:
            info_col = COLOUR[ST_FAILURE] if (s.error or s.status == ST_FAILURE) else FG_MUTED
            self._info_lbl.setStyleSheet(_link_css(info_col, 11))

        has_badges = False
        if s.head_branch:
            # PR mode shows the PR title as the headline; actor mode falls back
            # to the workflow name (so the title link can point at the workflow).
            if s.pr_title:
                self._name_lbl.setVisible(False)
                self._name_branch_gap.setVisible(False)
                self._pr_title_lbl.setText(s.pr_title)
                self._pr_title_widget.setVisible(True)
            else:
                self._name_lbl.setText(s.name)
                self._name_lbl.setVisible(True)
                self._name_branch_gap.setVisible(True)
                self._pr_title_widget.setVisible(False)

            branch_text = s.branch_short or s.head_branch
            if s.pr_number:
                branch_text = f"#{s.pr_number}  {branch_text}"
            self._branch_lbl.setText(branch_text)
            self._branch_lbl.setVisible(True)
            # In PR mode the branch label is the run link; the target arrow
            # is its own label so the branch name remains the branch link.
            # branch_lbl keeps stretch=1 so target_lbl sits at the same
            # column as the branch subtitle in non-PR rows.
            if s.pr_number:
                self._branch_lbl.setToolTip("Open latest run on GitHub")
                if s.pr_target:
                    self._target_lbl.setText(f"→ {s.pr_target}")
                    self._target_lbl.setVisible(True)
                else:
                    self._target_lbl.setVisible(False)
            else:
                self._branch_lbl.setToolTip("Open branch on GitHub")
                self._target_lbl.setVisible(False)

            if s.branch_prefix:
                self._prefix_lbl.setText(s.branch_prefix)
                self._prefix_lbl.setVisible(True)
                has_badges = True
            else:
                self._prefix_lbl.setVisible(False)

            self._draft_lbl.setVisible(bool(s.is_draft))
            if s.is_draft:
                has_badges = True

            self._conflict_lbl.setVisible(bool(s.has_conflict))
            if s.has_conflict:
                has_badges = True

            if s.unresolved_threads > 0:
                self._unresolved_lbl.setText(f"{s.unresolved_threads} UNRESOLVED")
                self._unresolved_lbl.setVisible(True)
                has_badges = True
            else:
                self._unresolved_lbl.setVisible(False)

            if s.jira_key and self._jira_base_url:
                self._jira_lbl.setText(s.jira_key)
                self._jira_lbl.setVisible(True)
                has_badges = True
            else:
                self._jira_lbl.setVisible(False)

            if s.review_status:
                text, bg_col, fg_col = _REVIEW_BADGE_CFG.get(
                    s.review_status, ("REVIEW PENDING", *_P["REVIEW_PENDING"]))
                if s.review_status in ("approved", "changes_requested"):
                    kind = "bot" if s.review_by_bot else "user"
                    b64 = _reviewer_icon_b64(kind, fg_col, 12)
                    html = (f"<img src='data:image/png;base64,{b64}' "
                            f"width='11' height='11' "
                            f"style='vertical-align:middle' />&nbsp;{text}")
                    self._review_lbl.setText(html)
                    self._review_lbl.setToolTip(
                        "Reviewed by bot" if s.review_by_bot else "Reviewed by human")
                else:
                    self._review_lbl.setText(text)
                    self._review_lbl.setToolTip("")
                self._review_lbl.setStyleSheet(self._badge_css(bg_col, fg_col))
                self._review_lbl.setVisible(True)
                has_badges = True
            else:
                self._review_lbl.setVisible(False)
                self._review_lbl.setToolTip("")

            if s.staleness_level and s.pr_updated_at:
                bg_col, fg_col = _STALENESS_BADGE_CFG.get(s.staleness_level, _P["STALE_SLIGHT"])
                age = _format_age(s.pr_updated_at)
                self._stale_lbl.setText(f"STALE {age}" if age else "STALE")
                self._stale_lbl.setStyleSheet(self._badge_css(bg_col, fg_col, bold=True))
                self._stale_lbl.setVisible(True)
                has_badges = True
            else:
                self._stale_lbl.setVisible(False)

            self._snooze_lbl.setVisible(self._snoozed)
            if self._snoozed:
                has_badges = True

            self._badge_widget.setVisible(has_badges)
        else:
            self._name_lbl.setVisible(True)

            # Branch mode: surface the branch as a clickable subtitle alongside
            # the workflow-name title.
            if s.branch:
                self._branch_lbl.setText(s.branch)
                self._branch_lbl.setVisible(True)
                self._branch_lbl.setToolTip("Open branch on GitHub")
            else:
                self._branch_lbl.setVisible(False)
            self._target_lbl.setVisible(False)
            self._prefix_lbl.setVisible(False)
            self._draft_lbl.setVisible(False)
            self._conflict_lbl.setVisible(False)
            self._unresolved_lbl.setVisible(False)
            self._jira_lbl.setVisible(False)
            self._review_lbl.setVisible(False)
            self._stale_lbl.setVisible(False)
            self._pr_title_widget.setVisible(False)
            self._name_branch_gap.setVisible(True)

            self._snooze_lbl.setVisible(self._snoozed)
            self._badge_widget.setVisible(self._snoozed)

        # Name-label tooltip reflects whichever URL its click currently opens.
        if s.workflow_url:
            self._name_lbl.setToolTip("Open workflow on GitHub")
        else:
            self._name_lbl.setToolTip("Open latest run on GitHub")

        # Snooze button visibility (always visible)
        key = "active" if self._snoozed else "normal"
        self._snooze_btn.setPixmap(_snooze_qpixmaps.get(key, QPixmap()))
        self._snooze_btn.setVisible(True)
