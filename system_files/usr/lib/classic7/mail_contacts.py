"""Mail: Contacts (Address Cards and Phone List), the contact form, the Address Book and
Select Names dialogs, and vCard import/export."""
from __future__ import annotations

import quopri
import re
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QStackedWidget,
                               QStyle, QStyledItemDelegate, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import mail_icons as icons
import mail_ui as ui
from mail_store import Contact, Store


# =============================================================================
# vCard
# =============================================================================
def _unescape(v: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def parse_vcards(text: str) -> list[Contact]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].upper():
            lines[-1] = lines[-1][:-1] + raw
        else:
            lines.append(raw)
    out, cur = [], None
    for line in lines:
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        parts = head.split(";")
        name = parts[0].split(".")[-1].upper()
        params = ";".join(parts[1:]).upper()
        if "QUOTED-PRINTABLE" in params:
            cs = re.search(r"CHARSET=([\w-]+)", params)
            value = quopri.decodestring(value.encode("latin-1", errors="replace")).decode(
                cs.group(1) if cs else "utf-8", errors="replace")
        if name == "BEGIN" and value.strip().upper() == "VCARD":
            cur = Contact()
        elif name == "END" and cur is not None:
            if not cur.full_name:
                cur.full_name = " ".join(x for x in (cur.first, cur.last) if x) or cur.company or cur.email
            out.append(cur)
            cur = None
        elif cur is None:
            continue
        elif name == "FN":
            cur.full_name = _unescape(value).strip()
        elif name == "N":
            f = (re.split(r"(?<!\\);", value) + [""] * 5)
            cur.last, cur.first = _unescape(f[0]).strip(), _unescape(f[1]).strip()
        elif name == "ORG":
            cur.company = _unescape(re.split(r"(?<!\\);", value)[0]).strip()
        elif name == "TITLE":
            cur.job_title = _unescape(value).strip()
        elif name == "EMAIL":
            v = _unescape(value).strip()
            if not cur.email:
                cur.email = v
            elif not cur.email2:
                cur.email2 = v
        elif name == "TEL":
            v = _unescape(value).strip().replace("tel:", "")
            if "CELL" in params or "MOBILE" in params:
                cur.phone_mobile = cur.phone_mobile or v
            elif "HOME" in params:
                cur.phone_home = cur.phone_home or v
            elif "WORK" in params:
                cur.phone_work = cur.phone_work or v
            elif not cur.phone_mobile:
                cur.phone_mobile = v
        elif name == "ADR":
            f = [_unescape(x).strip() for x in (re.split(r"(?<!\\);", value) + [""] * 7)[:7]]
            # pobox; ext; street; city; region; zip; country
            cur.address = "\n".join(x for x in (f[2], " ".join(y for y in (f[5], f[3]) if y), f[4], f[6]) if x)
        elif name == "URL":
            cur.web = _unescape(value).strip()
        elif name == "NOTE":
            cur.notes = _unescape(value)
    return out


