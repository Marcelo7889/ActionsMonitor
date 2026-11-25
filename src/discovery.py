"""Opt-in repository discovery. Workers only fetch; Qt applies config changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import queue
import tempfile
import threading
from urllib.parse import quote, unquote, urlparse

import requests
import yaml

from gh_api import _github_api_get, _build_workflow_url, RateLimited
from pollers import parse_duration


@dataclass(frozen=True)
class DiscoveryOptions:
    token: str = field(default="", repr=False)
    enabled: bool = False
    interval: int = 300
    polling_rate: int = 60


def discovery_options(config: dict) -> DiscoveryOptions:
    raw = config.get("autodiscovery") or {}
    if not isinstance(raw, dict):
        raw = {}
    try:
        parsed = parse_duration(raw.get("interval", "5m"))
        interval = max(60, parsed) if parsed else 300
    except (ValueError, TypeError, OverflowError):
        interval = 300
    try:
        polling_rate = max(10, int(raw.get("polling_rate", 60)))
    except (ValueError, TypeError, OverflowError):
        polling_rate = 60
    return DiscoveryOptions(str(config.get("github_token") or "").strip(),
                            raw.get("enabled") is True, interval, polling_rate)


@dataclass
class DiscoveryResult:
    generation: int
    account: str = ""
    entries: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def _pages(path, token, session, key=None, **params):
    page = 1
    while True:
        data = _github_api_get(f"https://api.github.com{path}", token, session,
                               dict(params, page=page, per_page=100))
        items = data[key] if key else data
        if not isinstance(items, list):
            raise ValueError("Unexpected GitHub response")
        yield from items
        if len(items) < 100:
            return
        page += 1


def discover_workflows(options: DiscoveryOptions, session, cancelled=lambda: False):
    """Return owned active workflows (all pages), plus inaccessible repositories."""
    if not options.token:
        raise ValueError("missing-token")
    account = _github_api_get("https://api.github.com/user", options.token, session)["login"]
    entries, warnings = [], []
    for repo in _pages("/user/repos", options.token, session,
                       affiliation="owner", sort="full_name"):
        if cancelled():
            break
        if (repo["owner"]["login"].casefold() != account.casefold()
                or repo.get("archived") or repo.get("disabled")):
            continue
        owner, name = repo["full_name"].split("/", 1)
        try:
            for workflow in _pages(f"/repos/{owner}/{name}/actions/workflows", options.token,
                                   session, key="workflows"):
                if cancelled():
                    break
                path = workflow.get("path", "")
                if (workflow.get("state") != "active"
                        or not path.startswith(".github/workflows/")
                        or not path.endswith((".yml", ".yaml"))):
                    continue
                filename = path.rsplit("/", 1)[-1]
                entries.append({"url": _build_workflow_url(owner, name, quote(filename, safe="")),
                                "name": f"{name} — {workflow.get('name') or filename}",
                                "polling_rate": options.polling_rate})
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code not in (403, 404):
                raise
            warnings.append(f"{owner}/{name} (HTTP {code})")
    return account, entries, warnings


def _workflow_key(url):
    parsed = urlparse(str(url))
    parts = unquote(parsed.path).strip("/").split("/")
    if (parsed.hostname != "github.com" or len(parts) != 5
            or parts[2:4] != ["actions", "workflows"]):
        return None
    return parts[0].casefold(), parts[1].casefold(), parts[4]


def missing_workflows(existing, discovered):
    if not isinstance(existing, list) or any(not isinstance(w, dict) for w in existing):
        raise ValueError("Invalid workflows list")
    seen, actors = set(), set()
    for entry in existing:
        key = _workflow_key(entry.get("url", ""))
        mode = entry.get("mode", "branch")
        if mode == "actor":
            parsed = urlparse(str(entry.get("url", "")))
            parts = parsed.path.strip("/").split("/")
            # Only unfiltered actor sections cover every workflow in the repo.
            if parsed.hostname == "github.com" and len(parts) >= 2 and not entry.get("filter"):
                actors.add(tuple(p.casefold() for p in parts[:2]))
        if key and mode in ("branch", "pr"):
            seen.add(key)
            if mode == "pr":
                for extra in entry.get("extra_workflows") or []:
                    if isinstance(extra, str):
                        extra_key = _workflow_key(extra) or (key[0], key[1], extra)
                        seen.add(extra_key)
    result = []
    for entry in sorted(discovered, key=lambda w: w["url"].casefold()):
        key = _workflow_key(entry["url"])
        if key and key not in seen and key[:2] not in actors:
            seen.add(key)
            result.append(entry)
    return result


def _append_yaml(original: bytes, config: dict, entries: list[dict]) -> bytes:
    """Extend only the YAML sequence, preserving comments, token and settings."""
    text = original.decode("utf-8")
    root = yaml.compose(text)
    nodes = [value for key, value in root.value if key.value == "workflows"]
    block = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False)
    if not nodes:
        end = root.end_mark.index
        text = text[:end].rstrip("\n") + "\nworkflows:\n" + block + text[end:]
    elif len(nodes) != 1 or not isinstance(nodes[0], yaml.SequenceNode):
        raise ValueError("workflows precisa ser uma lista YAML única")
    elif nodes[0].flow_style:
        node = nodes[0]
        # Flow lists are uncommon, but preserve them and their existing settings.
        # Every entry must already have been parsed before we reach this point.
        combined = yaml.safe_dump(config.get("workflows", []) + entries,
                                  allow_unicode=True, sort_keys=False)
        block = "\n" + "".join("  " + line + "\n" for line in combined.splitlines())
        text = text[:node.start_mark.index] + block + text[node.end_mark.index:]
    else:
        node = nodes[0]
        indent = " " * node.start_mark.column
        block = "".join(indent + line + "\n" for line in block.splitlines())
        end = node.end_mark.index
        text = text[:end].rstrip("\n") + "\n" + block + text[end:]
    expected = dict(config, workflows=(config.get("workflows") or []) + entries)
    if yaml.safe_load(text) != expected:
        raise ValueError("A validação da configuração falhou; arquivo preservado")
    return text.encode("utf-8")


def append_workflows(path: Path, discovered: list[dict], options: DiscoveryOptions):
    """Called on Qt's thread; reject disabled discovery, stale tokens and edits."""
    original = path.read_bytes()
    config = yaml.safe_load(original)
    if not isinstance(config, dict) or discovery_options(config) != options or not options.enabled:
        return []
    entries = missing_workflows(config.get("workflows", []), discovered)
    if not entries:
        return []
    candidate = _append_yaml(original, config, entries)
    fd, temporary = tempfile.mkstemp(prefix=".autodiscovery-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise ValueError("Configuração alterada durante a busca; nova tentativa no próximo ciclo")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return entries


class RepositoryDiscovery(threading.Thread):
    """A single cancellable worker. Results are persisted by the Qt consumer."""
    def __init__(self, config, results: queue.Queue):
        super().__init__(name="repository-discovery", daemon=True)
        self.results = results
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._wake = threading.Event()
        self._generation = 0
        self._options = discovery_options(config)
        self._status = "Aguardando busca" if self._options.enabled else "Desativada"

    @property
    def options(self):
        with self._lock:
            return self._options

    @property
    def status(self):
        with self._lock:
            return self._status

    def configure(self, config):
        options = discovery_options(config)
        with self._lock:
            if options == self._options:
                return
            self._options = options
            self._generation += 1
            self._status = "Aguardando busca" if options.enabled else "Desativada"
        self._wake.set()

    def is_current(self, result):
        with self._lock:
            return (not self._stop_evt.is_set() and self._options.enabled
                    and result.generation == self._generation)

    def set_status(self, result, text):
        with self._lock:
            if result.generation == self._generation and self._options.enabled:
                self._status = text

    def trigger_poll(self):
        self._wake.set()

    def stop(self):
        self._stop_evt.set()
        self._wake.set()

    def run(self):
        with requests.Session() as session:
            while not self._stop_evt.is_set():
                self._wake.clear()
                with self._lock:
                    options, generation = self._options, self._generation
                if options.enabled:
                    result = DiscoveryResult(generation)
                    self.set_status(result, "Buscando repositórios…")
                    try:
                        if not options.token:
                            result.error = "Configure um token do GitHub para habilitar a busca."
                        else:
                            result.account, result.entries, result.warnings = discover_workflows(
                                options, session, lambda: not self.is_current(result))
                    except RateLimited:
                        result.error = "Limite do GitHub atingido; a busca será retomada automaticamente."
                    except requests.HTTPError as exc:
                        code = exc.response.status_code if exc.response is not None else "?"
                        result.error = ("Token inválido ou expirado." if code == 401
                                        else f"Não foi possível consultar o GitHub (HTTP {code}).")
                    except requests.RequestException:
                        result.error = "Não foi possível acessar o GitHub. Nova tentativa no próximo ciclo."
                    except Exception as exc:
                        result.error = "Não foi possível concluir a busca. Nova tentativa no próximo ciclo."
                        print(f"[Discovery] {type(exc).__name__}")
                    if self.is_current(result):
                        self.results.put(result)
                self._wake.wait(options.interval if options.enabled else None)


def result_status(result: DiscoveryResult, added: int):
    if result.error:
        return result.error
    text = f"{result.account} · última busca às {datetime.now():%H:%M} · {added} workflow(s) adicionado(s)"
    if result.warnings:
        text += ". Sem acesso: " + ", ".join(result.warnings)
    return text
