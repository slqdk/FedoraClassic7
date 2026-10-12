"""Mail: Add New E-mail Account (Auto Account Setup, Microsoft sign-in, manual settings),
Account Settings and Signatures."""
from __future__ import annotations

import socket
import threading
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSpinBox, QStackedWidget, QTextBrowser, QTextEdit,
                               QToolButton, QVBoxLayout, QWidget)

import mail_accounts as acc_mod
import mail_icons as icons
import mail_imap as imap
import mail_oauth as oauth
import mail_send
from mail_worker import Bridge

SECURITY = [("SSL/TLS", "ssl"), ("STARTTLS", "starttls"), ("None", "none")]
GMAIL_HELP = ("Gmail needs an <b>app password</b>, not your normal password: turn on 2-Step Verification, then "
              "create one at <a href=\"https://myaccount.google.com/apppasswords\">myaccount.google.com/apppasswords</a> "
              "and paste the 16 letters here.")
MS_HELP = ("Outlook.com, Hotmail and Live accounts sign in with Microsoft. You don't type your password here: "
           "on the next page Mail shows a code to enter on Microsoft's sign-in page.")


def _title_band(title: str, text: str) -> QWidget:
    w = QFrame()
    w.setStyleSheet("QFrame{background:white;border-bottom:1px solid #A0A0A0}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(12, 8, 12, 8)
    t = QLabel(title)
    f = t.font()
    f.setBold(True)
    t.setFont(f)
    t.setStyleSheet("border:none")
    s = QLabel(text)
    s.setWordWrap(True)
    s.setStyleSheet("border:none;padding-left:12px")
    lay.addWidget(t)
    lay.addWidget(s)
    return w


class StepRow(QWidget):
    def __init__(self, text: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 2, 4, 2)
        self.icon = QLabel()
        self.icon.setFixedWidth(20)
        self.label = QLabel(text)
        lay.addWidget(self.icon)
        lay.addWidget(self.label, 1)
        self.set_state("")

    def set_state(self, state: str):
        sym = {"": "", "busy": "…", "ok": "✔", "fail": "✘"}[state]
        color = {"": "#000", "busy": "#15428B", "ok": "#2C8A2C", "fail": "#C00000"}[state]
        self.icon.setText(f"<span style='color:{color};font-weight:bold;font-size:12pt'>{sym}</span>")
        f = self.label.font()
        f.setBold(state == "busy")
        self.label.setFont(f)


class AccountWizard(QDialog):
    PAGE_AUTO, PAGE_MS, PAGE_RUN, PAGE_MANUAL = range(4)

    def __init__(self, parent=None, account: acc_mod.Account | None = None):
        super().__init__(parent)
        self.editing = account
        self.acc: acc_mod.Account | None = None
        self.bridge = Bridge()
        self.cancel = threading.Event()
        self.history: list[int] = []
        self.setWindowTitle("Change E-mail Account" if account else "Add New E-mail Account")
        self.setWindowIcon(icons.get("account"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self._page_auto()
        self._page_ms()
        self._page_run()
        self._page_manual()
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        lay.addWidget(line)
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 8, 10, 10)
        bar.addStretch(1)
        self.b_back = QPushButton("< &Back")
        self.b_next = QPushButton("&Next >")
        self.b_finish = QPushButton("Finish")
        self.b_cancel = QPushButton("Cancel")
        for b in (self.b_back, self.b_next, self.b_finish, self.b_cancel):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.b_back.clicked.connect(self.back)
        self.b_next.clicked.connect(self.next)
        self.b_finish.clicked.connect(self.finish)
        self.b_cancel.clicked.connect(self.reject)
        self.resize(760, 540)
        if account:
            self._fill_manual(account)
            if account.auth == "oauth-microsoft":
                self.ms_client.setText(account.oauth_client_id)
                self.acc = acc_mod.Account(**account.__dict__)
                self.go(self.PAGE_MS)
            else:
                self.go(self.PAGE_MANUAL)
        else:
            self.go(self.PAGE_AUTO)

    # ---- pages ----------------------------------------------------------------------------
    def _page_auto(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title_band("Auto Account Setup", "Clicking Next will contact your e-mail server and "
                                "configure your account settings."))
        f = QFormLayout()
        f.setContentsMargins(30, 20, 30, 10)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Example: Søren Lyder")
        self.email = QLineEdit()
        self.email.setPlaceholderText("Example: soren@contoso.com")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        f.addRow("&Your Name:", self.name)
        f.addRow("&E-mail Address:", self.email)
        self.pw_label = QLabel("&Password:")
        self.pw_label.setBuddy(self.pw)
        self.pw2_label = QLabel("Re&type Password:")
        self.pw2_label.setBuddy(self.pw2)
        f.addRow(self.pw_label, self.pw)
        f.addRow(self.pw2_label, self.pw2)
        v.addLayout(f)
        self.auto_note = QLabel("Type the password your Internet service provider has given you.")
        self.auto_note.setWordWrap(True)
        self.auto_note.setOpenExternalLinks(True)
        self.auto_note.setContentsMargins(150, 0, 30, 0)
        self.auto_note.setTextFormat(Qt.RichText)
        v.addWidget(self.auto_note)
        v.addStretch(1)
        self.manual = QCheckBox("&Manually configure server settings")
        mrow = QHBoxLayout()
        mrow.setContentsMargins(20, 0, 0, 0)
        mrow.addWidget(self.manual)
        v.addLayout(mrow)
        v.addSpacing(10)
        self.email.textChanged.connect(self._email_changed)
        try:
            import pwd
            import os
            gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0]
            self.name.setText(gecos)
        except Exception:   # noqa: BLE001
            pass
        self.stack.addWidget(w)

    def _email_changed(self, text: str):
        dom = acc_mod.domain_of(text)
        ms = dom in acc_mod.MICROSOFT_DOMAINS
        for wdg in (self.pw, self.pw2, self.pw_label, self.pw2_label):
            wdg.setVisible(not ms)
        if dom in acc_mod.GOOGLE_DOMAINS:
            self.auto_note.setText(GMAIL_HELP)
        elif ms:
            self.auto_note.setText(MS_HELP)
        else:
            self.auto_note.setText("Type the password your Internet service provider has given you.")

    def _page_ms(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title_band("Sign in with Microsoft", "Outlook.com accounts are opened with a Microsoft "
                                "sign-in instead of a password."))
        body = QVBoxLayout()
        body.setContentsMargins(24, 14, 24, 8)
        row = QHBoxLayout()
        self.ms_client = QLineEdit()
        lbl = QLabel("Application (client) &ID:")
        lbl.setBuddy(self.ms_client)
        row.addWidget(lbl)
        self.ms_client.setPlaceholderText("00000000-0000-0000-0000-000000000000")
        row.addWidget(self.ms_client, 1)
        help_b = QToolButton()
        help_b.setText("How do I get one?")
        help_b.setCheckable(True)
        row.addWidget(help_b)
        body.addLayout(row)
        self.ms_help = QTextBrowser()
        self.ms_help.setOpenExternalLinks(True)
        self.ms_help.setHtml(oauth.ENTRA_STEPS)
        self.ms_help.setVisible(False)
        help_b.toggled.connect(self.ms_help.setVisible)
        body.addWidget(self.ms_help, 1)
        self.ms_sign = QPushButton("&Sign in...")
        self.ms_sign.clicked.connect(self._ms_start)
        body.addWidget(self.ms_sign, 0, Qt.AlignLeft)
        self.ms_code_box = QFrame()
        self.ms_code_box.setStyleSheet("QFrame{background:#F3F7FD;border:1px solid #A5BFE1}")
        cb = QVBoxLayout(self.ms_code_box)
        self.ms_text = QLabel()
        self.ms_text.setWordWrap(True)
        self.ms_text.setStyleSheet("border:none")
        self.ms_text.setOpenExternalLinks(True)
        self.ms_code = QLabel()
        f = QFont("Monospace")
        f.setPointSize(20)
        f.setBold(True)
        self.ms_code.setFont(f)
        self.ms_code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ms_code.setStyleSheet("border:none;color:#15428B")
        crow = QHBoxLayout()
        crow.addWidget(self.ms_code)
        self.ms_open = QPushButton("&Copy code and open the sign-in page")
        self.ms_open.clicked.connect(self._ms_open)
        crow.addWidget(self.ms_open)
        crow.addStretch(1)
        cb.addWidget(self.ms_text)
        cb.addLayout(crow)
        self.ms_status = QLabel()
        self.ms_status.setStyleSheet("border:none")
        cb.addWidget(self.ms_status)
        self.ms_code_box.hide()
        body.addWidget(self.ms_code_box)
        body.addStretch(1)
        v.addLayout(body, 1)
        self.stack.addWidget(w)

    def _page_run(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title_band("Online search for your server settings...", "Configuring"))
        v.addSpacing(10)
        self.run_title = QLabel("Configuring e-mail server settings. This might take several minutes:")
        self.run_title.setContentsMargins(20, 0, 20, 6)
        v.addWidget(self.run_title)
        self.steps = [StepRow("Establish network connection"), StepRow("Search for server settings"),
                      StepRow("Log on to the incoming mail server (IMAP)"),
                      StepRow("Log on to the outgoing mail server (SMTP)")]
        for s in self.steps:
            v.addWidget(s)
        v.addSpacing(14)
        self.run_result = QLabel()
        self.run_result.setWordWrap(True)
        self.run_result.setContentsMargins(20, 0, 20, 0)
        self.run_result.setTextFormat(Qt.RichText)
        self.run_result.setOpenExternalLinks(True)
        v.addWidget(self.run_result)
        v.addStretch(1)
        self.run_manual = QCheckBox("&Manually configure server settings")
        mrow = QHBoxLayout()
        mrow.setContentsMargins(20, 0, 0, 10)
        mrow.addWidget(self.run_manual)
        v.addLayout(mrow)
        self.stack.addWidget(w)

    def _page_manual(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title_band("Internet E-mail Settings",
                                "Each of these settings are required to get your e-mail account working."))
        grid = QHBoxLayout()
        grid.setContentsMargins(14, 10, 14, 4)
        left = QVBoxLayout()
        g1 = QGroupBox("User Information")
        f1 = QFormLayout(g1)
        self.m_name = QLineEdit()
        self.m_email = QLineEdit()
        f1.addRow("Your Name:", self.m_name)
        f1.addRow("E-mail Address:", self.m_email)
        left.addWidget(g1)
        g2 = QGroupBox("Server Information")
        f2 = QGridLayout(g2)
        f2.addWidget(QLabel("Account Type:"), 0, 0)
        f2.addWidget(QLabel("IMAP"), 0, 1)
        self.m_in = QLineEdit()
        self.m_in_port = QSpinBox()
        self.m_in_port.setRange(1, 65535)
        self.m_in_sec = QComboBox()
        self.m_out = QLineEdit()
        self.m_out_port = QSpinBox()
        self.m_out_port.setRange(1, 65535)
        self.m_out_sec = QComboBox()
        for c in (self.m_in_sec, self.m_out_sec):
            for label, key in SECURITY:
                c.addItem(label, key)
        f2.addWidget(QLabel("Incoming mail server:"), 1, 0)
        f2.addWidget(self.m_in, 1, 1)
        f2.addWidget(self.m_in_port, 1, 2)
        f2.addWidget(self.m_in_sec, 1, 3)
        f2.addWidget(QLabel("Outgoing mail server (SMTP):"), 2, 0)
        f2.addWidget(self.m_out, 2, 1)
        f2.addWidget(self.m_out_port, 2, 2)
        f2.addWidget(self.m_out_sec, 2, 3)
        f2.setColumnStretch(1, 1)
        for e in (self.m_in, self.m_out):
            e.setMinimumWidth(170)
        for sp in (self.m_in_port, self.m_out_port):
            sp.setFixedWidth(68)
        self.m_in_sec.currentIndexChanged.connect(lambda: self._default_port(self.m_in_sec, self.m_in_port, 993, 143))
        self.m_out_sec.currentIndexChanged.connect(lambda: self._default_port(self.m_out_sec, self.m_out_port, 465, 587))
        left.addWidget(g2)
        g3 = QGroupBox("Logon Information")
        f3 = QFormLayout(g3)
        self.m_user = QLineEdit()
        self.m_pw = QLineEdit()
        self.m_pw.setEchoMode(QLineEdit.Password)
        self.m_pw.setPlaceholderText("(unchanged)" if self.editing else "")
        self.m_smtp_auth = QCheckBox("My outgoing server (SMTP) requires authentication")
        self.m_smtp_auth.setChecked(True)
        self.m_smtp_user = QLineEdit()
        self.m_smtp_user.setPlaceholderText("same as above")
        f3.addRow("User Name:", self.m_user)
        f3.addRow("Password:", self.m_pw)
        f3.addRow(self.m_smtp_auth)
        f3.addRow("SMTP user name:", self.m_smtp_user)
        left.addWidget(g3)
        grid.addLayout(left, 3)
        right = QVBoxLayout()
        g4 = QGroupBox("Test Account Settings")
        f4 = QVBoxLayout(g4)
        t = QLabel("After filling out the information on this screen, we recommend you test your account by "
                   "clicking the button below. (Requires network connection)")
        t.setWordWrap(True)
        f4.addWidget(t)
        self.m_test = QPushButton("&Test Account Settings ...")
        self.m_test.clicked.connect(self._manual_test)
        f4.addWidget(self.m_test)
        self.m_test_result = QLabel()
        self.m_test_result.setWordWrap(True)
        f4.addWidget(self.m_test_result)
        f4.addStretch(1)
        right.addWidget(g4)
        g5 = QGroupBox("More Settings")
        f5 = QFormLayout(g5)
        self.m_acc_name = QLineEdit()
        self.m_acc_name.setPlaceholderText("shown in the folder list")
        self.m_check = QSpinBox()
        self.m_check.setRange(0, 240)
        self.m_check.setSuffix(" min")
        self.m_check.setSpecialValueText("never")
        self.m_reply = QLineEdit()
        self.m_save_sent = QCheckBox("Save sent items in the Sent folder")
        f5.addRow("Account name:", self.m_acc_name)
        f5.addRow("Check every:", self.m_check)
        f5.addRow("Reply e-mail:", self.m_reply)
        f5.addRow(self.m_save_sent)
        right.addWidget(g5)
        grid.addLayout(right, 2)
        v.addLayout(grid, 1)
        self.stack.addWidget(w)

    @staticmethod
    def _default_port(combo, spin, ssl_port, plain_port):
        key = combo.currentData()
        if key == "ssl" and spin.value() in (143, 587, 25):
            spin.setValue(ssl_port)
        elif key != "ssl" and spin.value() in (993, 465):
            spin.setValue(plain_port)

    def _fill_manual(self, a: acc_mod.Account):
        self.m_name.setText(a.display_name)
        self.m_email.setText(a.email)
        self.m_in.setText(a.imap_host)
        self.m_in_port.setValue(a.imap_port)
        self.m_in_sec.setCurrentIndex([k for _l, k in SECURITY].index(a.imap_security))
        self.m_out.setText(a.smtp_host)
        self.m_out_port.setValue(a.smtp_port)
        self.m_out_sec.setCurrentIndex([k for _l, k in SECURITY].index(a.smtp_security))
        self.m_user.setText(a.username or a.email)
        self.m_smtp_user.setText(a.smtp_username)
        self.m_smtp_auth.setChecked(a.smtp_auth)
        self.m_acc_name.setText(a.name)
        self.m_check.setValue(a.check_minutes)
        self.m_reply.setText(a.reply_address)
        self.m_save_sent.setChecked(a.save_sent)
        is_oauth = a.auth == "oauth-microsoft"
        self.m_pw.setEnabled(not is_oauth)
        if is_oauth:
            self.m_pw.setPlaceholderText("Microsoft sign-in")

    def _manual_account(self) -> acc_mod.Account:
        base = self.acc or self.editing or acc_mod.Account()
        a = acc_mod.Account(**{**base.__dict__})
        a.display_name = self.m_name.text().strip()
        a.email = self.m_email.text().strip()
        a.imap_host = self.m_in.text().strip()
        a.imap_port = self.m_in_port.value()
        a.imap_security = self.m_in_sec.currentData()
        a.smtp_host = self.m_out.text().strip()
        a.smtp_port = self.m_out_port.value()
        a.smtp_security = self.m_out_sec.currentData()
        a.username = self.m_user.text().strip() or a.email
        a.smtp_username = self.m_smtp_user.text().strip()
        a.smtp_auth = self.m_smtp_auth.isChecked()
        a.name = self.m_acc_name.text().strip() or a.email
        a.check_minutes = self.m_check.value()
        a.reply_address = self.m_reply.text().strip()
        a.save_sent = self.m_save_sent.isChecked()
        return a

    # ---- navigation -----------------------------------------------------------------------
    def go(self, page: int, remember=True):
        cur = self.stack.currentIndex()
        if remember and self.stack.count() and cur != page and self.isVisible():
            self.history.append(cur)
        self.stack.setCurrentIndex(page)
        self.b_back.setEnabled(bool(self.history))
        self.b_finish.setVisible(False)
        self.b_next.setVisible(True)
        self.b_next.setEnabled(True)
        if page == self.PAGE_MANUAL:
            self.b_next.setText("&Next >")
        if page == self.PAGE_MS:
            self.b_next.setEnabled(False)

    def back(self):
        self.cancel.set()
        if self.history:
            self.go(self.history.pop(), remember=False)
            self.b_back.setEnabled(bool(self.history))

    def next(self):
        page = self.stack.currentIndex()
        if page == self.PAGE_AUTO:
            self._auto_next()
        elif page == self.PAGE_RUN:
            if self.run_manual.isChecked():
                if self.acc:
                    self._fill_manual(self.acc)
                self.go(self.PAGE_MANUAL)
        elif page == self.PAGE_MANUAL:
            a = self._manual_account()
            if not acc_mod.valid_email(a.email) or not a.imap_host or not a.smtp_host:
                QMessageBox.information(self, self.windowTitle(), "Fill in the e-mail address and both server names.")
                return
            self.acc = a
            pw = self.m_pw.text()
            if pw or a.auth != "password" or not self.editing:
                self._run_tests(a, pw if a.auth == "password" else None, skip_search=True)
            else:
                self._run_tests(a, None, skip_search=True)

    def _auto_next(self):
        email = self.email.text().strip()
        if not acc_mod.valid_email(email):
            QMessageBox.information(self, self.windowTitle(), "Type a valid e-mail address, like soren@contoso.com.")
            return
        ms = acc_mod.domain_of(email) in acc_mod.MICROSOFT_DOMAINS
        if not ms and self.pw.text() != self.pw2.text():
            QMessageBox.information(self, self.windowTitle(), "The passwords don't match. Type them again.")
            return
        if self.manual.isChecked():
            a, _src = acc_mod.autodetect(email, online=False)
            a.display_name = self.name.text().strip()
            self.acc = a
            self._fill_manual(a)
            self.m_pw.setText(self.pw.text())
            self.go(self.PAGE_MANUAL)
            return
        if ms:
            self.acc = acc_mod.microsoft_preset(email)
            self.acc.display_name = self.name.text().strip()
            self.go(self.PAGE_MS)
            return
        self._run_tests(None, self.pw.text(), skip_search=False)

    # ---- Microsoft sign-in --------------------------------------------------------------------
    def _ms_start(self):
        cid = self.ms_client.text().strip()
        if len(cid) < 30:
            QMessageBox.information(self, self.windowTitle(), "Paste the Application (client) ID first "
                                    "(click \"How do I get one?\").")
            return
        self.cancel = threading.Event()
        cancel = self.cancel
        tenant = self.acc.oauth_tenant if self.acc else "consumers"
        self.ms_sign.setEnabled(False)
        self.ms_status.setText("Contacting Microsoft...")
        self.ms_code_box.show()

        def work():
            try:
                flow = oauth.start_device_code(cid, tenant)
                self.bridge.post(lambda: self._ms_show(flow))
                tokens = oauth.wait_device_code(cid, flow, tenant, cancel)
                self.bridge.post(lambda: self._ms_done(cid, tokens))
            except oauth.OAuthError as e:
                if not cancel.is_set():
                    self.bridge.post(lambda m=str(e): self._ms_fail(m))

        threading.Thread(target=work, daemon=True).start()

    def _ms_show(self, flow):
        self.flow = flow
        self.ms_text.setText(f"Go to <a href=\"{flow['verification_uri']}\">{flow['verification_uri']}</a>, enter "
                             "this code and sign in with your Microsoft account. Then allow Classic 7 Mail to "
                             "read and send your mail.")
        self.ms_code.setText(flow["user_code"])
        self.ms_status.setText("Waiting for you to sign in...")

    def _ms_open(self):
        if getattr(self, "flow", None):
            QGuiApplication.clipboard().setText(self.flow["user_code"])
            webbrowser.open(self.flow["verification_uri"])

    def _ms_fail(self, msg):
        self.ms_status.setText(f"<span style='color:#C00000'>{msg}</span>")
        self.ms_sign.setEnabled(True)

    def _ms_done(self, cid, tokens):
        a = self.acc or acc_mod.microsoft_preset(self.email.text().strip())
        a.oauth_client_id = cid
        a.auth = "oauth-microsoft"
        if not a.id:
            a.id = acc_mod.new_id()
        oauth.store_tokens(a.id, tokens)
        self.acc = a
        self.ms_status.setText("<span style='color:#2C8A2C'>Signed in.</span>")
        self.ms_sign.setEnabled(True)
        self._run_tests(a, None, skip_search=True)

    # ---- testing ------------------------------------------------------------------------------
    def _run_tests(self, acc, password, skip_search):
        self.go(self.PAGE_RUN)
        self.b_next.setEnabled(False)
        self.b_back.setEnabled(True)
        self.run_result.setText("")
        self.run_manual.setChecked(False)
        for s in self.steps:
            s.set_state("")
        self.cancel = threading.Event()
        cancel = self.cancel
        email = self.email.text().strip() if acc is None else acc.email
        name = self.name.text().strip()
        temp_id = (acc.id if acc and acc.id else acc_mod.new_id())

        def post(fn):
            if not cancel.is_set():
                self.bridge.post(fn)

        def work():
            a = acc
            step = 0
            try:
                post(lambda: self.steps[0].set_state("busy"))
                host = acc.imap_host if acc else "autoconfig.thunderbird.net"
                try:
                    socket.getaddrinfo(host, None)
                except OSError:
                    socket.getaddrinfo("autoconfig.thunderbird.net", None)
                post(lambda: self.steps[0].set_state("ok"))
                step = 1
                post(lambda: self.steps[1].set_state("busy"))
                if not skip_search:
                    a, _src = acc_mod.autodetect(email)
                    a.display_name = name
                post(lambda: self.steps[1].set_state("ok"))
                a.id = a.id or temp_id
                if password is not None:
                    acc_mod.set_secret(a.id, "password", password)
                step = 2
                post(lambda: self.steps[2].set_state("busy"))
                imap.test_account(a)
                post(lambda: self.steps[2].set_state("ok"))
                step = 3
                post(lambda: self.steps[3].set_state("busy"))
                mail_send.test_smtp(a)
                post(lambda: self.steps[3].set_state("ok"))
                post(lambda: self._tests_ok(a))
            except Exception as e:   # noqa: BLE001
                msg = str(e) or type(e).__name__
                post(lambda st=step, m=msg, acc_=a: self._tests_failed(st, m, acc_))

        threading.Thread(target=work, daemon=True).start()

    def _tests_ok(self, a):
        self.acc = a
        self.run_result.setText("<b>Congratulations!</b> Your e-mail account is successfully configured and "
                                "ready to use.")
        self.run_manual.setVisible(True)
        self.b_next.setVisible(False)
        self.b_finish.setVisible(True)
        self.b_finish.setDefault(True)

    def _tests_failed(self, step, msg, a):
        if a is not None:
            self.acc = a
        self.steps[step].set_state("fail")
        hint = ""
        if a is not None and a.provider == "gmail" and step == 2:
            hint = "<br><br>" + GMAIL_HELP
        self.run_result.setText(f"<span style='color:#C00000'><b>Problem:</b> {msg}</span>{hint}<br><br>"
                                "Check the settings and try again, or tick <i>Manually configure server settings</i> "
                                "and click Next.")
        self.run_manual.setChecked(True)
        self.b_next.setEnabled(True)
        if step >= 3 and a is not None:
            # incoming works: allow finishing anyway (sending can be fixed later)
            self.b_finish.setVisible(True)
            self.b_finish.setText("Finish anyway")

    def _manual_test(self):
        a = self._manual_account()
        a.id = a.id or acc_mod.new_id()
        self.acc = a
        pw = self.m_pw.text()
        if pw and a.auth == "password":
            acc_mod.set_secret(a.id, "password", pw)
        self.m_test.setEnabled(False)
        self.m_test_result.setText("Testing...")

        def work():
            out = []
            try:
                imap.test_account(a)
                out.append("✔ Log on to incoming mail server (IMAP)")
            except Exception as e:   # noqa: BLE001
                out.append(f"✘ Incoming: {e}")
            try:
                mail_send.test_smtp(a)
                out.append("✔ Log on to outgoing mail server (SMTP)")
            except Exception as e:   # noqa: BLE001
                out.append(f"✘ Outgoing: {e}")
            self.bridge.post(lambda: (self.m_test_result.setText("\n".join(out)), self.m_test.setEnabled(True)))

        threading.Thread(target=work, daemon=True).start()

    def finish(self):
        a = self.acc
        if a is None:
            return
        if self.stack.currentIndex() == self.PAGE_MANUAL:
            a = self._manual_account()
            a.id = a.id or acc_mod.new_id()
            if self.m_pw.text() and a.auth == "password":
                acc_mod.set_secret(a.id, "password", self.m_pw.text())
        if not a.name:
            a.name = a.email
        if self.editing:
            a.default = self.editing.default
        acc_mod.upsert(a)
        self.acc = a
        self.accept()

    def reject(self):
        self.cancel.set()
        super().reject()


def add_account_wizard(parent=None) -> acc_mod.Account | None:
    w = AccountWizard(parent)
    return w.acc if w.exec() else None


class AccountSettings(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Account Settings")
        self.setWindowIcon(icons.get("account"))
        lay = QVBoxLayout(self)
        lay.addWidget(_title_band("E-mail Accounts", "You can add or remove an account. You can select an account "
                                  "and change its settings."))
        bar = QHBoxLayout()
        self.b_new = QToolButton()
        self.b_new.setText("New...")
        self.b_change = QToolButton()
        self.b_change.setText("Change...")
        self.b_default = QToolButton()
        self.b_default.setText("Set as Default")
        self.b_remove = QToolButton()
        self.b_remove.setText("Remove")
        for b, ic in ((self.b_new, "new"), (self.b_change, "account"), (self.b_default, "flag-done"),
                      (self.b_remove, "delete")):
            b.setIcon(icons.get(ic))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.note = QLabel()
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.b_new.clicked.connect(self._new)
        self.b_change.clicked.connect(self._change)
        self.list.itemDoubleClicked.connect(lambda *_: self._change())
        self.b_default.clicked.connect(self._default)
        self.b_remove.clicked.connect(self._remove)
        self.fill()
        self.resize(600, 380)

    def fill(self):
        self.list.clear()
        for a in acc_mod.load():
            kind = "IMAP/SMTP" + (" (Microsoft sign-in)" if a.auth == "oauth-microsoft" else "")
            text = f"{a.name or a.email}    —    {kind}" + ("    (send from this account by default)" if a.default else "")
            it = QListWidgetItem(icons.get("account"), text)
            it.setData(Qt.UserRole, a.id)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.note.setText("Selected e-mail account delivers new messages to its own folders.")

    def _sel(self):
        it = self.list.currentItem()
        return acc_mod.get(it.data(Qt.UserRole)) if it else None

    def _new(self):
        if add_account_wizard(self):
            self.fill()

    def _change(self):
        a = self._sel()
        if a and AccountWizard(self, a).exec():
            self.fill()

    def _default(self):
        a = self._sel()
        if a:
            a.default = True
            acc_mod.upsert(a)
            self.fill()

    def _remove(self):
        a = self._sel()
        if a and QMessageBox.question(self, "Account Settings", f"Remove the account \"{a.name or a.email}\"? "
                                      "Its messages are removed from this computer (they stay on the server).") \
                == QMessageBox.Yes:
            if a.auth == "oauth-microsoft":
                oauth.forget(a.id)
            acc_mod.remove(a.id)
            self.fill()


class SignaturesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Signatures and Stationery")
        self.setWindowIcon(icons.get("signature"))
        self.accounts = acc_mod.load()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("E-mail &account:"))
        self.combo = QComboBox()
        for a in self.accounts:
            self.combo.addItem(a.name or a.email, a.id)
        row.addWidget(self.combo, 1)
        lay.addLayout(row)
        tools = QHBoxLayout()
        self.edit = QTextEdit()
        self.edit.setAcceptRichText(True)
        for text, fn in (("B", lambda: self._toggle("bold")), ("I", lambda: self._toggle("italic")),
                         ("U", lambda: self._toggle("underline"))):
            b = QToolButton()
            b.setText(text)
            b.clicked.connect(fn)
            tools.addWidget(b)
        tools.addStretch(1)
        lay.addWidget(QLabel("Edi&t signature:"))
        lay.addLayout(tools)
        lay.addWidget(self.edit, 1)
        self.new_cb = QCheckBox("Add to &new messages")
        self.reply_cb = QCheckBox("Add to &replies and forwards")
        lay.addWidget(self.new_cb)
        lay.addWidget(self.reply_cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.current = None
        self.combo.currentIndexChanged.connect(self._load)
        self._load()
        self.resize(560, 420)

    def _toggle(self, what):
        c = self.edit.textCursor()
        f = c.charFormat()
        if what == "bold":
            f.setFontWeight(QFont.Normal if f.fontWeight() > QFont.Normal else QFont.Bold)
        elif what == "italic":
            f.setFontItalic(not f.fontItalic())
        else:
            f.setFontUnderline(not f.fontUnderline())
        c.mergeCharFormat(f)
        self.edit.mergeCurrentCharFormat(f)

    def _stash(self):
        if self.current is not None:
            a = self.current
            a.signature = self.edit.toHtml() if self.edit.toPlainText().strip() else ""
            a.extra["sig_new"] = self.new_cb.isChecked()
            a.extra["sig_reply"] = self.reply_cb.isChecked()

    def _load(self):
        self._stash()
        aid = self.combo.currentData()
        self.current = next((a for a in self.accounts if a.id == aid), None)
        if self.current:
            self.edit.setHtml(self.current.signature)
            self.new_cb.setChecked(self.current.extra.get("sig_new", True))
            self.reply_cb.setChecked(self.current.extra.get("sig_reply", True))

    def _save(self):
        self._stash()
        acc_mod.save(self.accounts)
        self.accept()
