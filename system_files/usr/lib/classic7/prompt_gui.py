"""Command Prompt: a terminal with a built-in assistant that uses your local language model."""
from __future__ import annotations

import html
import os
import re
import shlex
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QKeySequence, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSizePolicy, QSpinBox, QSplitter, QTextBrowser, QToolButton, QVBoxLayout, QWidget)

import prompt_llm as llm
import prompt_recipes as recipes
import prompt_safety as safety
from prompt_term import TerminalWidget

APP_NAME = "Command Prompt"
RISK_STYLE = {
    safety.SAFE: ("Safe", "#ffffff", "#2e7d32"),
    safety.CAUTION: ("Caution", "#000000", "#f0b400"),
    safety.DANGER: ("DANGER", "#ffffff", "#c00000"),
}


def banner() -> bytes:
    rel = llm._os_release()
    version = rel.get("VERSION", rel.get("VERSION_ID", ""))
    lines = [
        f"FedoraClassic7 [Version {version}]".rstrip(),
        "Type a command, or ask the assistant below in plain words (Danish or English).",
        "",
    ]
    return ("\r\n".join(lines) + "\r\n").encode()


class Worker(QObject):
    """Runs one assistant request in a thread; signals arrive in the GUI thread."""
    chunk = Signal(str)
    suggestion = Signal(dict)
    explained = Signal(str)
    failed = Signal(str)
    models = Signal(list)

    def __init__(self, settings: llm.Settings):
        super().__init__()
        self.client = llm.Client(settings)

    def _run(self, fn):
        def target():
            try:
                fn()
            except llm.LLMError as e:
                self.failed.emit(str(e))
            except Exception as e:  # noqa: BLE001
                self.failed.emit(f"{type(e).__name__}: {e}")
        threading.Thread(target=target, daemon=True).start()

    def suggest(self, request, cwd, history):
        self._run(lambda: self.suggestion.emit(self.client.suggest(request, cwd, history)))

    def explain(self, output, command, cwd, question=None):
        self._run(lambda: self.explained.emit(
            self.client.explain(output, command, cwd, question, on_chunk=self.chunk.emit)))

    def list_models(self):
        self._run(lambda: self.models.emit(self.client.list_models()))

    def cancel(self):
        self.client.cancelled = True


# ------------------------------------------------------------------------------------------
# Settings dialog
# ------------------------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, settings: llm.Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assistant Settings")
        self.settings = settings
        form = QFormLayout()

        self.server = QLineEdit(settings.server)
        self.server.setPlaceholderText("http://30.11.0.104:11434")
        form.addRow("&Server address:", self.server)

        self.api = QComboBox()
        self.api.addItem("Ollama", "ollama")
        self.api.addItem("OpenAI-compatible (llama.cpp, LM Studio, vLLM)", "openai")
        self.api.setCurrentIndex(max(0, self.api.findData(settings.api)))
        form.addRow("&Type:", self.api)

        self.key = QLineEdit(settings.api_key)
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("only if the server needs one")
        form.addRow("API &key:", self.key)

        row = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItem("(automatic)", "")
        if settings.model:
            self.model.addItem(settings.model, settings.model)
            self.model.setCurrentIndex(1)
        self.model.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        refresh = QPushButton("&Refresh list")
        refresh.clicked.connect(self.refresh_models)
        row.addWidget(self.model)
        row.addWidget(refresh)
        form.addRow("&Model:", row)

        self.language = QComboBox()
        for label, code in (("Same as my question", "auto"), ("Dansk", "da"), ("English", "en")):
            self.language.addItem(label, code)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        form.addRow("Answer &language:", self.language)

        self.font_size = QSpinBox()
        self.font_size.setRange(6, 40)
        self.font_size.setValue(settings.font_size)
        form.addRow("Terminal &font size:", self.font_size)

        self.status = QLabel(" ")
        self.status.setWordWrap(True)
        test = QPushButton("&Test connection")
        test.clicked.connect(self.refresh_models)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(test)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        box = QVBoxLayout(self)
        intro = QLabel("Command Prompt asks your own language model server. Nothing leaves your network.")
        intro.setWordWrap(True)
        box.addWidget(intro)
        box.addLayout(form)
        box.addWidget(self.status)
        box.addLayout(bottom)
        self.resize(520, 0)

    def current(self) -> llm.Settings:
        s = llm.Settings(**{**self.settings.__dict__})
        s.server = llm.normalize_server(self.server.text())
        s.api = self.api.currentData()
        s.api_key = self.key.text().strip()
        text = self.model.currentText().strip()
        s.model = "" if text in ("", "(automatic)") else text
        s.language = self.language.currentData()
        s.font_size = self.font_size.value()
        return s

    def refresh_models(self):
        self.status.setText("Connecting...")
        self._worker = Worker(self.current())
        self._worker.models.connect(self._got_models)
        self._worker.failed.connect(lambda msg: self.status.setText(f"<span style='color:#c00000'>{html.escape(msg)}</span>"))
        self._worker.list_models()

    def _got_models(self, models):
        keep = self.model.currentText()
        self.model.clear()
        self.model.addItem("(automatic)", "")
        for m in models:
            self.model.addItem(m, m)
        i = self.model.findText(keep)
        self.model.setCurrentIndex(i if i >= 0 else 0)
        self.status.setText(f"<span style='color:#2e7d32'>Connected. {len(models)} model(s) on the server.</span>")


