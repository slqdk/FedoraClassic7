"""Command Prompt assistant: settings and the client for a local language model.

Talks to Ollama's own API (/api/chat, /api/tags) or to any OpenAI-compatible server
(/v1/chat/completions, /v1/models: llama.cpp server, LM Studio, vLLM, Ollama's /v1).
Only the standard library is used, so the CLI works without Qt.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import socket
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "classic7"
CONFIG_FILE = CONFIG_DIR / "prompt.json"
SYSTEM_CONFIG = Path("/etc/classic7/prompt.json")

PREFERRED_MODELS = ("qwen3", "qwen2.5-coder", "qwen2.5", "llama3", "mistral", "gemma")


@dataclass
class Settings:
    server: str = "http://30.11.0.104:11434"
    api: str = "ollama"            # "ollama" or "openai"
    model: str = ""                # empty: pick a suitable installed model
    api_key: str = ""              # only for OpenAI-compatible servers that need one
    language: str = "auto"         # "auto", "da", "en"
    timeout: int = 120
    font_size: int = 11
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        data: dict = {}
        for path in (SYSTEM_CONFIG, CONFIG_FILE):
            try:
                data.update(json.loads(path.read_text()))
            except (OSError, ValueError):
                pass
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        s = cls(**known)
        s.server = normalize_server(s.server)
        return s

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n")
        os.chmod(tmp, 0o600)       # may hold an API key
        tmp.replace(CONFIG_FILE)


def normalize_server(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and not re.match(r"^https?://", url):
        url = "http://" + url
    if re.match(r"^https?://[^/:]+$", url):
        url += ":11434"            # Ollama's usual port when none is given
    for suffix in ("/api", "/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


class LLMError(Exception):
    pass


# ---------------------------------------------------------------------------------------
# System description sent with every question
# ---------------------------------------------------------------------------------------

def _os_release() -> dict:
    out = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            for line in open(path):
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    out.setdefault(k, v.strip('"'))
        except OSError:
            continue
    return out


def system_facts(cwd: str | None = None) -> str:
    rel = _os_release()
    in_box = os.path.exists("/run/.containerenv") or os.path.exists("/.dockerenv")
    tools = [t for t in ("flatpak", "brew", "distrobox", "rpm-ostree", "bootc", "ujust", "udisksctl", "lact", "steam")
             if shutil.which(t)]
    lines = [
        f"OS: {rel.get('PRETTY_NAME', 'Linux')} (version {rel.get('VERSION', '?')}, based on Fedora {rel.get('VERSION_ID', '?')})",
        f"User: {getpass.getuser()}  Host: {socket.gethostname()}  Shell: bash",
        f"Current folder: {cwd or os.getcwd()}",
        f"Inside a container (distrobox/toolbox): {'yes' if in_box else 'no'}",
        f"Available tools: {', '.join(tools) or 'unknown'}",
    ]
    return "\n".join(lines)


SYSTEM_GUIDE = """\
You are the assistant inside "Command Prompt" on FedoraClassic7: a Windows 7 Classic styled
desktop built on Bazzite, which is Fedora Atomic (KDE Plasma) for gaming, on an AMD Radeon
RX 7900 XTX. The user is technical but new to Linux.

Facts about this system - always follow them:
- The base system is an immutable image (bootc/rpm-ostree). /usr is read-only.
  `dnf install` and `sudo dnf` DO NOT work on the host. Never suggest them on the host.
- Install desktop programs with Flatpak from Flathub: `flatpak install -y flathub <app id>`
  (or the Bazaar app store). Command-line tools: Homebrew `brew install <tool>`.
- Software only available as .deb/.rpm, or development environments: Distrobox
  (`distrobox create -i ubuntu:24.04 -n ubuntu`, then `distrobox enter ubuntu` and apt inside).
- `rpm-ostree install <pkg>` layers a package onto the image (needs a restart, slows updates):
  only as a last resort, e.g. for drivers.
- Updates: `classic7-update` (also --check, --status, --rollback). Bazzite tasks: `ujust`.
- Removable drives mount under /run/media/$USER; use `udisksctl` to mount/unmount.
- GPU tools: LACT (`lact`), `sensors`. Games: Steam, Proton.
- /etc and /var and the home folder are writable as usual. sudo works for the main user.
- If inside a container, normal dnf/apt for that container DO work.
- Never invent systemd unit names, file paths or options. If you are not sure a unit or
  file exists, suggest a command that lists or checks it first (for example
  `systemctl list-unit-files | grep -i sleep`) and say so in the explanation.
- Sleep/suspend: Plasma's own setting is System Settings > Power Management. To stop the
  whole machine from ever suspending (also at the login screen, useful in a VM):
  `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`
  (undo with `unmask`).
"""

SUGGEST_RULES = """\
Reply with ONE JSON object and nothing else:
{"command": "<a single bash command line, or empty if no command fits>",
 "explanation": "<1-3 short sentences: what it does and what to look for>",
 "risk": "safe" | "caution" | "danger"}
