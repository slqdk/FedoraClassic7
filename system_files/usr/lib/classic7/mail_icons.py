"""Mail: small colour icons drawn in code, in the Outlook 2007 manner (yellow envelopes,
coloured arrows, yellow folders). Theme icons are used where they exist and look right."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)

SIZES = (16, 24, 32, 48)


def _pix(size: int, draw) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 16, size / 16)
    draw(p)
    p.end()
    return pm


def _icon(draw) -> QIcon:
    ic = QIcon()
    for s in SIZES:
        ic.addPixmap(_pix(s, draw))
    return ic


def _grad(y0, y1, c0, c1):
    g = QLinearGradient(0, y0, 0, y1)
    g.setColorAt(0, QColor(c0))
    g.setColorAt(1, QColor(c1))
    return QBrush(g)


# ---- pieces ------------------------------------------------------------------------------------
def envelope(p: QPainter, x=1.0, y=3.5, w=14.0, h=10.0, opened=False, color=("#FFF8D8", "#F2CF6A"), edge="#9C7A26"):
    pen = QPen(QColor(edge), 0.9)
    pen.setJoinStyle(Qt.RoundJoin)
    if opened:
        # flap open above the envelope
        p.setPen(pen)
        p.setBrush(_grad(y - 3, y + 2, "#FFFFFF", "#F4E6B8"))
        p.drawPolygon(QPolygonF([QPointF(x, y + 3), QPointF(x + w / 2, y - 2.5), QPointF(x + w, y + 3)]))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(QRectF(x + 2, y - 0.5, w - 4, 5))
        p.setBrush(_grad(y + 3, y + h, "#FFFDF3", "#EFE3BE"))
        p.drawRect(QRectF(x, y + 3, w, h - 3))
        p.drawLine(QPointF(x, y + 3), QPointF(x + w / 2, y + 3 + (h - 3) * 0.6))
        p.drawLine(QPointF(x + w, y + 3), QPointF(x + w / 2, y + 3 + (h - 3) * 0.6))
        return
    p.setPen(pen)
    p.setBrush(_grad(y, y + h, *color))
    p.drawRoundedRect(QRectF(x, y, w, h), 0.8, 0.8)
    p.drawPolyline(QPolygonF([QPointF(x + 0.4, y + 0.6), QPointF(x + w / 2, y + h * 0.6), QPointF(x + w - 0.4, y + 0.6)]))


def arrow(p: QPainter, x, y, direction=1, color="#7B3FA0", scale=1.0, double=False):
    """Curved arrow like Outlook's reply (direction -1, purple) / forward (+1, blue)."""
    s = scale
    for k in ((0, 1) if double else (0,)):
        dx = -k * 3.2 * s * direction
        path = QPainterPath()
        # shaft: arc from right/bottom towards the head
        path.moveTo(x - direction * 5 * s + dx, y + 4.5 * s)
        path.cubicTo(x - direction * 5 * s + dx, y + 0.5 * s, x - direction * 2.5 * s + dx, y - 0.8 * s,
                     x + direction * 0.5 * s + dx, y - 0.8 * s)
        pen = QPen(QColor(color), 2.2 * s)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        hx = x + direction * 0.4 * s + dx
        p.drawPolygon(QPolygonF([QPointF(hx, y - 4.0 * s), QPointF(hx + direction * 4.2 * s, y - 0.8 * s),
                                 QPointF(hx, y + 2.4 * s)]))


def folder(p: QPainter, x=1.0, y=2.5, w=14.0, h=11.0, colors=("#FBE39A", "#E6B84A"), edge="#A87F23"):
    pen = QPen(QColor(edge), 0.9)
    p.setPen(pen)
    p.setBrush(_grad(y, y + h, "#F6D57A", "#D9A63A"))
    p.drawPolygon(QPolygonF([QPointF(x, y + 1.2), QPointF(x + 4.5, y + 1.2), QPointF(x + 5.8, y + 2.6),
                             QPointF(x + w, y + 2.6), QPointF(x + w, y + h), QPointF(x, y + h)]))
    p.setBrush(_grad(y + 3.5, y + h, *colors))
    p.drawRect(QRectF(x, y + 3.6, w, h - 3.6))


def _x(p: QPainter, cx, cy, r, color="#202020", width=2.2):
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
    p.drawLine(QPointF(cx - r, cy + r), QPointF(cx + r, cy - r))


# ---- icons ------------------------------------------------------------------------------------
@lru_cache(None)
def get(name: str) -> QIcon:
    return _icon(DRAW[name])


def _new_mail(p):
    envelope(p, 0.5, 4, 13, 9.5)
    # sparkle
    p.setPen(QPen(QColor("#E08A00"), 1.2))
    for a, b in (((13, 0.5), (13, 5.5)), ((10.5, 3), (15.5, 3)), ((11.2, 1.2), (14.8, 4.8)), ((11.2, 4.8), (14.8, 1.2))):
        p.drawLine(QPointF(*a), QPointF(*b))


