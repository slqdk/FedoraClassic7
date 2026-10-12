"""Mail: turning a downloaded message into something to show, and into replies/forwards."""
from __future__ import annotations

import email
import email.policy
import html as htmlmod
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import getaddresses, parsedate_to_datetime

from mail_imap import decode_mime, format_addresses

REMOTE = re.compile(r"""(?is)(<img[^>]+src\s*=\s*["']?\s*https?:|url\(\s*["']?\s*https?:|<link[^>]+href\s*=\s*["']?https?:|background\s*=\s*["']?https?:)""")
URL = re.compile(r"""(?i)\b((?:https?://|www\.)[^\s<>"']+[^\s<>"'.,;:!?)\]])|\b([\w.+-]+@[\w-]+(?:\.[\w-]+)+)""")


@dataclass
class Attachment:
    name: str
    mime: str
    data: bytes
    cid: str = ""
    inline: bool = False

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class Parsed:
    subject: str = ""
    from_: list = field(default_factory=list)
    to: list = field(default_factory=list)
    cc: list = field(default_factory=list)
    bcc: list = field(default_factory=list)
    reply_to: list = field(default_factory=list)
    date: datetime | None = None
    msgid: str = ""
    references: str = ""
    html: str = ""
    text: str = ""
    attachments: list = field(default_factory=list)      # real attachments
    related: dict = field(default_factory=dict)          # cid -> Attachment (inline images)
    importance: int = 0
    receipt_to: str = ""

    @property
    def has_remote(self) -> bool:
        return bool(self.html and REMOTE.search(self.html))

    @property
    def from_text(self) -> str:
        return format_addresses(self.from_)

    @property
    def to_text(self) -> str:
        return format_addresses(self.to)

    @property
    def cc_text(self) -> str:
        return format_addresses(self.cc)


def _addrs(msg, name):
    return [(decode_mime(n), a) for n, a in getaddresses([str(v) for v in msg.get_all(name, [])]) if a or n]


def _text_of(part) -> str:
    try:
        return part.get_content()
    except Exception:   # noqa: BLE001
        payload = part.get_payload(decode=True) or b""
        cs = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(cs, errors="replace")
        except LookupError:
            return payload.decode("latin-1", errors="replace")


def parse(raw: bytes) -> Parsed:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    p = Parsed()
    p.subject = decode_mime(msg.get("Subject", "") and str(msg.get("Subject")))
    p.from_ = _addrs(msg, "From")
    p.to = _addrs(msg, "To")
    p.cc = _addrs(msg, "Cc")
    p.bcc = _addrs(msg, "Bcc")
    p.reply_to = _addrs(msg, "Reply-To")
    try:
        p.date = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else None
    except (TypeError, ValueError, IndexError):
        p.date = None
    p.msgid = str(msg.get("Message-ID", "") or "").strip()
    p.references = " ".join(str(msg.get("References", "") or "").split())
    prio = str(msg.get("X-Priority", "") or "").strip()[:1]
    imp = str(msg.get("Importance", "") or "").lower()
    p.importance = 1 if prio in ("1", "2") or imp == "high" else -1 if prio in ("4", "5") or imp == "low" else 0
    p.receipt_to = str(msg.get("Disposition-Notification-To", "") or "")

    try:
        hb = msg.get_body(preferencelist=("html",))
    except Exception:   # noqa: BLE001
        hb = None
    try:
        tb = msg.get_body(preferencelist=("plain",))
    except Exception:   # noqa: BLE001
        tb = None
    if hb is not None:
        p.html = _text_of(hb)
    if tb is not None:
        p.text = _text_of(tb)
    if not p.html and not p.text and not msg.is_multipart():
        p.text = _text_of(msg) if msg.get_content_maintype() == "text" else ""

    body_parts = {id(hb), id(tb)}
    for part in msg.walk():
        if part.is_multipart() or id(part) in body_parts:
            continue
        cid = str(part.get("Content-ID", "") or "").strip().strip("<>")
        disp = part.get_content_disposition()
        name = part.get_filename()
        name = decode_mime(name) if name else ""
        mime = part.get_content_type()
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:   # noqa: BLE001
            data = b""
        if mime == "message/rfc822":
            sub = part.get_payload()
            sub = sub[0] if isinstance(sub, list) and sub else sub
            try:
                data = sub.as_bytes() if hasattr(sub, "as_bytes") else bytes(sub)
            except Exception:   # noqa: BLE001
                data = b""
            name = name or (decode_mime(str(sub.get("Subject", "message"))) if hasattr(sub, "get") else "message") + ".eml"
        if cid and disp != "attachment" and mime.startswith("image/"):
            p.related[cid] = Attachment(name or cid, mime, data, cid, True)
            if p.html and f"cid:{cid}" in p.html:
                continue
        if disp == "attachment" or name or (mime not in ("text/plain", "text/html") and not cid):
            if not name:
                ext = {"text/calendar": ".ics", "text/plain": ".txt", "text/html": ".html"}.get(mime, "")
                name = f"attachment{len(p.attachments) + 1}{ext}"
            p.attachments.append(Attachment(name, mime, data, cid, disp == "inline"))
        elif mime == "text/plain" and not p.text:
            p.text = _text_of(part)
    return p


