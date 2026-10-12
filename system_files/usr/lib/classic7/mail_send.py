"""Mail: building outgoing messages and sending them (smtplib)."""
from __future__ import annotations

import mimetypes
import re
import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from pathlib import Path

import mail_accounts as acc_mod

TIMEOUT = 60


class SendError(Exception):
    pass


@dataclass
class Outgoing:
    to: str = ""
    cc: str = ""
    bcc: str = ""
    subject: str = ""
    html: str = ""
    text: str = ""
    images: dict = field(default_factory=dict)        # cid -> (bytes, "image/png")
    attachments: list = field(default_factory=list)   # paths, or (name, bytes, mime)
    in_reply_to: str = ""
    references: str = ""
    importance: int = 0                               # -1 low, 1 high
    read_receipt: bool = False
    plain_only: bool = False


ADDR = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
ANGLE = re.compile(r'^\s*"?(.*?)"?\s*<([^<>]+)>\s*$')


def _parts(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;\n]", text or "") if p.strip()]


def split_addresses(text: str) -> list[tuple[str, str]]:
    """'Søren <s@x.dk>; b@y.dk, c@z.dk; Lyder, Søren <d@x.dk>' -> [(name, addr), ...].
    Names may contain commas; entries are separated by ';' (or ',' between bare addresses)."""
    out = []
    for part in _parts(text):
        m = ANGLE.match(part)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
            continue
        out += [(n, a.strip()) for n, a in getaddresses([part]) if a.strip()]
    return out


def bad_addresses(text: str) -> list[str]:
    bad = []
    for part in _parts(text):
        m = ANGLE.match(part)
        if m:
            if not ADDR.match(m.group(2).strip()):
                bad.append(part)
            continue
        for item in [x.strip() for x in part.split(",") if x.strip()]:
            pairs = getaddresses([item])
            if not pairs or not ADDR.match(pairs[0][1] or ""):
                bad.append(item)
    return bad


def _header_list(pairs) -> str:
    return ", ".join(formataddr((n, a)) if n else a for n, a in pairs)


def build(account: acc_mod.Account, out: Outgoing) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = account.sender
    if account.reply_address:
        msg["Reply-To"] = account.reply_address
    if out.to.strip():
        msg["To"] = _header_list(split_addresses(out.to))
    if out.cc.strip():
        msg["Cc"] = _header_list(split_addresses(out.cc))
    if out.bcc.strip():
        msg["Bcc"] = _header_list(split_addresses(out.bcc))
    msg["Subject"] = out.subject
    msg["Date"] = formatdate(localtime=True)
    domain = acc_mod.domain_of(account.email) or "classic7.local"
    msg["Message-ID"] = make_msgid(domain=domain)
    if out.in_reply_to:
        msg["In-Reply-To"] = out.in_reply_to
    if out.references:
        msg["References"] = out.references
    if out.importance > 0:
        msg["X-Priority"] = "1"
        msg["Importance"] = "High"
    elif out.importance < 0:
        msg["X-Priority"] = "5"
        msg["Importance"] = "Low"
    if out.read_receipt:
        msg["Disposition-Notification-To"] = account.sender
    msg["X-Mailer"] = "Classic 7 Mail"

    text = out.text if out.text else html_to_text(out.html)
    msg.set_content(text)
    if out.html and not out.plain_only:
        msg.add_alternative(out.html, subtype="html")
        if out.images:
            html_part = msg.get_payload()[-1]
            for cid, (data, mime) in out.images.items():
                maintype, subtype = (mime or "image/png").split("/", 1)
                html_part.add_related(data, maintype=maintype, subtype=subtype, cid=f"<{cid}>",
                                      disposition="inline", filename=f"{cid.split('@')[0]}.{subtype}")
    for a in out.attachments:
        if isinstance(a, (str, Path)):
            p = Path(a)
            data = p.read_bytes()
            name = p.name
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        else:
            name, data, mime = a
            mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg


def html_to_text(html: str) -> str:
    try:
        import html2text
        h = html2text.HTML2Text()
        h.body_width = 0
        h.ignore_images = True
        h.unicode_snob = True
        return h.handle(html).strip() + "\n"
    except Exception:   # noqa: BLE001
        from html import unescape
        t = re.sub(r"(?is)<(script|style|head).*?</\1>", "", html)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", t)
        t = re.sub(r"<[^>]+>", "", t)
        return re.sub(r"\n{3,}", "\n\n", unescape(t)).strip() + "\n"


def recipients(msg: EmailMessage) -> list[str]:
    return [a for _n, a in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []) + msg.get_all("Bcc", []))
            if a]


def explain(e: Exception) -> str:
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "The outgoing mail server (SMTP) did not accept the user name or password."
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        bad = ", ".join(e.recipients)
        return f"The server refused these recipients: {bad}"
    if isinstance(e, smtplib.SMTPSenderRefused):
        return f"The server refused the sender address ({e.smtp_error.decode(errors='replace')})."
    if isinstance(e, smtplib.SMTPDataError):
        return f"The server refused the message: {e.smtp_error.decode(errors='replace')}"
    if isinstance(e, socket.gaierror):
        return "The outgoing mail server name can't be found."
    if isinstance(e, ConnectionRefusedError):
        return "The outgoing mail server refused the connection. Check the port number and encryption."
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "The outgoing mail server did not answer in time."
    if isinstance(e, ssl.SSLError):
        return "A secure connection to the outgoing mail server could not be made. Check port and encryption."
    if isinstance(e, smtplib.SMTPNotSupportedError):
        return "The outgoing mail server doesn't support this way of logging on. Check the encryption setting."
    return str(e) or type(e).__name__


def connect(account: acc_mod.Account) -> smtplib.SMTP:
    a = account
    ctx = ssl.create_default_context()
    if a.smtp_security == "ssl":
        s = smtplib.SMTP_SSL(a.smtp_host, a.smtp_port, timeout=TIMEOUT, context=ctx)
    else:
        s = smtplib.SMTP(a.smtp_host, a.smtp_port, timeout=TIMEOUT)
        s.ehlo()
        if a.smtp_security == "starttls":
            s.starttls(context=ctx)
            s.ehlo()
    if a.smtp_auth:
        if a.auth == "oauth-microsoft":
            import mail_oauth
            token = mail_oauth.access_token(a)
            raw = mail_oauth.xoauth2(a.smtp_login, token)
            s.auth("XOAUTH2", lambda challenge=None: raw if challenge is None else "", initial_response_ok=True)
        else:
            s.login(a.smtp_login, acc_mod.get_secret(a.id, "password"))
    return s


def send(account: acc_mod.Account, msg: EmailMessage):
    to = recipients(msg)
    if not to:
        raise SendError("There must be at least one name or contact group in the To, Cc, or Bcc box.")
    try:
        s = connect(account)
        try:
            s.send_message(msg, from_addr=account.email, to_addrs=to)
        finally:
            try:
                s.quit()
            except Exception:   # noqa: BLE001
                pass
    except SendError:
        raise
    except Exception as e:   # noqa: BLE001
        raise SendError(explain(e)) from e


def test_smtp(account: acc_mod.Account):
    try:
        s = connect(account)
        s.quit()
    except Exception as e:   # noqa: BLE001
        raise SendError(explain(e)) from e
