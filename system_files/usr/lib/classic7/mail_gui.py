"""Mail: the main window, laid out like Outlook 2007.

Navigation Pane (folders / Mail and Contacts buttons) | message list grouped by date |
Reading Pane. Mail is fetched in the background (mail_worker) into a local copy (mail_store).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta

from PySide6.QtCore import (QAbstractListModel, QByteArray, QDate, QEvent, QItemSelectionModel, QLocale, QMimeData,
                            QModelIndex, QPoint, QRect, QRectF, QSettings, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QHBoxLayout,
                               QInputDialog, QLabel, QListView, QMainWindow, QMenu, QMessageBox, QSplitter,
                               QStackedWidget, QStyle, QStyledItemDelegate, QSystemTrayIcon, QToolBar, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import mail_accounts as acc_mod
import mail_icons as icons
import mail_imap as imap
import mail_render as render
import mail_ui as ui
from mail_store import ROLE_NAMES, Message, Store
from mail_view import MessageWindow, ReadingPane
from mail_worker import Workers

UNREAD_VIEW = -1
MIME_IDS = "application/x-classic7-mail-ids"
APP = ui.APP


# =============================================================================
# message list
# =============================================================================
def group_label(ts: float, today: datetime) -> tuple[int, str]:
    """(sort key, label) of Outlook's date groups."""
    if not ts:
        return 99, "Older"
    d = datetime.fromtimestamp(ts).date()
    t = today.date()
    days = (t - d).days
    if days < 0:
        return 0, "Today"           # dated in the future: show with today's
    if days == 0:
        return 1, "Today"
    if days == 1:
        return 2, "Yesterday"
    start_week = t - timedelta(days=t.weekday())
    if d >= start_week:
        return 3 + (6 - d.weekday()), QLocale().dayName(d.isoweekday())
    if d >= start_week - timedelta(days=7):
        return 20, "Last Week"
    if d >= start_week - timedelta(days=14):
        return 21, "Two Weeks Ago"
    if d >= start_week - timedelta(days=21):
        return 22, "Three Weeks Ago"
    if d.year == t.year and d.month == t.month:
        return 23, "Earlier this Month"
    first_this = t.replace(day=1)
    last_month_start = (first_this - timedelta(days=1)).replace(day=1)
    if d >= last_month_start:
        return 24, "Last Month"
    return 30, "Older"


def short_date(ts: float, today: datetime) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts)
    loc = QLocale()
    if dt.date() == today.date():
        return dt.strftime("%H:%M")
    if (today.date() - dt.date()).days < 7 and dt.date() <= today.date():
        return f"{loc.dayName(dt.isoweekday(), QLocale.ShortFormat)} {dt.strftime('%H:%M')}"
    if loc.name() in ("C", "en_US_POSIX"):
        return dt.strftime("%d-%m-%Y")
    return loc.toString(QDate(dt.year, dt.month, dt.day), QLocale.ShortFormat)


class MessageModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []
        self.messages: list[Message] = []
        self.grouped = True
        self.collapsed: set[str] = set()
        self.show_to = False

    def set_messages(self, msgs: list[Message], grouped: bool, show_to: bool = False):
        self.beginResetModel()
        self.messages = msgs
        self.grouped = grouped
        self.show_to = show_to
        self._build()
        self.endResetModel()

    def _build(self):
        rows = []
        if self.grouped:
            today = datetime.now()
            groups: dict[str, list] = {}
            order: list[str] = []
            for m in self.messages:
                _k, label = group_label(m.date, today)
                if label not in groups:
                    groups[label] = []
                    order.append(label)
                groups[label].append(m)
            for label in order:
                rows.append(("g", label, len(groups[label])))
                if label not in self.collapsed:
                    rows += [("m", m) for m in groups[label]]
        else:
            rows = [("m", m) for m in self.messages]
        self.rows = rows

    def toggle_group(self, label: str):
        self.beginResetModel()
        if label in self.collapsed:
            self.collapsed.discard(label)
        else:
            self.collapsed.add(label)
        self._build()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.UserRole:
            return row
        if role == Qt.DisplayRole:
            return row[1] if row[0] == "g" else row[1].subject
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled
        if self.rows[index.row()][0] == "g":
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled

    def mimeTypes(self):
        return [MIME_IDS]

    def mimeData(self, indexes):
        ids = [self.rows[i.row()][1].id for i in indexes if self.rows[i.row()][0] == "m"]
        md = QMimeData()
        md.setData(MIME_IDS, QByteArray(json.dumps(ids).encode()))
        return md

    def supportedDragActions(self):
        return Qt.MoveAction

    def row_of(self, msg_id: int) -> int:
        for i, r in enumerate(self.rows):
            if r[0] == "m" and r[1].id == msg_id:
                return i
        return -1

    def update_message(self, msg: Message):
        i = self.row_of(msg.id)
        if i >= 0:
            self.rows[i] = ("m", msg)
            self.messages = [msg if m.id == msg.id else m for m in self.messages]
            idx = self.index(i)
            self.dataChanged.emit(idx, idx)