def _reply(p):
    envelope(p, 4, 5, 11.5, 8.5)
    arrow(p, 3.5, 6.0, -1, "#8A3FB5", 0.95)


def _reply_all(p):
    envelope(p, 5, 5, 10.5, 8.5)
    arrow(p, 5.2, 6.0, -1, "#8A3FB5", 0.85, double=True)


def _forward(p):
    envelope(p, 0.5, 5, 11.5, 8.5)
    arrow(p, 12.0, 6.0, 1, "#2266CC", 0.95)


def _send_receive(p):
    envelope(p, 0.5, 6, 11, 8)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2A9A2A"))
    p.drawPolygon(QPolygonF([QPointF(11, 0.5), QPointF(15.5, 3.5), QPointF(11, 6.5)]))
    p.drawRect(QRectF(7.5, 2.5, 4, 2))
    p.setBrush(QColor("#2266CC"))
    p.drawPolygon(QPolygonF([QPointF(12, 7), QPointF(16, 7), QPointF(14, 10)]))
    p.drawRect(QRectF(13.1, 4.5, 1.8, 3))


def _delete(p):
    _x(p, 8, 8, 5, "#1B1B1B", 2.6)


def _closed(p):
    envelope(p)


def _opened(p):
    envelope(p, 1, 5, 14, 9, opened=True)


def _replied(p):
    envelope(p, 1, 5, 14, 9, opened=True)
    arrow(p, 6.0, 4.0, -1, "#8A3FB5", 0.75)


def _forwarded(p):
    envelope(p, 1, 5, 14, 9, opened=True)
    arrow(p, 10.0, 4.0, 1, "#2266CC", 0.75)


def _draft(p):
    envelope(p, 1, 5, 14, 9, opened=True)
    _pencil(p, 7, 0.5)


def _pencil(p, x, y):
    p.save()
    p.translate(x, y)
    p.rotate(45)
    p.setPen(QPen(QColor("#5A4410"), 0.6))
    p.setBrush(QColor("#F2B233"))
    p.drawRect(QRectF(0, 0, 2.6, 7.5))
    p.setBrush(QColor("#F7D9A8"))
    p.drawPolygon(QPolygonF([QPointF(0, 7.5), QPointF(2.6, 7.5), QPointF(1.3, 10)]))
    p.setBrush(QColor("#E46C6C"))
    p.drawRect(QRectF(0, -1.2, 2.6, 1.2))
    p.restore()


def _folder(p):
    folder(p)


def _inbox(p):
    folder(p)
    envelope(p, 4, 7.5, 9, 6)


def _sent(p):
    folder(p)
    envelope(p, 3.5, 8, 8, 5.5)
    arrow(p, 12.5, 9.5, 1, "#2266CC", 0.6)


def _drafts(p):
    folder(p)
    _pencil(p, 10.5, 4)


def _trash(p):
    folder(p)
    _x(p, 8.5, 9.5, 2.6, "#C02020", 1.8)


def _junk(p):
    folder(p)
    p.setPen(QPen(QColor("#C02020"), 1.4))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(8.5, 9.5), 3.0, 3.0)
    p.drawLine(QPointF(6.4, 11.6), QPointF(10.6, 7.4))


def _archive(p):
    folder(p, colors=("#E9D9A8", "#C9AE5C"))


def _account(p):
    # a mailbox/server: grey-blue box with an envelope
    p.setPen(QPen(QColor("#4A6185"), 0.9))
    p.setBrush(_grad(1, 15, "#E6EEF9", "#A9BEDC"))
    p.drawRoundedRect(QRectF(1, 1.5, 14, 13), 1.5, 1.5)
    envelope(p, 3.5, 5, 9, 6.5)


def _search_folder(p):
    folder(p, colors=("#D7E6FA", "#9DBBE5"), edge="#4C6E9E")
    p.setPen(QPen(QColor("#203A64"), 1.3))
    p.setBrush(QColor(255, 255, 255, 170))
    p.drawEllipse(QPointF(7.5, 9), 2.6, 2.6)
    p.drawLine(QPointF(9.4, 10.9), QPointF(12, 13.5))


def _contact(p):
    # business card with a person
    p.setPen(QPen(QColor("#5B6E8C"), 0.9))
    p.setBrush(_grad(3, 14, "#FFFFFF", "#DCE6F4"))
    p.drawRoundedRect(QRectF(0.5, 3, 15, 10.5), 1, 1)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#E0A060"))
    p.drawEllipse(QPointF(5, 6.8), 1.9, 1.9)
    p.setBrush(QColor("#3A6EA5"))
    p.drawChord(QRectF(1.8, 8.6, 6.4, 6), 0, 180 * 16)
    p.setPen(QPen(QColor("#8090A8"), 1))
    for yy in (6, 8.5, 11):
        p.drawLine(QPointF(9, yy), QPointF(14, yy))


def _contacts(p):
    p.save()
    p.translate(1.2, -1.2)
    _contact(p)
    p.restore()
    _contact(p)


