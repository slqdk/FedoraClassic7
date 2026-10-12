"""Mail: e-mail accounts, their passwords and automatic server settings.

Accounts live in ~/.config/classic7/mail/accounts.json. Passwords and sign-in tokens are kept
in the desktop's password store (KWallet, through the Secret Service API) when it works, and
otherwise in ~/.config/classic7/mail/secrets.json, readable only by the user.
"""
from __future__ import annotations

import json
import os
import re
import secrets as _secrets
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

SERVICE = "classic7-mail"

MICROSOFT_DOMAINS = ("outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.dk", "hotmail.dk", "live.dk",
                     "hotmail.co.uk", "live.co.uk", "outlook.de", "hotmail.de", "hotmail.fr", "outlook.fr",
                     "passport.com")
GOOGLE_DOMAINS = ("gmail.com", "googlemail.com")


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "classic7" / "mail"


def data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "classic7" / "mail"


def cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "classic7" / "mail"


# ---- accounts ---------------------------------------------------------------------------------
@dataclass
class Account:
    id: str = ""
    name: str = ""                     # shown in the folder list ("Gmail", "soren@firma.dk")
    email: str = ""
    display_name: str = ""             # "Your Name" on outgoing mail
    imap_host: str = ""
    imap_port: int = 993
    imap_security: str = "ssl"         # ssl | starttls | none
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: str = "ssl"
    username: str = ""
    smtp_username: str = ""            # empty: same as username
    smtp_auth: bool = True
    auth: str = "password"             # password | oauth-microsoft
    oauth_client_id: str = ""
    oauth_tenant: str = "consumers"
    provider: str = ""                 # gmail | microsoft | ""
    save_sent: bool = True             # put a copy in Sent (Gmail and Outlook.com do it themselves)
    signature: str = ""                # HTML
    check_minutes: int = 10
    reply_address: str = ""
    default: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def login_name(self) -> str:
        return self.username or self.email

    @property
    def smtp_login(self) -> str:
        return self.smtp_username or self.login_name

    @property
    def sender(self) -> str:
        from email.utils import formataddr
        return formataddr((self.display_name, self.email)) if self.display_name else self.email


def accounts_file() -> Path:
    return config_dir() / "accounts.json"


def load() -> list[Account]:
    try:
        data = json.loads(accounts_file().read_text())
    except (OSError, ValueError):
        return []
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            out.append(Account(**{k: v for k, v in d.items() if k in Account.__dataclass_fields__}))
        except TypeError:
            continue
    return out


def save(accounts: list[Account]):
    config_dir().mkdir(parents=True, exist_ok=True)
    tmp = accounts_file().with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(a) for a in accounts], indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(accounts_file())


def new_id() -> str:
    return _secrets.token_hex(4)


def get(account_id: str) -> Account | None:
    return next((a for a in load() if a.id == account_id), None)


def default_account(accounts: list[Account] | None = None) -> Account | None:
    accounts = load() if accounts is None else accounts
    return next((a for a in accounts if a.default), accounts[0] if accounts else None)


def upsert(acc: Account):
    accs = load()
    if not acc.id:
        acc.id = new_id()
    if not accs:
        acc.default = True
    if acc.default:
        for a in accs:
            a.default = False
    for i, a in enumerate(accs):
        if a.id == acc.id:
            accs[i] = acc
            break
    else:
        accs.append(acc)
    save(accs)


def remove(account_id: str):
    accs = [a for a in load() if a.id != account_id]
    if accs and not any(a.default for a in accs):
        accs[0].default = True
    save(accs)
    for kind in ("password", "oauth"):
        delete_secret(account_id, kind)


# ---- secrets ----------------------------------------------------------------------------------
def _secret_file() -> Path:
    return config_dir() / "secrets.json"


def _keyring():
    """The keyring module if a real password store answers, else None."""
    if os.environ.get("CLASSIC7_MAIL_NO_KEYRING") == "1":
        return None
    try:
        import keyring
        kr = keyring.get_keyring()
        name = type(kr).__name__.lower() + type(kr).__module__.lower()
        if "fail" in name or "null" in name:
            return None
        return keyring
    except Exception:   # noqa: BLE001
        return None


def _file_secrets() -> dict:
    try:
        return json.loads(_secret_file().read_text())
    except (OSError, ValueError):
        return {}