# ------------------------------------------------------------------------------------------
# Assistant panel
# ------------------------------------------------------------------------------------------

class AssistantPanel(QFrame):
    runRequested = Signal(str)
    insertRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(5)

        ask_row = QHBoxLayout()
        label = QLabel("&What do you want to do?")
        self.input = QLineEdit()
        self.input.setPlaceholderText("e.g.  how much space is free  /  installer VLC  /  hvorfor kan jeg ikke se min USB-nøgle")
        self.input.setClearButtonEnabled(True)
        label.setBuddy(self.input)
        self.ask_btn = QPushButton("&Ask")
        self.ask_btn.setDefault(True)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.hide()
        self.tasks_btn = QToolButton()
        self.tasks_btn.setText("&Tasks")
        self.tasks_btn.setPopupMode(QToolButton.InstantPopup)
        self.tasks_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        ask_row.addWidget(label)
        ask_row.addWidget(self.input, 1)
        ask_row.addWidget(self.ask_btn)
        ask_row.addWidget(self.stop_btn)
        ask_row.addWidget(self.tasks_btn)
        lay.addLayout(ask_row)

        # suggested command
        self.cmd_frame = QFrame()
        cmd_row = QHBoxLayout(self.cmd_frame)
        cmd_row.setContentsMargins(0, 0, 0, 0)
        self.risk = QLabel()
        self.risk.setAlignment(Qt.AlignCenter)
        self.risk.setMinimumWidth(70)
        self.command = QLineEdit()
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(max(9, mono.pointSize()))
        self.command.setFont(mono)
        self.command.setToolTip("You can edit the command before running it")
        self.run_btn = QPushButton("&Run")
        self.insert_btn = QPushButton("&Insert")
        self.insert_btn.setToolTip("Type it into the terminal without pressing Enter")
        self.copy_btn = QPushButton("&Copy")
        cmd_row.addWidget(self.risk)
        cmd_row.addWidget(self.command, 1)
        cmd_row.addWidget(self.run_btn)
        cmd_row.addWidget(self.insert_btn)
        cmd_row.addWidget(self.copy_btn)
        lay.addWidget(self.cmd_frame)
        self.cmd_frame.hide()

        self.answer = QTextBrowser()
        self.answer.setOpenLinks(False)
        self.answer.setMinimumHeight(60)
        self.answer.setPlaceholderText("The assistant's explanation appears here. Right-click text in the terminal "
                                       "and choose \"Explain\" to have an error explained.")
        lay.addWidget(self.answer, 1)

        self.command.textChanged.connect(self._rerate)
        self.run_btn.clicked.connect(lambda: self.runRequested.emit(self.command.text().strip()))
        self.insert_btn.clicked.connect(lambda: self.insertRequested.emit(self.command.text().strip()))
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.command.text().strip()))
        self.model_risk = "safe"

    def show_command(self, command: str, model_risk: str = "safe"):
        self.model_risk = model_risk
        self.command.setText(command)
        self.cmd_frame.setVisible(bool(command))
        if command:
            self._select_placeholder()

    def _select_placeholder(self):
        m = re.search(r"<[^<>]+>", self.command.text())
        if m:
            self.command.setFocus()
            self.command.setSelection(m.start(), m.end() - m.start())

    def current_risk(self) -> safety.Risk:
        return safety.combine(self.command.text(), self.model_risk)

    def _rerate(self):
        risk = self.current_risk()
        text, fg, bg = RISK_STYLE[risk.level]
        self.risk.setText(text)
        self.risk.setStyleSheet(f"QLabel {{ color: {fg}; background: {bg}; font-weight: bold; padding: 2px 6px; }}")
        self.risk.setToolTip("\n".join(risk.reasons) or "Only reads information")

    def set_busy(self, busy: bool):
        self.ask_btn.setVisible(not busy)
        self.stop_btn.setVisible(busy)
        self.input.setEnabled(not busy)


