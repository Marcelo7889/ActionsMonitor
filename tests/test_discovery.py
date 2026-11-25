"""Native discovery: GitHub pagination, opt-in, persistence and Qt lifecycle."""
from __future__ import annotations

import queue
import threading
from unittest.mock import Mock

import pytest
import requests
import yaml

import discovery
from discovery import (DiscoveryOptions, DiscoveryResult, RepositoryDiscovery,
                       append_workflows, discovery_options, missing_workflows)
import gh_api
import settings_ui


def entry(repo="new", workflow="deploy.yml"):
    return {"url": f"https://github.com/example/{repo}/actions/workflows/{workflow}",
            "name": f"{repo} — Publicação", "polling_rate": 60}


CONFIG = ("# configuração pessoal\ngithub_token: test-token\n"
          "autodiscovery:\n  enabled: true\n  interval: 5m\nworkflows: []\n")
OPTIONS = discovery_options(yaml.safe_load(CONFIG))


def test_defaults_are_opt_in_and_credentials_are_not_in_repr():
    assert not discovery_options({}).enabled
    assert discovery_options({}).interval == 300
    assert "secret" not in repr(DiscoveryOptions(token="secret"))
    opts = discovery_options({'autodiscovery': {'enabled': 'false', 'interval': -1, 'polling_rate': 'bad'}})
    assert not opts.enabled
    assert opts.interval == 60
    assert opts.polling_rate == 60


def test_paginates_repositories_and_workflows_and_uses_authenticated_account(monkeypatch):
    calls = []
    repo = lambda name, **extra: dict(name=name, full_name=f"example/{name}",
                                     owner={'login': 'example'}, **extra)
    workflow = lambda name, **extra: dict(name=name, path=f".github/workflows/{name}.yml",
                                        state='active', **extra)
    def get(url, token, session, params=None):
        calls.append((url, params))
        assert token == 'test-token'
        if url.endswith('/user'):
            return {'login': 'Example'}
        if url.endswith('/user/repos'):
            assert params['affiliation'] == 'owner'
            if params['page'] == 1:
                return [repo(str(i), archived=True) for i in range(100)]
            return [repo('new'), repo('disabled', disabled=True),
                    dict(name='other', full_name='someone/other', owner={'login': 'someone'})]
        if params['page'] == 1:
            return {'workflows': [workflow(str(i)) for i in range(100)]}
        return {'workflows': [workflow('last'), {'name': 'bot', 'state': 'active', 'path': 'dynamic/bot'},
                              {'name': 'old', 'state': 'disabled_manually', 'path': '.github/workflows/old.yml'}]}
    monkeypatch.setattr(discovery, '_github_api_get', get)
    account, entries, warnings = discovery.discover_workflows(OPTIONS, None)
    assert account == 'Example'
    assert len(entries) == 101
    assert not warnings
    assert len(calls) == 5
    assert all('/example/new/' in e['url'] for e in entries)


def test_missing_workflows_avoids_duplicates_and_covered_sections():
    old = entry()
    old['url'] = old['url'].replace('/example/new/', '/EXAMPLE/NEW/') + '?query=branch%3Amain'
    existing = [old, {'url': entry('pr')['url'], 'mode': 'pr', 'extra_workflows': ['lint.yml']},
                {'url': 'https://github.com/example/actor/actions', 'mode': 'actor'},
                {'url': 'https://github.com/example/failed/actions', 'mode': 'actor', 'filter': 'failed'}]
    assert missing_workflows(existing, [entry(), entry('pr', 'lint.yml'), entry('actor'),
                                        entry('failed'), entry('next'), entry('next')]) == [entry('failed'), entry('next')]


@pytest.mark.parametrize('workflows', ['workflows: []\n', 'workflows:\n  - url: old\n    polling_rate: 10\n',
                                       'workflows: [{url: old, polling_rate: 10}]\n', ''])
def test_persistence_preserves_settings_comments_and_is_idempotent(tmp_path, workflows):
    path = tmp_path / 'config.yaml'
    text = CONFIG.split('workflows:')[0] + workflows + '# manter\nbeta:\n  settings_ui: false\n'
    path.write_text(text)
    before = yaml.safe_load(text)
    assert append_workflows(path, [entry()], OPTIONS) == [entry()]
    after = path.read_text()
    parsed = yaml.safe_load(after)
    assert parsed['workflows'] == before.get('workflows', []) + [entry()]
    assert {k: v for k, v in parsed.items() if k != 'workflows'} == {k: v for k, v in before.items() if k != 'workflows'}
    assert '# configuração pessoal' in after and '# manter' in after
    assert append_workflows(path, [entry()], OPTIONS) == []
    assert path.read_text() == after


