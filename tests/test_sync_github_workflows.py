import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml

SPEC = importlib.util.spec_from_file_location(
    "sync", Path(__file__).resolve().parents[1] / "tools/sync_github_workflows.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def entry(repo="new", filename="deploy.yml"):
    return {"url": f"https://github.com/Marcelo7889/{repo}/actions/workflows/{filename}",
            "name": f"{repo} — Publicação", "polling_rate": 60}


class SyncTests(unittest.TestCase):
    def test_existing_settings_comments_token_and_following_keys_preserved(self):
        for indent in ("", "  "):
            original = ("# cabeçalho\ngithub_token: 'secret' # comentário\nworkflows:\n"
                        + indent + "- url: https://github.com/Marcelo7889/old/actions/workflows/deploy.yml\n"
                        + indent + "  polling_rate: 10\n# opção personalizada\nbeta:\n  settings_ui: true\n").encode()
            config = yaml.safe_load(original)
            result = sync.updated_bytes(original, config, [entry()])
            self.assertEqual(yaml.safe_load(result), dict(config, workflows=config['workflows'] + [entry()]))
            for fragment in ("github_token: 'secret' # comentário".encode(),
                             b"# cabe", b"# op", b"polling_rate: 10", b"settings_ui: true"):
                self.assertIn(fragment, result)

    def test_empty_list_and_missing_newline(self):
        for original in (b"github_token: abc\nworkflows: []", b"github_token: abc\nworkflows:\n- url: old"):
            config = yaml.safe_load(original)
            self.assertEqual(yaml.safe_load(sync.updated_bytes(original, config, [entry()]))['workflows'],
                             config['workflows'] + [entry()])

    def test_deduplication_case_branch_filter_and_actor(self):
        old = entry()
        old['url'] = old['url'].replace('Marcelo7889/new', 'marcelo7889/NEW') + '?branch=main'
        config = {'workflows': [old, {'mode': 'actor', 'url': 'https://github.com/Marcelo7889/actor/actions'}]}
        self.assertEqual(sync.additions(config, [entry(), entry('actor'), entry('other'), entry('other')]),
                         [entry('other')])

    def test_idempotent_noop_is_byte_identical(self):
        original = b"github_token: secret\nworkflows: []\n"
        self.assertIs(sync.updated_bytes(original, yaml.safe_load(original), []), original)

    def test_atomic_save_backup_and_concurrent_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.yaml'
            original = b"github_token: secret\nworkflows: []\n"
            path.write_bytes(original)
            candidate = sync.updated_bytes(original, yaml.safe_load(original), [entry()])
            sync.save(path, original, candidate)
            self.assertEqual(path.read_bytes(), candidate)
            self.assertEqual(path.with_name('config.yaml.before-autodiscovery').read_bytes(), original)
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            with self.assertRaises(sync.SyncError):
                sync.save(path, original, original)
            self.assertEqual(path.read_bytes(), candidate)

    def test_pagination_over_100(self):
        api = object.__new__(sync.GitHub)
        calls = []
        def get(path, params):
            calls.append(params['page'])
            return list(range(100)) if params['page'] == 1 else [101]
        api.get = get
        self.assertEqual(len(list(api.pages('/user/repos'))), 101)
        self.assertEqual(calls, [1, 2])

    def test_only_active_owned_workflows_including_new_projects(self):
        class API:
            def get(self, path):
                return {'login': 'Marcelo7889'}
            def pages(self, path, **params):
                if path == '/user/repos':
                    return [{'name': name, 'full_name': f'Marcelo7889/{name}',
                             'owner': {'login': 'Marcelo7889'}, 'archived': archived}
                            for name, archived in [('new', False), ('archived', True)]]
                return [{'path': '.github/workflows/deploy.yml', 'name': 'Deploy', 'state': 'active'},
                        {'path': '.github/workflows/disabled.yml', 'state': 'disabled_manually'},
                        {'path': 'dynamic/dependabot', 'state': 'active'}]
        count, entries = sync.discover(API(), 'Marcelo7889')
        self.assertEqual(count, 1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(sync.workflow_key(entries[0]['url']), ('marcelo7889', 'new', 'deploy.yml'))

    def test_wrong_account_and_invalid_yaml_are_rejected(self):
        class API:
            def get(self, path):
                return {'login': 'other'}
        with self.assertRaises(sync.SyncError):
            sync.discover(API(), 'Marcelo7889')
        with self.assertRaises(sync.SyncError):
            sync.additions({'workflows': 'bad'}, [entry()])


if __name__ == '__main__':
    unittest.main()
