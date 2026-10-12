"""Mail end-to-end test, run by .github/workflows/test-mail.yml inside the image:
pymap (IMAP) + aiosmtpd (SMTP), then sync, read, reply, send, Sent copy, contacts, folders, drafts."""
import os, sys, tempfile, time, shutil
OUT = sys.argv[1] if len(sys.argv) > 1 else "shots"
os.makedirs(OUT, exist_ok=True)
H = tempfile.mkdtemp()
os.environ.update(HOME=H, XDG_CONFIG_HOME=H+"/.config", XDG_DATA_HOME=H+"/.local/share", XDG_CACHE_HOME=H+"/.cache",
                  CLASSIC7_MAIL_NO_KEYRING="1", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path.insert(0, os.environ.get("CLASSIC7_LIB", "/usr/lib/classic7"))

# SMTP sink
from aiosmtpd.controller import Controller
received = []
class H_:
    async def handle_DATA(self, server, session, envelope):
        received.append((envelope.mail_from, envelope.rcpt_tos, envelope.content)); return "250 OK"
ctl = Controller(H_(), hostname="127.0.0.1", port=1025); ctl.start()

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon, QFont
from PySide6.QtCore import QTimer, Qt, QEventLoop
app = QApplication([])
app.setStyle("Windows")
import subprocess
QIcon.setThemeName("breeze")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: print("INFO:", a[2]))
QMessageBox.warning = staticmethod(lambda *a, **k: print("WARN:", a[2]) or QMessageBox.Yes)
QMessageBox.critical = staticmethod(lambda *a, **k: print("CRIT:", a[2]))

import mail_accounts as A
a = A.Account(name="soren@firma.dk", email="demouser@example.com", display_name="Søren Lyder", imap_host="127.0.0.1",
              imap_port=1143, imap_security="none", smtp_host="127.0.0.1", smtp_port=1025, smtp_security="none",
              smtp_auth=False, username="demouser", check_minutes=10)
A.upsert(a); A.set_secret(a.id, "password", "demopass")

# put some richer mail on the server
import imaplib, email.message, email.utils
c = imaplib.IMAP4("127.0.0.1", 1143); c.login("demouser", "demopass")
def put(folder, subj, frm, body_html=None, text="Hej", att=None, days=0, seen=False, flags=""):
    m = email.message.EmailMessage()
    m["From"] = frm; m["To"] = "Søren Lyder <demouser@example.com>"; m["Subject"] = subj
    m["Date"] = email.utils.formatdate(time.time() - days * 86400, localtime=True)
    m["Message-ID"] = email.utils.make_msgid()
    m.set_content(text)
    if body_html: m.add_alternative(body_html, subtype="html")
    if att: m.add_attachment(att[1], maintype="application", subtype="octet-stream", filename=att[0])
    c.append(folder, "(\\Seen)" if seen else "()", imaplib.Time2Internaldate(time.time() - days * 86400), m.as_bytes())
docx = b"PK\x03\x04" + b"0" * 3000
put("INBOX", "Kursus i TwinCAT 3 – uge 44", "Beckhoff Danmark <kursus@beckhoff.dk>",
    "<p>Hej Søren,</p><p>Her er programmet for <b>TwinCAT 3</b> kurset i uge 44.</p><ul><li>Mandag: PLC</li><li>Tirsdag: Motion</li></ul>"
    "<p><img src='https://example.com/logo.png'></p><p>Venlig hilsen<br>Mette</p>", att=("Program uge 44.docx", docx))
put("INBOX", "Frokost fredag?", "Jens Hansen <jens@example.dk>", text="Skal vi tage frokost på fredag?")
put("INBOX", "Faktura 2026-118", "Bogholderiet <faktura@example.dk>", text="Se vedhæftede faktura.", days=1, seen=True,
    att=("Faktura 2026-118.pdf", b"%PDF-1.4 test"))
put("INBOX", "Møde om ny maskine", "Peter Nielsen <peter@kunde.dk>", text="Kan du torsdag kl. 10?", days=3, seen=True)
put("INBOX", "Velkommen til Classic 7", "Classic 7 <hello@classic7.local>", "<h2 style='color:#1F497D'>Velkommen!</h2><p>Mail er klar.</p>", days=9, seen=True)
c.logout()

