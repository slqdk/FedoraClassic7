"""Mail: the Reading Pane (and the window a message opens in when double-clicked)."""
from __future__ import annotations

import html as htmlmod
import os
import re
import secrets
import shutil
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QKeySequence, QAction
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSizePolicy, QTextBrowser, QToolBar, QToolButton, QVBoxLayout, QWidget)

import mail_accounts as acc_mod
import mail_icons as icons
import mail_render as render
import mail_ui as ui

WRITE_TYPES = (".doc", ".docx", ".rtf", ".odt", ".dot", ".dotx")

try:
    from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
                                         QWebEngineUrlRequestInterceptor)
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEBENGINE = os.environ.get("CLASSIC7_MAIL_NO_WEBENGINE") != "1"
except ImportError:      # pragma: no cover - the image ships QtWebEngine
    HAVE_WEBENGINE = False


def open_dir() -> Path:
    return acc_mod.cache_dir() / "open"


def save_temp(name: str, data: bytes) -> Path:
    d = open_dir() / secrets.token_hex(4)
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[/\\\x00]", "_", name).strip() or "attachment"
    p = d / safe
    p.write_bytes(data)
    return p


def open_file(path: Path, prefer_write: bool = True):
    from PySide6.QtCore import QProcess
    if prefer_write and path.suffix.lower() in WRITE_TYPES and shutil.which("classic7-write"):
        QProcess.startDetached("classic7-write", [str(path)])
    elif path.suffix.lower() == ".eml" and shutil.which("classic7-mail"):
        QProcess.startDetached("classic7-mail", [str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# ---- body views -------------------------------------------------------------------------------
if HAVE_WEBENGINE:
    class _Guard(QWebEngineUrlRequestInterceptor):
        """Blocks pictures and other content from the Internet unless allowed for this message."""

        def __init__(self):
            super().__init__()
            self.allow_remote = False

        def interceptRequest(self, info):
            scheme = info.requestUrl().scheme()
            if scheme in ("http", "https", "ftp", "ws", "wss") and not self.allow_remote:
                info.block(True)

    class _Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, nav_type, is_main):
            if nav_type == QWebEnginePage.NavigationTypeLinkClicked:
                QDesktopServices.openUrl(url)
                return False
            return url.scheme() in ("file", "data", "about") or not is_main

        def createWindow(self, _type):
            return None

    _profile = None
    _guard = None

    def _shared_profile():
        global _profile, _guard
        if _profile is None:
            _profile = QWebEngineProfile()          # off the record: no cookies or cache on disk
            _guard = _Guard()
            _profile.setUrlRequestInterceptor(_guard)
            s = _profile.settings()
            s.setAttribute(QWebEngineSettings.JavascriptEnabled, False)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
            s.setAttribute(QWebEngineSettings.AutoLoadImages, True)
            s.setAttribute(QWebEngineSettings.ErrorPageEnabled, False)
        return _profile, _guard


class BodyView(QWidget):
    """The message text: QtWebEngine (scripts off, Internet content blocked) or, without it,
    QTextBrowser."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.web = None
        if HAVE_WEBENGINE:
            profile, self.guard = _shared_profile()
            self.web = QWebEngineView()
            self.web.setPage(_Page(profile, self.web))
            self.web.setContextMenuPolicy(Qt.DefaultContextMenu)
            lay.addWidget(self.web)
            self.view = self.web
        else:
            self.text = QTextBrowser()
            self.text.setOpenLinks(False)
            self.text.anchorClicked.connect(QDesktopServices.openUrl)
            self.text.setFrameShape(QFrame.NoFrame)
            lay.addWidget(self.text)
            self.view = self.text
        self.dir: Path | None = None

    def show_html(self, html: str, files: dict[str, bytes], allow_remote: bool):
        """files: name -> bytes written next to the page (inline pictures)."""
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir = acc_mod.cache_dir() / "view" / secrets.token_hex(4)
        self.dir.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (self.dir / name).write_bytes(data)
        page = self.dir / "message.html"
        page.write_text(html, encoding="utf-8")
        if self.web is not None:
            self.guard.allow_remote = allow_remote
            self.web.setUrl(QUrl.fromLocalFile(str(page)))
        else:
            self.text.document().setBaseUrl(QUrl.fromLocalFile(str(self.dir) + "/"))
            self.text.setSearchPaths([str(self.dir)])
            body = re.sub(r"(?is)<style.*?</style>", "", html)
            self.text.setHtml(body)

    def clear(self):
        if self.web is not None:
            self.web.setHtml("<html><body style='background:white'></body></html>")
        else:
            self.text.clear()
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir = None

    def print_to(self, printer, done=None):
        if self.web is not None:
            self.web.page().print(printer, lambda ok: done and done(ok))
        else:
            self.text.document().print_(printer)
            if done:
                done(True)


# ---- reading pane -----------------------------------------------------------------------------
class InfoBar(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("infobar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        self.icon = QLabel()
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.icon)
        lay.addWidget(self.label, 1)
        self.hide()

    def show_text(self, text: str, icon: QIcon | None = None, clickable=False):
        self.label.setText(text)
        self.label.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        self.icon.setPixmap(icon.pixmap(16, 16) if icon else QIcon().pixmap(16, 16))
        self.icon.setVisible(icon is not None)
        self.clickable = clickable
        self.show()

    def mouseReleaseEvent(self, e):
        if getattr(self, "clickable", False) and e.button() == Qt.LeftButton:
            self.clicked.emit()


class ReadingPane(QWidget):
    """Header (subject, sender, date, recipients, attachments) and the message text."""

    attachmentOpened = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pane")
        self.settings = QSettings("Classic7", "Mail")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.info_pictures = InfoBar()
        self.info_pictures.clicked.connect(self._picture_menu)
        self.info_other = InfoBar()
        lay.addWidget(self.info_other)
        lay.addWidget(self.info_pictures)

        self.header = QFrame()
        self.header.setObjectName("readHeader")
        h = QVBoxLayout(self.header)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(1)
        self.subject = ui.bold(QLabel(), 12)
        self.subject.setWordWrap(True)
        self.subject.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sender = ui.bold(QLabel())
        self.sender.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sent = QLabel()
        self.to = QLabel()
        self.to.setWordWrap(True)
        self.to.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.cc = QLabel()
        self.cc.setWordWrap(True)
        self.cc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        for w in (self.subject, self.sender, self.sent, self.to, self.cc):
            h.addWidget(w)
        self.attach_row = QWidget()
        ar = QHBoxLayout(self.attach_row)
        ar.setContentsMargins(0, 4, 0, 0)
        ar.setSpacing(2)
        lbl = QLabel("Attachments:")
        lbl.setStyleSheet("color:#505050")
        ar.addWidget(lbl)
        self.attach_box = QHBoxLayout()
        self.attach_box.setSpacing(2)
        ar.addLayout(self.attach_box)
        ar.addStretch(1)
        h.addWidget(self.attach_row)
        lay.addWidget(self.header)

        self.body = BodyView()
        lay.addWidget(self.body, 1)

        self.empty = QLabel("Select an item to read")
        self.empty.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.empty.setContentsMargins(0, 40, 0, 0)
        self.empty.setStyleSheet("color:#808080; background:white")
        lay.addWidget(self.empty, 1)
        self.parsed: render.Parsed | None = None
        self.allowed_remote = False
        self.clear()

    # -- showing --
    def clear(self, text: str = "Select an item to read"):
        self.parsed = None
        self.empty.setText(text)
        self.header.hide()
        self.info_pictures.hide()
        self.info_other.hide()
        self.body.hide()
        self.body.clear()
        self.empty.show()

    def safe_senders(self) -> list[str]:
        return [s.lower() for s in (self.settings.value("safeSenders", [], list) or [])]

    def show_message(self, p: render.Parsed, answered=False, forwarded=False, allow_remote=None):
        self.parsed = p
        self.empty.hide()
        self.header.show()
        self.body.show()
        self.subject.setText(htmlmod.escape(p.subject) or "(no subject)")
        self.subject.setTextFormat(Qt.RichText)
        frm = p.from_[0] if p.from_ else ("", "")
        self.sender.setText(f"{frm[0]} [{frm[1]}]" if frm[0] and frm[1] and frm[0] != frm[1] else (frm[1] or frm[0]))
        self.sent.setText(f"Sent: {render.outlook_date(p.date)}" if p.date else "")
        self.to.setText(f"To: {p.to_text}" if p.to else "")
        self.to.setVisible(bool(p.to))
        self.cc.setText(f"Cc: {p.cc_text}" if p.cc else "")
        self.cc.setVisible(bool(p.cc))
        self._fill_attachments(p)

        notes = []
        if p.importance > 0:
            notes.append("This message was sent with High importance.")
        if answered:
            notes.append("You replied to this message.")
        elif forwarded:
            notes.append("You forwarded this message.")
        if notes:
            icon = icons.get("high") if p.importance > 0 else icons.get("replied" if answered else "forwarded")
            self.info_other.show_text(" ".join(notes), icon)
        else:
            self.info_other.hide()

        sender = (frm[1] or "").lower()
        if allow_remote is None:
            allow_remote = sender in self.safe_senders() or (sender and "@" + sender.split("@")[-1] in self.safe_senders())
        self.allowed_remote = bool(allow_remote)
        if p.has_remote and not self.allowed_remote:
            self.info_pictures.show_text(
                "Click here to download pictures. To help protect your privacy, Mail prevented automatic "
                "download of some pictures in this message.", icons.theme("dialog-information", "flag-outline"), True)
        else:
            self.info_pictures.hide()

        files, cid_map = {}, {}
        for i, (cid, att) in enumerate(p.related.items()):
            ext = att.mime.split("/")[-1].split("+")[0] if "/" in att.mime else "bin"
            name = f"inline{i}.{ext}"
            files[name] = att.data
            cid_map[cid] = name
        self.body.show_html(render.body_html(p, cid_map), files, self.allowed_remote)

    def _fill_attachments(self, p: render.Parsed):
        while self.attach_box.count():
            it = self.attach_box.takeAt(0)
            wdg = it.widget()
            if wdg is not None:
                wdg.hide()
                wdg.setParent(None)
                wdg.deleteLater()
        for att in p.attachments:
            b = QToolButton()
            b.setAutoRaise(True)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setText(f"{att.name} ({render.human_size(att.size)})")
            b.setIcon(_file_icon(att.name, att.mime))
            b.setPopupMode(QToolButton.InstantPopup)
            b.setMenu(self._attachment_menu(att))
            b.setStyleSheet("QToolButton{padding:1px 4px} QToolButton::menu-indicator{image:none}")
            self.attach_box.addWidget(b)
        self.attach_row.setVisible(bool(p.attachments))

    def _attachment_menu(self, att) -> QMenu:
        m = QMenu(self)
        ext = Path(att.name).suffix.lower()
        if ext in WRITE_TYPES:
            a = m.addAction(icons.theme(["x-office-document"], "folder"), "&Open in Write", lambda: self.open_attachment(att))
        else:
            a = m.addAction("&Open", lambda: self.open_attachment(att))
        f = a.font()
        f.setBold(True)
        a.setFont(f)
        m.addSeparator()
        m.addAction(icons.theme("document-save-as", "folder"), "Save &As...", lambda: self.save_attachment(att))
        if self.parsed and len(self.parsed.attachments) > 1:
            m.addAction("Save A&ll Attachments...", self.save_all)
        return m

    def open_attachment(self, att):
        p = save_temp(att.name, att.data)
        open_file(p)
        self.attachmentOpened.emit(str(p))

    def save_attachment(self, att):
        start = str(_downloads() / att.name)
        path, _ = QFileDialog.getSaveFileName(self, "Save Attachment", start)
        if path:
            Path(path).write_bytes(att.data)

    def save_all(self):
        if not self.parsed:
            return
        d = QFileDialog.getExistingDirectory(self, "Save All Attachments", str(_downloads()))
        if d:
            for att in self.parsed.attachments:
                target = Path(d) / att.name
                n = 1
                while target.exists():
                    target = Path(d) / f"{Path(att.name).stem} ({n}){Path(att.name).suffix}"
                    n += 1
                target.write_bytes(att.data)

    def _picture_menu(self):
        if not self.parsed:
            return
        m = QMenu(self)
        m.addAction("&Download Pictures", lambda: self.show_message(self.parsed, allow_remote=True))
        frm = self.parsed.from_[0][1] if self.parsed.from_ else ""
        if frm:
            m.addAction(f"Add Sender to Safe Senders &List", lambda: self._add_safe(frm))
            m.addAction(f"Add the Domain @{frm.split('@')[-1]} to Safe Senders List",
                        lambda: self._add_safe("@" + frm.split("@")[-1]))
        m.exec(self.info_pictures.mapToGlobal(self.info_pictures.rect().bottomLeft()))

    def _add_safe(self, who: str):
        lst = self.settings.value("safeSenders", [], list) or []
        if who.lower() not in [x.lower() for x in lst]:
            lst.append(who)
            self.settings.setValue("safeSenders", lst)
        self.show_message(self.parsed, allow_remote=True)

    def print_message(self, parent=None):
        if not self.parsed:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, parent or self)
        if dlg.exec():
            print_parsed(self.parsed, printer)


def print_parsed(p: render.Parsed, printer):
    """Memo style, like Outlook: the name at the top, a rule, the header lines, the text."""
    from PySide6.QtGui import QTextDocument
    acc = acc_mod.default_account()
    who = acc.display_name or acc.email if acc else ""
    rows = [("From", p.from_text), ("Sent", render.outlook_date(p.date)), ("To", p.to_text)]
    if p.cc:
        rows.append(("Cc", p.cc_text))
    rows.append(("Subject", p.subject))
    if p.attachments:
        rows.append(("Attachments", "; ".join(a.name for a in p.attachments)))
    head = "".join(f"<tr><td style='padding-right:12px'><b>{k}:</b></td><td>{htmlmod.escape(v)}</td></tr>"
                   for k, v in rows)
    inner = render._inner_body(p.html) if p.html else render.text_html(p.text)
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Calibri", 11))
    doc.setHtml(f"<p style='font-size:14pt'><b>{htmlmod.escape(who)}</b></p><hr>"
                f"<table>{head}</table><br>{inner}")
    doc.print_(printer)


def _downloads() -> Path:
    for name in ("Downloads", "Overførsler", "Hentede filer"):
        p = Path.home() / name
        if p.is_dir():
            return p
    return Path.home()


def _file_icon(name: str, mime: str) -> QIcon:
    from PySide6.QtCore import QMimeDatabase
    db = QMimeDatabase()
    mt = db.mimeTypeForFile(name, QMimeDatabase.MatchExtension)
    for n in (mt.iconName(), mt.genericIconName(), mime.replace("/", "-")):
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return icons.get("attach")


# ---- a message in its own window --------------------------------------------------------------
class MessageWindow(QMainWindow):
    """Double-clicked message (or an .eml file). Actions are handed to `handler` (the main
    window), which knows the accounts; for a lone .eml file it may be None."""

    def __init__(self, parsed: render.Parsed, handler=None, msg=None, raw: bytes | None = None):
        super().__init__()
        self.parsed = parsed
        self.handler = handler
        self.msg = msg
        self.raw = raw
        self.setWindowTitle(f"{parsed.subject or '(no subject)'} - Message")
        self.setWindowIcon(icons.get("opened"))
        self.setStyleSheet(ui.STYLE)
        tb = QToolBar()
        tb.setObjectName("standard")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        def act(text, icon, slot, key=None):
            a = QAction(icon, text, self)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(QKeySequence(key))
            tb.addAction(a)
            return a

        act("&Reply", icons.get("reply"), lambda: self._do("reply"), "Ctrl+R")
        act("Reply to A&ll", icons.get("reply-all"), lambda: self._do("reply_all"), "Ctrl+Shift+R")
        act("For&ward", icons.get("forward"), lambda: self._do("forward"), "Ctrl+F")
        tb.addSeparator()
        act("", icons.theme("document-print", "folder"), lambda: self.pane.print_message(self), "Ctrl+P").setToolTip("Print")
        if handler is not None and msg is not None:
            act("", icons.get("delete"), lambda: self._do("delete"), "Delete").setToolTip("Delete")
            act("", icons.get("move"), lambda: self._do("move"), "Ctrl+Shift+V").setToolTip("Move to Folder")
            tb.addSeparator()
            act("", icons.theme("go-up", "folder"), lambda: self._do("previous"), "Ctrl+,").setToolTip("Previous Item")
            act("", icons.theme("go-down", "folder"), lambda: self._do("next"), "Ctrl+.").setToolTip("Next Item")
        if raw is not None:
            act("Save &As", icons.theme("document-save-as", "folder"), self.save_as, "F12")
        act("", QIcon(), self.close, "Esc").setVisible(False)
        self.pane = ReadingPane()
        self.setCentralWidget(self.pane)
        self.pane.show_message(parsed, msg.answered if msg else False, msg.forwarded if msg else False)
        self.resize(780, 680)

    def set_message(self, parsed, msg, raw=None):
        self.parsed, self.msg, self.raw = parsed, msg, raw
        self.setWindowTitle(f"{parsed.subject or '(no subject)'} - Message")
        self.pane.show_message(parsed, msg.answered if msg else False, msg.forwarded if msg else False)

    def _do(self, what: str):
        if what in ("reply", "reply_all", "forward"):
            import mail_compose
            mail_compose.open_reply(self.parsed, what, self.msg, parent_handler=self.handler)
            return
        if self.handler is not None:
            self.handler.message_window_action(self, what)

    def save_as(self):
        name = re.sub(r"[/\\:*?\"<>|]", "_", self.parsed.subject or "message")[:80] + ".eml"
        path, _ = QFileDialog.getSaveFileName(self, "Save As", str(Path.home() / "Documents" / name),
                                              "Mail message (*.eml);;Text Only (*.txt);;HTML (*.html)")
        if not path:
            return
        if path.endswith(".txt"):
            Path(path).write_text(self.parsed.text or __import__("mail_send").html_to_text(self.parsed.html))
        elif path.endswith(".html"):
            Path(path).write_text(render.body_html(self.parsed))
        else:
            Path(path).write_bytes(self.raw or b"")


def open_eml_file(path: str) -> MessageWindow | None:
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        QMessageBox.critical(None, ui.APP, f"The file can't be opened.\n\n{e}")
        return None
    w = MessageWindow(render.parse(raw), None, None, raw)
    w.show()
    return w
