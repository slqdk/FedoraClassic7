"""Mail: talking to IMAP servers (imaplib), and keeping the local copy in step.

Only headers are downloaded when a folder is synchronised; a message's full text is fetched
when it is opened and then kept in the cache.
"""
from __future__ import annotations

import base64
import email
import email.policy
import imaplib
import re
import socket
import ssl
import time
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

import mail_accounts as acc_mod
from mail_store import Message, Store

SYNC_LIMIT = 2000          # newest messages per folder kept locally
CHUNK = 200
TIMEOUT = 40
SKIP_AUTO_SYNC = ("all", "important", "flagged")
HEADER_FIELDS = "FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES CONTENT-TYPE X-PRIORITY IMPORTANCE"

ROLE_FLAGS = {"\\sent": "sent", "\\drafts": "drafts", "\\trash": "trash", "\\junk": "junk", "\\archive": "archive",
              "\\all": "all", "\\flagged": "flagged", "\\important": "important"}
ROLE_GUESS = {
    "sent": ("sent", "sent items", "sent messages", "sent mail", "sendt", "sendte elementer", "sendt post",
             "inbox.sent", "inbox/sent", "[gmail]/sent mail"),
    "drafts": ("drafts", "draft", "kladder", "inbox.drafts", "inbox/drafts", "[gmail]/drafts"),
    "trash": ("trash", "deleted items", "deleted messages", "papirkurv", "slettet post", "slettede elementer",
              "inbox.trash", "inbox/trash", "[gmail]/trash", "bin"),
    "junk": ("junk", "junk e-mail", "junk email", "spam", "uønsket e-mail", "uønsket post", "inbox.junk",
             "inbox.spam", "inbox/spam", "[gmail]/spam"),
    "archive": ("archive", "arkiv", "inbox.archive"),
}


class MailError(Exception):
    pass


class AuthError(MailError):
    pass