import mail_gui
from mail_store import Store
store = Store()
store.save_contact(__import__("mail_store").Contact(full_name="Jens Hansen", first="Jens", last="Hansen", email="jens@example.dk", company="Hansen VVS", phone_mobile="+45 20 30 40 50"))
store.save_contact(__import__("mail_store").Contact(full_name="Mette Kjær", first="Mette", last="Kjær", email="mette@beckhoff.dk", company="Beckhoff Danmark", job_title="Kursuskoordinator", phone_work="+45 43 20 80 00"))
store.save_contact(__import__("mail_store").Contact(full_name="Peter Nielsen", first="Peter", last="Nielsen", email="peter@kunde.dk", phone_work="+45 11 22 33 44", address="Industrivej 4\n7100 Vejle"))
w = mail_gui.MailWindow(store)
w.resize(1280, 800); w.show()

def wait(sec, cond=None):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(QEventLoop.AllEvents, 50)
        if cond and cond(): return True
        time.sleep(0.02)
    return False

def shot(name, widget=None):
    wg = widget or w
    wg.raise_(); wg.activateWindow(); wait(2.5)
    wg.grab().save(f"{OUT}/{name}.png")
    if os.environ.get("DISPLAY"):   # the whole screen too: WebEngine content is drawn by the GPU process
        subprocess.run(["import", "-window", "root", f"{OUT}/{name}-screen.png"])
    print("shot", name, flush=True)

wait(15, lambda: not w.syncing and w.model.messages)
print("folders:", [(f.display_name, f.unread, f.total) for f in store.folders()])
print("status:", w.lbl_status.text(), w.lbl_items.text())
# select first message (the Beckhoff one)
wait(4, lambda: w.reading.parsed is not None)
import mail_view
print("webengine:", mail_view.HAVE_WEBENGINE, flush=True)
print("reading:", w.reading.parsed and w.reading.parsed.subject, "attachments:", [x.name for x in (w.reading.parsed.attachments if w.reading.parsed else [])])
shot("01_main")
# reply
w.respond("reply")
wait(1)
import mail_compose
comp = mail_compose._open[-1]
comp.editor.textCursor().insertText("Tak, det ser godt ud!")
shot("02_reply", comp)
comp.send()
wait(10, lambda: received)
print("received:", [(r[0], r[1], len(r[2])) for r in received])
wait(3)
# new message with attachment
comp2 = mail_compose.Composer(store, handler=w, to="jens", subject="Tegninger")
open(H + "/Tegning.docx", "wb").write(docx); comp2.add_attachment(H + "/Tegning.docx")
comp2.editor.textCursor().insertText("Hej Jens\n\nHer er tegningerne.")
comp2.show(); shot("03_new", comp2)
comp2.send(); wait(10, lambda: len(received) >= 2)
print("received2:", [(r[0], r[1]) for r in received][-1:])
wait(3)
# Sent items
sent = store.folder_by_role(a.id, "sent")
w.select_folder(sent.id); wait(5, lambda: len(w.model.messages) >= 1)
print("sent items:", [m.subject for m in w.model.messages])
shot("04_sent")
# contacts
w.set_module("contacts"); shot("05_contacts")
w.contacts_view.set_mode("phone"); shot("06_phone")
w.set_module("mail")
inbox = store.folder_by_role(a.id, "inbox"); w.select_folder(inbox.id); wait(2)
print("inbox answered:", [(m.subject, m.answered, m.seen) for m in w.model.messages])
# new folder + move (pymap's demo Trash refuses MOVE, so test moving into a new folder)
from PySide6.QtWidgets import QInputDialog
QInputDialog.getText = staticmethod(lambda *a, **k: ("Projekter", True))
w.new_folder(parent_account=a.id); wait(5, lambda: store.folder_by_path(a.id, "Projekter"))
proj = store.folder_by_path(a.id, "Projekter")
w.select_folder(inbox.id); wait(2)
ids = [m.id for m in w.model.messages if "Frokost" in m.subject]
w.move_ids(ids, proj.id); wait(6, lambda: store.messages(proj.id))
print("STATUS:", w.statusBar().currentMessage())
print("after move inbox:", [m.subject for m in store.messages(inbox.id)])
print("projekter:", [m.subject for m in store.messages(proj.id)])
w.select_folder(inbox.id); wait(2); shot("07_folders")
# draft save
comp3 = mail_compose.Composer(store, handler=w, to="peter@kunde.dk", subject="Kladde test")
comp3.editor.textCursor().insertText("udkast"); comp3.save_draft(); wait(6, lambda: comp3.draft_ref is not None)
print("draft:", comp3.draft_ref)
comp3.editor.document().setModified(False); comp3.modified_fields=False; comp3.close()
w.close()
ctl.stop()
print("DONE")
