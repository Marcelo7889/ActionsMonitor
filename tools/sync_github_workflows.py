#!/usr/bin/env python3
"""Add owned GitHub workflows to Actions Monitor without rewriting personal settings."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from urllib.parse import quote, unquote, urlparse

import requests
import yaml


class SyncError(Exception):
    pass


class GitHub:
    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get(self, path, params=None):
        response = self.session.get(f"https://api.github.com{path}", params=params,
                                    timeout=(10, 30), allow_redirects=False)
        if response.status_code != 200:
            raise SyncError(f"GitHub HTTP {response.status_code}: {path}")
        return response.json()

    def pages(self, path, key=None, **params):
        page = 1
        while True:
            data = self.get(path, dict(params, per_page=100, page=page))
            items = data[key] if key else data
            if not isinstance(items, list):
                raise SyncError("Resposta inesperada do GitHub")
            yield from items
            if len(items) < 100:
                return
            page += 1


def workflow_key(url):
    parsed = urlparse(str(url))
    parts = unquote(parsed.path).strip("/").split("/")
    if parsed.hostname != "github.com" or len(parts) != 5 or parts[2:4] != ["actions", "workflows"]:
        return None
    return parts[0].casefold(), parts[1].casefold(), parts[4]


def discover(api, owner):
    if api.get("/user").get("login", "").casefold() != owner.casefold():
        raise SyncError("O token configurado pertence a outra conta do GitHub")
    entries = []
    repositories = 0
    for repo in api.pages("/user/repos", affiliation="owner", sort="full_name"):
        if repo["owner"]["login"].casefold() != owner.casefold() or repo.get("archived") or repo.get("disabled"):
            continue
        repositories += 1
        full_name = repo["full_name"]
        for workflow in api.pages(f"/repos/{full_name}/actions/workflows", key="workflows"):
            path = workflow.get("path", "")
            if workflow.get("state") != "active" or not path.startswith(".github/workflows/"):
                continue
            filename = path.rsplit("/", 1)[-1]
            if not filename.endswith((".yml", ".yaml")):
                continue
            entries.append({
                "url": f"https://github.com/{full_name}/actions/workflows/{quote(filename, safe='')}",
                "name": f"{repo['name']} — {workflow.get('name') or filename}",
                "polling_rate": 60,
            })
    return repositories, entries


def additions(config, discovered):
    existing = config.get("workflows")
    if not isinstance(existing, list) or any(not isinstance(w, dict) for w in existing):
        raise SyncError("workflows precisa ser uma lista de configurações")
    seen = {workflow_key(w.get("url", "")) for w in existing}
    # Actor mode already covers every workflow in that repository.
    actors = set()
    for entry in existing:
        parts = urlparse(str(entry.get("url", ""))).path.strip("/").split("/")
        if entry.get("mode") == "actor" and len(parts) >= 2:
            actors.add(tuple(p.casefold() for p in parts[:2]))
        for url in entry.get("extra_workflows", []) or []:
            if isinstance(url, str):
                seen.add(workflow_key(url))
    result = []
    for entry in sorted(discovered, key=lambda w: w["url"].casefold()):
        key = workflow_key(entry["url"])
        if key and key not in seen and key[:2] not in actors:
            result.append(entry)
            seen.add(key)
    return result


def updated_bytes(original, config, new_entries):
    if not new_entries:
        return original
    # YAML node marks locate the sequence without rewriting comments or secrets.
    text = original.decode("utf-8")
    root = yaml.compose(text)
    nodes = [value for key, value in root.value if key.value == "workflows"]
    if len(nodes) != 1 or not isinstance(nodes[0], yaml.SequenceNode):
        raise SyncError("workflows precisa ser uma lista YAML única")
    node = nodes[0]
    block = yaml.safe_dump(new_entries, allow_unicode=True, sort_keys=False)
    if node.flow_style:
        if config["workflows"]:
            raise SyncError("workflows precisa usar uma lista YAML em bloco")
        indent = "  "
        block = "\n" + "".join(indent + line + "\n" for line in block.splitlines())
        candidate = (text[:node.start_mark.index] + block + text[node.end_mark.index:]).encode("utf-8")
    else:
        indent = " " * node.start_mark.column
        block = "".join(indent + line + "\n" for line in block.splitlines())
        end = node.end_mark.index
        candidate = (text[:end].rstrip("\n") + "\n" + block + text[end:]).encode("utf-8")
    expected = dict(config, workflows=config["workflows"] + new_entries)
    if yaml.safe_load(candidate) != expected:
        raise SyncError("A validação da configuração falhou; arquivo preservado")
    return candidate


def save(config_path, original, candidate):
    if config_path.read_bytes() != original:
        raise SyncError("Configuração alterada durante a busca; tentar novamente no próximo ciclo")
    backup = config_path.with_name("config.yaml.before-autodiscovery")
    try:
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
    fd, temporary = tempfile.mkstemp(prefix=".config-sync-", dir=config_path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(config_path.stat().st_mode) & 0o600)
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        if config_path.read_bytes() != original:
            raise SyncError("Configuração alterada durante a gravação; arquivo preservado")
        os.replace(temporary, config_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--apply", action="store_true", help="Gravar; por padrão apenas simula")
    args = parser.parse_args()
    path = args.config.resolve()
    try:
        # Lock the directory's inode, without writing a lock file during dry runs.
        lock = os.open(path.parent, os.O_RDONLY)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            original = path.read_bytes()
            config = yaml.safe_load(original)
            if not isinstance(config, dict) or not config.get("github_token"):
                raise SyncError("Token do GitHub ausente na configuração")
            repositories, entries = discover(GitHub(config["github_token"]), args.owner)
            new = additions(config, entries)
            candidate = updated_bytes(original, config, new)
            if args.apply and new:
                save(path, original, candidate)
            print(json.dumps({"repositorios": repositories, "workflows_ativos": len(entries),
                              "adicionados" if args.apply else "faltantes": [w["name"] for w in new],
                              "total_configurado": len(config["workflows"]) + (len(new) if args.apply else 0)},
                             ensure_ascii=False))
        finally:
            os.close(lock)
        return 0
    except BlockingIOError:
        print("Sincronização já em andamento")
        return 0
    except (SyncError, requests.RequestException, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        # Do not log HTTP bodies, headers or config fragments containing credentials.
        detail = str(exc) if isinstance(exc, SyncError) else type(exc).__name__
        print(f"Sincronização não concluída: {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
