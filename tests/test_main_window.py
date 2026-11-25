"""Integration tests for the main window (offscreen Qt, no network)."""

from __future__ import annotations

from demo_data import DEMO_CONFIG, demo_events
from pollers import StatusEvent, WorkflowState


def test_empty_state_shown_without_workflows(app_env):
    win = app_env.make_window("workflows: []\n")
    assert win._empty_state is not None
    assert win._empty_state.isVisible()
    assert win._summary_lbl.text() == "No workflows monitored"


def test_branch_row_created_at_startup(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    assert win._empty_state is None
    # Two branch-mode rows exist immediately; PR rows appear per event.
    assert (0, None) in win._rows
    assert (1, None) in win._rows
    assert len(win._rows) == 2


def test_events_render_rows_and_summary(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    assert len(win._rows) == 4
    # 1 failed (production), 1 running (PR 4308), 2 passing
    assert win._summary_lbl.text() == "1 failed · 1 running · 2 passing"
    assert win._updated_lbl.text().startswith("Updated ")
    # Worst status escalates the summary dot to the failure colour
    from widgets import COLOUR
    assert COLOUR["failure"] in win._summary_dot.styleSheet()


def test_section_counts(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    assert win._section_counts["Workflows"].text() == "2"
    assert win._section_counts["Acceptance/PR"].text() == "2"


def test_pr_row_removal(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    events = demo_events()
    for ev in events:
        app_env.push(win, ev)
    sub_key = events[2].sub_key
    app_env.push(win, StatusEvent(2, events[2].new_state, sub_key=sub_key, removed=True))
    assert (2, sub_key) not in win._rows
    assert win._section_counts["Acceptance/PR"].text() == "1"
    assert win._summary_lbl.text() == "1 failed · 2 passing"


def test_snooze_toggle_and_summary_exclusion(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    key = (1, None)  # the failing production row
    win._toggle_snooze(key)
    assert key in win._snoozed
    assert win._rows[key]._snoozed
    win._update_summary()
    assert win._summary_lbl.text() == "1 running · 2 passing"
    win._toggle_snooze(key)
    assert key not in win._snoozed
    assert not win._rows[key]._snoozed


def test_sort_menu_state(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    win._set_sort("Workflows", "status_asc")
    assert win._sort_labels["Workflows"].text() == f"Sort: Status {win._ARROW_UP}"
    # Persisted
    state = win._load_state()
    assert state["section_sort"]["Workflows"] == "status_asc"
    win._clear_sort("Workflows")
    assert win._sort_labels["Workflows"].text() == "Sort ▾"
    assert "section_sort" not in win._load_state()


def test_failed_row_info_line_is_red(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    from widgets import COLOUR
    failed_row = win._rows[(1, None)]
    ok_row = win._rows[(0, None)]
    assert COLOUR["failure"] in failed_row._info_lbl.styleSheet()
    assert COLOUR["failure"] not in ok_row._info_lbl.styleSheet()


def test_error_state_renders(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    app_env.push(win, StatusEvent(0, WorkflowState(
        name="Acceptance Merge", url="", branch="acceptance",
        status="failure", error="404 - repository not found. Check your token's repo scope.")))
    row = win._rows[(0, None)]
    assert "Error: 404" in row._info_lbl.text()


def test_beta_gating_off_by_default(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    assert win._settings_btn.isVisible()
    assert win._settings_btn.toolTip() == "Descoberta automática"
    assert not win._footer_settings_lbl.isVisible()
    assert win._footer_config_lbl.isVisible()


def test_beta_gating_on(app_env):
    win = app_env.make_window("beta:\n  settings_ui: true\nworkflows: []\n")
    assert win._settings_btn.isVisible()
    assert win._footer_settings_lbl.isVisible()
    assert not win._footer_config_lbl.isVisible()


def test_beta_env_override(app_env, monkeypatch):
    monkeypatch.setenv("ACTIONS_MONITOR_BETA", "settings_ui")
    win = app_env.make_window(DEMO_CONFIG)  # config has no beta block
    assert win._settings_btn.isVisible()
    assert win._footer_settings_lbl.isVisible()


def test_beta_gating_follows_config_reload(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    assert win._settings_btn.toolTip() == "Descoberta automática"
    app_env.config_path.write_text(
        "beta:\n  settings_ui: true\n" + DEMO_CONFIG, encoding="utf-8")
    win._config_mgr._mtime = 0  # force mtime-diff so load() reports a change
    win._watch_config()
    assert win._settings_btn.isVisible()
    assert win._settings_btn.toolTip() == "Settings"


# ---------------------------------------------------------------------------
# Screenshots (also run standalone via `task screenshots`)
# ---------------------------------------------------------------------------
def test_screenshot_main_empty(app_env, screenshot):
    win = app_env.make_window("workflows: []\n")
    win.resize(460, 420)
    screenshot(win, "main-empty")


def test_screenshot_main_populated(app_env, screenshot):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    win.resize(620, 560)
    screenshot(win, "main-populated")


def test_screenshot_main_snoozed(app_env, screenshot):
    win = app_env.make_window(DEMO_CONFIG)
    events = demo_events()
    for ev in events:
        app_env.push(win, ev)
    win._toggle_snooze((2, events[3].sub_key))
    win.resize(620, 560)
    screenshot(win, "main-snoozed-row")


# ---------------------------------------------------------------------------
# Tray / window visibility (KDE Plasma integration)
# ---------------------------------------------------------------------------
def _with_tray(monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))


def test_toggle_window_hides_and_restores(app_env, monkeypatch):
    _with_tray(monkeypatch)
    win = app_env.make_window("workflows: []\n")
    assert win.isVisible()
    win._toggle_window()
    assert not win.isVisible()
    win._toggle_window()
    assert win.isVisible()


def test_tray_single_click_toggles_on_linux(app_env, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    m = app_env.main
    monkeypatch.setattr(m, "IS_LINUX", True)
    _with_tray(monkeypatch)
    win = app_env.make_window("workflows: []\n")
    # StatusNotifierItem hosts (Plasma) send Trigger for a left click.
    win._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert not win.isVisible()
    win._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert win.isVisible()


def test_tray_single_click_ignored_on_windows(app_env, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    m = app_env.main
    monkeypatch.setattr(m, "IS_LINUX", False)
    _with_tray(monkeypatch)
    win = app_env.make_window("workflows: []\n")
    # Windows keeps the historical double-click-to-show behaviour.
    win._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert win.isVisible()


def test_no_tray_host_means_no_tray(app_env, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    win = app_env.make_window("workflows: []\n")
    assert win._tray is None


def test_close_and_minimise_hide_to_tray(app_env, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    from PySide6.QtCore import Qt
    _with_tray(monkeypatch)
    win = app_env.make_window("workflows: []\n")
    assert win._tray is not None
    win._sync_tray_menu()
    assert win._tray_toggle_action.text() == "Hide"

    win.close()  # "Minimize to tray" is on by default
    app_env.main.QApplication.processEvents()
    assert not win.isVisible()
    win._sync_tray_menu()
    assert win._tray_toggle_action.text() == "Show"

    win._show_window()
    win.setWindowState(Qt.WindowState.WindowMinimized)
    for _ in range(3):
        app_env.main.QApplication.processEvents()
    assert not win.isVisible()


# ---------------------------------------------------------------------------
# Child-process environment (frozen Linux builds)
# ---------------------------------------------------------------------------
def test_frozen_linux_child_env_is_restored(app_env, monkeypatch):
    import sys
    m = app_env.main
    monkeypatch.setattr(m, "IS_LINUX", True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/am/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    monkeypatch.setenv("QT_PLUGIN_PATH", "/opt/am/_internal/PySide6/Qt/plugins")
    monkeypatch.setenv("QML2_IMPORT_PATH", "/opt/am/_internal/PySide6/Qt/qml")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb;wayland")
    m._restore_child_environment(forced_qpa=True)
    for var in ("LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM"):
        assert var not in m.os.environ, var


def test_frozen_linux_keeps_users_own_library_path(app_env, monkeypatch):
    import sys
    m = app_env.main
    monkeypatch.setattr(m, "IS_LINUX", True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/am/_internal:/home/u/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/home/u/lib")
    m._restore_child_environment(forced_qpa=False)
    assert m.os.environ["LD_LIBRARY_PATH"] == "/home/u/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in m.os.environ


def test_source_run_leaves_env_alone(app_env, monkeypatch):
    m = app_env.main
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/somewhere")
    m._restore_child_environment(forced_qpa=False)  # not frozen, user's QPA
    assert m.os.environ["QT_QPA_PLATFORM"] == "offscreen"
    assert m.os.environ["QT_PLUGIN_PATH"] == "/somewhere"