Rules: prefer read-only commands when the user asks for information. Use real paths and
names when the user gave them; otherwise use <placeholders>. Never chain unrelated steps.
risk: safe = only reads; caution = changes files/settings/software or needs sudo;
danger = can destroy data or make the system unbootable. If the request is a question
that needs no command, leave "command" empty and answer in "explanation".
"""

EXPLAIN_RULES = """\
Explain the terminal output or error below for this user in plain words: what happened,
the likely cause, and the next step (with an exact command if useful, in a ``` block).
Keep it short: at most 8 sentences. Do not repeat the whole output.
"""


def language_rule(settings: Settings) -> str:
    return {
        "da": "Answer in Danish.",
        "en": "Answer in English.",
    }.get(settings.language, "Answer in the language the user writes in (Danish or English).")


# ---------------------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------------------

class Client:
    def __init__(self, settings: Settings):
        self.s = settings
        self.cancelled = False
        self._picked = ""

    # -- low level ------------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return normalize_server(self.s.server) + path

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.s.api_key:
            headers["Authorization"] = f"Bearer {self.s.api_key}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self._url(path), data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.s.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            raise LLMError(f"The server answered {e.code}: {body or e.reason}") from None
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise LLMError(f"Can't reach {self.s.server} ({reason}). Is the server on, and is the address right?") from None

    # -- models ---------------------------------------------------------------------------
    def list_models(self) -> list[str]:
        if self.s.api == "openai":
            with self._request("/v1/models", timeout=8) as r:
                data = json.load(r)
            return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))
        with self._request("/api/tags", timeout=8) as r:
            data = json.load(r)
        return sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))

    def pick_model(self) -> str:
        if self.s.model:
            return self.s.model
        if self._picked:
            return self._picked
        models = self.list_models()
        chat = [m for m in models if not re.search(r"embed|bge|minilm|nomic|rerank|vl\b|vision|llava", m, re.I)]
        for pref in PREFERRED_MODELS:
            for m in chat:
                if m.lower().startswith(pref):
                    self._picked = m
                    return m
        if chat:
            self._picked = chat[0]
            return chat[0]
        raise LLMError("The server has no chat model. Install one, for example: ollama pull qwen3:14b")

    # -- chat -----------------------------------------------------------------------------
    def chat(self, messages: list[dict], json_mode: bool = False, on_chunk=None) -> str:
        """Send a chat; calls on_chunk(text) while streaming; returns the whole answer."""
        model = self.pick_model()
        self.cancelled = False
        parts: list[str] = []
        if self.s.api == "openai":
            payload = {"model": model, "messages": messages, "stream": True, "temperature": 0.2}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            with self._request("/v1/chat/completions", payload) as r:
                for raw in r:
                    if self.cancelled:
                        break
                    line = raw.decode(errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        delta = json.loads(line)["choices"][0].get("delta", {}).get("content") or ""
                    except (ValueError, KeyError, IndexError):
                        continue
                    if delta:
                        parts.append(delta)
                        if on_chunk:
                            on_chunk(delta)
        else:
            payload = {"model": model, "messages": messages, "stream": True, "think": False,
                       "options": {"temperature": 0.2}}
            if json_mode:
                payload["format"] = "json"
            with self._request("/api/chat", payload) as r:
                for raw in r:
                    if self.cancelled:
                        break
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        continue
                    if obj.get("error"):
                        raise LLMError(str(obj["error"]))
                    delta = (obj.get("message") or {}).get("content") or ""
                    if delta:
                        parts.append(delta)
                        if on_chunk:
                            on_chunk(delta)
                    if obj.get("done"):
                        break
        return strip_thinking("".join(parts))

    # -- the two jobs ---------------------------------------------------------------------
    def suggest(self, request: str, cwd: str | None = None, history: list[str] | None = None) -> dict:
        system = "\n\n".join((SYSTEM_GUIDE, system_facts(cwd), SUGGEST_RULES, language_rule(self.s)))
        user = request
        if history:
            user += "\n\nRecent commands in this terminal:\n" + "\n".join(history[-5:])
        text = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True)
        return parse_suggestion(text)

    def explain(self, output: str, command: str | None = None, cwd: str | None = None,
                question: str | None = None, on_chunk=None) -> str:
        system = "\n\n".join((SYSTEM_GUIDE, system_facts(cwd), EXPLAIN_RULES, language_rule(self.s)))
        user = ""
        if question:
            user += f"My question: {question}\n\n"
        if command:
            user += f"Command: {command}\n\n"
        user += "Output:\n```\n" + output[-6000:] + "\n```"
        return self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                         on_chunk=on_chunk)


def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in text:                   # opening tag cut off
        text = text.split("</think>", 1)[1]
    return text.strip()


def parse_suggestion(text: str) -> dict:
    """Read the model's JSON answer; tolerate code fences and text around it."""
    text = strip_thinking(text)
    m = re.search(r"\{.*\}", text, re.S)
    obj = None
    if m:
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            obj = None
    if not isinstance(obj, dict):
        fence = re.search(r"```(?:bash|sh)?\s*\n(.+?)```", text, re.S)
        return {"command": fence.group(1).strip().splitlines()[0] if fence else "",
                "explanation": re.sub(r"```.*?```", "", text, flags=re.S).strip()[:600],
                "risk": "caution"}
    command = str(obj.get("command") or "").strip()
    command = re.sub(r"^```(?:bash|sh)?\s*|\s*```$", "", command).strip()
    if command.startswith("$ "):
        command = command[2:]
    return {"command": command,
            "explanation": str(obj.get("explanation") or "").strip(),
            "risk": str(obj.get("risk") or "caution").strip().lower()}
