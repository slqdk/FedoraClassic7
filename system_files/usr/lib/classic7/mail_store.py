"""Mail: the local copy of folders, message headers and contacts (SQLite), and the cached
message files (.eml) of messages that have been opened.

  ~/.local/share/classic7/mail/mail.db
  ~/.local/share/classic7/mail/messages/<account>/<folder id>/<uid>.eml
"""
from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import mail_accounts as acc_mod

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY,
    account TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    parent TEXT NOT NULL DEFAULT '',
    delim TEXT NOT NULL DEFAULT '/',
    role TEXT NOT NULL DEFAULT '',
    selectable INTEGER NOT NULL DEFAULT 1,
    uidvalidity INTEGER NOT NULL DEFAULT 0,
    synced REAL NOT NULL DEFAULT 0,
    UNIQUE (account, path)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    folder INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    uid INTEGER NOT NULL,
    msgid TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    from_name TEXT NOT NULL DEFAULT '',
    from_addr TEXT NOT NULL DEFAULT '',
    to_addrs TEXT NOT NULL DEFAULT '',
    cc_addrs TEXT NOT NULL DEFAULT '',
    date REAL NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    seen INTEGER NOT NULL DEFAULT 0,
    answered INTEGER NOT NULL DEFAULT 0,
    flagged INTEGER NOT NULL DEFAULT 0,
    forwarded INTEGER NOT NULL DEFAULT 0,
    draft INTEGER NOT NULL DEFAULT 0,
    attach INTEGER NOT NULL DEFAULT 0,
    importance INTEGER NOT NULL DEFAULT 0,
    in_reply_to TEXT NOT NULL DEFAULT '',
    refs TEXT NOT NULL DEFAULT '',
    UNIQUE (folder, uid)
);
CREATE INDEX IF NOT EXISTS messages_folder_date ON messages(folder, date);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL DEFAULT '',
    first TEXT NOT NULL DEFAULT '',
    last TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    job_title TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    email2 TEXT NOT NULL DEFAULT '',
    web TEXT NOT NULL DEFAULT '',
    phone_work TEXT NOT NULL DEFAULT '',
    phone_home TEXT NOT NULL DEFAULT '',
    phone_mobile TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    changed REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recent_addresses (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    count INTEGER NOT NULL DEFAULT 0,
    last REAL NOT NULL DEFAULT 0
);
"""

ROLE_ORDER = {"inbox": 0, "drafts": 1, "sent": 2, "trash": 3, "junk": 4, "archive": 5, "": 6,
              "all": 7, "flagged": 8, "important": 9}
ROLE_NAMES = {"inbox": "Inbox", "drafts": "Drafts", "sent": "Sent Items", "trash": "Deleted Items",
              "junk": "Junk E-mail", "archive": "Archive", "outbox": "Outbox"}


@dataclass
class Folder:
    id: int
    account: str
    path: str
    name: str
    parent: str
    delim: str
    role: str
    selectable: bool
    uidvalidity: int
    synced: float
    unread: int = 0
    total: int = 0

    @property
    def display_name(self) -> str:
        if self.role == "inbox" or self.path.upper() == "INBOX":
            return "Inbox"
        if self.role in ("sent", "trash", "junk", "drafts"):
            return ROLE_NAMES[self.role]
        return self.name


@dataclass
class Message:
    id: int
    folder: int
    uid: int
    msgid: str = ""
    subject: str = ""
    from_name: str = ""
    from_addr: str = ""
    to_addrs: str = ""
    cc_addrs: str = ""
    date: float = 0
    size: int = 0
    seen: bool = False
    answered: bool = False
    flagged: bool = False
    forwarded: bool = False
    draft: bool = False
    attach: bool = False
    importance: int = 0          # -1 low, 0 normal, 1 high
    in_reply_to: str = ""
    refs: str = ""

    @property
    def sender(self) -> str:
        return self.from_name or self.from_addr


@dataclass
class Contact:
    id: int = 0
    full_name: str = ""
    first: str = ""
    last: str = ""
    company: str = ""
    job_title: str = ""
    email: str = ""
    email2: str = ""
    web: str = ""
    phone_work: str = ""
    phone_home: str = ""
    phone_mobile: str = ""
    address: str = ""
    notes: str = ""
    changed: float = 0

    @property
    def file_as(self) -> str:
        if self.last and self.first:
            return f"{self.last}, {self.first}"
        return self.full_name or self.company or self.email

    @property
    def display(self) -> str:
        return self.full_name or " ".join(x for x in (self.first, self.last) if x) or self.email


MSG_COLS = [f for f in Message.__dataclass_fields__]
CONTACT_COLS = [f for f in Contact.__dataclass_fields__]


class Store:
    """Thread-safe: every thread gets its own connection; writes are serialised."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else acc_mod.data_dir() / "mail.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write = threading.RLock()
        self.db().executescript(SCHEMA)

    def db(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA journal_mode = WAL")
            self._local.conn = c
        return _Ctx(c, self._write)

    # ---- folders --------------------------------------------------------------------------------
    def folders(self, account: str | None = None) -> list[Folder]:
        q = ("SELECT f.*, (SELECT COUNT(*) FROM messages m WHERE m.folder = f.id AND m.seen = 0) AS unread, "
             "(SELECT COUNT(*) FROM messages m WHERE m.folder = f.id) AS total FROM folders f")
        args: tuple = ()
        if account is not None:
            q += " WHERE f.account = ?"
            args = (account,)
        with self.db() as db:
            rows = db.execute(q, args).fetchall()
        out = [Folder(**{k: r[k] for k in r.keys()}) for r in rows]
        for f in out:
            f.selectable = bool(f.selectable)
        out.sort(key=lambda f: (f.account, ROLE_ORDER.get(f.role, 6), f.path.lower()))
        return out

    def folder(self, folder_id: int) -> Folder | None:
        return next((f for f in self.folders() if f.id == folder_id), None)

    def folder_by_path(self, account: str, path: str) -> Folder | None:
        return next((f for f in self.folders(account) if f.path == path), None)

    def folder_by_role(self, account: str, role: str) -> Folder | None:
        return next((f for f in self.folders(account) if f.role == role), None)

    def set_folders(self, account: str, items: list[dict]):
        """items: dicts with path, name, parent, delim, role, selectable. Removes folders that
        are gone."""
        with self.db() as db:
            known = {r["path"]: r["id"] for r in db.execute("SELECT id, path FROM folders WHERE account = ?",
                                                             (account,))}
            for it in items:
                if it["path"] in known:
                    db.execute("UPDATE folders SET name=?, parent=?, delim=?, role=?, selectable=? WHERE id=?",
                               (it["name"], it["parent"], it["delim"], it["role"], int(it["selectable"]),
                                known[it["path"]]))
                else:
                    db.execute("INSERT INTO folders (account, path, name, parent, delim, role, selectable) "
                               "VALUES (?,?,?,?,?,?,?)", (account, it["path"], it["name"], it["parent"],
                                                          it["delim"], it["role"], int(it["selectable"])))
            gone = set(known) - {it["path"] for it in items}
            for p in gone:
                fid = known[p]
                db.execute("DELETE FROM messages WHERE folder = ?", (fid,))
                db.execute("DELETE FROM folders WHERE id = ?", (fid,))
                self._drop_cache(account, fid)

    def set_uidvalidity(self, folder_id: int, uidvalidity: int) -> bool:
        """Store the folder's UIDVALIDITY. Returns True if it changed (and the cached messages
        were dropped)."""
        with self.db() as db:
            r = db.execute("SELECT account, uidvalidity FROM folders WHERE id = ?", (folder_id,)).fetchone()
            if r is None:
                return False
            if r["uidvalidity"] == uidvalidity:
                return False
            db.execute("UPDATE folders SET uidvalidity = ? WHERE id = ?", (uidvalidity, folder_id))
            if r["uidvalidity"]:
                db.execute("DELETE FROM messages WHERE folder = ?", (folder_id,))
                self._drop_cache(r["account"], folder_id)
                return True
            return False

    def mark_synced(self, folder_id: int):
        with self.db() as db:
            db.execute("UPDATE folders SET synced = ? WHERE id = ?", (time.time(), folder_id))

    def remove_account(self, account: str):
        with self.db() as db:
            db.execute("DELETE FROM messages WHERE folder IN (SELECT id FROM folders WHERE account = ?)", (account,))
            db.execute("DELETE FROM folders WHERE account = ?", (account,))
        shutil.rmtree(self.cache_root() / account, ignore_errors=True)

    # ---- messages -------------------------------------------------------------------------------
    def uids(self, folder_id: int) -> set[int]:
        with self.db() as db:
            return {r[0] for r in db.execute("SELECT uid FROM messages WHERE folder = ?", (folder_id,))}

    def add_messages(self, msgs: list[Message]):
        cols = [c for c in MSG_COLS if c != "id"]
        with self.db() as db:
            db.executemany(
                f"INSERT OR REPLACE INTO messages ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [tuple(int(v) if isinstance(v, bool) else v for v in (getattr(m, c) for c in cols)) for m in msgs])

    def update_flags(self, folder_id: int, flags: dict[int, set[str]]):
        with self.db() as db:
            db.executemany("UPDATE messages SET seen=?, answered=?, flagged=?, draft=?, forwarded=? "
                           "WHERE folder=? AND uid=?",
                           [(int("\\Seen" in f), int("\\Answered" in f), int("\\Flagged" in f), int("\\Draft" in f),
                             int("$Forwarded" in f), folder_id, uid) for uid, f in flags.items()])

    def set_flag(self, ids: list[int], column: str, value: bool):
        assert column in ("seen", "answered", "flagged", "forwarded")
        with self.db() as db:
            db.executemany(f"UPDATE messages SET {column} = ? WHERE id = ?", [(int(value), i) for i in ids])

    def remove_uids(self, folder_id: int, uids: set[int] | list[int]):
        if not uids:
            return
        f = self.folder(folder_id)
        with self.db() as db:
            db.executemany("DELETE FROM messages WHERE folder = ? AND uid = ?", [(folder_id, u) for u in uids])
        if f:
            for u in uids:
                try:
                    self.eml_path(f.account, folder_id, u).unlink()
                except OSError:
                    pass

    def remove_ids(self, ids: list[int]):
        for m in self.messages_by_ids(ids):
            self.remove_uids(m.folder, [m.uid])

    def _row_msg(self, r) -> Message:
        d = {k: r[k] for k in r.keys() if k in Message.__dataclass_fields__}
        for k in ("seen", "answered", "flagged", "forwarded", "draft", "attach"):
            d[k] = bool(d[k])
        return Message(**d)

    def messages(self, folder_id: int, search: str = "", order: str = "date", desc: bool = True,
                 unread_only: bool = False) -> list[Message]:
        col = {"date": "date", "from": "from_name || from_addr", "subject": "subject", "size": "size",
               "to": "to_addrs", "attach": "attach", "flag": "flagged", "importance": "importance"}.get(order, "date")
        q = "SELECT * FROM messages WHERE folder = ?"
        args: list = [folder_id]
        if search:
            q += " AND (subject LIKE ? OR from_name LIKE ? OR from_addr LIKE ? OR to_addrs LIKE ? OR cc_addrs LIKE ?)"
            args += [f"%{search}%"] * 5
        if unread_only:
            q += " AND seen = 0"
        q += f" ORDER BY {col} COLLATE NOCASE {'DESC' if desc else 'ASC'}, date DESC"
        with self.db() as db:
            return [self._row_msg(r) for r in db.execute(q, args)]

    def unread_messages(self, accounts: list[str] | None = None) -> list[Message]:
        q = ("SELECT m.* FROM messages m JOIN folders f ON f.id = m.folder WHERE m.seen = 0 "
             "AND f.role NOT IN ('junk', 'trash', 'sent', 'drafts', 'all', 'important', 'flagged')")
        with self.db() as db:
            rows = db.execute(q + " ORDER BY m.date DESC").fetchall()
        msgs = [self._row_msg(r) for r in rows]
        if accounts is not None:
            fids = {f.id for f in self.folders() if f.account in accounts}
            msgs = [x for x in msgs if x.folder in fids]
        return msgs

    def message(self, msg_id: int) -> Message | None:
        with self.db() as db:
            r = db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
        return self._row_msg(r) if r else None

    def messages_by_ids(self, ids: list[int]) -> list[Message]:
        out = []
        for i in ids:
            m = self.message(i)
            if m:
                out.append(m)
        return out

    def message_by_uid(self, folder_id: int, uid: int) -> Message | None:
        with self.db() as db:
            r = db.execute("SELECT * FROM messages WHERE folder = ? AND uid = ?", (folder_id, uid)).fetchone()
        return self._row_msg(r) if r else None

    # ---- cached message files -------------------------------------------------------------------
    def cache_root(self) -> Path:
        return self.path.parent / "messages"

    def eml_path(self, account: str, folder_id: int, uid: int) -> Path:
        return self.cache_root() / account / str(folder_id) / f"{uid}.eml"

    def cached_eml(self, msg: Message) -> bytes | None:
        f = self.folder(msg.folder)
        if not f:
            return None
        p = self.eml_path(f.account, msg.folder, msg.uid)
        try:
            return p.read_bytes()
        except OSError:
            return None

    def cache_eml(self, msg: Message, raw: bytes):
        f = self.folder(msg.folder)
        if not f:
            return
        p = self.eml_path(f.account, msg.folder, msg.uid)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(p)

    def _drop_cache(self, account: str, folder_id: int):
        shutil.rmtree(self.cache_root() / account / str(folder_id), ignore_errors=True)

    # ---- contacts -------------------------------------------------------------------------------
    def contacts(self, search: str = "") -> list[Contact]:
        q = "SELECT * FROM contacts"
        args: list = []
        if search:
            q += (" WHERE full_name LIKE ? OR email LIKE ? OR email2 LIKE ? OR company LIKE ? OR first LIKE ? "
                  "OR last LIKE ?")
            args = [f"%{search}%"] * 6
        with self.db() as db:
            rows = db.execute(q, args).fetchall()
        out = [Contact(**{k: r[k] for k in r.keys()}) for r in rows]
        out.sort(key=lambda c: c.file_as.lower())
        return out

    def contact(self, cid: int) -> Contact | None:
        with self.db() as db:
            r = db.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
        return Contact(**{k: r[k] for k in r.keys()}) if r else None

    def save_contact(self, c: Contact) -> int:
        c.changed = time.time()
        cols = [k for k in CONTACT_COLS if k != "id"]
        with self.db() as db:
            if c.id:
                db.execute(f"UPDATE contacts SET {', '.join(k + ' = ?' for k in cols)} WHERE id = ?",
                           [getattr(c, k) for k in cols] + [c.id])
            else:
                cur = db.execute(f"INSERT INTO contacts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                 [getattr(c, k) for k in cols])
                c.id = cur.lastrowid
        return c.id

    def delete_contacts(self, ids: list[int]):
        with self.db() as db:
            db.executemany("DELETE FROM contacts WHERE id = ?", [(i,) for i in ids])

    def contact_by_email(self, email: str) -> Contact | None:
        e = email.strip().lower()
        with self.db() as db:
            r = db.execute("SELECT * FROM contacts WHERE lower(email) = ? OR lower(email2) = ?", (e, e)).fetchone()
        return Contact(**{k: r[k] for k in r.keys()}) if r else None

    def remember_addresses(self, pairs: list[tuple[str, str]]):
        """(name, address) pairs the user sent to: they come first in address completion."""
        now = time.time()
        with self.db() as db:
            for name, addr in pairs:
                if not addr:
                    continue
                db.execute("INSERT INTO recent_addresses (email, name, count, last) VALUES (?, ?, 1, ?) "
                           "ON CONFLICT(email) DO UPDATE SET count = count + 1, last = excluded.last, "
                           "name = CASE WHEN excluded.name != '' THEN excluded.name ELSE name END",
                           (addr.lower(), name, now))

    def address_book(self) -> list[tuple[str, str]]:
        """(name, address) for completion: contacts first, then addresses used before."""
        out: list[tuple[str, str]] = []
        seen = set()
        for c in self.contacts():
            for e in (c.email, c.email2):
                if e and e.lower() not in seen:
                    seen.add(e.lower())
                    out.append((c.display, e))
        with self.db() as db:
            for r in db.execute("SELECT email, name FROM recent_addresses ORDER BY count DESC, last DESC"):
                if r["email"] not in seen:
                    seen.add(r["email"])
                    out.append((r["name"], r["email"]))
        return out


class _Ctx:
    """`with store.db() as db:` -> the connection, holding the write lock for the block."""

    def __init__(self, conn, lock):
        self.conn = conn
        self.lock = lock

    def __enter__(self):
        self.lock.acquire()
        self.conn.execute("BEGIN")
        return self.conn

    def __exit__(self, et, ev, tb):
        try:
            self.conn.execute("COMMIT" if et is None else "ROLLBACK")
        finally:
            self.lock.release()
        return False

    # allow db().execute(...) directly too
    def execute(self, *a):
        with self as c:
            return c.execute(*a)

    def executescript(self, s):
        self.lock.acquire()
        try:
            return self.conn.executescript(s)
        finally:
            self.lock.release()