def _address_book(p):
    p.setPen(QPen(QColor("#3A4F7A"), 0.9))
    p.setBrush(_grad(1, 15, "#7FA4D8", "#3D68A8"))
    p.drawRoundedRect(QRectF(2.5, 1, 11.5, 14), 1, 1)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRect(QRectF(4.5, 3, 7.5, 3))
    p.setPen(QPen(QColor("#203050"), 1.3))
    for yy in (3, 6, 9, 12):
        p.drawLine(QPointF(1.5, yy), QPointF(3.5, yy))


def _move(p):
    folder(p, 3, 4, 12, 10)
    arrow(p, 5.5, 4.5, 1, "#2A9A2A", 0.8)


def _attach(p):
    pen = QPen(QColor("#505050"), 1.2)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(10.5, 5)
    path.lineTo(10.5, 12)
    path.arcTo(QRectF(6, 9.5, 4.5, 5), 0, -180)
    path.lineTo(6, 3.5)
    path.arcTo(QRectF(6, 1, 3, 3), 180, -180)
    path.lineTo(9, 11)
    p.drawPath(path)


def _flag(p):
    p.setPen(QPen(QColor("#505050"), 1.1))
    p.drawLine(QPointF(4, 2), QPointF(4, 15))
    p.setPen(QPen(QColor("#9E0B0B"), 0.8))
    p.setBrush(_grad(2, 9, "#F45A4A", "#C81616"))
    p.drawPolygon(QPolygonF([QPointF(4.4, 2.2), QPointF(13, 2.5), QPointF(11, 5.3), QPointF(13, 8.3),
                             QPointF(4.4, 8.3)]))


def _flag_outline(p):
    p.setPen(QPen(QColor("#B0B0B0"), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(4, 2), QPointF(4, 15))
    p.drawPolygon(QPolygonF([QPointF(4.4, 2.2), QPointF(13, 2.5), QPointF(11, 5.3), QPointF(13, 8.3),
                             QPointF(4.4, 8.3)]))


def _flag_done(p):
    p.setPen(QPen(QColor("#2C8A2C"), 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(3, 8.5), QPointF(6.5, 12), QPointF(13, 4)]))


def _high(p):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#D01010"))
    p.drawRoundedRect(QRectF(6.5, 1.5, 3, 9), 1.2, 1.2)
    p.drawEllipse(QPointF(8, 13.3), 1.7, 1.7)


def _low(p):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1C5FC0"))
    p.drawRect(QRectF(6.8, 2, 2.4, 7))
    p.drawPolygon(QPolygonF([QPointF(3.5, 8.5), QPointF(12.5, 8.5), QPointF(8, 14)]))


def _send(p):
    envelope(p, 0.5, 5.5, 11, 8)
    arrow(p, 12.2, 6.5, 1, "#2266CC", 0.9)


def _names(p):
    _address_book(p)
    p.setPen(QPen(QColor("#1B7E1B"), 1.6))
    p.drawLine(QPointF(9, 11), QPointF(15, 11))
    p.drawLine(QPointF(12, 8), QPointF(12, 14))


def _signature(p):
    p.setPen(QPen(QColor("#5B6E8C"), 0.9))
    p.setBrush(QColor("#FFFFFF"))
    p.drawRect(QRectF(0.5, 2.5, 15, 11))
    pen = QPen(QColor("#1F3B78"), 1.1)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(2, 10)
    path.cubicTo(4, 4, 5, 13, 7, 8)
    path.cubicTo(8, 5, 9, 11, 11, 8)
    path.lineTo(14, 8)
    p.drawPath(path)


def _unread_folder(p):
    _search_folder(p)


def _mark_read(p):
    _opened(p)


def _mark_unread(p):
    _closed(p)


DRAW = {
    "new": _new_mail, "reply": _reply, "reply-all": _reply_all, "forward": _forward,
    "send-receive": _send_receive, "delete": _delete, "closed": _closed, "opened": _opened,
    "replied": _replied, "forwarded": _forwarded, "draft": _draft, "folder": _folder, "inbox": _inbox,
    "sent": _sent, "drafts": _drafts, "trash": _trash, "junk": _junk, "archive": _archive, "account": _account,
    "search-folder": _search_folder, "contact": _contact, "contacts": _contacts, "address-book": _address_book,
    "move": _move, "attach": _attach, "flag": _flag, "flag-outline": _flag_outline, "flag-done": _flag_done,
    "high": _high, "low": _low, "send": _send, "names": _names, "signature": _signature,
    "unread-folder": _unread_folder, "mark-read": _mark_read, "mark-unread": _mark_unread,
}

FOLDER_ROLE_ICON = {"inbox": "inbox", "sent": "sent", "drafts": "drafts", "trash": "trash", "junk": "junk",
                    "archive": "archive", "all": "search-folder", "flagged": "search-folder",
                    "important": "search-folder"}


def folder_icon(role: str) -> QIcon:
    return get(FOLDER_ROLE_ICON.get(role, "folder"))


def theme(names, fallback: str) -> QIcon:
    for n in ([names] if isinstance(names, str) else names):
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return get(fallback)