def linkify(text: str) -> str:
    out, last = [], 0
    for m in URL.finditer(text):
        out.append(htmlmod.escape(text[last:m.start()]))
        if m.group(1):
            url = m.group(1)
            href = url if url.lower().startswith("http") else "http://" + url
            out.append(f'<a href="{htmlmod.escape(href)}">{htmlmod.escape(url)}</a>')
        else:
            out.append(f'<a href="mailto:{m.group(2)}">{htmlmod.escape(m.group(2))}</a>')
        last = m.end()
    out.append(htmlmod.escape(text[last:]))
    return "".join(out)


BODY_CSS = ("body{font-family:Calibri,Carlito,'Segoe UI',sans-serif;font-size:11pt;margin:8px 10px;"
            "color:#000;background:#fff;word-wrap:break-word}"
            "blockquote{margin:0 0 0 .8ex;border-left:2px solid #1F497D;padding-left:1ex}")


def text_html(text: str) -> str:
    return ('<div class="c7plain" style="white-space:pre-wrap;font-family:Calibri,Carlito,\'Segoe UI\',sans-serif;'
            f'font-size:11pt">{linkify(text)}</div>')


def body_html(p: Parsed, cid_map: dict | None = None) -> str:
    """Full HTML document for the reading pane. cid_map: cid -> URL to show inline images."""
    if p.html:
        h = p.html
        if cid_map:
            for cid, url in cid_map.items():
                h = h.replace(f"cid:{cid}", url)
        if not re.search(r"(?i)<html", h):
            h = f"<html><head></head><body>{h}</body></html>"
        style = f"<style>{BODY_CSS}</style>"
        h = re.sub(r"(?i)<head[^>]*>", lambda m: m.group(0) + '<meta charset="utf-8">' + style, h, count=1) \
            if re.search(r"(?i)<head", h) else re.sub(r"(?i)<html[^>]*>", lambda m: m.group(0) + f"<head>{style}</head>", h, count=1)
        return h
    return (f'<html><head><meta charset="utf-8"><style>{BODY_CSS}</style></head><body>'
            f"{text_html(p.text)}</body></html>")


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{max(1, round(n / 1024))} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def outlook_date(d: datetime | None) -> str:
    """'Monday, October 12, 2026 9:41 AM' like Outlook's Sent: line."""
    if not d:
        return ""
    d = d.astimezone()
    return d.strftime("%A, %B %d, %Y %H:%M").replace(" 0", " ")


# ---- replies and forwards ---------------------------------------------------------------------
def _strip_prefix(subject: str) -> str:
    return re.sub(r"^\s*((re|sv|vs|aw|fw|fwd|vb|wg|tr)\s*(\[\d+\])?\s*:\s*)+", "", subject, flags=re.I)


def reply_subject(subject: str) -> str:
    return "RE: " + _strip_prefix(subject)


def forward_subject(subject: str) -> str:
    return "FW: " + _strip_prefix(subject)


def quote_header_html(p: Parsed) -> str:
    rows = [("From", p.from_text), ("Sent", outlook_date(p.date)), ("To", p.to_text)]
    if p.cc:
        rows.append(("Cc", p.cc_text))
    rows.append(("Subject", p.subject))
    lines = "<br>".join(f"<b>{k}:</b> {htmlmod.escape(v)}" for k, v in rows)
    return ('<hr style="border:none;border-top:1px solid #B5C4DF;height:1px;margin:0">'
            f'<p style="font-family:Tahoma,sans-serif;font-size:10pt;margin:3pt 0 12pt 0">{lines}</p>')


def _inner_body(h: str) -> str:
    m = re.search(r"(?is)<body[^>]*>(.*)</body>", h)
    h = m.group(1) if m else h
    h = re.sub(r"(?is)<(script|style|head|title|meta)[^>]*>.*?</\1>", "", h)
    return re.sub(r"(?is)<(meta|link)[^>]*>", "", h)


def quoted_body_html(p: Parsed) -> str:
    """The original message, below a reply or forward."""
    inner = _inner_body(p.html) if p.html else text_html(p.text)
    return "<br><br>" + quote_header_html(p) + inner


def reply_all_recipients(p: Parsed, me: list[str]) -> tuple[str, str]:
    mine = {m.lower() for m in me}
    first = p.reply_to or p.from_
    to = first + [x for x in p.to if x[1].lower() not in mine]
    cc = [x for x in p.cc if x[1].lower() not in mine]
    seen, out_to, out_cc = set(), [], []
    for lst, out in ((to, out_to), (cc, out_cc)):
        for n, a in lst:
            if a.lower() in seen:
                continue
            seen.add(a.lower())
            out.append((n, a))
    return format_addresses(out_to), format_addresses(out_cc)
