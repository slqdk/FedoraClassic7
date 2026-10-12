"""Mail: background work. Each account has two worker threads with their own IMAP connection:
"sync" (Send/Receive, which can take a while) and "ui" (opening messages, flags, moving), so
clicking a message never waits for a long download. Results come back on the GUI thread.
"""
from __future__ import annotations

import queue
import threading
import traceback

from PySide6.QtCore import QObject, Qt, Signal

import mail_accounts as acc_mod
import mail_imap as imap
import mail_send
from mail_store import Store


class Bridge(QObject):
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda f: f(), Qt.QueuedConnection)

    def post(self, fn):
        self.call.emit(fn)


class Runner:
    """A thread with one IMAP connection that runs jobs one after another."""

    def __init__(self, account: acc_mod.Account, bridge: Bridge, name: str):
        self.account = account
        self.bridge = bridge
        self.name = name
        self.q: queue.Queue = queue.Queue()
        self.conn: imap.Connection | None = None
        self.pending = 0
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._loop, name=f"mail-{name}-{account.id}", daemon=True)
        self.thread.start()

    def submit(self, fn, on_ok=None, on_err=None, imap_needed: bool = True):
        with self.lock:
            self.pending += 1
        self.q.put((fn, on_ok, on_err, imap_needed))

    def stop(self):
        self.q.put(None)

    def _connection(self) -> imap.Connection:
        if self.conn is None:
            self.conn = imap.Connection(self.account)
        self.conn.ensure()
        return self.conn

    def _loop(self):
        while True:
            job = self.q.get()
            if job is None:
                if self.conn:
                    self.conn.close()
                return
            fn, on_ok, on_err, imap_needed = job
            try:
                if imap_needed:
                    try:
                        conn = self._connection()
                        result = fn(conn)
                    except (imap.MailError, OSError, imap.imaplib.IMAP4.abort) as e:
                        if isinstance(e, imap.AuthError):
                            raise
                        # one retry on a fresh connection (servers drop idle sessions)
                        if self.conn:
                            self.conn.close()
                        self.conn = None
                        conn = self._connection()
                        result = fn(conn)
                else:
                    result = fn(None)
                if on_ok:
                    self.bridge.post(lambda r=result, f=on_ok: f(r))
            except Exception as e:   # noqa: BLE001
                msg = str(e) or type(e).__name__
                if not isinstance(e, (imap.MailError, mail_send.SendError)):
                    msg = imap.explain(e) if isinstance(e, OSError) else msg
                    traceback.print_exc()
                if self.conn and not isinstance(e, imap.AuthError):
                    try:
                        self.conn.close()
                    except Exception:   # noqa: BLE001
                        pass
                    self.conn = None
                if on_err:
                    self.bridge.post(lambda m=msg, f=on_err, ex=e: f(m, ex))
            finally:
                with self.lock:
                    self.pending -= 1


class AccountWorkers:
    def __init__(self, account: acc_mod.Account, bridge: Bridge):
        self.account = account
        self.sync = Runner(account, bridge, "sync")
        self.ui = Runner(account, bridge, "ui")

    def stop(self):
        self.sync.stop()
        self.ui.stop()

    @property
    def busy(self) -> bool:
        return self.sync.pending > 0


class Workers:
    def __init__(self, store: Store):
        self.store = store
        self.bridge = Bridge()
        self.by_id: dict[str, AccountWorkers] = {}

    def reload(self, accounts: list[acc_mod.Account]):
        ids = {a.id for a in accounts}
        for aid in list(self.by_id):
            if aid not in ids:
                self.by_id.pop(aid).stop()
        for a in accounts:
            w = self.by_id.get(a.id)
            if w is None or w.account != a:
                if w:
                    w.stop()
                self.by_id[a.id] = AccountWorkers(a, self.bridge)

    def get(self, account_id: str) -> AccountWorkers | None:
        return self.by_id.get(account_id)

    def stop_all(self):
        for w in self.by_id.values():
            w.stop()
        self.by_id.clear()

    @property
    def busy(self) -> bool:
        return any(w.busy for w in self.by_id.values())