# ---- modified UTF-7 (RFC 3501 folder names) ---------------------------------------------------
def utf7_decode(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "&":
            j = s.find("-", i)
            if j == -1:
                out.append(s[i:])
                break
            chunk = s[i + 1:j]
            if not chunk:
                out.append("&")
            else:
                b = chunk.replace(",", "/")
                b += "=" * (-len(b) % 4)
                try:
                    out.append(base64.b64decode(b).decode("utf-16-be"))
                except Exception:   # noqa: BLE001
                    out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def utf7_encode(s: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append(f"&{b}-")
            buf.clear()

    for c in s:
        if 0x20 <= ord(c) <= 0x7E:
            flush()
            out.append("&-" if c == "&" else c)
        else:
            buf.append(c)
    flush()
    return "".join(out)


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---- IMAP response parsing --------------------------------------------------------------------
class _Lit(bytes):
    pass


def _flatten(data) -> bytes:
    """imaplib's FETCH data -> one byte string where each {n} is followed by its n bytes."""
    out = bytearray()
    for item in data:
        if item is None:
            continue
        if isinstance(item, tuple):
            out += item[0]
            out += item[1]
        else:
            if out and not out.endswith(b"\r\n") and re.match(rb"^\d+ \(", item):
                out += b"\r\n"
            out += item
    return bytes(out)


def parse(buf: bytes, pos: int = 0):
    """Parse IMAP data into nested Python lists. Atoms -> str, strings -> bytes, NIL -> None."""
    items = []
    n = len(buf)
    while pos < n:
        c = buf[pos:pos + 1]
        if c in (b" ", b"\r", b"\n"):
            pos += 1
        elif c == b"(":
            sub, pos = parse(buf, pos + 1)
            items.append(sub)
        elif c == b")":
            return items, pos + 1
        elif c == b'"':
            pos += 1
            s = bytearray()
            while pos < n and buf[pos:pos + 1] != b'"':
                if buf[pos:pos + 1] == b"\\":
                    pos += 1
                s += buf[pos:pos + 1]
                pos += 1
            items.append(bytes(s))
            pos += 1
        elif c == b"{":
            end = buf.index(b"}", pos)
            size = int(buf[pos + 1:end].rstrip(b"+"))
            pos = end + 1
            items.append(_Lit(buf[pos:pos + size]))
            pos += size
        else:
            start = pos
            while pos < n and buf[pos:pos + 1] not in (b" ", b"(", b")", b"\r", b"\n"):
                if buf[pos:pos + 1] == b"[":
                    close = buf.find(b"]", pos)
                    pos = close if close != -1 else n - 1
                pos += 1
            atom = buf[start:pos].decode("latin-1")
            items.append(None if atom.upper() == "NIL" else atom)
    return items, pos


def fetch_items(data) -> list[dict]:
    """FETCH response -> [{"UID": "101", "FLAGS": [...], "BODY[...]": b"..."}] (keys upper case)."""
    toks, _ = parse(_flatten(data))
    out = []
    i = 0
    while i < len(toks):
        if isinstance(toks[i], str) and toks[i].isdigit() and i + 1 < len(toks) and isinstance(toks[i + 1], list):
            lst = toks[i + 1]
            d = {}
            for k in range(0, len(lst) - 1, 2):
                key = lst[k].upper() if isinstance(lst[k], str) else str(lst[k])
                key = re.sub(r"\.PEEK", "", key)
                d[key] = lst[k + 1]
            out.append(d)
            i += 2
        else:
            i += 1
    return out


def _body_key(d: dict, prefix: str):
    for k, v in d.items():
        if k.startswith(prefix):
            return v
    return None


def has_attachment(bs) -> bool:
    """Walk a BODYSTRUCTURE: a part with disposition "attachment", or a named non-text part."""
    if not isinstance(bs, list) or not bs:
        return False
    if isinstance(bs[0], list):                      # multipart: parts..., subtype, ...
        return any(has_attachment(p) for p in bs if isinstance(p, list) and p and not isinstance(p, (str, bytes)))
    def low(x):
        return x.decode(errors="replace").lower() if isinstance(x, bytes) else (x or "").lower()
    mtype = low(bs[0]) if len(bs) > 0 else ""
    params = bs[2] if len(bs) > 2 and isinstance(bs[2], list) else []
    named = any(low(params[i]) == "name" for i in range(0, len(params) - 1, 2))
    disp = None
    for x in bs[7:]:
        if isinstance(x, list) and x and isinstance(x[0], (bytes, str)) and low(x[0]) in ("attachment", "inline"):
            disp = low(x[0])
            break
    if disp == "attachment":
        return True
    if named and mtype not in ("text",) and disp != "inline":
        return True
    if named and mtype == "application":
        return True
    return False


def decode_mime(s: str | bytes | None) -> str:
    if s is None:
        return ""
    if isinstance(s, bytes):
        s = s.decode("utf-8", errors="replace")
    try:
        return str(make_header(decode_header(s))).replace("\r", "").replace("\n", "")
    except Exception:   # noqa: BLE001
        return s


def addresses(value: str) -> list[tuple[str, str]]:
    return [(decode_mime(n), a) for n, a in getaddresses([value or ""]) if a or n]


def format_addresses(pairs) -> str:
    return "; ".join(f"{n} <{a}>" if n and n != a else a for n, a in pairs)


def header_to_message(raw: bytes, folder_id: int, uid: int) -> Message:
    h = email.message_from_bytes(raw, policy=email.policy.compat32)
    frm = addresses(h.get("From", ""))
    try:
        date = parsedate_to_datetime(h.get("Date")).timestamp() if h.get("Date") else 0
    except (TypeError, ValueError, IndexError):
        date = 0
    prio = (h.get("X-Priority", "") or "").strip()[:1]
    imp = (h.get("Importance", "") or "").lower()
    importance = 1 if prio in ("1", "2") or imp == "high" else -1 if prio in ("4", "5") or imp == "low" else 0
    return Message(id=0, folder=folder_id, uid=uid,
                   msgid=(h.get("Message-ID") or "").strip(),
                   subject=decode_mime(h.get("Subject", "")),
                   from_name=frm[0][0] if frm else "", from_addr=frm[0][1] if frm else "",
                   to_addrs=format_addresses(addresses(h.get("To", ""))),
                   cc_addrs=format_addresses(addresses(h.get("Cc", ""))),
                   date=date, importance=importance,
                   in_reply_to=(h.get("In-Reply-To") or "").strip(),
                   refs=" ".join((h.get("References") or "").split()))


def _imap_date(s) -> float:
    if isinstance(s, bytes):
        s = s.decode()
    try:
        t = imaplib.Internaldate2tuple(f'INTERNALDATE "{s}"'.encode())
        return time.mktime(t) if t else 0
    except Exception:   # noqa: BLE001
        return 0


# ---- connection -------------------------------------------------------------------------------
def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def explain(e: Exception) -> str:
    s = str(e)
    if isinstance(e, (socket.gaierror,)):
        return "The server name can't be found. Check the server name and your Internet connection."
    if isinstance(e, ConnectionRefusedError):
        return "The server refused the connection. Check the port number and encryption type."
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "The server did not answer in time."
    if isinstance(e, ssl.SSLCertVerificationError):
        return f"The server's security certificate can't be trusted ({e.verify_message})."
    if isinstance(e, ssl.SSLError):
        return "A secure connection could not be made. Check the port number and encryption type."
    if isinstance(e, OSError) and getattr(e, "errno", None) in (101, 113):
        return "The server can't be reached. Check your network connection."
    return s or type(e).__name__


class Connection:
    """One IMAP session for an account."""

    def __init__(self, account: acc_mod.Account):
        self.account = account
        self.imap: imaplib.IMAP4 | None = None
        self.selected: str | None = None
        self.readonly = True
        self.caps: set[str] = set()

    # -- connecting --
    def open(self):
        a = self.account
        try:
            if a.imap_security == "ssl":
                self.imap = imaplib.IMAP4_SSL(a.imap_host, a.imap_port, ssl_context=_ssl_context(), timeout=TIMEOUT)
            else:
                self.imap = imaplib.IMAP4(a.imap_host, a.imap_port, timeout=TIMEOUT)
                if a.imap_security == "starttls":
                    self.imap.starttls(ssl_context=_ssl_context())
        except (OSError, imaplib.IMAP4.error) as e:
            self.imap = None
            raise MailError(explain(e)) from e
        try:
            if a.auth == "oauth-microsoft":
                import mail_oauth
                token = mail_oauth.access_token(a)
                self.imap.authenticate("XOAUTH2", lambda _c: mail_oauth.xoauth2(a.login_name, token).encode())
            else:
                pw = acc_mod.get_secret(a.id, "password")
                self.imap.login(a.login_name, pw)
        except imaplib.IMAP4.error as e:
            self.close()
            msg = str(e).strip("b'\"")
            if a.provider == "gmail" and ("application-specific" in msg.lower() or "AUTHENTICATIONFAILED" in msg
                                          or "Invalid credentials" in msg):
                raise AuthError("Gmail did not accept the password. Gmail needs an app password "
                                "(myaccount.google.com/apppasswords), not your normal password.") from e
            raise AuthError(f"The user name or password was not accepted ({msg}).") from e
        except Exception as e:   # noqa: BLE001  (OAuth errors, keyring trouble)
            self.close()
            raise AuthError(str(e)) from e
        try:
            self.caps = {c.upper() for c in self.imap.capabilities}
        except Exception:   # noqa: BLE001
            self.caps = set()
        return self

    def ensure(self):
        if self.imap is None:
            self.open()
            return
        try:
            self.imap.noop()
        except Exception:   # noqa: BLE001
            self.close()
            self.open()

    def close(self):
        if self.imap is not None:
            try:
                self.imap.logout()
            except Exception:   # noqa: BLE001
                pass
        self.imap = None
        self.selected = None

    def _check(self, typ, data, what: str):
        if typ != "OK":
            text = b" ".join(d for d in data if isinstance(d, bytes)).decode(errors="replace") if data else ""
            raise MailError(f"{what} failed: {text or typ}")
        return data

    def select(self, path: str, readonly: bool = True) -> int:
        """Select a folder (always read-write, like most mail programs: reading uses BODY.PEEK,
        so nothing changes by looking). Returns its UIDVALIDITY. A folder the server only
        allows reading is opened with EXAMINE."""
        if self.selected == path:
            return self._uidvalidity
        # no CLOSE first: it would expunge deleted messages; SELECT switches by itself
        try:
            typ, data = self.imap.select(quote(utf7_encode(path)), readonly=False)
            ro = False
        except imaplib.IMAP4.readonly:
            typ, data = self.imap.select(quote(utf7_encode(path)), readonly=True)
            ro = True
        self._check(typ, data, f"Opening folder {path}")
        self.selected = path
        self.readonly = ro
        uv = self.imap.response("UIDVALIDITY")[1]
        self._uidvalidity = int(uv[0]) if uv and uv[0] else 0
        return self._uidvalidity

    # -- folders --
    def list_folders(self) -> list[dict]:
        typ, data = self.imap.list()
        self._check(typ, data, "Listing folders")
        out = []
        for line in data:
            if line is None:
                continue
            if isinstance(line, tuple):
                line = line[0] + b'"' + line[1].replace(b'"', b'\\"') + b'"'
            m = re.match(rb'^\((.*?)\) (NIL|"(?:[^"\\]|\\.)*") (.*)$', line)
            if not m:
                continue
            flags = m.group(1).decode().lower().split()
            delim = m.group(2).decode().strip('"').replace("\\\\", "\\") if m.group(2) != b"NIL" else ""
            raw = m.group(3).strip()
            if raw.startswith(b'"'):
                raw = raw[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
            path = utf7_decode(raw.decode("utf-8", errors="replace"))
            name = path.split(delim)[-1] if delim else path
            parent = path[:-(len(name) + len(delim))] if delim and delim in path else ""
            role = ""
            if path.upper() == "INBOX":
                role, path, name = "inbox", "INBOX", "Inbox"
            else:
                for f in flags:
                    if f in ROLE_FLAGS:
                        role = ROLE_FLAGS[f]
                        break
            out.append({"path": path, "name": name, "parent": parent, "delim": delim or "/", "role": role,
                        "selectable": "\\noselect" not in flags and "\\nonexistent" not in flags})
        # name-based roles for servers without SPECIAL-USE
        taken = {f["role"] for f in out if f["role"]}
        for role, names in ROLE_GUESS.items():
            if role in taken:
                continue
            for f in out:
                if f["role"]:
                    continue
                if f["path"].lower() in names or (f["name"].lower() in names and f["parent"].upper() in ("", "INBOX")):
                    f["role"] = role
                    break
        return out

    def _leave(self):
        """Stop having a folder selected (before renaming/deleting it), without expunging."""
        if "UNSELECT" in self.caps:
            self.imap.unselect()
            self.selected = None
        else:
            self.selected = None
            self.select("INBOX")

    def create_folder(self, path: str):
        self._check(*self.imap.create(quote(utf7_encode(path))), f"Creating {path}")
        try:
            self.imap.subscribe(quote(utf7_encode(path)))
        except Exception:   # noqa: BLE001
            pass

    def rename_folder(self, old: str, new: str):
        if self.selected == old:
            self._leave()
        self._check(*self.imap.rename(quote(utf7_encode(old)), quote(utf7_encode(new))), f"Renaming {old}")

    def delete_folder(self, path: str):
        if self.selected == path:
            self._leave()
        self._check(*self.imap.delete(quote(utf7_encode(path))), f"Deleting {path}")

    # -- messages --
    def search_uids(self) -> list[int]:
        typ, data = self.imap.uid("SEARCH", None, "ALL")
        self._check(typ, data, "Searching")
        return sorted(int(x) for x in b" ".join(d for d in data if d).split())

    def fetch_headers(self, uids: list[int], folder_id: int) -> list[Message]:
        out = []
        for i in range(0, len(uids), CHUNK):
            part = uids[i:i + CHUNK]
            typ, data = self.imap.uid("FETCH", ",".join(map(str, part)),
                                      f"(UID FLAGS RFC822.SIZE INTERNALDATE BODYSTRUCTURE "
                                      f"BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])")
            self._check(typ, data, "Fetching headers")
            for d in fetch_items(data):
                if "UID" not in d:
                    continue
                uid = int(d["UID"])
                hdr = _body_key(d, "BODY[HEADER") or b""
                msg = header_to_message(bytes(hdr), folder_id, uid)
                flags = {f for f in (d.get("FLAGS") or []) if isinstance(f, str)}
                msg.seen = "\\Seen" in flags
                msg.answered = "\\Answered" in flags
                msg.flagged = "\\Flagged" in flags
                msg.draft = "\\Draft" in flags
                msg.forwarded = "$Forwarded" in flags
                msg.size = int(d.get("RFC822.SIZE") or 0)
                if not msg.date:
                    msg.date = _imap_date(d.get("INTERNALDATE"))
                msg.attach = has_attachment(d.get("BODYSTRUCTURE"))
                out.append(msg)
        return out

    def fetch_flags(self, first_uid: int) -> dict[int, set[str]]:
        typ, data = self.imap.uid("FETCH", f"{first_uid}:*", "(UID FLAGS)")
        self._check(typ, data, "Fetching flags")
        out = {}
        for d in fetch_items(data):
            if "UID" in d:
                out[int(d["UID"])] = {f for f in (d.get("FLAGS") or []) if isinstance(f, str)}
        return out

    def fetch_message(self, path: str, uid: int) -> bytes:
        self.select(path, readonly=True)
        typ, data = self.imap.uid("FETCH", str(uid), "(UID BODY.PEEK[])")
        self._check(typ, data, "Downloading the message")
        for d in fetch_items(data):
            body = _body_key(d, "BODY[")
            if body is not None and int(d.get("UID", uid)) == uid:
                return bytes(body)
        raise MailError("The message is no longer on the server.")

    def store(self, path: str, uids: list[int], op: str, flags: str):
        if not uids:
            return
        self.select(path, readonly=False)
        typ, data = self.imap.uid("STORE", ",".join(map(str, uids)), op, f"({flags})")
        self._check(typ, data, "Changing flags")

    def expunge(self, path: str, uids: list[int]):
        self.select(path, readonly=False)
        if "UIDPLUS" in self.caps:
            typ, data = self.imap.uid("EXPUNGE", ",".join(map(str, uids)))
        else:
            typ, data = self.imap.expunge()
        self._check(typ, data, "Removing messages")

    def copy(self, path: str, uids: list[int], dest: str):
        self.select(path, readonly=True)
        typ, data = self.imap.uid("COPY", ",".join(map(str, uids)), quote(utf7_encode(dest)))
        self._check(typ, data, f"Copying to {dest}")

    def move(self, path: str, uids: list[int], dest: str):
        if not uids:
            return
        self.select(path, readonly=False)
        if "MOVE" in self.caps:
            typ, data = self.imap.uid("MOVE", ",".join(map(str, uids)), quote(utf7_encode(dest)))
            self._check(typ, data, f"Moving to {dest}")
        else:
            self.copy(path, uids, dest)
            self.store(path, uids, "+FLAGS.SILENT", "\\Deleted")
            self.expunge(path, uids)

    def find_uid(self, path: str, msgid: str) -> int | None:
        """UID of the message with this Message-ID (for servers that don't report APPENDUID)."""
        if not msgid:
            return None
        self.select(path, readonly=True)
        typ, data = self.imap.uid("SEARCH", None, "HEADER", "Message-ID", quote(msgid))
        if typ != "OK":
            return None
        uids = [int(x) for x in b" ".join(d for d in data if d).split()]
        return max(uids) if uids else None

    def append(self, path: str, raw: bytes, flags: str = "\\Seen") -> int | None:
        """Add a message to a folder. Returns its new UID if the server says (UIDPLUS)."""
        typ, data = self.imap.append(quote(utf7_encode(path)), f"({flags})", imaplib.Time2Internaldate(time.time()),
                                     raw)
        self._check(typ, data, f"Saving to {path}")
        m = re.search(rb"APPENDUID \d+ (\d+)", b" ".join(d for d in data if isinstance(d, bytes)))
        return int(m.group(1)) if m else None


# ---- synchronisation --------------------------------------------------------------------------
def sync_folders(conn: Connection, store: Store) -> list:
    store.set_folders(conn.account.id, conn.list_folders())
    return store.folders(conn.account.id)


def sync_folder(conn: Connection, store: Store, folder, progress=None) -> list[Message]:
    """Bring one folder up to date. Returns the messages that are new since last time."""
    if not folder.selectable:
        return []
    uv = conn.select(folder.path, readonly=True)
    store.set_uidvalidity(folder.id, uv)
    server = conn.search_uids()
    keep = set(server[-SYNC_LIMIT:])
    local = store.uids(folder.id)
    store.remove_uids(folder.id, local - keep)
    new = sorted(keep - local, reverse=True)          # newest first
    first_sync = not local
    msgs: list[Message] = []
    for i in range(0, len(new), CHUNK):
        part = new[i:i + CHUNK]
        got = conn.fetch_headers(part, folder.id)
        store.add_messages(got)
        msgs += got
        if progress:
            progress(min(len(new), i + CHUNK), len(new))
    if local & keep:
        flags = conn.fetch_flags(min(local & keep))
        store.update_flags(folder.id, {u: f for u, f in flags.items() if u in local})
    store.mark_synced(folder.id)
    return [] if first_sync else msgs


def test_account(account: acc_mod.Account) -> list[str]:
    """Log on and list folders, the way "Test Account Settings" does. Returns folder names."""
    conn = Connection(account).open()
    try:
        return [f["name"] for f in conn.list_folders()]
    finally:
        conn.close()