def _write_file_secrets(d: dict):
    config_dir().mkdir(parents=True, exist_ok=True)
    fd = os.open(_secret_file(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.chmod(_secret_file(), 0o600)


def set_secret(account_id: str, kind: str, value: str):
    key = f"{account_id}:{kind}"
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, key, value)
            d = _file_secrets()
            if key in d:
                d.pop(key)
                _write_file_secrets(d)
            return
        except Exception:   # noqa: BLE001
            pass
    d = _file_secrets()
    d[key] = value
    _write_file_secrets(d)


def get_secret(account_id: str, kind: str) -> str:
    key = f"{account_id}:{kind}"
    d = _file_secrets()
    if key in d:
        return d[key]
    kr = _keyring()
    if kr is not None:
        try:
            return kr.get_password(SERVICE, key) or ""
        except Exception:   # noqa: BLE001
            return ""
    return ""


def delete_secret(account_id: str, kind: str):
    key = f"{account_id}:{kind}"
    d = _file_secrets()
    if key in d:
        d.pop(key)
        _write_file_secrets(d)
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, key)
        except Exception:   # noqa: BLE001
            pass


# ---- automatic setup --------------------------------------------------------------------------
def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""


def valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def gmail_preset(email: str) -> Account:
    return Account(name=email, email=email, imap_host="imap.gmail.com", imap_port=993, imap_security="ssl",
                   smtp_host="smtp.gmail.com", smtp_port=465, smtp_security="ssl", username=email,
                   provider="gmail", save_sent=False)


def microsoft_preset(email: str) -> Account:
    return Account(name=email, email=email, imap_host="outlook.office365.com", imap_port=993,
                   imap_security="ssl", smtp_host="smtp-mail.outlook.com", smtp_port=587,
                   smtp_security="starttls", username=email, auth="oauth-microsoft", provider="microsoft",
                   save_sent=False, oauth_tenant="consumers")


def _fetch(url: str, timeout: float = 8) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Classic7-Mail/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (https/http config only)
        return r.read(256 * 1024)


def parse_autoconfig(xml: bytes, email: str) -> Account | None:
    """A Thunderbird autoconfig file (config-v1.1.xml) -> Account, or None without IMAP."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    local = email.split("@")[0]
    dom = domain_of(email)

    def subst(s: str) -> str:
        return (s or "").replace("%EMAILADDRESS%", email).replace("%EMAILLOCALPART%", local) \
            .replace("%EMAILDOMAIN%", dom)

    def sec(sock: str) -> str:
        return {"SSL": "ssl", "STARTTLS": "starttls"}.get((sock or "").upper(), "none")

    imap = next((s for s in root.iter("incomingServer") if s.get("type") == "imap"), None)
    smtp = next((s for s in root.iter("outgoingServer") if s.get("type") == "smtp"), None)
    if imap is None:
        return None
    acc = Account(name=email, email=email)
    acc.imap_host = subst(imap.findtext("hostname", ""))
    acc.imap_port = int(imap.findtext("port", "993") or 993)
    acc.imap_security = sec(imap.findtext("socketType", "SSL"))
    acc.username = subst(imap.findtext("username", "%EMAILADDRESS%"))
    if smtp is not None:
        acc.smtp_host = subst(smtp.findtext("hostname", ""))
        acc.smtp_port = int(smtp.findtext("port", "465") or 465)
        acc.smtp_security = sec(smtp.findtext("socketType", "SSL"))
        user = subst(smtp.findtext("username", "") or "")
        acc.smtp_username = "" if user == acc.username else user
    return acc


def guess(email: str) -> Account:
    dom = domain_of(email)
    return Account(name=email, email=email, imap_host=f"imap.{dom}", imap_port=993, imap_security="ssl",
                   smtp_host=f"smtp.{dom}", smtp_port=465, smtp_security="ssl", username=email)


def autodetect(email: str, online: bool = True) -> tuple[Account, str]:
    """Best server settings for an address. Returns (account, where the settings came from)."""
    email = email.strip()
    dom = domain_of(email)
    if dom in GOOGLE_DOMAINS:
        return gmail_preset(email), "gmail"
    if dom in MICROSOFT_DOMAINS:
        return microsoft_preset(email), "microsoft"
    if online and dom:
        q = urllib.parse.quote(email)
        for url in (f"https://autoconfig.{dom}/mail/config-v1.1.xml?emailaddress={q}",
                    f"https://{dom}/.well-known/autoconfig/mail/config-v1.1.xml?emailaddress={q}",
                    f"https://autoconfig.thunderbird.net/v1.1/{dom}"):
            try:
                acc = parse_autoconfig(_fetch(url), email)
            except Exception:   # noqa: BLE001
                continue
            if acc and acc.imap_host:
                if "gmail.com" in acc.imap_host or "googlemail" in acc.imap_host:
                    acc.provider, acc.save_sent = "gmail", False
                return acc, "autoconfig"
    return guess(email), "guess"