class MessageDelegate(QStyledItemDelegate):
    """Two-line items like Outlook 2007 with the Reading Pane on the right."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index):
        row = index.data(Qt.UserRole)
        fm = QFontMetrics(option.font)
        if row and row[0] == "g":
            return QSize(100, fm.height() + 9)
        return QSize(100, fm.height() * 2 + 10)

    def paint(self, p: QPainter, option, index):
        row = index.data(Qt.UserRole)
        r = option.rect
        p.save()
        if row[0] == "g":
            f = QFont(option.font)
            f.setBold(True)
            p.setFont(f)
            collapsed = row[1] in index.model().collapsed
            p.setPen(QPen(QColor(ui.GROUP_LINE)))
            p.drawLine(r.left() + 4, r.bottom() - 1, r.right() - 4, r.bottom() - 1)
            # triangle
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#4C607A"))
            cx, cy = r.left() + 10, r.center().y()
            if collapsed:
                pts = [QPoint(cx - 2, cy - 4), QPoint(cx + 3, cy), QPoint(cx - 2, cy + 4)]
            else:
                pts = [QPoint(cx - 4, cy - 2), QPoint(cx + 4, cy - 2), QPoint(cx, cy + 3)]
            p.drawPolygon(pts)
            p.setPen(QColor(ui.TITLE))
            p.drawText(r.adjusted(20, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, row[1])
            p.restore()
            return

        m: Message = row[1]
        selected = option.state & QStyle.State_Selected
        active = option.state & QStyle.State_Active and self.view.hasFocus()
        if selected:
            p.fillRect(r, QColor(ui.SELECT if active else ui.SELECT_INACTIVE))
            p.setPen(QColor(ui.SELECT_BORDER if active else "#B8B8B8"))
            p.drawRect(r.adjusted(0, 0, -1, -1))
        else:
            p.fillRect(r, Qt.white)
        p.setPen(QColor("#E6E6E6"))
        p.drawLine(r.left() + 22, r.bottom(), r.right(), r.bottom())

        # envelope
        icon = "draft" if m.draft else "replied" if m.answered else "forwarded" if m.forwarded else \
            "opened" if m.seen else "closed"
        icons.get(icon).paint(p, QRect(r.left() + 4, r.top() + 5, 16, 16))
        fm = QFontMetrics(option.font)
        line_h = fm.height()
        bf = QFont(option.font)
        bf.setBold(not m.seen)
        right_w = 18
        # flag column
        flag_rect = QRect(r.right() - 18, r.top() + (r.height() - 16) // 2, 16, 16)
        if m.flagged:
            icons.get("flag").paint(p, flag_rect)
        elif option.state & QStyle.State_MouseOver:
            icons.get("flag-outline").paint(p, flag_rect)
        x = r.left() + 24
        w = r.width() - 24 - right_w - 4
        today = datetime.now()
        date_text = short_date(m.date, today)
        p.setFont(bf)
        dfm = QFontMetrics(bf)
        date_w = dfm.horizontalAdvance(date_text) + 6
        extra = 0
        if m.attach:
            icons.get("attach").paint(p, QRect(x + w - date_w - 16, r.top() + 3, 14, 14))
            extra += 18
        if m.importance > 0:
            icons.get("high").paint(p, QRect(x + w - date_w - extra - 12, r.top() + 3, 12, 12))
            extra += 12
        who = m.to_addrs.split(";")[0].split("<")[0].strip() if index.model().show_to else m.sender
        if index.model().show_to and len(m.to_addrs.split(";")) > 1:
            who += "; ..."
        p.setPen(QColor("#000000"))
        p.drawText(QRect(x, r.top() + 3, w - date_w - extra, line_h), Qt.AlignLeft | Qt.AlignVCenter,
                   dfm.elidedText(who or "(no sender)", Qt.ElideRight, max(10, w - date_w - extra)))
        p.drawText(QRect(x, r.top() + 3, w, line_h), Qt.AlignRight | Qt.AlignVCenter, date_text)
        p.setFont(bf if not m.seen else option.font)
        p.setPen(QColor("#000000") if not m.seen else QColor("#303030"))
        subj = m.subject or "(no subject)"
        p.drawText(QRect(x, r.top() + 4 + line_h, w, line_h), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(p.font()).elidedText(subj, Qt.ElideRight, w))
        p.restore()

    def editorEvent(self, event, model, option, index):
        row = index.data(Qt.UserRole)
        if event.type() == QEvent.MouseButtonRelease and row:
            if row[0] == "g":
                model.toggle_group(row[1])
                return True
            r = option.rect
            if event.position().x() > r.right() - 22:
                self.view.flagClicked.emit(row[1].id)
                return True
        return super().editorEvent(event, model, option, index)


class MessageList(QListView):
    flagClicked = Signal(int)
    activatedMessage = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("messages")
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMouseTracking(True)
        self.setUniformItemSizes(False)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setItemDelegate(MessageDelegate(self))
        self.doubleClicked.connect(self._double)

    def _double(self, index):
        row = index.data(Qt.UserRole)
        if row and row[0] == "m":
            self.activatedMessage.emit(row[1].id)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            ids = self.selected_ids()
            if ids:
                self.activatedMessage.emit(ids[0])
                return
        super().keyPressEvent(e)

    def selected_ids(self) -> list[int]:
        out = []
        for i in sorted(self.selectionModel().selectedIndexes(), key=lambda i: i.row()):
            row = i.data(Qt.UserRole)
            if row and row[0] == "m":
                out.append(row[1].id)
        return out


# =============================================================================
# folder tree
# =============================================================================
class FolderDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        count = index.data(Qt.UserRole + 1) or 0
        kind = index.data(Qt.UserRole + 2) or ""
        if not count:
            return super().paint(p, option, index)
        opt = option
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, p, opt.widget)
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget)
        f = QFont(opt.font)
        f.setBold(kind != "drafts")
        p.save()
        p.setFont(f)
        p.setPen(QColor("#000000"))
        fm = QFontMetrics(f)
        p.drawText(rect.adjusted(2, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        tag = f"[{count}]" if kind == "drafts" else f"({count})"
        p.setPen(QColor("#008000" if kind == "drafts" else ui.UNREAD_COUNT))
        p.drawText(rect.adjusted(2 + fm.horizontalAdvance(text) + 4, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, tag)
        p.restore()


class FolderTree(QTreeWidget):
    droppedMessages = Signal(list, int)        # message ids, folder id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("folders")
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setItemDelegate(FolderDelegate(self))
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setDropIndicatorShown(True)
        self.setIconSize(QSize(16, 16))
        self.setUniformRowHeights(True)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def mimeTypes(self):
        return [MIME_IDS]

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_IDS):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        fid = it.data(0, Qt.UserRole) if it else None
        if e.mimeData().hasFormat(MIME_IDS) and isinstance(fid, int) and fid > 0:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        fid = it.data(0, Qt.UserRole) if it else None
        if e.mimeData().hasFormat(MIME_IDS) and isinstance(fid, int) and fid > 0:
            ids = json.loads(bytes(e.mimeData().data(MIME_IDS)).decode())
            e.acceptProposedAction()
            self.droppedMessages.emit(ids, fid)
        else:
            e.ignore()


class FolderPicker(QDialog):
    """Edit > Move to Folder."""

    def __init__(self, store: Store, account: str, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Move the selected items to the folder:"))
        self.tree = FolderTree()
        self.tree.setAcceptDrops(False)
        lay.addWidget(self.tree)
        fill_folder_tree(self.tree, store, [a for a in acc_mod.load() if a.id == account], counts=False)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.tree.itemDoubleClicked.connect(lambda *_: self.accept())
        self.resize(320, 380)

    def folder_id(self) -> int | None:
        it = self.tree.currentItem()
        v = it.data(0, Qt.UserRole) if it else None
        return v if isinstance(v, int) and v > 0 else None


def fill_folder_tree(tree: QTreeWidget, store: Store, accounts, counts=True) -> dict[int, QTreeWidgetItem]:
    tree.clear()
    items: dict[int, QTreeWidgetItem] = {}
    for a in accounts:
        top = QTreeWidgetItem([a.name or a.email])
        top.setIcon(0, icons.get("account"))
        top.setData(0, Qt.UserRole, f"account:{a.id}")
        f = top.font(0)
        f.setBold(True)
        top.setFont(0, f)
        tree.addTopLevelItem(top)
        by_path: dict[str, QTreeWidgetItem] = {}
        folders = store.folders(a.id)
        roles_top = ("inbox", "drafts", "sent", "trash", "junk")
        for fo in folders:
            parent = top
            if fo.role not in roles_top and fo.parent and fo.parent in by_path:
                parent = by_path[fo.parent]
            elif fo.role not in roles_top and fo.parent.upper() == "INBOX" and "INBOX" in by_path:
                parent = by_path["INBOX"]
            it = QTreeWidgetItem(parent, [fo.display_name])
            it.setIcon(0, icons.folder_icon(fo.role))
            it.setData(0, Qt.UserRole, fo.id if fo.selectable else f"noselect:{fo.id}")
            if counts:
                if fo.role == "drafts":
                    it.setData(0, Qt.UserRole + 1, fo.total)
                elif fo.role not in ("sent", "trash", "junk", "all"):
                    it.setData(0, Qt.UserRole + 1, fo.unread)
            it.setData(0, Qt.UserRole + 2, fo.role)
            if not fo.selectable:
                it.setForeground(0, QColor("#606060"))
            by_path[fo.path] = it
            items[fo.id] = it
        top.setExpanded(True)
        for it in by_path.values():
            it.setExpanded(True)
    return items


# =============================================================================
# main window
# =============================================================================
class MailWindow(QMainWindow):
    def __init__(self, store: Store | None = None):
        super().__init__()
        self.store = store or Store()
        self.settings = QSettings("Classic7", "Mail")
        self.workers = Workers(self.store)
        self.accounts: list[acc_mod.Account] = []
        self.folder_id: int | None = None
        self.current_id: int | None = None
        self.loading_id: int | None = None
        self.message_windows: list[MessageWindow] = []
        self.status_text = ""
        self.syncing: set[str] = set()
        self.errors: dict[str, str] = {}
        self.notified_uids: set[tuple[int, int]] = set()

        self.setWindowTitle(f"Inbox - {APP}")
        self.setWindowIcon(icons.get("inbox"))
        self.setStyleSheet(ui.STYLE)
        self._actions()
        self._menus()
        self._toolbar()
        self._layout()
        self._statusbar()
        self._tray()
        self.mark_timer = QTimer(self, singleShot=True, interval=1500, timeout=self._mark_current_read)
        self.check_timer = QTimer(self, interval=60_000, timeout=self._scheduled_check)
        self.last_check: dict[str, float] = {}
        self.restore_state()
        self.reload_accounts()
        self.check_timer.start()
        QTimer.singleShot(400, self._first_run)

    # ---- actions -------------------------------------------------------------------------
    def act(self, text, slot, key=None, icon=None, tip=None, checkable=False):
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(icon)
        if key:
            a.setShortcuts([QKeySequence(k) for k in (key if isinstance(key, list) else [key])])
            a.setShortcutContext(Qt.WindowShortcut)
        if slot:
            a.triggered.connect(slot)
        a.setCheckable(checkable)
        if tip or text:
            a.setToolTip((tip or text.replace("&", "").replace("...", "")) +
                         (f" ({QKeySequence(key if isinstance(key, str) else key[0]).toString(QKeySequence.NativeText)})" if key else ""))
        self.addAction(a)
        return a

    def _actions(self):
        A = self.act
        self.a_new_mail = A("&Mail Message", lambda: self.new_mail(), "Ctrl+N", icons.get("new"))
        self.a_new_contact = A("&Contact", self.new_contact, "Ctrl+Shift+C", icons.get("contact"))
        self.a_new_folder = A("Fold&er...", lambda: self.new_folder(), "Ctrl+Shift+E", icons.get("folder"))
        self.a_open_file = A("Open &File...", self.open_file, "Ctrl+O")
        self.a_save_as = A("Save &As...", self.save_as, "F12", icons.theme("document-save-as", "folder"))
        self.a_save_atts = A("Save Attach&ments...", lambda: self.reading.save_all())
        self.a_print = A("&Print...", self.print_current, "Ctrl+P", icons.theme("document-print", "folder"), "Print")
        self.a_import = A("&Import Contacts (vCard)...", self.import_vcards)
        self.a_export = A("E&xport Contacts (vCard)...", self.export_vcards)
        self.a_exit = A("E&xit", self.quit_app)
        self.a_close = A("&Close", self.close)
        self.a_delete = A("&Delete", self.delete_selected, "Delete", icons.get("delete"), "Delete")
        self.a_move = A("Mo&ve to Folder...", self.move_selected, "Ctrl+Shift+V", icons.get("move"), "Move to Folder")
        self.a_copy_folder = A("Cop&y to Folder...", lambda: self.move_selected(copy=True))
        self.a_select_all = A("Select A&ll", lambda: self.list.selectAll(), "Ctrl+A")
        self.a_mark_read = A("Mark as Rea&d", lambda: self.set_seen(True), "Ctrl+Q", icons.get("mark-read"))
        self.a_mark_unread = A("Mark as U&nread", lambda: self.set_seen(False), "Ctrl+U", icons.get("mark-unread"))
        self.a_mark_all = A("Mark All as Read", self.mark_all_read)
        self.a_flag = A("&Follow Up", self.toggle_flag, "Insert", icons.get("flag"))
        self.a_reply = A("&Reply", lambda: self.respond("reply"), "Ctrl+R", icons.get("reply"))
        self.a_reply_all = A("Reply to A&ll", lambda: self.respond("reply_all"), "Ctrl+Shift+R", icons.get("reply-all"))
        self.a_forward = A("For&ward", lambda: self.respond("forward"), "Ctrl+F", icons.get("forward"))
        self.a_forward_att = A("Forward as &Attachment", lambda: self.respond("forward_attachment"), "Ctrl+Alt+F")
        self.a_send_receive = A("Send/Re&ceive", self.send_receive_all, "F9", icons.get("send-receive"),
                                "Send/Receive All Folders")
        self.a_find = A("&Instant Search", lambda: (self.search.setFocus(), self.search.selectAll()),
                        ["Ctrl+E", "F3"], icons.theme("edit-find", "search-folder"))
        self.a_address_book = A("Address &Book...", lambda: self.address_book(), "Ctrl+Shift+B", icons.get("address-book"),
                                "Address Book")
        self.a_accounts = A("Account Settings...", self.account_settings, None, icons.get("account"))
        self.a_add_account = A("Add New E-mail &Account...", self.add_account)
        self.a_signatures = A("&Signatures...", self.signatures, None, icons.get("signature"))
        self.a_empty_trash = A("Empty \"Deleted Items\" Folder", self.empty_trash)
        self.a_rename_folder = A("&Rename Folder...", self.rename_folder)
        self.a_delete_folder = A("Delete &Folder", self.delete_folder)
        self.a_mail = A("&Mail", lambda: self.set_module("mail"), "Ctrl+1", icons.get("inbox"))
        self.a_contacts = A("&Contacts", lambda: self.set_module("contacts"), "Ctrl+3", icons.get("contacts"))
        self.a_nav = A("&Navigation Pane", self._toggle_nav, "Alt+F1", checkable=True)
        self.a_status = A("Status &Bar", lambda on: self.statusBar().setVisible(on), checkable=True)
        self.a_new_msg_contact = A("New &Message to Contact", self.message_to_contact, None, icons.get("new"))
        self.a_about = A(f"&About {APP}", self.about)
        self.a_prev = A("&Previous Item", lambda: self.step(-1), "Ctrl+,")
        self.a_next = A("&Next Item", lambda: self.step(+1), "Ctrl+.")
        pane = QActionGroup(self)
        self.a_pane_right = A("&Right", lambda: self.set_reading_pane("right"), checkable=True)
        self.a_pane_bottom = A("&Bottom", lambda: self.set_reading_pane("bottom"), checkable=True)
        self.a_pane_off = A("&Off", lambda: self.set_reading_pane("off"), checkable=True)
        for a in (self.a_pane_right, self.a_pane_bottom, self.a_pane_off):
            pane.addAction(a)
        arr = QActionGroup(self)
        self.arrange_actions = {}
        for key, label in (("date", "&Date"), ("from", "&From"), ("to", "&To"), ("subject", "S&ubject"),
                           ("size", "Si&ze"), ("attach", "&Attachments"), ("flag", "F&lag"),
                           ("importance", "&Importance")):
            a = A(label, lambda _=False, k=key: self.arrange(k), checkable=True)
            arr.addAction(a)
            self.arrange_actions[key] = a
        self.a_newest = A("Newest on top", lambda on: self.arrange(self.order, on), checkable=True)
        self.a_unread_only = A("Show only &unread messages", lambda on: self.refresh_list(), checkable=True)

    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        new = f.addMenu(icons.get("new"), "Ne&w")
        for a in (self.a_new_mail, self.a_new_folder, self.a_new_contact):
            new.addAction(a)
        f.addAction(self.a_open_file)
        f.addSeparator()
        f.addAction(self.a_save_as)
        f.addAction(self.a_save_atts)
        f.addSeparator()
        fm = f.addMenu("Fol&der")
        fm.addAction(self.a_new_folder)
        fm.addAction(self.a_rename_folder)
        fm.addAction(self.a_delete_folder)
        fm.addSeparator()
        fm.addAction(self.a_mark_all)
        fm.addAction(self.a_empty_trash)
        f.addSeparator()
        f.addAction(self.a_import)
        f.addAction(self.a_export)
        f.addSeparator()
        f.addAction(self.a_print)
        f.addSeparator()
        f.addAction(self.a_close)
        f.addAction(self.a_exit)

        e = mb.addMenu("&Edit")
        for a in (self.a_select_all, None, self.a_delete, self.a_move, self.a_copy_folder, None,
                  self.a_mark_read, self.a_mark_unread, self.a_mark_all, None, self.a_flag):
            e.addSeparator() if a is None else e.addAction(a)

        v = mb.addMenu("&View")
        arrange = v.addMenu("&Arrange By")
        for a in self.arrange_actions.values():
            arrange.addAction(a)
        arrange.addSeparator()
        arrange.addAction(self.a_newest)
        arrange.addAction(self.a_unread_only)
        v.addSeparator()
        v.addAction(self.a_nav)
        rp = v.addMenu("&Reading Pane")
        for a in (self.a_pane_right, self.a_pane_bottom, self.a_pane_off):
            rp.addAction(a)
        v.addSeparator()
        v.addAction(self.a_prev)
        v.addAction(self.a_next)
        v.addSeparator()
        v.addAction(self.a_status)

        g = mb.addMenu("&Go")
        g.addAction(self.a_mail)
        g.addAction(self.a_contacts)

        t = mb.addMenu("&Tools")
        sr = t.addMenu(icons.get("send-receive"), "Send/Re&ceive")
        sr.aboutToShow.connect(lambda m=sr: self._fill_send_receive(m))
        t.addAction(self.a_find)
        t.addAction(self.a_address_book)
        t.addSeparator()
        t.addAction(self.a_accounts)
        t.addAction(self.a_signatures)
        t.addAction(self.a_add_account)

        ac = mb.addMenu("&Actions")
        for a in (self.a_new_mail, None, self.a_reply, self.a_reply_all, self.a_forward, self.a_forward_att, None,
                  self.a_flag, None, self.a_new_msg_contact):
            ac.addSeparator() if a is None else ac.addAction(a)

        h = mb.addMenu("&Help")
        h.addAction(self.a_about)

    def _fill_send_receive(self, m: QMenu):
        m.clear()
        m.addAction(self.a_send_receive)
        m.addSeparator()
        for a in self.accounts:
            m.addAction(f"\"{a.name or a.email}\"", lambda aid=a.id: self.send_receive(aid))

    def _toolbar(self):
        tb = QToolBar("Standard")
        tb.setObjectName("standard")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.tb = tb
        new_menu = QMenu(self)
        new_menu.addAction(self.a_new_mail)
        new_menu.addAction(self.a_new_folder)
        new_menu.addSeparator()
        new_menu.addAction(self.a_new_contact)
        self.new_button = QToolButton()
        self.new_button.setText("&New")
        self.new_button.setIcon(icons.get("new"))
        self.new_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.new_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.new_button.setMenu(new_menu)
        self.new_button.clicked.connect(lambda: self.new_contact() if self.module == "contacts" else self.new_mail())
        self.new_button.setToolTip("New Mail Message (Ctrl+N)")
        tb.addWidget(self.new_button)
        tb.addSeparator()
        for a in (self.a_print, self.a_move, self.a_delete):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.addSeparator()
        self.mail_tools = [self.a_reply, self.a_reply_all, self.a_forward]
        self.contact_tools = [self.a_new_msg_contact]
        for a in self.mail_tools + self.contact_tools:
            tb.addAction(a)
        self.a_new_msg_contact.setVisible(False)
        tb.addSeparator()
        sr_menu = QMenu(self)
        sr_menu.aboutToShow.connect(lambda: self._fill_send_receive(sr_menu))
        sr = QToolButton()
        sr.setDefaultAction(self.a_send_receive)
        sr.setPopupMode(QToolButton.MenuButtonPopup)
        sr.setMenu(sr_menu)
        sr.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.addWidget(sr)
        tb.addSeparator()
        self.find_contact = ui.SearchBox("Type a contact to find")
        self.find_contact.setMaximumWidth(180)
        self.find_contact.returnPressed.connect(self._find_contact)
        tb.addWidget(self.find_contact)
        tb.addAction(self.a_address_book)
        tb.widgetForAction(self.a_address_book).setToolButtonStyle(Qt.ToolButtonIconOnly)

    def _layout(self):
        # navigation pane
        nav = QWidget()
        nav.setObjectName("pane")
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        self.nav_header = ui.PaneHeader("Mail", 12)
        nl.addWidget(self.nav_header)
        self.nav_stack = QStackedWidget()
        nl.addWidget(self.nav_stack, 1)

        mail_nav = QWidget()
        ml = QVBoxLayout(mail_nav)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        ml.addWidget(ui.SubHeader("Favorite Folders"))
        self.favorites = FolderTree()
        self.favorites.setRootIsDecorated(False)
        self.favorites.setMaximumHeight(70)
        self.favorites.itemClicked.connect(self._favorite_clicked)
        self.favorites.droppedMessages.connect(self.move_ids)
        ml.addWidget(self.favorites)
        ml.addWidget(ui.SubHeader("Mail Folders"))
        self.tree = FolderTree()
        self.tree.currentItemChanged.connect(self._folder_clicked)
        self.tree.droppedMessages.connect(self.move_ids)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._folder_menu)
        ml.addWidget(self.tree, 1)
        self.nav_stack.addWidget(mail_nav)

        import mail_contacts
        self.contacts_nav = mail_contacts.ContactsNav()
        self.nav_stack.addWidget(self.contacts_nav)

        self.btn_mail = ui.NavButton("Mail", icons.get("inbox"))
        self.btn_contacts = ui.NavButton("Contacts", icons.get("contacts"))
        self.btn_mail.clicked.connect(lambda: self.set_module("mail"))
        self.btn_contacts.clicked.connect(lambda: self.set_module("contacts"))
        nl.addWidget(self.btn_mail)
        nl.addWidget(self.btn_contacts)

        # message list pane
        lst = QWidget()
        lst.setObjectName("pane")
        ll = QVBoxLayout(lst)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self.list_header = ui.PaneHeader("Inbox", 14)
        self.search = ui.SearchBox("Search Inbox")
        self.search.setFixedWidth(170)
        self.search_timer = QTimer(self, singleShot=True, interval=300, timeout=self.refresh_list)
        self.search.textChanged.connect(self.search_timer.start)
        self.list_header.add_right(self.search)
        ll.addWidget(self.list_header)
        self.arranged = ui.SubHeader("Arranged By: Date", "Newest on top")
        self.arranged.clicked.connect(self._arrange_menu)
        ll.addWidget(self.arranged)
        self.model = MessageModel(self)
        self.list = MessageList()
        self.list.setModel(self.model)
        self.list.selectionModel().selectionChanged.connect(self._selection_changed)
        self.list.activatedMessage.connect(self.open_message_window)
        self.list.flagClicked.connect(lambda mid: self.toggle_flag([mid]))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        ll.addWidget(self.list, 1)

        self.reading = ReadingPane()

        self.mail_split = QSplitter(Qt.Horizontal)
        self.mail_split.addWidget(lst)
        self.mail_split.addWidget(self.reading)
        self.mail_split.setStretchFactor(0, 0)
        self.mail_split.setStretchFactor(1, 1)
        self.mail_split.setChildrenCollapsible(False)

        self.contacts_view = mail_contacts.ContactsView(self.store, self)
        self.contacts_nav.viewChanged.connect(self.contacts_view.set_mode)
        self.contacts_view.messageTo.connect(self.new_mail_to)

        self.content = QStackedWidget()
        self.content.addWidget(self.mail_split)
        self.content.addWidget(self.contacts_view)

        self.main_split = QSplitter(Qt.Horizontal)
        self.main_split.addWidget(nav)
        self.main_split.addWidget(self.content)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setChildrenCollapsible(False)
        self.main_split.setSizes([220, 1000])
        self.mail_split.setSizes([360, 640])
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(4, 4, 4, 4)
        wl.addWidget(self.main_split)
        self.setCentralWidget(wrap)
        self.module = "mail"
        self.btn_mail.setChecked(True)

    def _statusbar(self):
        sb = self.statusBar()
        self.lbl_items = QLabel()
        self.lbl_status = QLabel()
        sb.addWidget(self.lbl_items, 1)
        sb.addPermanentWidget(self.lbl_status)

    def _tray(self):
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icons.get("closed"), self)
            self.tray.setToolTip("You have new unopened items.")
            self.tray.activated.connect(lambda *_: (self.showNormal(), self.raise_(), self.activateWindow()))

    # ---- state ---------------------------------------------------------------------------
    def restore_state(self):
        g = self.settings.value("geometry")
        if g:
            self.restoreGeometry(g)
        else:
            self.resize(1180, 760)
        for key, split in (("mainSplit", self.main_split), ("mailSplit", self.mail_split)):
            v = self.settings.value(key)
            if v:
                split.restoreState(v)
        self.set_reading_pane(self.settings.value("readingPane", "right"))
        self.order = self.settings.value("order", "date")
        self.desc = self.settings.value("newestOnTop", "true") in (True, "true")
        self.arrange_actions.get(self.order, self.arrange_actions["date"]).setChecked(True)
        self.a_newest.setChecked(self.desc)
        self.a_status.setChecked(True)
        nav_on = self.settings.value("navPane", "true") in (True, "true")
        self.a_nav.setChecked(nav_on)
        self.main_split.widget(0).setVisible(nav_on)
        self._update_arranged()

    def save_state(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("mainSplit", self.main_split.saveState())
        self.settings.setValue("mailSplit", self.mail_split.saveState())
        if self.folder_id:
            self.settings.setValue("lastFolder", self.folder_id)

    def _toggle_nav(self, on):
        self.main_split.widget(0).setVisible(on)
        self.settings.setValue("navPane", on)

    def set_reading_pane(self, where: str):
        where = where if where in ("right", "bottom", "off") else "right"
        self.settings.setValue("readingPane", where)
        {"right": self.a_pane_right, "bottom": self.a_pane_bottom, "off": self.a_pane_off}[where].setChecked(True)
        self.mail_split.setOrientation(Qt.Vertical if where == "bottom" else Qt.Horizontal)
        self.reading.setVisible(where != "off")

    def set_module(self, module: str):
        self.module = module
        is_mail = module == "mail"
        self.btn_mail.setChecked(is_mail)
        self.btn_contacts.setChecked(not is_mail)
        self.nav_stack.setCurrentIndex(0 if is_mail else 1)
        self.content.setCurrentIndex(0 if is_mail else 1)
        self.nav_header.set_text("Mail" if is_mail else "Contacts")
        for a in self.mail_tools:
            a.setVisible(is_mail)
        for a in self.contact_tools:
            a.setVisible(not is_mail)
        self.a_move.setVisible(is_mail)
        self.new_button.setIcon(icons.get("new" if is_mail else "contact"))
        self.new_button.setToolTip("New Mail Message (Ctrl+N)" if is_mail else "New Contact (Ctrl+Shift+C)")
        if is_mail:
            self.setWindowTitle(f"{self.list_header.text} - {APP}")
            self.setWindowIcon(icons.get("inbox"))
        else:
            self.contacts_view.reload()
            self.setWindowTitle(f"Contacts - {APP}")
            self.setWindowIcon(icons.get("contacts"))
        self._update_counts()

    # ---- accounts ------------------------------------------------------------------------
    def reload_accounts(self):
        self.accounts = acc_mod.load()
        self.workers.reload(self.accounts)
        for aid in {f.account for f in self.store.folders()} - {a.id for a in self.accounts}:
            self.store.remove_account(aid)
        self.rebuild_tree()
        if self.folder_id is None or not self.store.folder(self.folder_id) and self.folder_id != UNREAD_VIEW:
            last = self.settings.value("lastFolder")
            f = self.store.folder(int(last)) if last else None
            if not f and self.accounts:
                f = self.store.folder_by_role(acc_mod.default_account(self.accounts).id, "inbox")
            if f:
                self.select_folder(f.id)
            else:
                self.folder_id = None
                self.model.set_messages([], True)
                self.reading.clear("No e-mail account is set up yet." if not self.accounts else "Select an item to read")
                self.list_header.set_text("Inbox")
        self._update_counts()

    def _first_run(self):
        if not self.accounts:
            self.add_account()
        else:
            self.send_receive_all()

    def add_account(self):
        import mail_setup
        acc = mail_setup.add_account_wizard(self)
        if acc:
            self.reload_accounts()
            self.send_receive(acc.id, first=True)

    def account_settings(self):
        import mail_setup
        mail_setup.AccountSettings(self).exec()
        self.reload_accounts()

    def signatures(self):
        import mail_setup
        mail_setup.SignaturesDialog(self).exec()
        self.accounts = acc_mod.load()

    # ---- folder tree ---------------------------------------------------------------------
    def rebuild_tree(self):
        current = self.folder_id
        self.tree.blockSignals(True)
        self.items = fill_folder_tree(self.tree, self.store, self.accounts)
        if current in self.items:
            self.tree.setCurrentItem(self.items[current])
        self.tree.blockSignals(False)
        # favourites: Inbox, Unread Mail, Sent Items of the default account
        self.favorites.clear()
        d = acc_mod.default_account(self.accounts)
        if d:
            for role, label in (("inbox", "Inbox"), (None, "Unread Mail"), ("sent", "Sent Items")):
                if role is None:
                    it = QTreeWidgetItem([label])
                    it.setIcon(0, icons.get("unread-folder"))
                    it.setData(0, Qt.UserRole, UNREAD_VIEW)
                    it.setData(0, Qt.UserRole + 1, len(self.store.unread_messages([a.id for a in self.accounts])))
                    self.favorites.addTopLevelItem(it)
                    continue
                f = self.store.folder_by_role(d.id, role)
                if f:
                    it = QTreeWidgetItem([label])
                    it.setIcon(0, icons.folder_icon(role))
                    it.setData(0, Qt.UserRole, f.id)
                    if role == "inbox":
                        it.setData(0, Qt.UserRole + 1, f.unread)
                    it.setData(0, Qt.UserRole + 2, role)
                    self.favorites.addTopLevelItem(it)
        self._update_tray()

    def update_counts_only(self):
        """Refresh the unread numbers without rebuilding the tree."""
        by_id = {f.id: f for f in self.store.folders()}
        for fid, it in getattr(self, "items", {}).items():
            f = by_id.get(fid)
            if not f:
                continue
            if f.role == "drafts":
                it.setData(0, Qt.UserRole + 1, f.total)
            elif f.role not in ("sent", "trash", "junk", "all"):
                it.setData(0, Qt.UserRole + 1, f.unread)
        for i in range(self.favorites.topLevelItemCount()):
            it = self.favorites.topLevelItem(i)
            fid = it.data(0, Qt.UserRole)
            if fid == UNREAD_VIEW:
                it.setData(0, Qt.UserRole + 1, len(self.store.unread_messages([a.id for a in self.accounts])))
            elif fid in by_id and by_id[fid].role == "inbox":
                it.setData(0, Qt.UserRole + 1, by_id[fid].unread)
        self.tree.viewport().update()
        self.favorites.viewport().update()
        self._update_counts()
        self._update_tray()

    def _favorite_clicked(self, item, _col=0):
        fid = item.data(0, Qt.UserRole)
        if isinstance(fid, int):
            self.select_folder(fid)

    def _folder_clicked(self, item, _prev=None):
        if item is None:
            return
        fid = item.data(0, Qt.UserRole)
        if isinstance(fid, int):
            self.select_folder(fid)

    def select_folder(self, fid: int):
        if self.module != "mail":
            self.set_module("mail")
        self.folder_id = fid
        self.settings.setValue("lastFolder", fid)
        if fid == UNREAD_VIEW:
            title = "Unread Mail"
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(None)
            self.tree.clearSelection()
            self.tree.blockSignals(False)
        else:
            f = self.store.folder(fid)
            if not f:
                return
            title = f.display_name
            if fid in getattr(self, "items", {}) and self.tree.currentItem() is not self.items[fid]:
                self.tree.blockSignals(True)
                self.tree.setCurrentItem(self.items[fid])
                self.tree.blockSignals(False)
            if f.role in imap.SKIP_AUTO_SYNC or time.time() - f.synced > 120:
                self.sync_folder(fid)
        self.list_header.set_text(title)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.search.setPlaceholderText(f"Search {title}")
        self.setWindowTitle(f"{title} - {APP}")
        self.current_id = None
        self.refresh_list(select_first=True)

    def _folder_menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        fid = it.data(0, Qt.UserRole)
        m = QMenu(self)
        if isinstance(fid, str) and fid.startswith("account:"):
            aid = fid.split(":", 1)[1]
            m.addAction(icons.get("send-receive"), "Send/Receive", lambda: self.send_receive(aid))
            m.addAction(icons.get("folder"), "New Folder...", lambda: self.new_folder(parent_account=aid))
            m.addSeparator()
            m.addAction(icons.get("account"), "Account Settings...", self.account_settings)
        elif isinstance(fid, int):
            self.select_folder(fid)
            f = self.store.folder(fid)
            m.addAction("Open", lambda: self.select_folder(fid))
            m.addAction(icons.get("send-receive"), "Update Folder", lambda: self.sync_folder(fid))
            m.addSeparator()
            m.addAction(icons.get("folder"), "New Folder...", self.new_folder)
            if f and f.role not in ("inbox",):
                m.addAction("Rename Folder...", self.rename_folder)
                m.addAction(icons.get("delete"), "Delete Folder", self.delete_folder)
            m.addSeparator()
            m.addAction("Mark All as Read", self.mark_all_read)
            if f and f.role in ("trash", "junk"):
                m.addAction("Empty Folder", self.empty_trash)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ---- list ----------------------------------------------------------------------------
    def current_folder(self):
        return self.store.folder(self.folder_id) if self.folder_id and self.folder_id > 0 else None

    def refresh_list(self, select_first=False):
        if self.folder_id is None:
            return
        keep = self.list.selected_ids()
        search = self.search.text().strip()
        if self.folder_id == UNREAD_VIEW:
            msgs = self.store.unread_messages([a.id for a in self.accounts])
            if search:
                s = search.lower()
                msgs = [m for m in msgs if s in (m.subject + m.from_name + m.from_addr).lower()]
            show_to = False
        else:
            msgs = self.store.messages(self.folder_id, search, self.order, self.desc, self.a_unread_only.isChecked())
            f = self.current_folder()
            show_to = bool(f and f.role in ("sent", "drafts"))
        self.model.set_messages(msgs, self.order == "date" and not search, show_to)
        sel = self.list.selectionModel()
        sel.blockSignals(True)
        restored = False
        for mid in keep:
            r = self.model.row_of(mid)
            if r >= 0:
                sel.select(self.model.index(r), QItemSelectionModel.Select)
                if not restored:
                    sel.setCurrentIndex(self.model.index(r), QItemSelectionModel.NoUpdate)
                restored = True
        sel.blockSignals(False)
        if not restored:
            self.current_id = None
            if select_first:
                for i, row in enumerate(self.model.rows):
                    if row[0] == "m":
                        self.list.setCurrentIndex(self.model.index(i))
                        break
                else:
                    self.reading.clear("There are no items to show in this view." if self.folder_id else "")
            else:
                self.reading.clear()
        self._update_counts()

    def _update_counts(self):
        if self.module == "contacts":
            n = len(self.contacts_view.contacts)
            self.lbl_items.setText(f"{n} Item{'s' if n != 1 else ''}")
        else:
            total = len(self.model.messages)
            unread = sum(1 for m in self.model.messages if not m.seen)
            self.lbl_items.setText(f"Items: {total}" + (f"     Unread: {unread}" if unread else ""))
        if self.syncing:
            self.lbl_status.setText("Send/Receive...")
        elif self.errors:
            self.lbl_status.setText("Send/Receive error")
            self.lbl_status.setToolTip("\n".join(f"{self._acc_name(a)}: {e}" for a, e in self.errors.items()))
        elif self.accounts:
            self.lbl_status.setText("All folders are up to date.")
            self.lbl_status.setToolTip("")
        else:
            self.lbl_status.setText("")

    def _acc_name(self, aid):
        a = next((x for x in self.accounts if x.id == aid), None)
        return (a.name or a.email) if a else aid

    def _arrange_menu(self):
        m = QMenu(self)
        for a in self.arrange_actions.values():
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_newest)
        m.addAction(self.a_unread_only)
        m.exec(self.arranged.mapToGlobal(QPoint(0, self.arranged.height())))

    def arrange(self, order: str, desc: bool | None = None):
        self.order = order
        if desc is not None:
            self.desc = desc
        elif order in ("from", "to", "subject"):
            self.desc = False
        else:
            self.desc = True
        self.a_newest.setChecked(self.desc)
        self.arrange_actions[order].setChecked(True)
        self.settings.setValue("order", order)
        self.settings.setValue("newestOnTop", self.desc)
        self._update_arranged()
        self.refresh_list()

    def _update_arranged(self):
        names = {"date": "Date", "from": "From", "to": "To", "subject": "Subject", "size": "Size",
                 "attach": "Attachments", "flag": "Flag", "importance": "Importance"}
        if self.order == "date":
            right = "Newest on top" if self.desc else "Oldest on top"
        elif self.order in ("from", "to", "subject"):
            right = "A on top" if not self.desc else "Z on top"
        else:
            right = "Largest on top" if self.desc else "Smallest on top"
        self.arranged.set_text(f"Arranged By: {names.get(self.order, 'Date')}", right)

    def _selection_changed(self, *_):
        ids = self.list.selected_ids()
        self._mark_current_read_now()
        if len(ids) != 1:
            if not ids:
                self.reading.clear()
            self.current_id = None
            return
        self.show_message(ids[0])

    def show_message(self, mid: int):
        m = self.store.message(mid)
        if not m:
            return
        self.current_id = mid
        raw = self.store.cached_eml(m)
        if raw is not None:
            self._display(m, raw)
            return
        f = self.store.folder(m.folder)
        w = self.workers.get(f.account) if f else None
        if not w:
            return
        self.loading_id = mid
        self.reading.clear("Downloading the message...")

        def job(conn, path=f.path, uid=m.uid):
            return conn.fetch_message(path, uid)

        def ok(raw, mid=mid):
            msg = self.store.message(mid)
            if msg is None:
                return
            self.store.cache_eml(msg, raw)
            if self.current_id == mid:
                self._display(msg, raw)

        def err(text, _e, mid=mid):
            if self.current_id == mid:
                self.reading.clear(f"The message could not be downloaded.\n\n{text}")

        w.ui.submit(job, ok, err)

    def _display(self, m: Message, raw: bytes):
        try:
            p = render.parse(raw)
        except Exception as e:   # noqa: BLE001
            self.reading.clear(f"This message can't be shown.\n\n{e}")
            return
        self.reading.show_message(p, m.answered, m.forwarded)
        self.current_parsed = p
        if not m.seen:
            self.mark_timer.start()

    def _mark_current_read(self):
        ids = self.list.selected_ids()
        if self.current_id and ids == [self.current_id]:
            m = self.store.message(self.current_id)
            if m and not m.seen:
                self.set_seen(True, [m.id])

    def _mark_current_read_now(self):
        if self.mark_timer.isActive():
            self.mark_timer.stop()
            if self.current_id:
                m = self.store.message(self.current_id)
                if m and not m.seen:
                    self.set_seen(True, [m.id], refresh=False)

    def step(self, delta: int):
        rows = [i for i, r in enumerate(self.model.rows) if r[0] == "m"]
        if not rows:
            return
        cur = self.list.currentIndex().row()
        pos = next((k for k, i in enumerate(rows) if i == cur), -1)
        nxt = rows[max(0, min(len(rows) - 1, pos + delta))] if pos >= 0 else rows[0]
        self.list.setCurrentIndex(self.model.index(nxt))
        return self.model.rows[nxt][1].id

    def _list_menu(self, pos):
        idx = self.list.indexAt(pos)
        if idx.isValid() and not self.list.selectionModel().isSelected(idx):
            self.list.setCurrentIndex(idx)
        ids = self.list.selected_ids()
        if not ids:
            return
        m = QMenu(self)
        if len(ids) == 1:
            m.addAction(icons.get("opened"), "&Open", lambda: self.open_message_window(ids[0]))
            m.addAction(self.a_print)
            m.addSeparator()
            m.addAction(self.a_reply)
            m.addAction(self.a_reply_all)
            m.addAction(self.a_forward)
            m.addSeparator()
        msgs = self.store.messages_by_ids(ids)
        if any(not x.seen for x in msgs):
            m.addAction(self.a_mark_read)
        if any(x.seen for x in msgs):
            m.addAction(self.a_mark_unread)
        m.addAction(icons.get("flag"), "Clear Flag" if all(x.flagged for x in msgs) else "Follow Up",
                    self.toggle_flag)
        m.addSeparator()
        m.addAction(self.a_move)
        m.addAction(self.a_delete)
        m.exec(self.list.viewport().mapToGlobal(pos))

    # ---- open in a window ----------------------------------------------------------------
    def open_message_window(self, mid: int):
        m = self.store.message(mid)
        if not m:
            return
        f = self.store.folder(m.folder)
        raw = self.store.cached_eml(m)

        def show(raw):
            msg = self.store.message(mid) or m
            self.store.cache_eml(msg, raw)
            p = render.parse(raw)
            if f and f.role == "drafts" or msg.draft:
                import mail_compose
                mail_compose.open_draft(p, raw, msg, self)
                return
            w = MessageWindow(p, self, msg, raw)
            w.setAttribute(Qt.WA_DeleteOnClose)
            w.destroyed.connect(lambda *_: self.message_windows.remove(w) if w in self.message_windows else None)
            self.message_windows.append(w)
            w.show()
            if not msg.seen:
                self.set_seen(True, [msg.id])

        if raw is not None:
            show(raw)
            return
        w = self.workers.get(f.account) if f else None
        if w:
            w.ui.submit(lambda conn: conn.fetch_message(f.path, m.uid), show,
                        lambda t, _e: QMessageBox.warning(self, APP, f"The message could not be opened.\n\n{t}"))

    def message_window_action(self, win: MessageWindow, what: str):
        if win.msg is None:
            return
        if what == "delete":
            self.delete_ids([win.msg.id])
            win.close()
        elif what == "move":
            self.move_selected(ids=[win.msg.id])
            win.close()
        elif what in ("previous", "next"):
            r = self.model.row_of(win.msg.id)
            if r >= 0:
                self.list.setCurrentIndex(self.model.index(r))
            nid = self.step(-1 if what == "previous" else 1)
            if nid and nid != win.msg.id:
                m = self.store.message(nid)
                raw = self.store.cached_eml(m) if m else None
                if m and raw is not None:
                    win.set_message(render.parse(raw), m, raw)
                elif m:
                    win.close()
                    self.open_message_window(nid)

    # ---- flags / moving / deleting ---------------------------------------------------------
    def _by_folder(self, ids):
        out: dict[int, list[Message]] = {}
        for m in self.store.messages_by_ids(ids):
            out.setdefault(m.folder, []).append(m)
        return out

    def _run(self, folder_id: int, fn, done=None, resync=True):
        f = self.store.folder(folder_id)
        w = self.workers.get(f.account) if f else None
        if not w:
            return

        def err(text, _e):
            self.statusBar().showMessage(f"{text}", 8000)
            if resync:
                self.sync_folder(folder_id)

        w.ui.submit(lambda conn: fn(conn, f), done, err)

    def set_seen(self, seen: bool, ids: list[int] | None = None, refresh=True):
        ids = ids if ids is not None else self.list.selected_ids()
        if not ids:
            return
        self.store.set_flag(ids, "seen", seen)
        for fid, msgs in self._by_folder(ids).items():
            uids = [m.uid for m in msgs]
            self._run(fid, lambda conn, f, u=uids: conn.store(f.path, u, "+FLAGS.SILENT" if seen else "-FLAGS.SILENT",
                                                             "\\Seen"))
        for m in self.store.messages_by_ids(ids):
            self.model.update_message(m)
        self.update_counts_only()

    def toggle_flag(self, ids=None):
        ids = ids if isinstance(ids, list) else self.list.selected_ids()
        msgs = self.store.messages_by_ids(ids)
        if not msgs:
            return
        on = not all(m.flagged for m in msgs)
        self.store.set_flag(ids, "flagged", on)
        for fid, ms in self._by_folder(ids).items():
            uids = [m.uid for m in ms]
            self._run(fid, lambda conn, f, u=uids: conn.store(f.path, u, "+FLAGS.SILENT" if on else "-FLAGS.SILENT",
                                                             "\\Flagged"))
        for m in self.store.messages_by_ids(ids):
            self.model.update_message(m)

    def mark_all_read(self):
        if not self.folder_id or self.folder_id < 0:
            ids = [m.id for m in self.model.messages if not m.seen]
        else:
            ids = [m.id for m in self.store.messages(self.folder_id) if not m.seen]
        self.set_seen(True, ids)
        self.refresh_list()

    def move_selected(self, copy=False, ids=None):
        ids = ids or self.list.selected_ids()
        if not ids:
            return
        first = self.store.message(ids[0])
        f = self.store.folder(first.folder) if first else None
        if not f:
            return
        dlg = FolderPicker(self.store, f.account, "Copy Items" if copy else "Move Items", self)
        if dlg.exec() and dlg.folder_id():
            self.move_ids(ids, dlg.folder_id(), copy=copy)

    def move_ids(self, ids: list[int], dest_id: int, copy=False):
        dest = self.store.folder(dest_id)
        if not dest:
            return
        groups = self._by_folder(ids)
        for fid, msgs in groups.items():
            src = self.store.folder(fid)
            if src is None or src.id == dest.id:
                continue
            if src.account != dest.account:
                QMessageBox.information(self, APP, "Messages can only be moved between folders of the same account.")
                return
            uids = [m.uid for m in msgs]
            if not copy:
                self.store.remove_uids(fid, uids)
            self._run(fid, (lambda conn, f, u=uids: conn.copy(f.path, u, dest.path)) if copy else
                      (lambda conn, f, u=uids: conn.move(f.path, u, dest.path)),
                      lambda _r, d=dest.id: self.sync_folder(d))
        self.refresh_list()
        self.update_counts_only()

    def delete_selected(self):
        if self.module == "contacts":
            self.contacts_view.delete_selected()
            return
        ids = self.list.selected_ids()
        if ids:
            nxt = self._row_after(ids)
            self.delete_ids(ids)
            if nxt is not None:
                r = self.model.row_of(nxt)
                if r >= 0:
                    self.list.setCurrentIndex(self.model.index(r))

    def _row_after(self, ids):
        rows = [r for r in self.model.rows if r[0] == "m"]
        idset = set(ids)
        last = max((i for i, r in enumerate(rows) if r[1].id in idset), default=-1)
        for r in rows[last + 1:]:
            if r[1].id not in idset:
                return r[1].id
        for r in reversed(rows[:last]):
            if r[1].id not in idset:
                return r[1].id
        return None

    def delete_ids(self, ids: list[int]):
        for fid, msgs in self._by_folder(ids).items():
            src = self.store.folder(fid)
            if not src:
                continue
            trash = self.store.folder_by_role(src.account, "trash")
            uids = [m.uid for m in msgs]
            if src.role == "trash" or trash is None:
                n = len(uids)
                if QMessageBox.warning(self, APP, f"The selected item{'s' if n > 1 else ''} will be permanently "
                                       "deleted. Do you want to continue?",
                                       QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                    continue

                def gone(conn, f, u=uids):
                    conn.store(f.path, u, "+FLAGS.SILENT", "\\Deleted")
                    conn.expunge(f.path, u)
                self.store.remove_uids(fid, uids)
                self._run(fid, gone)
            else:
                self.store.remove_uids(fid, uids)
                self._run(fid, lambda conn, f, u=uids, t=trash.path: conn.move(f.path, u, t),
                          lambda _r, t=trash.id: self.sync_folder(t))
        self.refresh_list()
        self.update_counts_only()

    def empty_trash(self):
        f = self.current_folder()
        if not f or f.role not in ("trash", "junk"):
            d = acc_mod.default_account(self.accounts)
            f = self.store.folder_by_role(d.id, "trash") if d else None
        if not f:
            return
        if QMessageBox.warning(self, APP, f"Everything in the \"{f.display_name}\" folder will be permanently "
                               "deleted. Do you want to continue?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        uids = list(self.store.uids(f.id))

        def job(conn, fo):
            conn.select(fo.path, readonly=False)
            all_uids = conn.search_uids()
            if all_uids:
                conn.store(fo.path, all_uids, "+FLAGS.SILENT", "\\Deleted")
                conn.expunge(fo.path, all_uids)
        self.store.remove_uids(f.id, uids)
        self._run(f.id, job)
        self.refresh_list()
        self.update_counts_only()

    # ---- folders ---------------------------------------------------------------------------
    def new_folder(self, parent_account: str | None = None):
        f = self.current_folder()
        aid = parent_account or (f.account if f else (acc_mod.default_account(self.accounts).id if self.accounts else None))
        if not aid:
            return
        name, ok = QInputDialog.getText(self, "Create New Folder", "Name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        folders = self.store.folders(aid)
        delim = folders[0].delim if folders else "/"
        parent = f.path if f and f.account == aid and not parent_account else ""
        # servers like Dovecot/Courier keep everything below INBOX
        if not parent and folders and all(x.path.upper().startswith("INBOX" + delim.upper()) or x.role == "inbox"
                                          for x in folders if x.selectable) and len(folders) > 1:
            parent = "INBOX"
        path = f"{parent}{delim}{name}" if parent else name
        w = self.workers.get(aid)
        if not w:
            return

        def job(conn):
            conn.create_folder(path)
            return imap.sync_folders(conn, self.store)
        w.ui.submit(job, lambda _r: (self.rebuild_tree(), self._select_path(aid, path)),
                    lambda t, _e: QMessageBox.warning(self, APP, f"The folder could not be created.\n\n{t}"))

    def _select_path(self, aid, path):
        f = self.store.folder_by_path(aid, path)
        if f:
            self.select_folder(f.id)

    def rename_folder(self):
        f = self.current_folder()
        if not f or f.role == "inbox":
            return
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=f.name)
        if not ok or not name.strip() or name.strip() == f.name:
            return
        new = (f.parent + f.delim if f.parent else "") + name.strip()
        w = self.workers.get(f.account)

        def job(conn):
            conn.rename_folder(f.path, new)
            return imap.sync_folders(conn, self.store)
        w.ui.submit(job, lambda _r: (self.rebuild_tree(), self._select_path(f.account, new)),
                    lambda t, _e: QMessageBox.warning(self, APP, f"The folder could not be renamed.\n\n{t}"))

    def delete_folder(self):
        f = self.current_folder()
        if not f or f.role in ("inbox", "sent", "drafts", "trash"):
            QMessageBox.information(self, APP, "This folder can't be deleted.")
            return
        if QMessageBox.warning(self, APP, f"Are you sure you want to delete the \"{f.display_name}\" folder and "
                               "all its messages?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        w = self.workers.get(f.account)
        inbox = self.store.folder_by_role(f.account, "inbox")

        def job(conn):
            conn.delete_folder(f.path)
            return imap.sync_folders(conn, self.store)

        def ok(_r):
            self.folder_id = inbox.id if inbox else None
            self.rebuild_tree()
            if inbox:
                self.select_folder(inbox.id)
        w.ui.submit(job, ok, lambda t, _e: QMessageBox.warning(self, APP, f"The folder could not be deleted.\n\n{t}"))

    # ---- send / receive ------------------------------------------------------------------
    def send_receive_all(self):
        for a in self.accounts:
            self.send_receive(a.id)

    def _scheduled_check(self):
        now = time.time()
        for a in self.accounts:
            if a.check_minutes and now - self.last_check.get(a.id, 0) >= a.check_minutes * 60 - 5:
                self.send_receive(a.id, quiet=True)

    def send_receive(self, aid: str, first=False, quiet=False):
        w = self.workers.get(aid)
        if not w or aid in self.syncing:
            return
        self.syncing.add(aid)
        self.last_check[aid] = time.time()
        self._update_counts()
        current = self.folder_id

        def job(conn):
            folders = imap.sync_folders(conn, self.store)
            new_inbox = []
            for f in folders:
                if not f.selectable or (f.role in imap.SKIP_AUTO_SYNC and f.id != current):
                    continue
                new = imap.sync_folder(conn, self.store, f)
                if f.role == "inbox":
                    new_inbox += [m for m in new if not m.seen]
            return new_inbox

        def ok(new_inbox):
            self.syncing.discard(aid)
            self.errors.pop(aid, None)
            self.rebuild_tree()
            if self.folder_id is None or (self.folder_id > 0 and not self.store.folder(self.folder_id)):
                inbox = self.store.folder_by_role(aid, "inbox")
                if inbox:
                    self.select_folder(inbox.id)
            else:
                self.refresh_list()
            self._notify(aid, new_inbox)
            self._update_counts()

        def err(text, e):
            self.syncing.discard(aid)
            self.errors[aid] = text
            self._update_counts()
            if not quiet or isinstance(e, imap.AuthError):
                self.statusBar().showMessage(f"{self._acc_name(aid)}: {text}", 15000)
            if isinstance(e, imap.AuthError) and not getattr(self, "_auth_warned", {}).get(aid):
                self._auth_warned = getattr(self, "_auth_warned", {})
                self._auth_warned[aid] = True
                QMessageBox.warning(self, APP, f"{self._acc_name(aid)}\n\n{text}\n\n"
                                    "Open Tools > Account Settings to correct it.")

        w.sync.submit(job, ok, err)

    def sync_folder(self, fid: int):
        f = self.store.folder(fid)
        w = self.workers.get(f.account) if f else None
        if not w:
            return
        w.sync.submit(lambda conn: imap.sync_folder(conn, self.store, f),
                      lambda _r: (self.refresh_list() if self.folder_id == fid else None, self.update_counts_only()),
                      lambda t, _e: self.statusBar().showMessage(t, 8000))

    def _notify(self, aid, new_msgs):
        fresh = [m for m in new_msgs if (m.folder, m.uid) not in self.notified_uids]
        for m in fresh:
            self.notified_uids.add((m.folder, m.uid))
        if not fresh:
            return
        QApplication.alert(self)
        if self.tray:
            self.tray.show()
            if len(fresh) == 1:
                m = fresh[0]
                self.tray.showMessage(m.sender or "New mail", m.subject or "(no subject)", icons.get("closed"), 8000)
            else:
                self.tray.showMessage("New mail", f"{len(fresh)} new messages", icons.get("closed"), 8000)

    def _update_tray(self):
        if not self.tray:
            return
        unread = 0
        for a in self.accounts:
            inbox = self.store.folder_by_role(a.id, "inbox")
            if inbox:
                unread += inbox.unread
        self.tray.setVisible(unread > 0 and bool(self.notified_uids))

    # ---- composing -----------------------------------------------------------------------
    def new_mail(self, to: str = ""):
        if not self.accounts:
            if QMessageBox.question(self, APP, "No e-mail account is set up. Set one up now?") == QMessageBox.Yes:
                self.add_account()
            return
        import mail_compose
        f = self.current_folder()
        mail_compose.Composer(self.store, account_id=f.account if f else None, to=to, handler=self).show()

    def new_mail_to(self, to: str):
        self.new_mail(to)

    def respond(self, kind: str):
        ids = self.list.selected_ids()
        if len(ids) != 1:
            return
        m = self.store.message(ids[0])
        raw = self.store.cached_eml(m) if m else None
        if raw is None:
            QMessageBox.information(self, APP, "The message is still being downloaded. Try again in a moment.")
            return
        import mail_compose
        p = render.parse(raw)
        if kind == "forward_attachment":
            mail_compose.forward_as_attachment(p, raw, m, self)
        else:
            mail_compose.open_reply(p, kind, m, parent_handler=self)

    def after_send(self, account_id: str, reply_to: Message | None, kind: str, folders_changed: list[str]):
        """Called by the composer when a message was sent or a draft saved."""
        if reply_to is not None:
            col = "answered" if kind in ("reply", "reply_all") else "forwarded"
            self.store.set_flag([reply_to.id], col, True)
            self.model.update_message(self.store.message(reply_to.id) or reply_to)
        for role in folders_changed:
            f = self.store.folder_by_role(account_id, role)
            if f:
                self.sync_folder(f.id)

    def message_to_contact(self):
        self.contacts_view.message_to_selected()

    def new_contact(self):
        self.contacts_view.new_contact()

    def address_book(self, find: str = ""):
        import mail_contacts
        dlg = mail_contacts.AddressBookDialog(self.store, self, find)
        dlg.messageTo.connect(self.new_mail_to)
        dlg.exec()

    def _find_contact(self):
        text = self.find_contact.text().strip()
        if text:
            self.address_book(text)

    def import_vcards(self):
        self.contacts_view.import_vcards()

    def export_vcards(self):
        self.contacts_view.export_vcards()

    # ---- files ---------------------------------------------------------------------------
    def open_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Open", str(os.path.expanduser("~")),
                                              "Mail messages (*.eml);;vCard (*.vcf);;All files (*)")
        if path.lower().endswith(".vcf"):
            self.contacts_view.import_vcards(path)
        elif path:
            import mail_view
            w = mail_view.open_eml_file(path)
            if w:
                self.message_windows.append(w)

    def save_as(self):
        ids = self.list.selected_ids()
        if len(ids) != 1:
            return
        m = self.store.message(ids[0])
        raw = self.store.cached_eml(m) if m else None
        if raw is None:
            return
        w = MessageWindow(render.parse(raw), None, None, raw)
        w.save_as()
        w.deleteLater()

    def print_current(self):
        if self.module == "contacts":
            self.contacts_view.print_cards()
        else:
            self.reading.print_message(self)

    # ---- misc ----------------------------------------------------------------------------
    def about(self):
        QMessageBox.about(self, f"About {APP}",
                          f"<b>{APP}</b> for Classic 7<br>E-mail and contacts in the Outlook 2007 style.<br><br>"
                          "IMAP and SMTP, Gmail (app password) and Outlook.com (Microsoft sign-in).<br>"
                          "Messages are written with Write's editor.")

    def quit_app(self):
        self.close()
        QApplication.quit()

    def closeEvent(self, e):
        self.save_state()
        self.workers.stop_all()
        if self.tray:
            self.tray.hide()
        e.accept()


# =============================================================================
# start-up: one Mail per user; later launches hand over their arguments
# =============================================================================
def _server_name() -> str:
    return f"classic7-mail-{os.getuid()}"


def _send_to_running(args: list[str]) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(_server_name())
    if not s.waitForConnected(500):
        return False
    s.write(json.dumps(args).encode() + b"\n")
    s.flush()
    s.waitForBytesWritten(1000)
    s.disconnectFromServer()
    return True


class App:
    def __init__(self, qapp):
        self.qapp = qapp
        self.store = Store()
        self.main: MailWindow | None = None
        self.windows = []
        from PySide6.QtNetwork import QLocalServer
        QLocalServer.removeServer(_server_name())
        self.server = QLocalServer()
        self.server.listen(_server_name())
        self.server.newConnection.connect(self._incoming)

    def _incoming(self):
        while self.server.hasPendingConnections():
            c = self.server.nextPendingConnection()
            c.waitForReadyRead(1000)
            try:
                args = json.loads(bytes(c.readAll()).decode() or "[]")
            except ValueError:
                args = []
            c.disconnectFromServer()
            self.handle(args, remote=True)

    def show_main(self):
        if self.main is None:
            self.main = MailWindow(self.store)
            self.main.destroyed.connect(lambda *_: setattr(self, "main", None))
            self.main.setAttribute(Qt.WA_DeleteOnClose)
        self.main.show()
        self.main.raise_()
        self.main.activateWindow()

    def handle(self, args: list[str], remote=False):
        import mail_compose
        attach = []
        mailto = None
        files = []
        compose = False
        it = iter(args)
        for a in it:
            if a == "--compose":
                compose = True
            elif a == "--attach":
                p = next(it, None)
                if p:
                    attach.append(p)
                    compose = True
            elif a.lower().startswith("mailto:"):
                mailto = a
                compose = True
            elif a.startswith("-"):
                continue
            else:
                files.append(a)
        handled = False
        for f in files:
            if f.lower().endswith(".eml"):
                import mail_view
                w = mail_view.open_eml_file(f)
                if w:
                    self.windows.append(w)
                handled = True
        if compose:
            handler = self.main
            fields = mail_compose.parse_mailto(mailto) if mailto else {}
            c = mail_compose.Composer(self.store, handler=handler, attachments=attach, **fields)
            c.show()
            c.raise_()
            c.activateWindow()
            self.windows.append(c)
            handled = True
        if not handled:
            self.show_main()


def main(argv=None) -> int:
    from PySide6.QtCore import QCoreApplication
    # files as absolute paths: a running Mail (another working folder) may open them
    argv = [os.path.abspath(a) if not a.startswith("-") and ":" not in a.split("/")[0] and os.path.exists(a) else a
            for a in (argv or [])]
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    qapp.setApplicationName("classic7-mail")
    qapp.setApplicationDisplayName(APP)
    qapp.setDesktopFileName("classic7-mail")
    qapp.setQuitOnLastWindowClosed(True)
    try:
        import write_model as wm
        for fam, subs in wm.FONT_SUBSTITUTES.items():
            QFont.insertSubstitutions(fam, subs)
    except ImportError:
        pass
    if _send_to_running(argv or ["--show"]):
        return 0
    app = App(qapp)
    app.handle(argv)
    qapp._classic7_mail = app
    return qapp.exec()