@pytest.mark.parametrize('replacement', [CONFIG.replace('enabled: true', 'enabled: false'),
                                         CONFIG.replace('test-token', 'another-account-token')])
def test_results_cannot_write_after_disable_or_account_change(tmp_path, replacement):
    path = tmp_path / 'config.yaml'
    path.write_text(replacement)
    assert append_workflows(path, [entry()], OPTIONS) == []
    assert path.read_text() == replacement


def test_concurrent_edit_is_preserved_and_temporary_file_is_cleaned(tmp_path, monkeypatch):
    path = tmp_path / 'config.yaml'
    path.write_text(CONFIG)
    original = discovery._append_yaml
    def edit(*args):
        candidate = original(*args)
        path.write_text(CONFIG + '# external edit\n')
        return candidate
    monkeypatch.setattr(discovery, '_append_yaml', edit)
    with pytest.raises(ValueError):
        append_workflows(path, [entry()], OPTIONS)
    assert path.read_text() == CONFIG + '# external edit\n'
    assert not list(tmp_path.glob('.autodiscovery-*'))


def test_corrupt_config_is_never_rewritten(tmp_path):
    path = tmp_path / 'config.yaml'
    text = CONFIG + 'notifications: [broken\n'
    path.write_text(text)
    with pytest.raises(yaml.YAMLError):
        append_workflows(path, [entry()], OPTIONS)
    assert path.read_text() == text


def test_disabled_worker_does_no_network_and_enable_starts_immediately(monkeypatch):
    fetch = Mock(return_value=('example', [entry()], []))
    monkeypatch.setattr(discovery, 'discover_workflows', fetch)
    results = queue.Queue()
    worker = RepositoryDiscovery({}, results)
    worker.start()
    try:
        assert not fetch.called
        worker.configure(yaml.safe_load(CONFIG))
        first = results.get(timeout=2)
        assert worker.is_current(first)
        assert first.entries == [entry()]
        fetch.return_value = ('example', [entry(), entry('new-project')], [])
        worker.trigger_poll()
        assert len(results.get(timeout=2).entries) == 2
        worker.configure({'autodiscovery': {'enabled': False}})
        assert not worker.is_current(first)
        assert worker.status == 'Desativada'
    finally:
        worker.stop()
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_late_results_are_discarded_when_disabled_during_fetch(monkeypatch):
    started, release = threading.Event(), threading.Event()
    def fetch(*args):
        started.set()
        assert release.wait(2)
        return 'example', [entry()], []
    monkeypatch.setattr(discovery, 'discover_workflows', fetch)
    results = queue.Queue()
    worker = RepositoryDiscovery(yaml.safe_load(CONFIG), results)
    worker.start()
    try:
        assert started.wait(2)
        worker.configure({'autodiscovery': {'enabled': False}})
        release.set()
        worker.stop()
        worker.join(timeout=2)
        assert results.empty()
    finally:
        release.set()
        worker.stop()
        worker.join(timeout=2)


def test_worker_reports_auth_failure_without_leaking_token(monkeypatch):
    response = requests.Response()
    response.status_code = 401
    monkeypatch.setattr(discovery, 'discover_workflows', Mock(side_effect=requests.HTTPError(response=response)))
    results = queue.Queue()
    worker = RepositoryDiscovery(yaml.safe_load(CONFIG), results)
    worker.start()
    try:
        result = results.get(timeout=2)
        assert result.error == 'Token inválido ou expirado.'
        assert not result.entries
        assert 'test-token' not in repr(result)
    finally:
        worker.stop()
        worker.join(timeout=2)


def test_qt_consumes_discovery_result_and_starts_monitoring_new_workflows(app_env):
    win = app_env.make_window(CONFIG)
    win._discovery_queue.put(DiscoveryResult(0, 'example', [entry()]))
    win._drain_queue()
    assert len(win._pollers) == 1
    assert win._states[(0, None)].name == entry()['name']
    assert len(win._config_mgr.get()['workflows']) == 1
    assert '1 workflow(s)' in win._discovery.status
    win._discovery_queue.put(DiscoveryResult(0, 'example', [entry()]))
    win._drain_queue()
    assert len(win._pollers) == 1
    assert '0 workflow(s)' in win._discovery.status