# ------------------------------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------------------------------

class PromptWindow(QMainWindow):
    def __init__(self, argv=None, cwd=None, hold=False):
        super().__init__()
        self.settings = llm.Settings.load()
        self.hold = hold
        self.history: list[str] = []
        self.worker: Worker | None = None
        self.streamed = ""
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon.fromTheme("utilities-terminal"))

        self.term = TerminalWidget(argv, cwd, self.settings.font_size)
        self.term.stream.feed(banner())
        self.term.titleChanged.connect(lambda t: self.setWindowTitle(f"{APP_NAME} - {t}" if t else APP_NAME))
        self.term.finished.connect(self._shell_finished)
        self.term.setContextMenuPolicy(Qt.CustomContextMenu)
        self.term.customContextMenuRequested.connect(self._term_menu)

        self.panel = AssistantPanel()
        self.panel.ask_btn.clicked.connect(self.ask)
        self.panel.input.returnPressed.connect(self.ask)
        self.panel.stop_btn.clicked.connect(self.stop)
        self.panel.runRequested.connect(self.run_suggested)
        self.panel.insertRequested.connect(self.insert_suggested)
        self.panel.tasks_btn.setMenu(self._tasks_menu())
        self.panel.answer.anchorClicked.connect(self._answer_link)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.term)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        self.split = split
        self.setCentralWidget(split)
        self._menus()
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self._update_status()
        self.resize(self.term.sizeHint().width(), self.term.sizeHint().height() + 230)
        split.setSizes([self.term.sizeHint().height(), 200])
        self.term.setFocus()

    # -- menus -----------------------------------------------------------------------------
    def _act(self, menu, text, slot, shortcut=None, icon=None):
        a = QAction(text, self)
        if icon:
            a.setIcon(QIcon.fromTheme(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WindowShortcut)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._act(f, "&New Window", self.new_window, "Ctrl+Shift+N", "window-new")
        self._act(f, "Open &Konsole Here", self.open_konsole, None, "utilities-terminal")
        f.addSeparator()
        self._act(f, "&Close", self.close, "Ctrl+Shift+W", "window-close")

        e = mb.addMenu("&Edit")
        self._act(e, "&Copy", self.copy, "Ctrl+Shift+C", "edit-copy")
        self._act(e, "&Paste", self.paste, "Ctrl+Shift+V", "edit-paste")
        e.addSeparator()
        self._act(e, "Clear &Screen", lambda: self.term.run_command("clear"), None, "edit-clear")

        v = mb.addMenu("&View")
        self._act(v, "&Bigger Text", lambda: self.term.zoom(+1), "Ctrl++", "zoom-in")
        self._act(v, "&Smaller Text", lambda: self.term.zoom(-1), "Ctrl+-", "zoom-out")
        self.toggle_panel = self._act(v, "&Assistant", self._toggle_panel, "F9")
        self.toggle_panel.setCheckable(True)
        self.toggle_panel.setChecked(True)

        a = mb.addMenu("&Assistant")
        self._act(a, "&Ask...", self.focus_ask, "Ctrl+Shift+A", "help-contextual")
        self._act(a, "&Explain Selection", self.explain_selection, "Ctrl+Shift+E", "help-hint")
        self._act(a, "Explain &Last Output", self.explain_last, "Ctrl+Shift+L")
        a.addSeparator()
        self._act(a, "&Settings...", self.open_settings, None, "configure")

        h = mb.addMenu("&Help")
        self._act(h, "&Keyboard Shortcuts", self.show_shortcuts, "F1", "help-keyboard-shortcuts")
        self._act(h, "&About Command Prompt", self.show_about, None, "help-about")

    def _tasks_menu(self) -> QMenu:
        menu = QMenu(self)
        for group, items in recipes.groups().items():
            sub = menu.addMenu(group)
            for r in items:
                act = sub.addAction(r.title)
                act.setToolTip(r.command)
                act.triggered.connect(lambda _=False, r=r: self.use_recipe(r))
        menu.setToolTipsVisible(True)
        return menu

    def _term_menu(self, pos):
        menu = QMenu(self)
        sel = self.term.selected_text()
        a = menu.addAction(QIcon.fromTheme("edit-copy"), "Copy")
        a.setEnabled(bool(sel))
        a.triggered.connect(lambda: QGuiApplication.clipboard().setText(sel))
        menu.addAction(QIcon.fromTheme("edit-paste"), "Paste",
                       lambda: self.term.paste(QGuiApplication.clipboard().text()))
        menu.addSeparator()
        ex = menu.addAction(QIcon.fromTheme("help-hint"), "Explain Selection")
        ex.setEnabled(bool(sel))
        ex.triggered.connect(self.explain_selection)
        menu.addAction("Explain Last Output", self.explain_last)
        if sel:
            menu.addAction("Ask About Selection...", lambda: self.focus_ask(f'About "{sel[:200]}": '))
        menu.addSeparator()
        menu.addAction("Clear Screen", lambda: self.term.run_command("clear"))
        menu.exec(self.term.mapToGlobal(pos))

    def copy(self):
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit, QTextBrowser)) and w is not self.term:
            w.copy()
        else:
            QGuiApplication.clipboard().setText(self.term.selected_text())

    def paste(self):
        w = QApplication.focusWidget()
        if isinstance(w, QLineEdit):
            w.paste()
        else:
            self.term.paste(QGuiApplication.clipboard().text())

    # -- status ------------------------------------------------------------------------------
    def _update_status(self, state: str = ""):
        model = self.settings.model or "automatic model"
        host = re.sub(r"^https?://", "", self.settings.server)
        self.status.setText(f"Assistant: {model} on {host}" + (f"  -  {state}" if state else ""))

    # -- asking ------------------------------------------------------------------------------
    def focus_ask(self, prefill: str | None = None):
        if not self.panel.isVisible():
            self._toggle_panel()
        if isinstance(prefill, str):
            self.panel.input.setText(prefill)
        self.panel.input.setFocus()
        self.panel.input.end(False)

    def _new_worker(self) -> Worker:
        if self.worker:
            self.worker.cancel()
        w = Worker(self.settings)
        w.chunk.connect(self._chunk)
        w.suggestion.connect(self._got_suggestion)
        w.explained.connect(self._got_explanation)
        w.failed.connect(self._failed)
        self.worker = w
        return w

    def ask(self):
        request = self.panel.input.text().strip()
        if not request:
            return
        self.last_request = request
        self.streamed = ""
        self.panel.set_busy(True)
        self.panel.show_command("")
        self.panel.answer.setHtml("<i>Thinking...</i>")
        self._update_status("thinking")
        self._new_worker().suggest(request, self.term.shell_cwd(), self.history)

    def stop(self):
        if self.worker:
            self.worker.cancel()
            self.worker = None
        self.panel.set_busy(False)
        self._update_status("stopped")

    def _chunk(self, text):
        if self.sender() is not self.worker:
            return
        self.streamed += text
        self.panel.answer.setPlainText(self.streamed)
        bar = self.panel.answer.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _got_suggestion(self, sug: dict):
        if self.sender() is not self.worker:
            return
        self.panel.set_busy(False)
        self._update_status("ready")
        command, explanation = sug.get("command", ""), sug.get("explanation", "")
        self.panel.show_command(command, sug.get("risk", "caution"))
        text = explanation or ("" if command else "The assistant had no command for that.")
        risk = self.panel.current_risk()
        if command and risk.reasons:
            text += "\n\n**Note:** " + "; ".join(risk.reasons) + "."
        self.panel.answer.setMarkdown(text)
        if command and "<" not in command:
            self.panel.run_btn.setFocus()

    def _got_explanation(self, text: str):
        if self.sender() is not self.worker:
            return
        self.panel.set_busy(False)
        self._update_status("ready")
        self.panel.answer.setMarkdown(text)
        blocks = re.findall(r"```(?:bash|sh|console)?\s*\n(.+?)```", text, re.S)
        if blocks:
            first = blocks[0].strip().splitlines()[0].lstrip("$ ").strip()
            self.panel.show_command(first, "caution")

    def _failed(self, message: str):
        if self.sender() is not self.worker:
            return
        self.panel.set_busy(False)
        self._update_status("offline")
        request = getattr(self, "last_request", "")
        found = recipes.search(request) if request else []
        out = [f"<p><b>The assistant isn't available:</b> {html.escape(message)}</p>",
               "<p>Change the address under <a href='settings:'>Assistant &gt; Settings</a>.</p>"]
        if found:
            out.append("<p><b>From the built-in task library:</b></p><ul>")
            for i, r in enumerate(found[:5]):
                out.append(f"<li><a href='recipe:{recipes.RECIPES.index(r)}'>{html.escape(r.title)}</a>"
                           f" &nbsp;<code>{html.escape(r.command)}</code></li>")
            out.append("</ul>")
            self.use_recipe(found[0], show_text=False)
        self.panel.answer.setHtml("".join(out))

    def _answer_link(self, url):
        s = url.toString()
        if s.startswith("recipe:"):
            self.use_recipe(recipes.RECIPES[int(s.split(":", 1)[1])])
        elif s.startswith("settings:"):
            self.open_settings()

    def use_recipe(self, r: recipes.Recipe, show_text: bool = True):
        if not self.panel.isVisible():
            self._toggle_panel()
        self.panel.show_command(r.command, "safe")
        if show_text:
            extra = "\n\nReplace the part in `<...>` first, then click **Run**." if r.needs_input else ""
            self.panel.answer.setMarkdown(f"**{r.title}**\n\n{r.explanation}{extra}")
        if not r.needs_input:
            self.panel.run_btn.setFocus()

    # -- explaining ---------------------------------------------------------------------------
    def _explain(self, text: str, question: str | None = None):
        if not text.strip():
            self.panel.answer.setPlainText("There is no text to explain yet.")
            return
        if not self.panel.isVisible():
            self._toggle_panel()
        self.streamed = ""
        self.panel.set_busy(True)
        self.panel.show_command("")
        self.panel.answer.setHtml("<i>Reading the output...</i>")
        self._update_status("thinking")
        last = self.history[-1] if self.history else None
        self._new_worker().explain(text, last, self.term.shell_cwd(), question)

    def explain_selection(self):
        self._explain(self.term.selected_text())

    def explain_last(self):
        self._explain(self.term.recent_output(60))

    # -- running -------------------------------------------------------------------------------
    def _confirm(self, command: str) -> bool:
        if not command:
            return False
        if re.search(r"<[^<>]+>", command):
            QMessageBox.information(self, APP_NAME, "Replace the part in <...> with your own value first.")
            self.panel._select_placeholder()
            return False
        if not self.term.foreground_is_shell():
            r = QMessageBox.question(self, APP_NAME,
                                     "A program is still running in the terminal.\n\n"
                                     "Send the command to it anyway? (Usually you first quit it with q or Ctrl+C.)")
            if r != QMessageBox.Yes:
                return False
        risk = self.panel.current_risk()
        if risk.level == safety.DANGER:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Dangerous command")
            box.setText(f"<b>This command can destroy data or break the system.</b><br><br>"
                        f"<code>{html.escape(command)}</code>")
            box.setInformativeText("Why: " + "; ".join(risk.reasons) + ".\n\nRun it only if you are sure.")
            check = QCheckBox("I understand what this command does")
            box.setCheckBox(check)
            run = box.addButton("Run anyway", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(QMessageBox.Cancel)
            run.setEnabled(False)
            check.toggled.connect(run.setEnabled)
            box.exec()
            return box.clickedButton() is run
        return True

    def run_suggested(self, command: str):
        if self._confirm(command):
            self.history.append(command)
            self.term.run_command(command)

    def insert_suggested(self, command: str):
        if command:
            self.term.send_text("\x15" + command)
            self.term.setFocus()

    # -- misc actions ----------------------------------------------------------------------------
    def _toggle_panel(self):
        visible = not self.panel.isVisible()
        self.panel.setVisible(visible)
        self.toggle_panel.setChecked(visible)
        (self.panel.input if visible else self.term).setFocus()

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            new = dlg.current()
            try:
                new.save()
            except OSError as e:
                QMessageBox.warning(self, APP_NAME, f"Could not save the settings: {e}")
            if new.font_size != self.settings.font_size:
                f = QFont(self.term.term_font)
                f.setPointSize(new.font_size)
                self.term.set_terminal_font(f)
            self.settings = new
            self._update_status()

    def new_window(self):
        import subprocess
        subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0])], cwd=self.term.shell_cwd(),
                         start_new_session=True)

    def open_konsole(self):
        import subprocess
        subprocess.Popen(["konsole", "--workdir", self.term.shell_cwd()], start_new_session=True)

    def show_shortcuts(self):
        QMessageBox.information(self, "Keyboard Shortcuts", (
            "Ctrl+Shift+C / Ctrl+Shift+V\tCopy / paste\n"
            "Select with the mouse\tcopies to the middle-click clipboard\n"
            "Shift+PgUp / Shift+PgDn\tScroll back / forward\n"
            "Ctrl + mouse wheel, Ctrl +/-\tText size\n"
            "Ctrl+Shift+A\t\tAsk the assistant\n"
            "Ctrl+Shift+E\t\tExplain the selected text\n"
            "Ctrl+Shift+L\t\tExplain the last output\n"
            "F9\t\t\tShow or hide the assistant\n"
            "Ctrl+C\t\t\tStop the running program\n"
            "Ctrl+Shift+N\t\tNew window"))

    def show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}", (
            f"<b>{APP_NAME}</b> for FedoraClassic7<br><br>"
            "A terminal with an assistant that uses your own language model server "
            "(Ollama or OpenAI-compatible). Commands only run when you click Run, and "
            "risky commands are checked by built-in rules, not by the model alone.<br><br>"
            f"Settings file: {llm.CONFIG_FILE}"))

    def _shell_finished(self, status):
        if self.hold:
            self.term.stream.feed(f"\r\n[Process finished with exit code {status}. Close the window.]\r\n".encode())
            self.term.update()
        else:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, ev):
        if self.term.exit_status is None and not self.term.foreground_is_shell():
            r = QMessageBox.question(self, APP_NAME, "A program is still running. Close the window anyway?")
            if r != QMessageBox.Yes:
                ev.ignore()
                return
        if self.worker:
            self.worker.cancel()
        self.term.close_terminal()
        ev.accept()


def windows_console_palette(app: QApplication):
    """Keep the system (Classic) palette; only make sure tooltips are readable."""
    pal = app.palette()
    pal.setColor(QPalette.ToolTipBase, QColor("#ffffe1"))
    pal.setColor(QPalette.ToolTipText, QColor("#000000"))
    app.setPalette(pal)


def main(argv=None, cwd=None, hold=False) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-prompt")
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName("classic7-prompt")
    windows_console_palette(app)
    win = PromptWindow(argv, cwd, hold)
    win.show()
    return app.exec()


def parse_exec(args: list[str]) -> list[str] | None:
    """`-e cmd args...` as used by desktop files with Terminal=true and other launchers."""
    if not args:
        return None
    if len(args) == 1 and " " in args[0]:
        return ["/bin/bash", "-c", args[0]]
    return args if not any(c in args[0] for c in " ;|&") else ["/bin/bash", "-c", shlex.join(args)]