def to_vcard(c: Contact) -> str:
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{_escape(c.display)}",
             f"N:{_escape(c.last)};{_escape(c.first)};;;"]
    if c.company:
        lines.append(f"ORG:{_escape(c.company)}")
    if c.job_title:
        lines.append(f"TITLE:{_escape(c.job_title)}")
    for e in (c.email, c.email2):
        if e:
            lines.append(f"EMAIL;TYPE=INTERNET:{e}")
    for kind, v in (("WORK,VOICE", c.phone_work), ("HOME,VOICE", c.phone_home), ("CELL", c.phone_mobile)):
        if v:
            lines.append(f"TEL;TYPE={kind}:{v}")
    if c.address:
        a = c.address.split("\n")
        street = a[0] if a else ""
        rest = " ".join(a[1:])
        lines.append(f"ADR;TYPE=WORK:;;{_escape(street)};{_escape(rest)};;;")
    if c.web:
        lines.append(f"URL:{c.web}")
    if c.notes:
        lines.append(f"NOTE:{_escape(c.notes)}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split()
    if len(parts) < 2:
        return full.strip(), ""
    return " ".join(parts[:-1]), parts[-1]


# =============================================================================
# contact form
# =============================================================================
class ContactDialog(QDialog):
    messageTo = Signal(str)

    def __init__(self, store: Store, contact: Contact | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.c = contact or Contact()
        self.setWindowTitle(f"{self.c.display or 'Untitled'} - Contact")
        self.setWindowIcon(icons.get("contact"))
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        save = QPushButton(icons.get("contact"), " Save && Close")
        save.setDefault(True)
        save.clicked.connect(self.save)
        bar.addWidget(save)
        if self.c.id:
            delete = QPushButton(icons.get("delete"), " Delete")
            delete.clicked.connect(self.delete)
            bar.addWidget(delete)
        mail = QPushButton(icons.get("new"), " E-mail")
        mail.clicked.connect(self._mail)
        bar.addWidget(mail)
        bar.addStretch(1)
        lay.addLayout(bar)

        body = QHBoxLayout()
        left = QVBoxLayout()
        g = QGroupBox()
        f = QFormLayout(g)
        self.full = QLineEdit(self.c.full_name or " ".join(x for x in (self.c.first, self.c.last) if x))
        self.company = QLineEdit(self.c.company)
        self.job = QLineEdit(self.c.job_title)
        self.file_as = QComboBox()
        self.file_as.setEditable(False)
        f.addRow("F&ull Name:", self.full)
        f.addRow("&Company:", self.company)
        f.addRow("&Job title:", self.job)
        f.addRow("File &as:", self.file_as)
        left.addWidget(g)
        g2 = QGroupBox("Internet")
        f2 = QFormLayout(g2)
        self.email = QLineEdit(self.c.email)
        self.email2 = QLineEdit(self.c.email2)
        self.web = QLineEdit(self.c.web)
        f2.addRow("&E-mail:", self.email)
        f2.addRow("E-mail &2:", self.email2)
        f2.addRow("&Web page address:", self.web)
        left.addWidget(g2)
        g3 = QGroupBox("Phone numbers")
        f3 = QFormLayout(g3)
        self.work = QLineEdit(self.c.phone_work)
        self.home = QLineEdit(self.c.phone_home)
        self.mobile = QLineEdit(self.c.phone_mobile)
        f3.addRow("&Business:", self.work)
        f3.addRow("&Home:", self.home)
        f3.addRow("&Mobile:", self.mobile)
        left.addWidget(g3)
        g4 = QGroupBox("Addresses")
        f4 = QVBoxLayout(g4)
        self.address = QPlainTextEdit(self.c.address)
        self.address.setFixedHeight(64)
        f4.addWidget(self.address)
        left.addWidget(g4)
        body.addLayout(left, 3)
        right = QVBoxLayout()
        right.addWidget(QLabel("Notes:"))
        self.notes = QPlainTextEdit(self.c.notes)
        right.addWidget(self.notes, 1)
        body.addLayout(right, 2)
        lay.addLayout(body, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.full.textChanged.connect(self._fill_file_as)
        self.company.textChanged.connect(self._fill_file_as)
        self._fill_file_as()
        self.resize(720, 520)

    def _fill_file_as(self):
        first, last = split_name(self.full.text())
        opts = []
        if last:
            opts.append(f"{last}, {first}")
        if self.full.text().strip():
            opts.append(self.full.text().strip())
        if self.company.text().strip():
            opts.append(self.company.text().strip())
        cur = self.file_as.currentText()
        self.file_as.clear()
        self.file_as.addItems(opts or [""])
        if cur in opts:
            self.file_as.setCurrentText(cur)

    def _collect(self) -> Contact:
        c = self.c
        c.full_name = self.full.text().strip()
        c.first, c.last = split_name(c.full_name)
        c.company = self.company.text().strip()
        c.job_title = self.job.text().strip()
        c.email = self.email.text().strip()
        c.email2 = self.email2.text().strip()
        c.web = self.web.text().strip()
        c.phone_work = self.work.text().strip()
        c.phone_home = self.home.text().strip()
        c.phone_mobile = self.mobile.text().strip()
        c.address = self.address.toPlainText().strip()
        c.notes = self.notes.toPlainText()
        return c

    def save(self):
        c = self._collect()
        if not (c.full_name or c.company or c.email):
            QMessageBox.information(self, "Contact", "Enter a name, a company or an e-mail address.")
            return
        self.store.save_contact(c)
        self.accept()

    def delete(self):
        if QMessageBox.question(self, "Contact", f"Delete {self.c.display}?") == QMessageBox.Yes:
            self.store.delete_contacts([self.c.id])
            self.accept()

    def _mail(self):
        c = self._collect()
        if c.email:
            self.messageTo.emit(_addr(c))


def _addr(c: Contact) -> str:
    n = c.display
    return f"{n} <{c.email}>" if n and n != c.email else c.email


# =============================================================================
# address cards
# =============================================================================
class CardModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.items: list[Contact] = []

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        c = self.items[index.row()]
        if role == Qt.UserRole:
            return c
        if role == Qt.DisplayRole:
            return c.file_as
        return None


CARD_W = 230


def card_fields(c: Contact) -> list[tuple[str, str]]:
    rows = []
    if c.full_name and c.full_name != c.file_as:
        rows.append(("Full Name:", c.full_name))
    if c.job_title:
        rows.append(("Job Title:", c.job_title))
    if c.company and c.company != c.file_as:
        rows.append(("Company:", c.company))
    for line in c.address.split("\n") if c.address else []:
        rows.append(("", line))
    for label, v in (("Business:", c.phone_work), ("Home:", c.phone_home), ("Mobile:", c.phone_mobile),
                     ("E-mail:", c.email), ("E-mail 2:", c.email2), ("Web Page:", c.web)):
        if v:
            rows.append((label, v))
    return rows


class CardDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        c = index.data(Qt.UserRole)
        fm = QFontMetrics(option.font)
        return QSize(CARD_W, fm.height() + 8 + max(1, len(card_fields(c))) * (fm.height() + 1) + 10)

    def paint(self, p: QPainter, option, index):
        c: Contact = index.data(Qt.UserRole)
        r = option.rect.adjusted(4, 3, -4, -3)
        fm = QFontMetrics(option.font)
        selected = option.state & QStyle.State_Selected
        p.save()
        head = QRect(r.left(), r.top(), r.width(), fm.height() + 6)
        g = QLinearGradient(0, head.top(), 0, head.bottom())
        if selected:
            g.setColorAt(0, QColor("#FFD98C"))
            g.setColorAt(1, QColor("#FFB843"))
        else:
            g.setColorAt(0, QColor("#EEF3FA"))
            g.setColorAt(1, QColor("#D3DEEE"))
        p.fillRect(head, g)
        p.setPen(QColor("#A8B8D0"))
        p.drawLine(head.bottomLeft(), head.bottomRight())
        f = QFont(option.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#000000"))
        p.drawText(head.adjusted(4, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(c.file_as, Qt.ElideRight, head.width() - 8))
        p.setFont(option.font)
        y = head.bottom() + 4
        fields = card_fields(c)
        label_w = max([fm.horizontalAdvance(l) for l, _v in fields if l] + [40]) + 8
        for label, value in fields:
            p.setPen(QColor("#404040"))
            p.drawText(QRect(r.left() + 4, y, label_w, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, label)
            p.setPen(QColor("#000000"))
            x = r.left() + 4 + (label_w if label else 0)
            p.drawText(QRect(x, y, r.right() - x - 2, fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(value, Qt.ElideRight, r.right() - x - 2))
            y += fm.height() + 1
        p.restore()


class ContactsNav(QWidget):
    viewChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(ui.SubHeader("My Contacts"))
        lst = QTreeWidget()
        lst.setObjectName("folders")
        lst.setHeaderHidden(True)
        lst.setRootIsDecorated(False)
        it = QTreeWidgetItem(["Contacts"])
        it.setIcon(0, icons.get("contacts"))
        lst.addTopLevelItem(it)
        lst.setCurrentItem(it)
        lst.setMaximumHeight(44)
        lay.addWidget(lst)
        lay.addWidget(ui.SubHeader("Current View"))
        box = QWidget()
        box.setStyleSheet("background:white")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(10, 6, 6, 6)
        group = QButtonGroup(self)
        for i, (key, label) in enumerate((("cards", "Address Cards"), ("phone", "Phone List"))):
            rb = QRadioButton(label)
            rb.setChecked(i == 0)
            rb.toggled.connect(lambda on, k=key: on and self.viewChanged.emit(k))
            group.addButton(rb)
            bl.addWidget(rb)
        bl.addStretch(1)
        lay.addWidget(box, 1)


class ContactsView(QWidget):
    messageTo = Signal(str)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.contacts: list[Contact] = []
        self.setObjectName("pane")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = ui.PaneHeader("Contacts", 14)
        self.search = ui.SearchBox("Search Contacts")
        self.search.setFixedWidth(180)
        self.search.textChanged.connect(self.reload)
        self.header.add_right(self.search)
        lay.addWidget(self.header)
        row = QHBoxLayout()
        row.setSpacing(0)
        self.stack = QStackedWidget()
        self.model = CardModel()
        self.cards = QListView()
        self.cards.setObjectName("cards")
        self.cards.setModel(self.model)
        self.cards.setItemDelegate(CardDelegate(self.cards))
        self.cards.setViewMode(QListView.ListMode)
        self.cards.setFlow(QListView.TopToBottom)
        self.cards.setWrapping(True)
        self.cards.setResizeMode(QListView.Adjust)
        self.cards.setSpacing(4)
        self.cards.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.cards.doubleClicked.connect(lambda i: self.edit(i.data(Qt.UserRole)))
        self.cards.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cards.customContextMenuRequested.connect(self._menu)
        self.stack.addWidget(self.cards)
        self.phone = QTreeWidget()
        self.phone.setObjectName("phoneList")
        self.phone.setRootIsDecorated(False)
        self.phone.setHeaderLabels(["Full Name", "Company", "File As", "Business Phone", "Home Phone",
                                    "Mobile Phone", "E-mail"])
        self.phone.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.phone.setSortingEnabled(True)
        self.phone.itemDoubleClicked.connect(lambda it, _c: self.edit(it.data(0, Qt.UserRole)))
        self.phone.setContextMenuPolicy(Qt.CustomContextMenu)
        self.phone.customContextMenuRequested.connect(self._menu)
        self.stack.addWidget(self.phone)
        row.addWidget(self.stack, 1)
        # letter index, like Outlook's
        idx = QWidget()
        idx.setStyleSheet("QToolButton{border:none;background:#EEF3FA;color:#15428B;font-size:8pt;padding:0}"
                          "QToolButton:hover{background:#FFE6A0}")
        il = QVBoxLayout(idx)
        il.setContentsMargins(1, 2, 1, 2)
        il.setSpacing(1)
        for label in ["123"] + [f"{a}{b}" for a, b in zip("acegikmoqsuwy", "bdfhjlnprtvxz")]:
            b = QToolButton()
            b.setText(label)
            b.setFixedWidth(26)
            b.clicked.connect(lambda _=False, l=label: self.jump(l))
            il.addWidget(b)
        il.addStretch(1)
        self.letter_index = idx
        row.addWidget(idx)
        lay.addLayout(row, 1)
        self.mode = "cards"

    def set_mode(self, mode: str):
        self.mode = mode
        self.stack.setCurrentIndex(0 if mode == "cards" else 1)
        self.letter_index.setVisible(mode == "cards")

    def reload(self):
        self.contacts = self.store.contacts(self.search.text().strip())
        self.model.set_items(self.contacts)
        self.phone.setSortingEnabled(False)
        self.phone.clear()
        for c in self.contacts:
            it = QTreeWidgetItem([c.display, c.company, c.file_as, c.phone_work, c.phone_home, c.phone_mobile, c.email])
            it.setData(0, Qt.UserRole, c)
            it.setIcon(0, icons.get("contact"))
            self.phone.addTopLevelItem(it)
        self.phone.setSortingEnabled(True)
        self.phone.sortByColumn(2, Qt.AscendingOrder)
        for i in range(self.phone.columnCount()):
            self.phone.resizeColumnToContents(i)
        w = self.window()
        if hasattr(w, "_update_counts"):
            w._update_counts()

    def jump(self, label: str):
        for i, c in enumerate(self.contacts):
            k = (c.file_as[:1] or " ").lower()
            if (label == "123" and not k.isalpha()) or k in label:
                idx = self.model.index(i)
                self.cards.scrollTo(idx, QAbstractItemView.PositionAtTop)
                self.cards.setCurrentIndex(idx)
                return

    def selected(self) -> list[Contact]:
        if self.mode == "cards":
            return [i.data(Qt.UserRole) for i in self.cards.selectionModel().selectedIndexes()]
        return [it.data(0, Qt.UserRole) for it in self.phone.selectedItems()]

    def _menu(self, pos):
        sel = self.selected()
        m = QMenu(self)
        if len(sel) == 1:
            m.addAction(icons.get("contact"), "&Open", lambda: self.edit(sel[0]))
        if sel:
            m.addAction(icons.get("new"), "Create &New Message to Contact", self.message_to_selected)
            m.addAction("E&xport as vCard...", lambda: self.export_vcards(selected=True))
            m.addSeparator()
            m.addAction(icons.get("delete"), "&Delete", self.delete_selected)
        else:
            m.addAction(icons.get("contact"), "&New Contact", self.new_contact)
        src = self.cards if self.mode == "cards" else self.phone
        m.exec(src.viewport().mapToGlobal(pos))

    def edit(self, c: Contact):
        dlg = ContactDialog(self.store, self.store.contact(c.id) or c, self)
        dlg.messageTo.connect(self.messageTo)
        dlg.exec()
        self.reload()

    def new_contact(self, email: str = "", name: str = ""):
        c = Contact(full_name=name, email=email)
        dlg = ContactDialog(self.store, c, self)
        dlg.messageTo.connect(self.messageTo)
        dlg.exec()
        self.reload()

    def delete_selected(self):
        sel = self.selected()
        if not sel:
            return
        if QMessageBox.question(self, "Contacts", f"Delete {len(sel)} contact{'s' if len(sel) > 1 else ''}?") \
                == QMessageBox.Yes:
            self.store.delete_contacts([c.id for c in sel])
            self.reload()

    def message_to_selected(self):
        sel = [c for c in self.selected() if c.email]
        if sel:
            self.messageTo.emit("; ".join(_addr(c) for c in sel))

    def import_vcards(self, path: str | None = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Import Contacts", str(Path.home()),
                                                  "vCard Files (*.vcf *.vcard);;All files (*)")
        if not path:
            return
        try:
            text = Path(path).read_bytes().decode("utf-8", errors="replace")
        except OSError as e:
            QMessageBox.warning(self, "Import", str(e))
            return
        cs = parse_vcards(text)
        added = 0
        for c in cs:
            if c.email and self.store.contact_by_email(c.email):
                continue
            self.store.save_contact(c)
            added += 1
        self.reload()
        QMessageBox.information(self, "Import", f"{added} contact{'s' if added != 1 else ''} imported"
                                + (f" ({len(cs) - added} already in Contacts)." if len(cs) > added else "."))

    def export_vcards(self, selected=False):
        cs = self.selected() if selected else self.store.contacts()
        if not cs:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Contacts", str(Path.home() / "Documents" / "Contacts.vcf"),
                                              "vCard Files (*.vcf)")
        if path:
            Path(path).write_text("".join(to_vcard(c) for c in cs), encoding="utf-8")

    def print_cards(self):
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        if not QPrintDialog(printer, self).exec():
            return
        import html
        parts = []
        for c in self.contacts:
            rows = "".join(f"<tr><td style='color:#404040;padding-right:8px'>{html.escape(l)}</td>"
                           f"<td>{html.escape(v)}</td></tr>" for l, v in card_fields(c))
            parts.append(f"<p style='margin:0'><b>{html.escape(c.file_as)}</b></p><table>{rows}</table><br>")
        doc = QTextDocument()
        doc.setHtml("".join(parts))
        doc.print_(printer)


# =============================================================================
# address book / select names
# =============================================================================
class _NameList(QTreeWidget):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.setRootIsDecorated(False)
        self.setHeaderLabels(["Name", "Display Name", "E-mail Address"])
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)

    def fill(self, text: str = ""):
        self.clear()
        t = text.lower()
        for c in self.store.contacts():
            for e in (c.email, c.email2):
                if not e:
                    continue
                if t and t not in (c.display + " " + e + " " + c.company).lower():
                    continue
                it = QTreeWidgetItem([c.file_as, c.display, e])
                it.setIcon(0, icons.get("contact"))
                it.setData(0, Qt.UserRole, c)
                it.setData(0, Qt.UserRole + 1, f"{c.display} <{e}>" if c.display and c.display != e else e)
                self.addTopLevelItem(it)
        self.sortByColumn(0, Qt.AscendingOrder)
        for i in range(3):
            self.resizeColumnToContents(i)
        if self.topLevelItemCount():
            self.setCurrentItem(self.topLevelItem(0))

    def chosen(self) -> list[str]:
        return [it.data(0, Qt.UserRole + 1) for it in self.selectedItems()]


class AddressBookDialog(QDialog):
    messageTo = Signal(str)

    def __init__(self, store: Store, parent=None, find: str = ""):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Address Book: Contacts")
        self.setWindowIcon(icons.get("address-book"))
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        for text, icon, slot in (("New Entry", "contact", self._new), ("Properties", "contacts", self._props),
                                 ("Delete", "delete", self._delete), ("New Message", "new", self._message)):
            b = QToolButton()
            b.setText(text)
            b.setIcon(icons.get(icon))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("&Search:"))
        self.find = QLineEdit(find)
        srow.addWidget(self.find, 1)
        lay.addLayout(srow)
        self.list = _NameList(store)
        lay.addWidget(self.list, 1)
        self.find.textChanged.connect(self.list.fill)
        self.list.itemDoubleClicked.connect(lambda *_: self._props())
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.fill(find)
        self.resize(620, 420)

    def _new(self):
        dlg = ContactDialog(self.store, None, self)
        dlg.messageTo.connect(self.messageTo)
        dlg.exec()
        self.list.fill(self.find.text())

    def _props(self):
        it = self.list.currentItem()
        if it:
            dlg = ContactDialog(self.store, self.store.contact(it.data(0, Qt.UserRole).id), self)
            dlg.messageTo.connect(self.messageTo)
            dlg.exec()
            self.list.fill(self.find.text())

    def _delete(self):
        its = self.list.selectedItems()
        if its and QMessageBox.question(self, "Address Book", "Delete the selected contacts?") == QMessageBox.Yes:
            self.store.delete_contacts(list({it.data(0, Qt.UserRole).id for it in its}))
            self.list.fill(self.find.text())

    def _message(self):
        names = self.list.chosen()
        if names:
            self.messageTo.emit("; ".join(names))
            self.accept()


class SelectNamesDialog(QDialog):
    """The composer's To... / Cc... / Bcc... dialog."""

    def __init__(self, store: Store, to: str, cc: str, bcc: str, parent=None, show_bcc=True):
        super().__init__(parent)
        self.setWindowTitle("Select Names: Contacts")
        self.setWindowIcon(icons.get("address-book"))
        lay = QVBoxLayout(self)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("&Search:"))
        self.find = QLineEdit()
        srow.addWidget(self.find, 1)
        lay.addLayout(srow)
        self.list = _NameList(store)
        lay.addWidget(self.list, 1)
        self.find.textChanged.connect(self.list.fill)
        grid = QGridLayout()
        self.fields = {}
        for row, (key, label, value) in enumerate((("to", "To ->", to), ("cc", "Cc ->", cc), ("bcc", "Bcc ->", bcc))):
            b = QPushButton(label)
            e = QLineEdit(value)
            b.clicked.connect(lambda _=False, e=e: self._add(e))
            grid.addWidget(b, row, 0)
            grid.addWidget(e, row, 1)
            self.fields[key] = e
            if key == "bcc" and not show_bcc and not bcc:
                b.setVisible(True)
        lay.addLayout(grid)
        self.list.itemDoubleClicked.connect(lambda *_: self._add(self.fields["to"]))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.fill()
        self.resize(620, 480)

    def _add(self, edit: QLineEdit):
        names = self.list.chosen()
        if not names:
            return
        cur = edit.text().strip().rstrip(";")
        edit.setText("; ".join(([cur] if cur else []) + names) + "; ")

    def values(self) -> tuple[str, str, str]:
        return tuple(self.fields[k].text().strip() for k in ("to", "cc", "bcc"))