def test_qt_rejects_old_generation(app_env):
    win = app_env.make_window(CONFIG)
    app_env.config_path.write_text(CONFIG.replace('enabled: true', 'enabled: false'))
    win._discovery_queue.put(DiscoveryResult(0, 'example', [entry()]))
    before = app_env.config_path.read_bytes()
    win._drain_queue()
    assert app_env.config_path.read_bytes() == before
    assert not win._pollers


def test_missing_token_does_not_call_github(monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(discovery, 'discover_workflows', fetch)
    results = queue.Queue()
    worker = RepositoryDiscovery({'autodiscovery': {'enabled': True}}, results)
    worker.start()
    try:
        result = results.get(timeout=2)
        assert 'token' in result.error
        assert not fetch.called
    finally:
        worker.stop()
        worker.join(timeout=2)


def test_one_inaccessible_repository_does_not_block_other_repositories(monkeypatch):
    def get(url, token, session, params=None):
        if url.endswith('/user'):
            return {'login': 'example'}
        if url.endswith('/user/repos'):
            return [dict(name=n, full_name=f'example/{n}', owner={'login': 'example'})
                    for n in ('blocked', 'ok')]
        if '/blocked/' in url:
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError(response=response)
        return {'workflows': [{'name': 'CI', 'path': '.github/workflows/ci.yml', 'state': 'active'}]}
    monkeypatch.setattr(discovery, '_github_api_get', get)
    account, entries, warnings = discovery.discover_workflows(OPTIONS, None)
    assert len(entries) == 1 and '/ok/' in entries[0]['url']
    assert warnings == ['example/blocked (HTTP 403)']


def test_full_settings_includes_discovery(app_env):
    app_env.config_path.write_text(CONFIG)
    manager = app_env.main.ConfigManager()
    dialog = settings_ui.SettingsDialog(manager)
    dialog._select_tab('github')
    assert dialog._discovery_widget._enabled_cb.isChecked()
    dialog.close()


def test_settings_toggle_interval_and_disable_are_persisted(app_env, qapp):
    win = app_env.make_window(CONFIG.replace('enabled: true', 'enabled: false'))
    widget = settings_ui.DiscoverySettingsWidget(win._config_mgr, win._discovery)
    assert not widget._enabled_cb.isChecked()
    widget._enabled_cb.setChecked(True)
    assert yaml.safe_load(app_env.config_path.read_text())['autodiscovery']['enabled'] is True
    assert win._discovery.options.enabled
    widget._interval_combo.setCurrentIndex(widget._interval_combo.findData('15m'))
    assert win._discovery.options.interval == 900
    assert yaml.safe_load(app_env.config_path.read_text())['autodiscovery']['interval'] == '15m'
    assert '# configuração pessoal' in app_env.config_path.read_text()
    # The settings save loads the snapshot before the main watcher runs.
    win._watch_config()
    assert win._active_config is win._config_mgr.get()
    widget._enabled_cb.setChecked(False)
    assert not win._discovery.options.enabled
    assert not widget._scan_btn.isEnabled()
    widget.close()


def test_gear_opens_discovery_without_beta(app_env, monkeypatch):
    win = app_env.make_window('workflows: []\n')
    opened = []
    monkeypatch.setattr(settings_ui.DiscoverySettingsDialog, 'exec', lambda dialog: opened.append(dialog))
    win._open_settings()
    assert opened and not opened[0]._discovery_widget._enabled_cb.isChecked()
    opened[0].close()


def test_etag_cache_is_scoped_to_token():
    session = Mock()
    response = Mock(status_code=200, headers={'ETag': 'etag'})
    response.json.return_value = {'login': 'first'}
    session.get.return_value = response
    gh_api._github_api_get('https://api.github.com/user', 'first-token', session)
    gh_api._github_api_get('https://api.github.com/user', 'second-token', session)
    assert 'If-None-Match' not in session.get.call_args.kwargs['headers']


def test_screenshot_discovery_settings(app_env, qapp, screenshot):
    win = app_env.make_window(CONFIG)
    dialog = settings_ui.DiscoverySettingsDialog(win._config_mgr, win._discovery)
    dialog.show()
    qapp.processEvents()
    screenshot(dialog, 'settings-discovery')
    dialog.close()
