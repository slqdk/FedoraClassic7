"""Mail: the message window (Untitled - Message), built on Write's editor and ribbon, laid out
like Outlook 2007's: Message / Insert / Options / Format Text tabs, a big Send button and the
To, Cc, Bcc, Subject and Attached lines above the text."""
from __future__ import annotations

import mimetypes
import re
import threading
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, QStringListModel, Qt, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QFont, QIcon, QImage, QKeySequence, QTextCursor, QTextDocument,
                           QTextImageFormat)
from PySide6.QtWidgets import (QApplication, QCompleter, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

import mail_accounts as acc_mod
import mail_icons as icons
import mail_imap as imap
import mail_render as render
import mail_send
import mail_ui as ui
import write_app as wa
import write_model as wm
import write_ribbon as rb
from mail_store import Store
from mail_worker import Bridge
from write_page import PageSetup

_open: list = []          # keeps message windows alive


# =============================================================================
# address line with completion
# =============================================================================
class AddressEdit(QLineEdit):
    """To/Cc/Bcc: completes the name after the last ';' from Contacts and earlier addresses."""

    def __init__(self, entries: list[str], parent=None):
        super().__init__(parent)
        self.model = QStringListModel(entries)
        self.comp = QCompleter(self.model, self)
        self.comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.comp.setFilterMode(Qt.MatchContains)
        self.comp.setWidget(self)
        self.comp.activated.connect(self._insert)
        self.textEdited.connect(self._edited)

    def _token(self) -> tuple[int, str]:
        text = self.text()[:self.cursorPosition()]
        cut = max(text.rfind(";"), text.rfind(","))
        return cut + 1, text[cut + 1:].lstrip()

    def _edited(self, _t):
        _start, tok = self._token()
        if len(tok) >= 1:
            self.comp.setCompletionPrefix(tok)
            if self.comp.completionCount():
                self.comp.complete()
                return
        self.comp.popup().hide()

    def _insert(self, value: str):
        start, _tok = self._token()
        head = self.text()[:start]
        tail = self.text()[self.cursorPosition():]
        sep = " " if head and not head.endswith(" ") else ""
        new = f"{head}{sep}{value}; "
        self.setText(new + tail.lstrip("; "))
        self.setCursorPosition(len(new))

    def keyPressEvent(self, e):
        if self.comp.popup().isVisible() and e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
            e.ignore()
            return
        super().keyPressEvent(e)


def _png(img) -> bytes:
    if not isinstance(img, QImage):
        try:
            img = img.toImage()
        except AttributeError:
            return b""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


# =============================================================================
# the message window
# =============================================================================
class Composer(wa.WriteWindow):
    def __init__(self, store: Store | None = None, account_id: str | None = None, to: str = "", cc: str = "",
                 bcc: str = "", subject: str = "", html: str = "", body: str = "", attachments=None,
                 handler=None, reply_msg=None, kind: str = "new", in_reply_to: str = "", references: str = "",
                 draft_ref: tuple | None = None, related: dict | None = None, signature: bool = True):
        self.store = store or (handler.store if handler is not None else Store())
        self.handler = handler
        self.accounts = acc_mod.load()
        acc = next((a for a in self.accounts if a.id == account_id), None) or acc_mod.default_account(self.accounts)
        self.account = acc
        self.reply_msg = reply_msg
        self.kind = kind
        self.in_reply_to = in_reply_to
        self.references = references
        self.draft_ref = draft_ref          # (account id, folder path, uid) of the saved draft
        self.attachments: list = []
        self.importance = 0
        self.plain = False
        self.sending = False
        self.bridge = Bridge()
        super().__init__(None)
        # Outlook's keys win over Write's: Ctrl+Enter sends, Ctrl+K checks names
        self.a_pagebreak.setShortcuts([])
        self.a_link.setShortcuts([])
        self.setWindowIcon(icons.get("new"))
        self.statusBar().hide()
        self.editor.set_fit(True)
        self.editor.apply_setup(PageSetup(top=3, bottom=3, left=3.5, right=3.5))
        self._header_widgets(to, cc, bcc, subject)

        doc = wm.new_document()
        wm.apply_style(QTextCursor(doc), "No Spacing")
        for cid, att in (related or {}).items():
            img = QImage.fromData(att.data)
            if not img.isNull():
                doc.addResource(QTextDocument.ImageResource, QUrl(f"cid:{cid}"), img)
        c = QTextCursor(doc)
        sig = self._signature_html(kind)
        if html:
            c.insertHtml(("<p></p>" if kind != "draft" else "") + (sig if kind != "draft" else "") + html)
        else:
            if body:
                c.insertText(body)
            c.insertBlock()
            if sig:
                c.insertHtml(sig)
        doc.setModified(False)
        self.set_document(doc, self.editor.setup)
        self.editor.set_fit(True)
        start = QTextCursor(doc)
        start.movePosition(QTextCursor.Start)
        self.editor.setTextCursor(start)
        for a in attachments or []:
            self.add_attachment(a)
        doc.setModified(False)
        self.modified_fields = False
        self._update_title()
        self.resize(1020, 720)
        _open.append(self)
        if to or kind in ("reply", "reply_all"):
            self.editor.setFocus()
        else:
            self.to_edit.setFocus()

    # ---- signature ----------------------------------------------------------------------------
    def _signature_html(self, kind: str) -> str:
        a = self.account
        if not a or not a.signature:
            return ""
        key = "sig_new" if kind == "new" else "sig_reply"
        if not a.extra.get(key, True) or kind == "draft":
            return ""
        inner = render._inner_body(a.signature)
        return f"<p></p>{inner}"

    def insert_signature(self, account=None):
        a = account or self.account
        if a and a.signature:
            self.editor.textCursor().insertHtml(render._inner_body(a.signature))

    # ---- window furniture -----------------------------------------------------------------------
    def _qat_actions(self):
        return [self.a_save, self.a_undo, self.a_redo]

    def _office_menu(self) -> QMenu:
        menu = QMenu(self)
        self.a_send_menu = menu.addAction(icons.get("send"), "Sen&d", self.send)
        menu.addSeparator()
        menu.addAction(icons.get("new"), "&New Message", lambda: Composer(self.store, handler=self.handler).show())
        menu.addAction(self.a_save)
        save_as = menu.addMenu(rb.icon("document-save-as", "A"), "Save &As")
        save_as.addAction("Mail Message (.eml)", lambda: self.save_file(".eml"))
        save_as.addAction("Word Document (.docx)", lambda: self.save_file(".docx"))
        save_as.addAction("HTML (.html)", lambda: self.save_file(".html"))
        save_as.addAction("Plain Text (.txt)", lambda: self.save_file(".txt"))
        menu.addAction(icons.get("delete"), "&Delete", self.discard)
        menu.addSeparator()
        menu.addAction(self.a_print)
        menu.addSeparator()
        menu.addAction(self.a_close)
        return menu

    def _ribbon(self):
        top, v = self._ribbon_top()
        r = rb.Ribbon()
        self.ribbon = r
        A = self.act

        self.a_send = A("&Send", self.send, ["Alt+S", "Ctrl+Return"], icon=icons.get("send"))
        self.a_attach = A("Attach File", self.attach_dialog, "Ctrl+Shift+A", icon=icons.get("attach"), size=rb.BIG)
        self.a_names = A("Address Book", self.select_names, "Ctrl+Shift+B", icon=icons.get("address-book"), size=rb.BIG)
        self.a_check = A("Check Names", self.check_names, "Ctrl+K", icon=icons.get("names"), size=rb.BIG)
        self.a_sig = A("Signature", None, None, icon=icons.get("signature"), size=rb.BIG)
        self.a_high = A("High Importance", lambda on: self._importance(1 if on else 0), None, icon=icons.get("high"),
                        checkable=True)
        self.a_low = A("Low Importance", lambda on: self._importance(-1 if on else 0), None, icon=icons.get("low"),
                       checkable=True)
        self.a_receipt = A("Request a Read Receipt", None, None, fallback="✓", checkable=True)
        self.a_bcc = A("Show Bcc", lambda on: self._show_bcc(on), None, fallback="Bcc", checkable=True, size=rb.BIG)
        self.a_from = A("Show From", lambda on: self._show_from(on), None, fallback="From", checkable=True, size=rb.BIG)
        fmt = QActionGroup(self)
        self.a_html = A("HTML", lambda: self._set_plain(False), None, fallback="Aa", checkable=True)
        self.a_plain = A("Plain Text", lambda: self._set_plain(True), None, fallback="Aa", checkable=True, bold=False)
        fmt.addAction(self.a_html)
        fmt.addAction(self.a_plain)
        self.a_html.setChecked(True)
        sig_menu = QMenu(self)
        sig_menu.aboutToShow.connect(lambda: self._fill_sig_menu(sig_menu))

        # Message
        msg = r.add_tab("Message")
        self._group_clipboard(r, msg)
        g = r.group(msg, "Basic Text")
        self.font_box = wa.QFontComboBox()
        self.font_box.setMaximumWidth(150)
        self.font_box.setMinimumWidth(120)
        self.font_box.textActivated.connect(self.set_family)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in wa.FONT_SIZES])
        self.size_box.setMaximumWidth(60)
        self.size_box.setMinimumWidth(54)
        self.size_box.textActivated.connect(self.set_size)
        color_menu = rb.color_menu(self, rb.WORD_COLORS, 10, self.set_color, "Automatic")
        hl_menu = rb.color_menu(self, rb.HIGHLIGHT_COLORS, 5, self.set_highlight, "No Color")
        g.add_column(
            [self.font_box, self.size_box, rb.small_button(self.a_grow), rb.small_button(self.a_shrink),
             rb.small_button(self.a_bullets), rb.small_button(self.a_numbering)],
            [rb.small_button(self.a_bold), rb.small_button(self.a_italic), rb.small_button(self.a_underline),
             rb.small_button(self.a_highlight, hl_menu, split=True), rb.small_button(self.a_color, color_menu, split=True),
             rb.small_button(self.a_left), rb.small_button(self.a_center), rb.small_button(self.a_right),
             rb.small_button(self.a_indent_less), rb.small_button(self.a_indent_more)])
        g = r.group(msg, "Names")
        g.add(rb.big_button(self.a_names))
        g.add(rb.big_button(self.a_check))
        g = r.group(msg, "Include")
        g.add(rb.big_button(self.a_attach))
        g.add(rb.big_button(self.a_sig, sig_menu))
        g = r.group(msg, "Options")
        g.add_column([rb.small_button(self.a_high, with_text=True)], [rb.small_button(self.a_low, with_text=True)])
        g = r.group(msg, "Proofing")
        g.add(rb.big_button(self.a_spell))

        # Insert
        ins = r.add_tab("Insert")
        g = r.group(ins, "Include")
        g.add(rb.big_button(self.a_attach))
        g.add(rb.big_button(self.a_sig, sig_menu))
        self._group_tables(r, ins)
        g = r.group(ins, "Illustrations")
        g.add(rb.big_button(self.a_picture))
        g = r.group(ins, "Links")
        g.add(rb.big_button(self.a_link))
        g = r.group(ins, "Text")
        g.add(rb.big_button(self.a_date))
        g.add(rb.big_button(self.a_hr))
        g = r.group(ins, "Symbols")
        g.add(rb.big_button(self.a_symbol, rb.symbol_menu(self, self.insert_text)))

        # Options
        op = r.add_tab("Options")
        g = r.group(op, "Fields")
        g.add(rb.big_button(self.a_bcc))
        g.add(rb.big_button(self.a_from))
        g = r.group(op, "Format")
        g.add_column([rb.small_button(self.a_html, with_text=True)], [rb.small_button(self.a_plain, with_text=True)])
        g = r.group(op, "Tracking")
        g.add_column([rb.small_button(self.a_receipt, with_text=True)])
        g = r.group(op, "Importance")
        g.add_column([rb.small_button(self.a_high, with_text=True)], [rb.small_button(self.a_low, with_text=True)])

        # Format Text (Write's Home tab)
        ft = r.add_tab("Format Text")
        fb, sb = self.font_box, self.size_box
        self._group_font(r, ft)
        self.font_boxes = [fb, self.font_box]
        self.size_boxes = [sb, self.size_box]
        self.font_box, self.size_box = fb, sb
        self._group_paragraph(r, ft)
        self._group_styles(r, ft)
        self._group_editing(r, ft)

        self._ribbon_finish(top, v, r)

    def _char_changed(self, cf):
        # keep both font boxes (Message and Format Text tabs) in step
        super()._char_changed(cf)
        boxes = getattr(self, "font_boxes", None)
        if boxes:
            fam = self.font_box.currentText()
            size = self.size_box.currentText()
            for b in boxes:
                if b is not self.font_box:
                    b.blockSignals(True)
                    b.setCurrentText(fam)
                    b.blockSignals(False)
            for b in self.size_boxes:
                if b is not self.size_box:
                    b.blockSignals(True)
                    b.setCurrentText(size)
                    b.blockSignals(False)

    def _header_widgets(self, to, cc, bcc, subject):
        entries = []
        for name, addr in self.store.address_book():
            entries.append(f"{name} <{addr}>" if name and name != addr else addr)
        box = QFrame()
        box.setStyleSheet("QFrame#hdr{background:#F3F6FB;border-bottom:1px solid #B6C7E0}")
        box.setObjectName("hdr")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(6, 6, 8, 6)
        self.send_btn = QToolButton()
        self.send_btn.setDefaultAction(self.a_send)
        self.send_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.send_btn.setIconSize(QSize(32, 32))
        self.send_btn.setFixedSize(58, 70)
        self.send_btn.setStyleSheet(
            "QToolButton{border:1px solid #8DB2E3;border-radius:3px;font-weight:bold;"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #FFFFFF,stop:0.5 #E3EFFF,stop:0.51 #D0E2FA,stop:1 #E6F0FD)}"
            "QToolButton:hover{border-color:#DBCE99;background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #FFFCD9,stop:0.5 #FFEFB0,stop:0.51 #FFE48A,stop:1 #FFF1B8)}"
            "QToolButton:pressed{background:#FFC870}")
        lay.addWidget(self.send_btn, 0, Qt.AlignTop)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        def name_button(text, slot):
            b = QPushButton(text)
            b.setFixedWidth(72)
            b.clicked.connect(slot)
            return b

        self.from_btn = QPushButton("Fro&m")
        self.from_btn.setFixedWidth(72)
        self.from_combo = QComboBox()
        for a in self.accounts:
            self.from_combo.addItem(f"{a.sender}", a.id)
        if self.account:
            self.from_combo.setCurrentIndex(max(0, self.from_combo.findData(self.account.id)))
        self.from_combo.currentIndexChanged.connect(self._from_changed)
        self.from_btn.clicked.connect(self.from_combo.showPopup)
        grid.addWidget(self.from_btn, 0, 0)
        grid.addWidget(self.from_combo, 0, 1)
        self.to_edit = AddressEdit(entries)
        self.to_edit.setText(to)
        self.cc_edit = AddressEdit(entries)
        self.cc_edit.setText(cc)
        self.bcc_edit = AddressEdit(entries)
        self.bcc_edit.setText(bcc)
        self.subject_edit = QLineEdit(subject)
        self.to_btn = name_button("T&o...", self.select_names)
        self.cc_btn = name_button("&Cc...", self.select_names)
        self.bcc_btn = name_button("&Bcc...", self.select_names)
        grid.addWidget(self.to_btn, 1, 0)
        grid.addWidget(self.to_edit, 1, 1)
        grid.addWidget(self.cc_btn, 2, 0)
        grid.addWidget(self.cc_edit, 2, 1)
        grid.addWidget(self.bcc_btn, 3, 0)
        grid.addWidget(self.bcc_edit, 3, 1)
        subj = QLabel("Subj&ect:")
        subj.setBuddy(self.subject_edit)
        subj.setFixedWidth(72)
        subj.setIndent(4)
        grid.addWidget(subj, 4, 0)
        grid.addWidget(self.subject_edit, 4, 1)
        self.att_label = QLabel("Attached:")
        self.att_label.setIndent(4)
        self.att_box = QWidget()
        self.att_lay = QHBoxLayout(self.att_box)
        self.att_lay.setContentsMargins(0, 0, 0, 0)
        self.att_lay.setSpacing(2)
        self.att_lay.addStretch(1)
        self.att_box.setStyleSheet("QWidget{background:white}")
        grid.addWidget(self.att_label, 5, 0)
        grid.addWidget(self.att_box, 5, 1)
        lay.addLayout(grid, 1)
        self.subject_edit.textChanged.connect(self._update_title)
        for e in (self.to_edit, self.cc_edit, self.bcc_edit, self.subject_edit):
            e.textEdited.connect(lambda *_: setattr(self, "modified_fields", True))

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(box)
        ed = self.takeCentralWidget()
        cl.addWidget(ed, 1)
        self.setCentralWidget(container)
        show_bcc = bool(bcc) or (self.settings.value("mail/showBcc", "false") in (True, "true"))
        show_from = len(self.accounts) > 1
        self.a_bcc.setChecked(show_bcc)
        self.a_from.setChecked(show_from)
        self._show_bcc(show_bcc, remember=False)
        self._show_from(show_from)
        self._refresh_attachments()

    def _show_bcc(self, on, remember=True):
        self.bcc_btn.setVisible(on)
        self.bcc_edit.setVisible(on)
        if remember:
            self.settings.setValue("mail/showBcc", on)

    def _show_from(self, on):
        self.from_btn.setVisible(on)
        self.from_combo.setVisible(on)

    def _from_changed(self):
        aid = self.from_combo.currentData()
        self.account = next((a for a in self.accounts if a.id == aid), self.account)

    def _fill_sig_menu(self, m: QMenu):
        m.clear()
        for a in self.accounts:
            if a.signature:
                m.addAction(a.name or a.email, lambda a=a: self.insert_signature(a))
        if not m.actions():
            m.addAction("(none)").setEnabled(False)
        m.addSeparator()
        m.addAction("Signatures...", self._edit_signatures)

    def _edit_signatures(self):
        import mail_setup
        mail_setup.SignaturesDialog(self).exec()
        self.accounts = acc_mod.load()
        self._from_changed()

    def _importance(self, value):
        self.importance = value
        self.a_high.blockSignals(True)
        self.a_low.blockSignals(True)
        self.a_high.setChecked(value > 0)
        self.a_low.setChecked(value < 0)
        self.a_high.blockSignals(False)
        self.a_low.blockSignals(False)

    def _set_plain(self, plain: bool):
        if plain == self.plain:
            return
        if plain:
            if QMessageBox.question(self, ui.APP, "Changing to Plain Text removes all formatting and pictures "
                                    "from this message. Continue?") != QMessageBox.Yes:
                self.a_html.setChecked(True)
                return
            text = self.editor.toPlainText().replace("￼", "")
            doc = wm.new_document()
            doc.setDefaultFont(QFont("Consolas", 10))
            QTextCursor(doc).insertText(text)
            self.set_document(doc, self.editor.setup)
            self.editor.set_fit(True)
            self.editor.setAcceptRichText(False)
        else:
            self.editor.setAcceptRichText(True)
        self.plain = plain
        self.editor.document().setModified(True)
        self._update_title()

    def _update_title(self):
        subj = self.subject_edit.text().strip() if hasattr(self, "subject_edit") else ""
        self.setWindowTitle(f"{subj or 'Untitled'} - Message ({'Plain Text' if self.plain else 'HTML'})")

    # ---- names ------------------------------------------------------------------------------
    def select_names(self):
        import mail_contacts
        dlg = mail_contacts.SelectNamesDialog(self.store, self.to_edit.text(), self.cc_edit.text(),
                                              self.bcc_edit.text(), self)
        if dlg.exec():
            to, cc, bcc = dlg.values()
            self.to_edit.setText(to)
            self.cc_edit.setText(cc)
            self.bcc_edit.setText(bcc)
            if bcc:
                self.a_bcc.setChecked(True)
                self._show_bcc(True, remember=False)
            self.modified_fields = True

    def _resolve(self, text: str) -> tuple[str, list[str]]:
        """Turn names typed without an address into "Name <address>" using Contacts."""
        out, unknown = [], []
        book = self.store.address_book()
        for part in [p.strip() for p in re.split(r"[;\n]", text) if p.strip()]:
            if "@" in part:
                out.append(part)
                continue
            low = part.lower()
            hits = [(n, a) for n, a in book if low in (n or "").lower()]
            exact = [(n, a) for n, a in hits if (n or "").lower() == low]
            pick = exact[0] if exact else hits[0] if len(hits) == 1 else None
            if pick:
                out.append(f"{pick[0]} <{pick[1]}>" if pick[0] else pick[1])
            else:
                out.append(part)
                unknown.append(part)
        return "; ".join(out) + ("; " if out else ""), unknown

    def check_names(self) -> bool:
        bad = []
        for e in (self.to_edit, self.cc_edit, self.bcc_edit):
            text, unknown = self._resolve(e.text())
            e.setText(text)
            bad += unknown
            bad += [b for b in mail_send.bad_addresses(text) if b not in unknown]
        if bad:
            QMessageBox.warning(self, ui.APP, "Mail does not recognize " + ", ".join(f"\"{b}\"" for b in bad) +
                                ".\n\nType a complete e-mail address, or pick the name with Address Book.")
            return False
        return True

    # ---- attachments ------------------------------------------------------------------------
    def attach_dialog(self):
        start = str(Path.home() / "Documents")
        paths, _ = QFileDialog.getOpenFileNames(self, "Insert File", start, "All Files (*)")
        for p in paths:
            self.add_attachment(p)

    def file_open(self):
        self.attach_dialog()

    def add_attachment(self, a):
        if isinstance(a, (str, Path)):
            p = Path(a)
            if not p.is_file():
                QMessageBox.warning(self, ui.APP, f"The file \"{p}\" can't be found.")
                return
            self.attachments.append(str(p))
        else:
            self.attachments.append(a)
        self.modified_fields = True
        self._refresh_attachments()

    def _att_name(self, a) -> str:
        return Path(a).name if isinstance(a, str) else a[0]

    def _att_size(self, a) -> int:
        try:
            return Path(a).stat().st_size if isinstance(a, str) else len(a[1])
        except OSError:
            return 0

    def _refresh_attachments(self):
        while self.att_lay.count() > 1:
            it = self.att_lay.takeAt(0)
            wdg = it.widget()
            if wdg is not None:
                wdg.hide()
                wdg.setParent(None)
                wdg.deleteLater()
        for i, a in enumerate(self.attachments):
            b = QToolButton()
            b.setAutoRaise(True)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            name = self._att_name(a)
            b.setText(f"{name} ({render.human_size(self._att_size(a))})")
            from mail_view import _file_icon
            b.setIcon(_file_icon(name, mimetypes.guess_type(name)[0] or ""))
            m = QMenu(b)
            ext = Path(name).suffix.lower()
            m.addAction("&Open in Write" if ext in (".doc", ".docx", ".rtf", ".odt") else "&Open",
                        lambda a=a: self._open_attachment(a))
            m.addAction(icons.get("delete"), "&Remove", lambda i=i: self._remove_attachment(i))
            b.setMenu(m)
            b.setPopupMode(QToolButton.InstantPopup)
            b.setStyleSheet("QToolButton::menu-indicator{image:none}")
            self.att_lay.insertWidget(self.att_lay.count() - 1, b)
        on = bool(self.attachments)
        self.att_label.setVisible(on)
        self.att_box.setVisible(on)

    def _open_attachment(self, a):
        import mail_view
        if isinstance(a, str):
            mail_view.open_file(Path(a))
        else:
            mail_view.open_file(mail_view.save_temp(a[0], a[1]))

    def _remove_attachment(self, i):
        if 0 <= i < len(self.attachments):
            self.attachments.pop(i)
            self.modified_fields = True
            self._refresh_attachments()

    # ---- building the message -----------------------------------------------------------------
    def outgoing(self) -> mail_send.Outgoing:
        doc = self.editor.document()
        out = mail_send.Outgoing(to=self.to_edit.text(), cc=self.cc_edit.text(),
                                 bcc=self.bcc_edit.text() if self.bcc_edit.isVisible() or self.bcc_edit.text() else "",
                                 subject=self.subject_edit.text().strip(), attachments=list(self.attachments),
                                 in_reply_to=self.in_reply_to, references=self.references.strip(),
                                 importance=self.importance, read_receipt=self.a_receipt.isChecked(),
                                 plain_only=self.plain)
        text = doc.toPlainText().replace("￼", "").replace(" ", "\n")
        out.text = text.rstrip() + "\n"
        if not self.plain:
            html = doc.toHtml()
            names = set()
            block = doc.begin()
            while block.isValid():
                it = block.begin()
                while not it.atEnd():
                    frag = it.fragment()
                    if frag.isValid() and frag.charFormat().isImageFormat():
                        names.add(frag.charFormat().toImageFormat().name())
                    it += 1
                block = block.next()
            dom = acc_mod.domain_of(self.account.email) if self.account else "classic7"
            for n, name in enumerate(sorted(names)):
                res = doc.resource(QTextDocument.ImageResource, QUrl(name))
                if res is None:
                    continue
                data = _png(res)
                if not data:
                    continue
                cid = name[4:] if name.startswith("cid:") else f"image{n + 1:03d}.{abs(hash(name)) % 10**8}@{dom}"
                out.images[cid] = (data, "image/png")
                html = html.replace(f'src="{name}"', f'src="cid:{cid}"')
            out.html = html
        return out

    # ---- sending ------------------------------------------------------------------------------
    def send(self):
        if self.sending:
            return
        if not self.account:
            QMessageBox.warning(self, ui.APP, "Set up an e-mail account first (Tools > Account Settings in Mail).")
            return
        if not (self.to_edit.text().strip() or self.cc_edit.text().strip() or self.bcc_edit.text().strip()):
            QMessageBox.warning(self, ui.APP, "There must be at least one name or contact group in the To, Cc, or "
                                "Bcc box.")
            self.to_edit.setFocus()
            return
        if not self.check_names():
            return
        if not self.subject_edit.text().strip():
            if QMessageBox.question(self, ui.APP, "This message has no subject. Do you want to send it anyway?") \
                    != QMessageBox.Yes:
                self.subject_edit.setFocus()
                return
        try:
            out = self.outgoing()
            msg = mail_send.build(self.account, out)
        except OSError as e:
            QMessageBox.critical(self, ui.APP, f"The message could not be prepared.\n\n{e}")
            return
        self.sending = True
        self.a_send.setEnabled(False)
        self.setEnabled(False)
        QApplication.setOverrideCursor(Qt.BusyCursor)
        acc = self.account
        store = self.store
        reply = self.reply_msg
        draft = self.draft_ref
        sent_role_changed = []

        def work():
            try:
                mail_send.send(acc, msg)
            except Exception as e:   # noqa: BLE001
                self.bridge.post(lambda m=str(e): self._send_failed(m))
                return
            warn = ""
            try:
                conn = imap.Connection(acc).open()
                try:
                    if acc.save_sent:
                        sent = store.folder_by_role(acc.id, "sent")
                        path = sent.path if sent else _find_role(conn, "sent")
                        if path:
                            conn.append(path, msg.as_bytes(policy=_smtp_policy()), "\\Seen")
                            sent_role_changed.append("sent")
                    elif acc.provider:
                        sent_role_changed.append("sent")
                    if reply is not None:
                        f = store.folder(reply.folder)
                        if f:
                            flag = "\\Answered" if self.kind in ("reply", "reply_all") else "$Forwarded"
                            conn.store(f.path, [reply.uid], "+FLAGS.SILENT", flag)
                    if draft:
                        conn.store(draft[1], [draft[2]], "+FLAGS.SILENT", "\\Deleted")
                        conn.expunge(draft[1], [draft[2]])
                        sent_role_changed.append("drafts")
                finally:
                    conn.close()
            except Exception as e:   # noqa: BLE001
                warn = str(e)
            pairs = mail_send.split_addresses(", ".join(x for x in (msg.get("To", ""), msg.get("Cc", ""),
                                                                    msg.get("Bcc", "")) if x))
            try:
                store.remember_addresses(pairs)
            except Exception:   # noqa: BLE001
                pass
            self.bridge.post(lambda: self._sent(warn, sent_role_changed))

        threading.Thread(target=work, daemon=True).start()

    def _send_failed(self, msg):
        QApplication.restoreOverrideCursor()
        self.sending = False
        self.setEnabled(True)
        self.a_send.setEnabled(True)
        QMessageBox.critical(self, ui.APP, f"The message could not be sent.\n\n{msg}")

    def _sent(self, warn, changed):
        QApplication.restoreOverrideCursor()
        if self.handler is not None:
            try:
                self.handler.after_send(self.account.id, self.reply_msg, self.kind, changed)
            except RuntimeError:
                pass
        if warn:
            QMessageBox.information(self, ui.APP, f"The message was sent, but a copy could not be saved in Sent "
                                    f"Items.\n\n{warn}")
        self.editor.document().setModified(False)
        self.modified_fields = False
        self.close()

    # ---- drafts ---------------------------------------------------------------------------------
    def file_save(self) -> bool:
        return self.save_draft()

    def save_draft(self, then_close=False) -> bool:
        if not self.account:
            return False
        try:
            out = self.outgoing()
            msg = mail_send.build(self.account, out)
        except OSError as e:
            QMessageBox.critical(self, ui.APP, f"The draft could not be saved.\n\n{e}")
            return False
        raw = msg.as_bytes(policy=_smtp_policy())
        acc, store, old = self.account, self.store, self.draft_ref
        msgid = str(msg["Message-ID"])
        QApplication.setOverrideCursor(Qt.BusyCursor)
        result = {}

        def work():
            try:
                conn = imap.Connection(acc).open()
                try:
                    f = store.folder_by_role(acc.id, "drafts")
                    path = f.path if f else _find_role(conn, "drafts")
                    if not path:
                        path = "Drafts"
                        conn.create_folder(path)
                    uid = conn.append(path, raw, "\\Draft \\Seen")
                    if uid is None:
                        uid = conn.find_uid(path, msgid)
                    if old and old[0] == acc.id:
                        try:
                            conn.store(old[1], [old[2]], "+FLAGS.SILENT", "\\Deleted")
                            conn.expunge(old[1], [old[2]])
                        except Exception:   # noqa: BLE001
                            pass
                    result["ref"] = (acc.id, path, uid) if uid else None
                finally:
                    conn.close()
            except Exception as e:   # noqa: BLE001
                result["error"] = str(e)
            self.bridge.post(done)

        def done():
            QApplication.restoreOverrideCursor()
            if "error" in result:
                QMessageBox.warning(self, ui.APP, f"The draft could not be saved in Drafts.\n\n{result['error']}")
                return
            self.draft_ref = result.get("ref")
            self.editor.document().setModified(False)
            self.modified_fields = False
            self.statusBar().showMessage("Saved in Drafts", 3000)
            if self.handler is not None:
                try:
                    self.handler.after_send(acc.id, None, "draft", ["drafts"])
                except RuntimeError:
                    pass
            if then_close:
                self.close()

        threading.Thread(target=work, daemon=True).start()
        return True

    def save_file(self, ext: str):
        name = re.sub(r"[/\\:*?\"<>|]", "_", self.subject_edit.text().strip() or "Untitled")[:80] + ext
        path, _ = QFileDialog.getSaveFileName(self, "Save As", str(Path.home() / "Documents" / name))
        if not path:
            return
        if ext == ".eml":
            out = self.outgoing()
            Path(path).write_bytes(mail_send.build(self.account or acc_mod.Account(email="me@localhost"), out)
                                   .as_bytes(policy=_smtp_policy()))
        elif ext == ".html":
            Path(path).write_text(self.editor.document().toHtml(), encoding="utf-8")
        elif ext == ".txt":
            Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")
        else:
            import write_docx
            write_docx.save_docx(self.editor.document(), PageSetup(), path)

    def discard(self):
        if QMessageBox.question(self, ui.APP, "Delete this message?") != QMessageBox.Yes:
            return
        d = self.draft_ref
        if d:
            acc = next((a for a in self.accounts if a.id == d[0]), None)
            if acc:
                def work():
                    try:
                        conn = imap.Connection(acc).open()
                        conn.store(d[1], [d[2]], "+FLAGS.SILENT", "\\Deleted")
                        conn.expunge(d[1], [d[2]])
                        conn.close()
                    except Exception:   # noqa: BLE001
                        pass
                threading.Thread(target=work, daemon=True).start()
        self.editor.document().setModified(False)
        self.modified_fields = False
        self.close()

    def maybe_save(self) -> bool:
        changed = self.editor.document().isModified() or self.modified_fields
        if not changed or self.sending:
            return True
        r = QMessageBox.question(self, ui.APP, "Do you want to save changes?",
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
        if r == QMessageBox.Yes:
            self.save_draft(then_close=True)
            return False
        return r == QMessageBox.No

    def closeEvent(self, ev):
        if self.maybe_save():
            ev.accept()
            if self in _open:
                _open.remove(self)
        else:
            ev.ignore()

    def file_new(self):
        Composer(self.store, handler=self.handler).show()


def _smtp_policy():
    from email import policy
    return policy.SMTP


def _find_role(conn, role: str) -> str | None:
    for f in conn.list_folders():
        if f["role"] == role:
            return f["path"]
    return None


# =============================================================================
# entry points
# =============================================================================
def _store_of(handler) -> Store:
    return handler.store if handler is not None else Store()


def _account_of(store: Store, msg) -> str | None:
    if msg is None:
        return None
    f = store.folder(msg.folder)
    return f.account if f else None


def open_reply(p: render.Parsed, kind: str, msg=None, parent_handler=None) -> Composer:
    store = _store_of(parent_handler)
    aid = _account_of(store, msg)
    accounts = acc_mod.load()
    acc = next((a for a in accounts if a.id == aid), None) or acc_mod.default_account(accounts)
    me = [a.email for a in accounts]
    attachments, to, cc = [], "", ""
    if kind == "reply":
        to = imap.format_addresses(p.reply_to or p.from_)
        subject = render.reply_subject(p.subject)
    elif kind == "reply_all":
        to, cc = render.reply_all_recipients(p, me)
        subject = render.reply_subject(p.subject)
    else:
        subject = render.forward_subject(p.subject)
        attachments = [(a.name, a.data, a.mime) for a in p.attachments]
    refs = (p.references + " " + p.msgid).strip() if kind != "forward" else ""
    c = Composer(store, account_id=acc.id if acc else None, to=to, cc=cc, subject=subject,
                 html=render.quoted_body_html(p), attachments=attachments, handler=parent_handler, reply_msg=msg,
                 kind=kind, in_reply_to=p.msgid if kind != "forward" else "", references=refs,
                 related=p.related)
    c.show()
    return c


def forward_as_attachment(p: render.Parsed, raw: bytes, msg, handler) -> Composer:
    store = _store_of(handler)
    name = re.sub(r"[/\\:*?\"<>|]", "_", p.subject or "message")[:60] + ".eml"
    c = Composer(store, account_id=_account_of(store, msg), subject=render.forward_subject(p.subject),
                 attachments=[(name, raw, "message/rfc822")], handler=handler, reply_msg=msg, kind="forward")
    c.show()
    return c


def open_draft(p: render.Parsed, raw: bytes, msg, handler) -> Composer:
    store = _store_of(handler)
    f = store.folder(msg.folder) if msg else None
    html = render._inner_body(p.html) if p.html else ""
    body = "" if p.html else p.text
    c = Composer(store, account_id=f.account if f else None, to=p.to_text, cc=p.cc_text,
                 bcc=imap.format_addresses(p.bcc), subject=p.subject, html=html, body=body,
                 attachments=[(a.name, a.data, a.mime) for a in p.attachments], handler=handler, kind="draft",
                 draft_ref=(f.account, f.path, msg.uid) if f else None, related=p.related)
    c.show()
    return c


def parse_mailto(url: str) -> dict:
    """mailto:a@b.c,d@e.f?subject=Hi&cc=x@y.z&body=Hello -> Composer arguments."""
    rest = url[len("mailto:"):] if url.lower().startswith("mailto:") else url
    addr, _, query = rest.partition("?")
    q = urllib.parse.parse_qs(query, keep_blank_values=True)
    out = {"to": "; ".join(x for x in [urllib.parse.unquote(addr)] + q.get("to", []) if x)}
    for key in ("cc", "bcc", "subject", "body"):
        if key in q:
            out[key] = "; ".join(q[key]) if key in ("cc", "bcc") else q[key][0]
    if "body" in out:
        out["body"] = out["body"].replace("\r\n", "\n")
    return out
