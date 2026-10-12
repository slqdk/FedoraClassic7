"""Show: presentations in the style of PowerPoint 2007 (Office button, ribbon, slides pane,
slide sorter, notes, slide show). Opens .pptx/.ppsx/.potx/.pptm and old .ppt/.pps files, saves .pptx,
.ppsx, PDF and pictures.
"""
from __future__ import annotations

import copy
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import (QByteArray, QMarginsF, QMimeData, QPointF, QRectF, QSettings, QSize, QSizeF, Qt, QTimer,
                            QUrl)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QFontDatabase, QIcon, QImage, QKeySequence, QPainter,
                           QPageLayout, QPageSize, QPen, QPixmap, QTextCursor)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout,
                               QLabel, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QSlider,
                               QSplitter, QStackedWidget, QStatusBar, QTabWidget, QTextBrowser,
                               QToolButton, QVBoxLayout, QWidget, QWidgetAction, QListWidgetItem)

import show_designs as sd
import show_dialogs as dlg
import show_edit as se
import show_geom as geom
import show_model as sm
import show_pptx as spx
import show_render as sr
import show_text as st
import show_widgets as sw
import write_ribbon as rb

APP = "Show"
MIME_SHAPES = "application/x-classic7-show-shapes"
MIME_SLIDES = "application/x-classic7-show-slides"
FONT_SIZES = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 66, 72, 80, 88, 96]
OPEN_FILTER = ("All PowerPoint Presentations (*.pptx *.pptm *.ppsx *.ppsm *.potx *.potm *.ppt *.pps *.pot);;"
               "PowerPoint Presentation (*.pptx);;PowerPoint 97-2003 Presentation (*.ppt *.pps);;All Files (*)")
SAVE_TYPES = [("PowerPoint Presentation (*.pptx)", ".pptx"), ("PowerPoint Show (*.ppsx)", ".ppsx"),
              ("PowerPoint Template (*.potx)", ".potx"), ("PDF (*.pdf)", ".pdf"),
              ("PNG Portable Network Graphics Format (*.png)", ".png"), ("JPEG File Interchange Format (*.jpg)", ".jpg")]
TRANSITIONS = [("none", "", "No Transition"), ("fade", "", "Fade Smoothly"), ("fade", "black", "Fade Through Black"),
               ("cut", "", "Cut"), ("push", "u", "Push Up"), ("push", "l", "Push Left"),
               ("wipe", "d", "Wipe Down"), ("wipe", "r", "Wipe Right"), ("split", "horz-out", "Split Horizontal Out"),
               ("split", "vert-out", "Split Vertical Out"), ("cover", "l", "Cover Left"), ("pull", "l", "Uncover Left"),
               ("zoom", "in", "Zoom In"), ("circle", "", "Circle"), ("diamond", "", "Diamond"), ("plus", "", "Plus"),
               ("wheel", "", "Wheel Clockwise"), ("wedge", "", "Wedge"), ("dissolve", "", "Dissolve"),
               ("randomBar", "horz", "Random Bars Horizontal"), ("blinds", "horz", "Blinds Horizontal"),
               ("checker", "horz", "Checkerboard Across"), ("newsflash", "", "Newsflash")]
ANIMATIONS = [("none", "No Animation"), ("appear", "Appear"), ("fade", "Fade"), ("wipe", "Wipe"),
              ("fly", "Fly In"), ("zoom", "Zoom")]


def _trans_icon(typ: str, d: str, size: int = 40) -> QIcon:
    """A small picture of a transition: two slides, the new one coming in."""
    pm = QPixmap(size, int(size * 0.75))
    pm.fill(QColor("#FFFFFF"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    w, h = pm.width(), pm.height()
    old, new = QColor("#9DB7DA"), QColor("#E68A2E")
    p.fillRect(0, 0, w, h, old)
    if typ == "none":
        p.fillRect(0, 0, w, h, QColor("#FFFFFF"))
        p.setPen(QColor("#999999"))
        p.drawText(pm.rect(), Qt.AlignCenter, "None")
    elif typ == "fade":
        p.fillRect(0, 0, w, h, QColor(0, 0, 0) if d == "black" else QColor("#C1A88F"))
        p.setOpacity(0.5)
        p.fillRect(0, 0, w, h, new)
    elif typ in ("push", "cover", "pull", "wipe"):
        if d in ("u", "d"):
            p.fillRect(0, int(h * 0.45), w, h, new)
        else:
            p.fillRect(int(w * 0.45), 0, w, h, new)
    elif typ == "split":
        if d.startswith("horz"):
            p.fillRect(0, int(h * 0.3), w, int(h * 0.4), new)
        else:
            p.fillRect(int(w * 0.3), 0, int(w * 0.4), h, new)
    elif typ in ("circle", "zoom"):
        p.setBrush(new)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(w / 2, h / 2), w * 0.28, h * 0.32)
    elif typ == "diamond":
        p.setBrush(new)
        p.setPen(Qt.NoPen)
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([QPointF(w / 2, h * 0.15), QPointF(w * 0.8, h / 2), QPointF(w / 2, h * 0.85),
                                 QPointF(w * 0.2, h / 2)]))
    elif typ == "plus":
        p.fillRect(int(w * 0.38), 0, int(w * 0.24), h, new)
        p.fillRect(0, int(h * 0.38), w, int(h * 0.24), new)
    elif typ in ("wheel", "wedge"):
        p.setBrush(new)
        p.setPen(Qt.NoPen)
        p.drawPie(QRectF(-w * 0.2, -h * 0.2, w * 1.4, h * 1.4), 90 * 16, -120 * 16)
    elif typ in ("dissolve", "checker", "randomBar", "blinds"):
        import random
        rnd = random.Random(len(typ))
        for i in range(8):
            for j in range(6):
                if (typ in ("checker",) and (i + j) % 2) or (typ == "dissolve" and rnd.random() > 0.5):
                    p.fillRect(int(i * w / 8), int(j * h / 6), int(w / 8) + 1, int(h / 6) + 1, new)
        if typ in ("randomBar", "blinds"):
            for j in range(0, 6, 2):
                p.fillRect(0, int(j * h / 6), w, int(h / 6) + 1, new)
    else:
        p.fillRect(int(w * 0.2), int(h * 0.2), int(w * 0.6), int(h * 0.6), new)
    p.setPen(QColor("#7F8FA6"))
    p.setOpacity(1)
    p.drawRect(0, 0, w - 1, h - 1)
    p.end()
    return QIcon(pm)


class ShowWindow(QMainWindow):
    untitled_counter = 0

    def __init__(self, path: str | None = None):
        super().__init__()
        self.settings = QSettings("Classic7", "Show")
        ShowWindow.untitled_counter += 1
        self.untitled = f"Presentation{ShowWindow.untitled_counter}"
        self.path: str | None = None
        self.save_kind = "pres"
        self.modified = False
        self.pres = sm.new_presentation("office")
        self.renderer = sr.Renderer(self.pres)
        self.current = 0
        self.undo_stack: list = []
        self.redo_stack: list = []
        self._depth = 0
        self._before = None
        self.show_opts = {"timings": True}
        self.slideshow = None
        self.find_dialog = None
        self.painter_format = None
        self.setWindowIcon(rb.icon(["x-office-presentation", "application-vnd.ms-powerpoint"], "P", 32))

        self.view = se.SlideView(self)
        try:
            from write_app import Speller
            self.view.speller = Speller(None)
            self.view.speller.enabled = self.settings.value("spelling", True, bool)
        except Exception:   # noqa: BLE001
            self.view.speller = None
        self._actions()
        self._ribbon()
        self._central()
        self._status()
        self.view.selectionChanged.connect(self.selection_changed)
        self.view.formatChanged.connect(self.update_text_state)
        self.view.editingChanged.connect(lambda _e: self.selection_changed())
        self.view.context_menu_requested.connect(self.context_menu)
        self.view.zoomChanged.connect(self._zoom_changed)
        self.view.shapeDrawn.connect(self._shape_drawn)
        self.view.slideStep.connect(lambda d: self.go_to(self.current + d))
        self.thumb_timer = QTimer(self, singleShot=True, interval=350, timeout=self._update_current_thumb)
        self.outline_timer = QTimer(self, singleShot=True, interval=800, timeout=self.refresh_outline)
        self.resize(1180, 820)
        self.load_presentation(self.pres)
        if path:
            QTimer.singleShot(0, lambda: self.open_path(path))
        self._update_title()

    # ==== actions ===================================================================================
    def act(self, text, slot=None, shortcut=None, icon=None, fallback="", checkable=False, tip=None, **kw):
        a = QAction(text, self)
        if icon is not None or fallback:
            a.setIcon(icon if isinstance(icon, QIcon) else rb.icon(icon or [], fallback or text[:1], **kw))
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, list) else [shortcut])])
        if slot:
            a.triggered.connect(lambda _c=False, f=slot: f() if not checkable else f(a.isChecked()))
        a.setCheckable(checkable)
        tip_text = tip or text.replace("&", "")
        if shortcut:
            first = shortcut[0] if isinstance(shortcut, list) else shortcut
            tip_text += f" ({QKeySequence(first).toString(QKeySequence.NativeText)})"
        a.setToolTip(tip_text)
        self.addAction(a)
        return a

    def _actions(self):
        A = self.act
        self.a_new = A("&New", self.file_new, "Ctrl+N", "document-new", "N")
        self.a_open = A("&Open...", self.file_open, "Ctrl+O", "document-open", "O")
        self.a_save = A("&Save", self.file_save, "Ctrl+S", "document-save", "S")
        self.a_saveas = A("Save &As...", self.file_save_as, "F12", "document-save-as", "A")
        self.a_print = A("&Print...", self.file_print, "Ctrl+P", "document-print", "P")
        self.a_preview = A("Print Pre&view", self.file_preview, None, "document-print-preview", "V")
        self.a_close = A("&Close", self.close, "Ctrl+W", "document-close", "X")
        self.a_undo = A("&Undo", self.undo, "Ctrl+Z", "edit-undo", "↶")
        self.a_redo = A("&Redo", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"], "edit-redo", "↷")
        self.a_cut = A("Cu&t", self.cut, "Ctrl+X", "edit-cut", "✂")
        self.a_copy = A("&Copy", self.copy, "Ctrl+C", "edit-copy", "C")
        self.a_paste = A("&Paste", self.paste, "Ctrl+V", "edit-paste", "P", size=rb.BIG)
        self.a_paste_text = A("Paste as Unformatted &Text", self.paste_text, "Ctrl+Alt+V", "edit-paste", "T")
        self.a_painter = A("Format Painter", self.format_painter, "Ctrl+Shift+C", "format-stroke-color", "🖌",
                           checkable=True)
        self.a_select_all = A("Select &All", self.view.select_all, "Ctrl+A", "edit-select-all", "A")
        self.a_find = A("&Find", lambda: self.show_find(False), "Ctrl+F", "edit-find", "F")
        self.a_replace = A("R&eplace", lambda: self.show_find(True), "Ctrl+H", "edit-find-replace", "R")
        self.a_duplicate = A("Duplicate", self.duplicate, "Ctrl+D", "edit-copy", "D")

        self.a_new_slide = A("New Slide", lambda: self.new_slide(None), "Ctrl+M", ["list-add", "document-new"],
                             "+", size=rb.BIG)
        self.a_new_slide.setData("split")
        self.a_layout = A("Layout", None, None, ["view-grid", "view-split-left-right"], "▤")
        self.a_reset = A("Reset", self.reset_slide, None, ["edit-undo", "view-refresh"], "↺")
        self.a_delete_slide = A("Delete", self.delete_slides, None, ["edit-delete", "list-remove"], "✕")
        self.a_dup_slide = A("Duplicate Selected Slides", self.duplicate_slides, None, "edit-copy", "D")
        self.a_hide_slide = A("Hide Slide", self.toggle_hide_slide, None, ["view-hidden", "visibility"], "⊘",
                              checkable=True, size=rb.BIG)

        self.a_bold = A("Bold", lambda on: self.set_run("bold", on), "Ctrl+B", "format-text-bold", "B",
                        checkable=True)
        self.a_italic = A("Italic", lambda on: self.set_run("italic", on), "Ctrl+I", "format-text-italic", "I",
                          checkable=True, italic=True)
        self.a_underline = A("Underline", lambda on: self.set_run("underline", on), "Ctrl+U",
                             "format-text-underline", "U", checkable=True, underline="#000000", bold=False)
        self.a_strike = A("Strikethrough", lambda on: self.set_run("strike", on), None,
                          "format-text-strikethrough", "abc", checkable=True, strike=True, bold=False)
        self.a_sub = A("Subscript", lambda on: self.set_run("baseline", -25 if on else None), "Ctrl+=",
                       "format-text-subscript", "x₂", checkable=True, bold=False)
        self.a_sup = A("Superscript", lambda on: self.set_run("baseline", 30 if on else None), "Ctrl+Shift+=",
                       "format-text-superscript", "x²", checkable=True, bold=False)
        self.a_grow = A("Increase Font Size", lambda: self.step_size(+1), ["Ctrl+Shift+>", "Ctrl+]"],
                        "format-font-size-more", "A⁺")
        self.a_shrink = A("Decrease Font Size", lambda: self.step_size(-1), ["Ctrl+Shift+<", "Ctrl+["],
                          "format-font-size-less", "A⁻")
        self.a_clear = A("Clear All Formatting", self.clear_formatting, "Ctrl+Space", "edit-clear-all", "⌫")
        self.a_color = A("Font Color", lambda: self.set_run("color", self.last_color), None, None, "A",
                         underline="#C00000", bold=True)
        self.last_color = {"rgb": "C00000"}

        align = QActionGroup(self)
        self.a_left = A("Align Text Left", lambda: self.set_para("align", "l"), "Ctrl+L", "format-justify-left",
                        "≡", checkable=True)
        self.a_center = A("Center", lambda: self.set_para("align", "ctr"), "Ctrl+E", "format-justify-center", "≡",
                          checkable=True)
        self.a_right = A("Align Text Right", lambda: self.set_para("align", "r"), "Ctrl+R", "format-justify-right",
                         "≡", checkable=True)
        self.a_justify = A("Justify", lambda: self.set_para("align", "just"), "Ctrl+J", "format-justify-fill", "≡",
                           checkable=True)
        for a in (self.a_left, self.a_center, self.a_right, self.a_justify):
            align.addAction(a)
        self.a_bullets = A("Bullets", lambda on: self.toggle_bullets("bullet", on), None, "format-list-unordered",
                           "•", checkable=True)
        self.a_numbering = A("Numbering", lambda on: self.toggle_bullets("number", on), None,
                             "format-list-ordered", "1.", checkable=True)
        self.a_level_down = A("Decrease List Level", lambda: self.change_level(-1), "Alt+Shift+Left",
                              "format-indent-less", "⇤")
        self.a_level_up = A("Increase List Level", lambda: self.change_level(1), "Alt+Shift+Right",
                            "format-indent-more", "⇥")

        self.a_table = A("Table", self.table_dialog, None, ["insert-table", "table"], "▦", size=rb.BIG)
        self.a_picture = A("Picture", self.picture_dialog, None, ["insert-image", "image-x-generic"], "🖼",
                           size=rb.BIG)
        self.a_shapes = A("Shapes", None, None, ["draw-rectangle", "shape-choose"], "◆", size=rb.BIG)
        self.a_textbox = A("Text Box", lambda: self.view.start_draw("textBox"), None,
                           ["insert-text-frame", "draw-text"], "A▭", size=rb.BIG)
        self.a_link = A("Hyperlink", self.hyperlink_dialog, "Ctrl+K", ["insert-link", "link"], "🔗", size=rb.BIG)
        self.a_headfoot = A("Header & Footer", self.header_footer, None, ["view-split-top-bottom", "go-bottom"],
                            "▁", size=rb.BIG)
        self.a_date = A("Date & Time", lambda: self.insert_field("datetime"), None,
                        ["view-calendar", "x-office-calendar"], "📅", size=rb.BIG)
        self.a_slidenum = A("Slide Number", lambda: self.insert_field("slidenum"), None, None, "#", size=rb.BIG)
        self.a_symbol = A("Symbol", None, None, None, "Ω", size=rb.BIG)

        self.a_page_setup = A("Page Setup", self.page_setup, None, ["document-page-setup", "page-simple"], "▭",
                              size=rb.BIG)
        self.a_orient = A("Slide Orientation", None, None, ["object-rotate-right", "transform-rotate"], "⤾",
                          size=rb.BIG)
        self.a_hide_bg = A("Hide Background Graphics", self.toggle_hide_bg, None, None, "", checkable=True)

        self.a_from_start = A("From Beginning", lambda: self.start_show(0), "F5",
                              ["media-playback-start", "view-presentation"], "▶", size=rb.BIG)
        self.a_from_current = A("From Current Slide", lambda: self.start_show(self.current), "Shift+F5",
                                ["media-skip-forward", "media-playback-start"], "▶|", size=rb.BIG)
        self.a_setup_show = A("Set Up Slide Show", self.setup_show, None, ["configure", "preferences-system"], "⚙",
                              size=rb.BIG)

        views = QActionGroup(self)
        self.a_normal = A("Normal", lambda: self.set_view("normal"), None, ["view-split-left-right", "view-list-details"],
                          "▭", checkable=True, size=rb.BIG)
        self.a_sorter = A("Slide Sorter", lambda: self.set_view("sorter"), None, ["view-grid", "view-list-icons"],
                          "▦", checkable=True, size=rb.BIG)
        for a in (self.a_normal, self.a_sorter):
            views.addAction(a)
        self.a_normal.setChecked(True)
        self.a_grid = A("Gridlines", self.toggle_grid, "Shift+F9", None, "#", checkable=True)
        self.a_fit = A("Fit to Window", self.view.zoom_fit, None, ["zoom-fit-best", "zoom-fit-page"], "⤢",
                       size=rb.BIG)
        self.a_zoom = A("Zoom", self.zoom_dialog, None, ["zoom-in", "zoom"], "🔍", size=rb.BIG)
        self.a_spell = A("Spelling", self.toggle_spelling, "F7", ["tools-check-spelling", "spellcheck"], "ABC✓",
                         checkable=True, size=rb.BIG)
        self.a_spell.setChecked(bool(self.view.speller and self.view.speller.enabled))

        self.a_front = A("Bring to Front", lambda: self.arrange("front"), "Ctrl+Shift+]", ["go-top", "object-order-front"], "⇈")
        self.a_back = A("Send to Back", lambda: self.arrange("back"), "Ctrl+Shift+[", ["go-bottom", "object-order-back"], "⇊")
        self.a_forward = A("Bring Forward", lambda: self.arrange("forward"), None, ["go-up", "object-order-raise"], "↑")
        self.a_backward = A("Send Backward", lambda: self.arrange("backward"), None, ["go-down", "object-order-lower"], "↓")
        self.a_group = A("Group", self.group, "Ctrl+G", ["object-group"], "▣")
        self.a_ungroup = A("Ungroup", self.ungroup, "Ctrl+Shift+G", ["object-ungroup"], "▢")
        self.a_rot_right = A("Rotate Right 90°", lambda: self.rotate(90), None, ["object-rotate-right"], "↻")
        self.a_rot_left = A("Rotate Left 90°", lambda: self.rotate(-90), None, ["object-rotate-left"], "↺")
        self.a_flip_v = A("Flip Vertical", lambda: self.flip("v"), None, ["object-flip-vertical"], "⇅")
        self.a_flip_h = A("Flip Horizontal", lambda: self.flip("h"), None, ["object-flip-horizontal"], "⇆")
        self.a_delete = A("Delete", self.delete_selection, None, "edit-delete", "✕")
        self.a_delete.setShortcutContext(Qt.WidgetShortcut)

    # ==== ribbon ===================================================================================
    def _ribbon(self):
        top = QWidget()
        v = QVBoxLayout(top)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        qat = QHBoxLayout()
        qat.setContentsMargins(4, 2, 4, 0)
        qat.setSpacing(1)
        self.office = QToolButton()
        self.office.setObjectName("orb")
        self.office.setIcon(rb.office_orb(36, "S"))
        self.office.setIconSize(QSize(36, 36))
        self.office.setPopupMode(QToolButton.InstantPopup)
        self.office.setToolTip("Office Button\nNew, Open, Save, Print, Close")
        self.office.setMenu(self._office_menu())
        self.office.setAutoRaise(True)
        qat.addWidget(self.office)
        qat.addSpacing(4)
        for a in (self.a_save, self.a_undo, self.a_redo, self.a_from_start):
            qat.addWidget(rb.small_button(a))
        qat.addStretch(1)
        v.addLayout(qat)
        r = rb.Ribbon()
        self.ribbon = r
        self._tab_home(r)
        self._tab_insert(r)
        self._tab_design(r)
        self._tab_animations(r)
        self._tab_show(r)
        self._tab_review(r)
        self._tab_view(r)
        self.ctx_tabs = {}
        self._tab_format(r)
        self._tab_table(r)
        v.addWidget(r)
        self.ribbon_top = top
        rb.apply_scheme(top, r, self.settings.value("ribbon/scheme", "blue"))
        self.setMenuWidget(top)

    def color_ctx(self) -> st.TextCtx:
        return sw.ctx_for(self.pres, self.slide)

    def _font_group(self, r, tab):
        g = r.group(tab, "Font")
        self.font_box = QComboBox()
        self.font_box.setEditable(True)
        self.font_box.setMinimumWidth(140)
        self.font_box.setMaximumWidth(170)
        self.font_box.setInsertPolicy(QComboBox.NoInsert)
        self._fill_fonts()
        self.font_box.textActivated.connect(self.font_chosen)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([f"{s:g}" for s in FONT_SIZES])
        self.size_box.setMinimumWidth(54)
        self.size_box.setMaximumWidth(60)
        self.size_box.setEditText("18")
        self.size_box.textActivated.connect(self.size_chosen)
        self.size_box.lineEdit().returnPressed.connect(lambda: self.size_chosen(self.size_box.currentText()))
        case_menu = QMenu(self)
        for label, mode in (("Sentence case.", "sentence"), ("lowercase", "lower"), ("UPPERCASE", "upper"),
                            ("Capitalize Each Word", "title"), ("tOGGLE cASE", "toggle")):
            case_menu.addAction(label, lambda mode=mode: self.change_case(mode))
        a_case = self.act("Change Case", lambda: self.change_case("cycle"), "Shift+F3", None, "Aa", bold=False)
        self.color_menu = sw.ThemeColorMenu(self, self.color_ctx, "Automatic")
        self.color_menu.picked.connect(self._font_color)
        g.add_column(
            [self.font_box, self.size_box, rb.small_button(self.a_grow), rb.small_button(self.a_shrink),
             rb.small_button(self.a_clear)],
            [rb.small_button(self.a_bold), rb.small_button(self.a_italic), rb.small_button(self.a_underline),
             rb.small_button(self.a_strike), rb.small_button(self.a_sub), rb.small_button(self.a_sup),
             rb.small_button(a_case, case_menu, split=True),
             rb.small_button(self.a_color, self.color_menu, split=True)])

    def _fill_fonts(self):
        self.font_box.clear()
        th = self.pres.master.theme if getattr(self, "pres", None) else sm.Theme()
        self.font_box.addItem(f"{th.major_font} (Headings)", "+mj-lt")
        self.font_box.addItem(f"{th.minor_font} (Body)", "+mn-lt")
        self.font_box.insertSeparator(2)
        for fam in QFontDatabase.families():
            if not QFontDatabase.isPrivateFamily(fam):
                self.font_box.addItem(fam, fam)

    def _paragraph_group(self, r, tab):
        g = r.group(tab, "Paragraph")
        bm = QMenu(self)
        for label, ch, font in (("• Filled Round Bullets", "•", "Arial"), ("o Hollow Round Bullets", "o", "Courier New"),
                                ("▪ Filled Square Bullets", "§", "Wingdings"), ("❖ Star Bullets", "v", "Wingdings"),
                                ("➢ Arrow Bullets", "Ø", "Wingdings"), ("✓ Checkmark Bullets", "ü", "Wingdings"),
                                ("– Dash", "–", "Arial")):
            bm.addAction(label, lambda ch=ch, font=font: self.set_bullet({"char": ch, "font": font}))
        bm.addSeparator()
        bm.addAction("None", lambda: self.set_bullet({"none": True}))
        nm = QMenu(self)
        for label, sch in (("1. 2. 3.", "arabicPeriod"), ("1) 2) 3)", "arabicParenR"), ("I. II. III.", "romanUcPeriod"),
                           ("A. B. C.", "alphaUcPeriod"), ("a) b) c)", "alphaLcParenR"), ("a. b. c.", "alphaLcPeriod"),
                           ("i. ii. iii.", "romanLcPeriod")):
            nm.addAction(label, lambda sch=sch: self.set_bullet({"auto": sch, "start": 1}))
        nm.addSeparator()
        nm.addAction("None", lambda: self.set_bullet({"none": True}))
        sp = QMenu(self)
        for v_ in (100, 150, 200, 250, 300):
            sp.addAction(f"{v_ / 100:.1f}", lambda v_=v_: self.set_para("line_spacing", float(v_)))
        a_sp = self.act("Line Spacing", None, None, ["format-line-spacing-normal", "format-line-spacing-double"], "↕")
        vm = QMenu(self)
        for label, anc in (("Top", "t"), ("Middle", "ctr"), ("Bottom", "b")):
            vm.addAction(label, lambda anc=anc: self.set_anchor(anc))
        a_valign = self.act("Align Text", None, None, ["format-align-vertical-center", "align-vertical-center"], "⇕")
        g.add_column(
            [rb.small_button(self.a_bullets, bm, split=True), rb.small_button(self.a_numbering, nm, split=True),
             rb.small_button(self.a_level_down), rb.small_button(self.a_level_up), rb.small_button(a_sp, sp)],
            [rb.small_button(self.a_left), rb.small_button(self.a_center), rb.small_button(self.a_right),
             rb.small_button(self.a_justify), rb.small_button(a_valign, vm)])

    def _shapes_menu(self) -> sw.GalleryMenu:
        m = sw.GalleryMenu(self, cols=10, cell=QSize(22, 22), with_labels=False)

        def items():
            out = []
            for group, entries in geom.GALLERY:
                for key, label in entries:
                    out.append((key, label, lambda key=key: self._shape_pixmap(key), group))
            return out
        m.set_items(items)
        m.picked.connect(self.view.start_draw)
        return m

    def _shape_pixmap(self, key) -> QPixmap:
        pm = QPixmap(22, 22)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(2, 3)
        path = geom.preset_path(key if key != "doubleArrowLine" else "line", 18, 16)
        p.setPen(QPen(QColor("#2F4F7F"), 1))
        if key not in geom.OPEN_SHAPES:
            p.setBrush(QColor("#C6D9F1"))
        p.drawPath(path)
        p.end()
        return pm

    def _drawing_group(self, r, tab, name="Drawing"):
        g = r.group(tab, name)
        if name == "Drawing":
            g.add(rb.big_button(self.a_shapes, self._shapes_menu()))
        am = QMenu(self)
        for a in (self.a_front, self.a_back, self.a_forward, self.a_backward):
            am.addAction(a)
        am.addSeparator()
        am.addAction(self.a_group)
        am.addAction(self.a_ungroup)
        am.addSeparator()
        am.addMenu(self._align_menu())
        ro = am.addMenu("Rotate")
        for a in (self.a_rot_right, self.a_rot_left, self.a_flip_v, self.a_flip_h):
            ro.addAction(a)
        a_arr = self.act("Arrange", None, None, ["object-order-front", "align-horizontal-center"], "▤", size=rb.BIG)
        if name == "Drawing":
            g.add(rb.big_button(a_arr, am))
        qs = sw.GalleryMenu(self, cols=7, cell=QSize(40, 26), with_labels=False)
        qs.set_items(self._quick_style_items)
        qs.picked.connect(self.apply_quick_style)
        a_qs = self.act("Quick Styles", None, None, ["draw-brush", "format-fill-color"], "▧", size=rb.BIG)
        g.add(rb.big_button(a_qs, qs))
        self.fill_menu = sw.ThemeColorMenu(self, self.color_ctx, "No Fill",
                                           extra=[None, self.act("Picture...", self.fill_picture),
                                                  self.act("Gradient", self.fill_gradient)])
        self.fill_menu.picked.connect(lambda c: self.set_fill(c))
        self.outline_menu = sw.ThemeColorMenu(self, self.color_ctx, "No Outline", extra=[None] + self._line_menus())
        self.outline_menu.picked.connect(lambda c: self.set_outline(color=c))
        a_fill = self.act("Shape Fill", lambda: self.set_fill(self.last_fill), None, sw.fill_icon(QColor("#4F81BD")))
        a_out = self.act("Shape Outline", lambda: self.set_outline(color=self.last_outline), None,
                         sw.outline_icon(QColor("#385D8A")))
        self.last_fill = sm.scheme("accent1")
        self.last_outline = sm.scheme("accent1", ("shade", 50000))
        g.add_column([rb.small_button(a_fill, self.fill_menu, with_text=True, split=True)],
                     [rb.small_button(a_out, self.outline_menu, with_text=True, split=True)])
        return g

    def _align_menu(self) -> QMenu:
        al = QMenu("Align", self)
        for label, how in (("Align Left", "l"), ("Align Center", "c"), ("Align Right", "r"), (None, None),
                           ("Align Top", "t"), ("Align Middle", "m"), ("Align Bottom", "b"), (None, None),
                           ("Distribute Horizontally", "dh"), ("Distribute Vertically", "dv")):
            if label is None:
                al.addSeparator()
            else:
                al.addAction(label, lambda how=how: self.align_shapes(how))
        return al

    def _line_menus(self) -> list:
        wm = QMenu("Weight", self)
        for w in (0.25, 0.5, 0.75, 1, 1.5, 2.25, 3, 4.5, 6):
            wm.addAction(f"{w:g} pt", lambda w=w: self.set_outline(width=sm.emu(w)))
        dm = QMenu("Dashes", self)
        for label, d in (("Solid", "solid"), ("Round Dot", "sysDot"), ("Square Dot", "sysDash"), ("Dash", "dash"),
                         ("Dash Dot", "dashDot"), ("Long Dash", "lgDash"), ("Long Dash Dot", "lgDashDot")):
            dm.addAction(label, lambda d=d: self.set_outline(dash=d))
        arr = QMenu("Arrows", self)
        for label, head, tail in (("No arrows", "none", "none"), ("Arrow at end", "none", "triangle"),
                                  ("Arrow at start", "triangle", "none"), ("Arrows at both ends", "triangle", "triangle"),
                                  ("Open arrow at end", "none", "arrow"), ("Oval ends", "oval", "oval")):
            arr.addAction(label, lambda h=head, t=tail: self.set_outline(head=h, tail=t))
        return [wm, dm, arr]

    def _quick_style_items(self):
        out = []
        for row, label in ((0, "Colored Outline"), (1, "Colored Fill"), (2, "Light"), (3, "Intense")):
            for col, key in enumerate(("tx1", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6")):
                out.append(((row, key), f"{label} - {key}", lambda row=row, key=key: self._style_pixmap(row, key),
                            None))
        return out

    def _quick_style(self, row, key):
        if row == 0:
            return ({"type": "solid", "color": sm.scheme("lt1")},
                    {"color": sm.scheme(key), "width": 25400, "dash": "solid"}, sm.scheme("dk1"))
        if row == 1:
            return ({"type": "solid", "color": sm.scheme(key)},
                    {"color": sm.scheme(key, ("shade", 50000)), "width": 25400, "dash": "solid"}, sm.scheme("lt1"))
        if row == 2:
            return ({"type": "grad", "stops": [[0, sm.scheme(key, ("tint", 50000))], [100000, sm.scheme(key, ("tint", 15000))]],
                     "angle": 90.0, "path": None},
                    {"color": sm.scheme(key), "width": 9525, "dash": "solid"}, sm.scheme("dk1"))
        return ({"type": "grad", "stops": [[0, sm.scheme(key, ("shade", 51000))], [80000, sm.scheme(key, ("shade", 93000))],
                                           [100000, sm.scheme(key, ("shade", 94000))]], "angle": 270.0, "path": None},
                {"color": sm.scheme("lt1"), "width": 38100, "dash": "solid"}, sm.scheme("lt1"))

    def _style_pixmap(self, row, key) -> QPixmap:
        fill, line, text = self._quick_style(row, key)
        pm = QPixmap(40, 26)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        ctx = self.color_ctx()
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRoundedRect(QRectF(3, 3, 34, 20), 3, 3)
        self.renderer.paint_fill(p, QRectF(3, 3, 34, 20), fill, ctx, path)
        p.setPen(QPen(ctx.color(line["color"]), 1.5))
        p.drawPath(path)
        p.setPen(ctx.color(text))
        f = p.font()
        f.setPixelSize(10)
        p.setFont(f)
        p.drawText(QRectF(3, 3, 34, 20), Qt.AlignCenter, "Abc")
        p.end()
        return pm

    def _tab_home(self, r):
        home = r.add_tab("Home")
        g = r.group(home, "Clipboard")
        pm = QMenu(self)
        pm.addAction(self.a_paste)
        pm.addAction(self.a_paste_text)
        g.add(rb.big_button(self.a_paste, pm))
        g.add_column([rb.small_button(self.a_cut, with_text=True)], [rb.small_button(self.a_copy, with_text=True)],
                     [rb.small_button(self.a_painter, with_text=True)])
        g = r.group(home, "Slides")
        self.new_slide_menu = self._layout_gallery(self.new_slide)
        self.new_slide_menu.extra_actions = [None, self.a_dup_slide]
        g.add(rb.big_button(self.a_new_slide, self.new_slide_menu))
        self.layout_menu = self._layout_gallery(self.apply_layout)
        g.add_column([rb.small_button(self.a_layout, self.layout_menu, with_text=True)],
                     [rb.small_button(self.a_reset, with_text=True)],
                     [rb.small_button(self.a_delete_slide, with_text=True)])
        self._font_group(r, home)
        self._paragraph_group(r, home)
        self._drawing_group(r, home)
        g = r.group(home, "Editing")
        sel = QMenu(self)
        sel.addAction(self.a_select_all)
        a_sel = self.act("Select", None, None, "edit-select", "⬚")
        g.add_column([rb.small_button(self.a_find, with_text=True)], [rb.small_button(self.a_replace, with_text=True)],
                     [rb.small_button(a_sel, sel, with_text=True)])

    def _layout_gallery(self, slot) -> sw.GalleryMenu:
        m = sw.GalleryMenu(self, cols=3, cell=QSize(88, 66))

        def items():
            out = []
            master = self.pres.master_of(self.slide) if self.slide is not None else self.pres.master
            for i, lay in enumerate(master.layouts):
                out.append((i, lay.name, lambda lay=lay, master=master: self._layout_pixmap(master, lay),
                            master.theme.name))
            return out
        m.set_items(items)
        m.picked.connect(lambda i: slot(i))
        return m

    def _layout_pixmap(self, master, lay) -> QPixmap:
        w, h = sm.pt(self.pres.width), sm.pt(self.pres.height)
        width = 88
        height = int(width * h / w)
        img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.white)
        p = QPainter(img)
        p.scale(width / w, height / h)
        self.renderer.paint_layout_preview(p, master, lay)
        p.end()
        return sw.frame_pixmap(img)

    def _tab_insert(self, r):
        ins = r.add_tab("Insert")
        g = r.group(ins, "Tables")
        tm = QMenu(self)
        grid = rb.TableGrid(8, 10)
        grid.picked.connect(lambda rr, cc: (tm.close(), self.insert_table(rr, cc)))
        ga = QWidgetAction(tm)
        ga.setDefaultWidget(grid)
        tm.addAction(ga)
        tm.addSeparator()
        tm.addAction("Insert Table...", self.table_dialog)
        g.add(rb.big_button(self.a_table, tm))
        g = r.group(ins, "Illustrations")
        g.add(rb.big_button(self.a_picture))
        g.add(rb.big_button(self.a_shapes, self._shapes_menu()))
        g = r.group(ins, "Links")
        g.add(rb.big_button(self.a_link))
        g = r.group(ins, "Text")
        for a in (self.a_textbox, self.a_headfoot, self.a_date, self.a_slidenum):
            g.add(rb.big_button(a))
        g.add(rb.big_button(self.a_symbol, rb.symbol_menu(self, self.insert_text)))

    def _tab_design(self, r):
        des = r.add_tab("Design")
        g = r.group(des, "Page Setup")
        g.add(rb.big_button(self.a_page_setup))
        om = QMenu(self)
        om.addAction("Portrait", lambda: self.set_orientation(True))
        om.addAction("Landscape", lambda: self.set_orientation(False))
        g.add(rb.big_button(self.a_orient, om))
        g = r.group(des, "Themes")
        self.theme_buttons = {}
        for key, d in sd.DESIGNS.items():
            b = QToolButton()
            b.setAutoRaise(True)
            b.setToolTip(d["name"])
            b.setIconSize(QSize(56, 42))
            b.clicked.connect(lambda _=False, key=key: self.apply_design(key))
            self.theme_buttons[key] = b
            g.add(b)
        QTimer.singleShot(0, self._theme_previews)
        colors = QMenu(self)
        for name in sd.COLOR_SETS:
            colors.addAction(self._colors_icon(name), name, lambda name=name: self.set_theme_colors(name))
        fonts = QMenu(self)
        for name, (mj, mn) in sd.FONT_SETS.items():
            a = fonts.addAction(f"{name}    —    {mj} / {mn}", lambda name=name: self.set_theme_fonts(name))
            f = QFont(mj)
            a.setFont(f)
        bgm = sw.GalleryMenu(self, cols=4, cell=QSize(48, 36), with_labels=False)
        bgm.set_items(lambda: [(i, label, lambda fill=fill: self._bg_pixmap(fill), None)
                               for i, (label, fill) in enumerate(sd.background_styles())])
        bgm.picked.connect(self.apply_background_style)
        bgm.extra_actions = [None, self.act("Format Background...", self.format_background),
                             self.act("Reset Slide Background", self.reset_background)]
        a_colors = self.act("Colors", None, None, ["preferences-desktop-color", "color-management"], "🎨")
        a_fonts = self.act("Fonts", None, None, ["preferences-desktop-font", "font"], "A")
        a_bg = self.act("Background Styles", None, None, ["preferences-desktop-wallpaper", "fill-color"], "▧")
        g.add_column([rb.small_button(a_colors, colors, with_text=True)],
                     [rb.small_button(a_fonts, fonts, with_text=True)],
                     [rb.small_button(a_bg, bgm, with_text=True)])
        g = r.group(des, "Background")
        g.add_column([rb.small_button(self.a_hide_bg, with_text=True)],
                     [rb.small_button(self.act("Format Background...", self.format_background, None,
                                               "preferences-desktop-wallpaper", "▧"), with_text=True)])

    def _colors_icon(self, name) -> QIcon:
        cs = sd.COLOR_SETS[name]
        pm = QPixmap(64, 14)
        pm.fill(Qt.white)
        p = QPainter(pm)
        for i, k in enumerate(("dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6")):
            p.fillRect(i * 8, 0, 8, 14, QColor("#" + cs[k]))
        p.end()
        return QIcon(pm)

    def _bg_pixmap(self, fill) -> QPixmap:
        pm = QPixmap(48, 36)
        pm.fill(Qt.white)
        p = QPainter(pm)
        self.renderer.paint_fill(p, QRectF(0, 0, 48, 36), fill, self.color_ctx(), None)
        p.setPen(QColor("#7F8FA6"))
        p.drawRect(0, 0, 47, 35)
        p.end()
        return pm

    def _theme_previews(self):
        size = (self.pres.width, self.pres.height)
        for key, b in self.theme_buttons.items():
            p = sm.new_presentation(key, size)
            s = p.slides[0]
            s.shapes[0].text = sm.TextBody(paragraphs=[sm.Paragraph(runs=[sm.Run("Aa", size=240.0)], align="ctr")],
                                           anchor="ctr")
            s.shapes[0].x, s.shapes[0].y = 0, 0
            s.shapes[0].cx, s.shapes[0].cy = p.width, p.height
            s.shapes[0].inherit = False
            s.shapes = s.shapes[:1]
            img = sr.Renderer(p).thumbnail(s, 56)
            b.setIcon(QIcon(sw.frame_pixmap(img)))

    def _tab_animations(self, r):
        an = r.add_tab("Animations")
        g = r.group(an, "Preview")
        g.add(rb.big_button(self.act("Preview", lambda: self.start_show(self.current, single=True), None,
                                     ["media-playback-start"], "▶", size=rb.BIG)))
        g = r.group(an, "Animations")
        self.anim_box = QComboBox()
        for key, label in ANIMATIONS:
            self.anim_box.addItem(label, key)
        self.anim_box.activated.connect(lambda _i: self.set_animation(self.anim_box.currentData()))
        g.add_column([QLabel("Animate:"), self.anim_box])
        g = r.group(an, "Transition to This Slide")
        self.trans_buttons = []
        for typ, d, label in TRANSITIONS[:9]:
            b = QToolButton()
            b.setAutoRaise(True)
            b.setCheckable(True)
            b.setIcon(_trans_icon(typ, d))
            b.setIconSize(QSize(40, 30))
            b.setToolTip(label)
            b.clicked.connect(lambda _=False, typ=typ, d=d: self.set_transition(typ, d))
            self.trans_buttons.append((typ, d, b))
            g.add(b)
        more = QMenu(self)
        for typ, d, label in TRANSITIONS:
            more.addAction(_trans_icon(typ, d, 32), label, lambda typ=typ, d=d: self.set_transition(typ, d))
        mb = QToolButton()
        mb.setText("More")
        mb.setPopupMode(QToolButton.InstantPopup)
        mb.setMenu(more)
        mb.setAutoRaise(True)
        g.add(mb)
        self.speed_box = QComboBox()
        for key, label in (("slow", "Slow"), ("med", "Medium"), ("fast", "Fast")):
            self.speed_box.addItem(label, key)
        self.speed_box.activated.connect(lambda _i: self.set_transition_speed(self.speed_box.currentData()))
        a_all = self.act("Apply To All", self.transition_to_all, None, ["edit-select-all"], "⇶")
        g.add_column([QLabel("Transition Speed:"), self.speed_box], [rb.small_button(a_all, with_text=True)])
        g = r.group(an, "Advance Slide")
        self.adv_click = QCheckBox("On Mouse Click")
        self.adv_click.clicked.connect(self.set_advance)
        self.adv_after = QCheckBox("Automatically After:")
        self.adv_after.clicked.connect(self.set_advance)
        self.adv_time = QDoubleSpinBox()
        self.adv_time.setRange(0, 3600)
        self.adv_time.setDecimals(1)
        self.adv_time.setSuffix(" s")
        self.adv_time.editingFinished.connect(self.set_advance)
        g.add_column([self.adv_click], [self.adv_after, self.adv_time])

    def _tab_show(self, r):
        ss = r.add_tab("Slide Show")
        g = r.group(ss, "Start Slide Show")
        g.add(rb.big_button(self.a_from_start))
        g.add(rb.big_button(self.a_from_current))
        g = r.group(ss, "Set Up")
        g.add(rb.big_button(self.a_setup_show))
        g.add(rb.big_button(self.a_hide_slide))

    def _tab_review(self, r):
        rv = r.add_tab("Review")
        g = r.group(rv, "Proofing")
        g.add(rb.big_button(self.a_spell))

    def _tab_view(self, r):
        vw = r.add_tab("View")
        g = r.group(vw, "Presentation Views")
        g.add(rb.big_button(self.a_normal))
        g.add(rb.big_button(self.a_sorter))
        g.add(rb.big_button(self.a_from_start, text="Slide Show"))
        g = r.group(vw, "Show/Hide")
        g.add_column([rb.small_button(self.a_grid, with_text=True)])
        g = r.group(vw, "Zoom")
        g.add(rb.big_button(self.a_zoom))
        g.add(rb.big_button(self.a_fit))

    def _tab_format(self, r):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(3, 2, 3, 2)
        lay.setSpacing(3)
        lay.addStretch(1)
        self.ctx_tabs["format"] = (page, "Format")
        g = r.group(lay, "Insert Shapes")
        g.add(rb.big_button(self.a_shapes, self._shapes_menu()))
        g.add(rb.big_button(self.a_textbox))
        self._drawing_group(r, lay, "Shape Styles")
        g = r.group(lay, "Arrange")
        g.add_column([rb.small_button(self.a_front, with_text=True)], [rb.small_button(self.a_back, with_text=True)],
                     [rb.small_button(self.a_group, with_text=True)])
        rm = QMenu(self)
        for a in (self.a_rot_right, self.a_rot_left, self.a_flip_v, self.a_flip_h):
            rm.addAction(a)
        a_rot = self.act("Rotate", None, None, ["object-rotate-right"], "↻")
        a_align = self.act("Align", None, None, ["align-horizontal-left", "format-justify-left"], "⫷")
        g.add_column([rb.small_button(self.a_forward, with_text=True)],
                     [rb.small_button(self.a_backward, with_text=True)],
                     [rb.small_button(a_rot, rm, with_text=True)])
        g.add_column([rb.small_button(a_align, self._align_menu(), with_text=True)],
                     [rb.small_button(self.a_ungroup, with_text=True)])
        g = r.group(lay, "Size")
        self.h_spin = dlg.unit_spin(914400)
        self.w_spin = dlg.unit_spin(914400)
        self.h_spin.editingFinished.connect(lambda: self.set_size("h"))
        self.w_spin.editingFinished.connect(lambda: self.set_size("w"))
        g.add_column([QLabel("Height:"), self.h_spin], [QLabel("Width:"), self.w_spin])

    def _tab_table(self, r):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(3, 2, 3, 2)
        lay.setSpacing(3)
        lay.addStretch(1)
        self.ctx_tabs["table_design"] = (page, "Table Design")
        g = r.group(lay, "Table Style Options")
        self.tbl_checks = {}
        for key, label in (("first_row", "Header Row"), ("last_row", "Total Row"), ("band_rows", "Banded Rows"),
                           ("first_col", "First Column"), ("last_col", "Last Column"), ("band_cols", "Banded Columns")):
            cb = QCheckBox(label)
            cb.clicked.connect(lambda on, key=key: self.set_table_flag(key, on))
            self.tbl_checks[key] = cb
        g.add_column([self.tbl_checks["first_row"], self.tbl_checks["first_col"]],
                     [self.tbl_checks["last_row"], self.tbl_checks["last_col"]],
                     [self.tbl_checks["band_rows"], self.tbl_checks["band_cols"]])
        g = r.group(lay, "Table Styles")
        for key in ("medium2-accent1", "medium2-accent2", "medium2-accent3", "medium2-accent4", "medium2-accent5",
                    "medium2-accent6", "medium2-dk1", "light1-accent1", "grid", "none"):
            b = QToolButton()
            b.setAutoRaise(True)
            b.setIconSize(QSize(44, 32))
            b.setToolTip(key.replace("medium2", "Medium Style 2").replace("light1", "Light Style 1")
                         .replace("-", " - ").replace("grid", "Table Grid").replace("none", "No Style"))
            b.setProperty("style_key", key)
            b.clicked.connect(lambda _=False, key=key: self.set_table_style(key))
            g.add(b)
            self.__dict__.setdefault("tbl_style_buttons", []).append(b)
        self.shade_menu = sw.ThemeColorMenu(self, self.color_ctx, "No Fill")
        self.shade_menu.picked.connect(self.set_cell_fill)
        a_shade = self.act("Shading", lambda: None, None, sw.fill_icon(QColor("#FFFF00")))
        g.add_column([rb.small_button(a_shade, self.shade_menu, with_text=True)])
        page2 = QWidget()
        lay2 = QHBoxLayout(page2)
        lay2.setContentsMargins(3, 2, 3, 2)
        lay2.setSpacing(3)
        lay2.addStretch(1)
        self.ctx_tabs["table_layout"] = (page2, "Table Layout")
        g = r.group(lay2, "Rows & Columns")
        for label, op, ic in (("Insert Above", "row_above", "edit-table-insert-row-above"),
                              ("Insert Below", "row_below", "edit-table-insert-row-below"),
                              ("Insert Left", "col_left", "edit-table-insert-column-left"),
                              ("Insert Right", "col_right", "edit-table-insert-column-right")):
            g.add(rb.big_button(self.act(label, lambda op=op: self.table_op(op), None, [ic], "+", size=rb.BIG)))
        dm = QMenu(self)
        dm.addAction("Delete Columns", lambda: self.table_op("del_col"))
        dm.addAction("Delete Rows", lambda: self.table_op("del_row"))
        dm.addAction("Delete Table", lambda: self.table_op("del_table"))
        g.add(rb.big_button(self.act("Delete", None, None, ["edit-table-delete-row", "edit-delete"], "✕",
                                     size=rb.BIG), dm))
        g = r.group(lay2, "Merge")
        g.add(rb.big_button(self.act("Merge Cells", lambda: self.table_op("merge"), None,
                                     ["edit-table-cell-merge"], "⊞", size=rb.BIG)))
        g.add(rb.big_button(self.act("Split Cells", lambda: self.table_op("split"), None,
                                     ["edit-table-cell-split"], "⊟", size=rb.BIG)))
        g = r.group(lay2, "Alignment")
        g.add_column([rb.small_button(self.a_left), rb.small_button(self.a_center), rb.small_button(self.a_right)],
                     [rb.small_button(self.act("Align Top", lambda: self.set_anchor("t"), None,
                                               ["format-align-vertical-top"], "⤒")),
                      rb.small_button(self.act("Center Vertically", lambda: self.set_anchor("ctr"), None,
                                               ["format-align-vertical-center"], "⇕")),
                      rb.small_button(self.act("Align Bottom", lambda: self.set_anchor("b"), None,
                                               ["format-align-vertical-bottom"], "⤓"))])

    def _show_ctx_tabs(self, wanted: list[str]):
        r = self.ribbon
        cur = r.currentWidget()
        changed = False
        for key, (page, title) in self.ctx_tabs.items():
            idx = r.indexOf(page)
            if key in wanted and idx < 0:
                r.addTab(page, title)
                changed = True
            elif key not in wanted and idx >= 0:
                r.removeTab(idx)
                changed = True
        if not changed:
            return
        r.setCurrentWidget(cur if r.indexOf(cur) >= 0 else r.widget(0))
        rb.apply_scheme(self.ribbon_top, r, self.settings.value("ribbon/scheme", "blue"))

    def _office_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self.a_new)
        menu.addAction(self.a_open)
        menu.addAction(self.a_save)
        save_as = menu.addMenu(rb.icon("document-save-as", "A"), "Save &As")
        for label, ext in SAVE_TYPES:
            save_as.addAction(label.split(" (")[0], lambda ext=ext: self.file_save_as(ext))
        menu.addSeparator()
        menu.addAction(self.a_print)
        menu.addAction(self.a_preview)
        send = menu.addMenu(rb.icon(["mail-send", "mail-message-new"], "@"), "Sen&d")
        send.addAction(rb.icon(["mail-message-new"], "@"), "&E-mail", lambda: self.send_by_mail(".pptx"))
        send.addAction(rb.icon(["application-pdf"], "PDF"), "E-mail as &PDF Attachment",
                       lambda: self.send_by_mail(".pdf"))
        menu.addSeparator()
        self.recent_menu = menu.addMenu(rb.icon("document-open-recent", "R"), "&Recent Presentations")
        self._fill_recent()
        menu.addSeparator()
        schemes = menu.addMenu(rb.icon("preferences-desktop-color", "C"), "Color &Scheme")
        grp = QActionGroup(schemes)
        current = self.settings.value("ribbon/scheme", "blue")
        for key, label in rb.SCHEME_NAMES.items():
            a = schemes.addAction(label, lambda key=key: self.set_ribbon_scheme(key))
            a.setCheckable(True)
            a.setChecked(key == current)
            grp.addAction(a)
        menu.addSeparator()
        menu.addAction(self.a_close)
        menu.addAction(rb.icon("application-exit", "X"), f"E&xit {APP}", QApplication.closeAllWindows)
        return menu

    def set_ribbon_scheme(self, key):
        self.settings.setValue("ribbon/scheme", key)
        for w in QApplication.topLevelWidgets():
            if isinstance(w, ShowWindow):
                rb.apply_scheme(w.ribbon_top, w.ribbon, key)

    def _fill_recent(self):
        self.recent_menu.clear()
        files = [f for f in self.settings.value("recent", [], list) or [] if os.path.exists(f)]
        for i, f in enumerate(files[:9]):
            self.recent_menu.addAction(f"&{i + 1} {Path(f).name}", lambda f=f: self.open_maybe_new(f))
        self.recent_menu.setEnabled(bool(files))

    def _add_recent(self, path):
        files = [path] + [f for f in (self.settings.value("recent", [], list) or []) if f != path]
        self.settings.setValue("recent", files[:9])
        self._fill_recent()

    # ==== central area =============================================================================
    def _central(self):
        self.slides_list = sw.SlideList(False)
        self.slides_list.currentRowChanged.connect(self._list_row)
        self.slides_list.moved.connect(self._slides_moved)
        self.slides_list.menuRequested.connect(lambda pos: self.slides_menu(self.slides_list, pos))
        self.slides_list.installEventFilter(self)
        self.outline = QTextBrowser()
        self.outline.setOpenLinks(False)
        self.outline.anchorClicked.connect(lambda url: self.go_to(int(url.toString().split(":")[1])))
        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(self.slides_list, "Slides")
        self.left_tabs.addTab(self.outline, "Outline")
        self.left_tabs.setMinimumWidth(150)
        self.left_tabs.currentChanged.connect(lambda i: self.refresh_outline() if i == 1 else None)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Click to add notes")
        self.notes.textChanged.connect(self._notes_changed)
        self._notes_loading = False
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.view)
        right.addWidget(self.notes)
        right.setStretchFactor(0, 5)
        right.setStretchFactor(1, 1)
        right.setSizes([620, 90])
        self.normal = QSplitter(Qt.Horizontal)
        self.normal.addWidget(self.left_tabs)
        self.normal.addWidget(right)
        self.normal.setStretchFactor(1, 1)
        self.normal.setSizes([200, 960])
        self.sorter = sw.SlideList(True)
        self.sorter.moved.connect(self._slides_moved)
        self.sorter.itemDoubleClicked.connect(lambda it: (self.set_view("normal"), self.go_to(self.sorter.row(it))))
        self.sorter.currentRowChanged.connect(lambda i: self._set_current(i) if i >= 0 else None)
        self.sorter.menuRequested.connect(lambda pos: self.slides_menu(self.sorter, pos))
        self.sorter.installEventFilter(self)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.normal)
        self.stack.addWidget(self.sorter)
        self.setCentralWidget(self.stack)

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if obj in (getattr(self, "slides_list", None), getattr(self, "sorter", None)) and \
                e.type() == QEvent.KeyPress:
            if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self.delete_slides()
                return True
            if e.key() in (Qt.Key_Return, Qt.Key_Enter) and obj is self.slides_list:
                self.new_slide(None)
                return True
            if e.matches(QKeySequence.Copy):
                self.copy_slides()
                return True
            if e.matches(QKeySequence.Cut):
                self.copy_slides()
                self.delete_slides()
                return True
            if e.matches(QKeySequence.Paste):
                self.paste()
                return True
        return super().eventFilter(obj, e)

    def _status(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_slide = QLabel()
        self.lbl_theme = QLabel()
        for w in (self.lbl_slide, self.lbl_theme):
            w.setFrameShape(QLabel.Panel)
            w.setFrameShadow(QLabel.Sunken)
            w.setContentsMargins(4, 0, 4, 0)
        sb.addWidget(self.lbl_slide)
        sb.addWidget(self.lbl_theme)
        for a in (self.a_normal, self.a_sorter, self.a_from_current):
            b = rb.small_button(a)
            b.setIconSize(QSize(16, 16))
            sb.addPermanentWidget(b)
        self.zoom_label = QToolButton()
        self.zoom_label.setAutoRaise(True)
        self.zoom_label.clicked.connect(self.zoom_dialog)
        sb.addPermanentWidget(self.zoom_label)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 400)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.valueChanged.connect(self._zoom_slider)
        sb.addPermanentWidget(self.zoom_slider)
        fit = rb.small_button(self.a_fit)
        fit.setIconSize(QSize(16, 16))
        sb.addPermanentWidget(fit)

    # ==== presentation <-> UI ======================================================================
    @property
    def slide(self) -> sm.Slide | None:
        if 0 <= self.current < len(self.pres.slides):
            return self.pres.slides[self.current]
        return None

    def load_presentation(self, pres: sm.Presentation):
        self.pres = pres
        self.renderer = sr.Renderer(pres)
        self.view.set_presentation(pres, self.renderer)
        self.current = min(self.current, max(0, len(pres.slides) - 1))
        self.rebuild_lists()
        self._fill_fonts()
        self.go_to(self.current)
        QTimer.singleShot(0, self._theme_previews)

    def rebuild_lists(self):
        lists = [(self.slides_list, 150)]
        if self.stack.currentWidget() is self.sorter:
            lists.append((self.sorter, 200))
            self._sorter_dirty = False
        else:
            self._sorter_dirty = True
        for lst, width in lists:
            lst.blockSignals(True)
            lst.clear()
            dpr = self.devicePixelRatioF()
            for i, s in enumerate(self.pres.slides):
                it = QListWidgetItem()
                pm = QPixmap.fromImage(self.renderer.thumbnail(s, width, i + 1, dpr))
                it.setData(Qt.DecorationRole, pm)
                it.setData(Qt.UserRole, i)
                it.setData(Qt.UserRole + 2, s.hidden)
                t = s.transition
                it.setData(Qt.UserRole + 3, (f"{t.after_ms / 1000:g}s " if t.after_ms else "") +
                           ("☆" if t.type not in ("none", "", None) else ""))
                it.setFlags(it.flags() | Qt.ItemIsDragEnabled)
                lst.addItem(it)
            lst.setCurrentRow(self.current)
            lst.blockSignals(False)
        self.outline_timer.start()
        self._update_status()

    def _update_current_thumb(self):
        if self.slide is None:
            return
        dpr = self.devicePixelRatioF()
        lists = [(self.slides_list, 150)] + ([(self.sorter, 200)] if self.stack.currentWidget() is self.sorter else [])
        if self.stack.currentWidget() is not self.sorter:
            self._sorter_dirty = True
        for lst, width in lists:
            it = lst.item(self.current)
            if it is not None:
                it.setData(Qt.DecorationRole, QPixmap.fromImage(self.renderer.thumbnail(self.slide, width,
                                                                                        self.current + 1, dpr)))
                it.setData(Qt.UserRole + 2, self.slide.hidden)

    def go_to(self, index: int):
        if not self.pres.slides:
            self.current = 0
            self.view.set_slide(None, 0)
            self._update_status()
            return
        index = max(0, min(len(self.pres.slides) - 1, index))
        self._set_current(index)
        for lst in (self.slides_list, self.sorter):
            lst.blockSignals(True)
            if lst.currentRow() != index:
                lst.setCurrentRow(index)
            lst.blockSignals(False)
            it = lst.item(index)
            if it is not None:
                lst.scrollToItem(it)

    def _set_current(self, index: int):
        self.current = index
        self.view.set_slide(self.slide, index + 1)
        self._notes_loading = True
        self.notes.setPlainText(self.slide.notes if self.slide else "")
        self._notes_loading = False
        self._update_status()
        self.update_slide_state()

    def _list_row(self, row):
        if row >= 0 and row != self.current:
            self.view.end_edit()
            self._set_current(row)
            self.sorter.blockSignals(True)
            self.sorter.setCurrentRow(row)
            self.sorter.blockSignals(False)

    def _update_status(self):
        n = len(self.pres.slides)
        self.lbl_slide.setText(f"Slide {self.current + 1} of {n}" if n else "No slides")
        master = self.pres.master_of(self.slide) if self.slide else self.pres.master
        self.lbl_theme.setText(f'"{master.theme.name}"')

    def _update_title(self):
        name = Path(self.path).name if self.path else self.untitled
        self.setWindowTitle(f"{name} - {APP}")

    def _notes_changed(self):
        if self._notes_loading or self.slide is None:
            return
        self.slide.notes = self.notes.toPlainText()
        self.modified = True

    def refresh_outline(self):
        if self.left_tabs.currentIndex() != 1:
            return
        from html import escape
        out = ['<html><body style="font-family: sans-serif; font-size: 10pt;">']
        for i, s in enumerate(self.pres.slides):
            title = ""
            body = []
            for sh in s.shapes:
                if sh.text is None or sh.text.is_empty():
                    continue
                if sh.ph is not None and sh.ph.type in ("title", "ctrTitle"):
                    title = sh.text.plain().replace("\v", " ").replace("\n", " ")
                elif sh.ph is not None and sh.ph.type not in ("dt", "ftr", "sldNum"):
                    for p in sh.text.paragraphs:
                        if p.text().strip():
                            body.append((p.level, p.text().replace("\v", " ")))
            out.append(f'<p style="margin: 6px 0 2px 0;"><a href="slide:{i}" style="color:#1F497D; '
                       f'text-decoration:none;"><b>{i + 1}&nbsp;▭&nbsp;{escape(title) or "&nbsp;"}</b></a></p>')
            for lvl, text in body:
                out.append(f'<p style="margin: 0 0 0 {28 + lvl * 18}px;">{escape(text)}</p>')
        out.append("</body></html>")
        self.outline.setHtml("".join(out))

    # ==== undo =====================================================================================
    def snapshot(self):
        return (copy.deepcopy((self.pres.masters, self.pres.slides)), self.pres.width, self.pres.height,
                copy.deepcopy(self.pres.footer), self.current)

    def begin_change(self, label: str = ""):
        if self._depth == 0:
            self._before = (label, self.snapshot())
        self._depth += 1
        return True

    def end_change(self):
        self._depth = max(0, self._depth - 1)
        if self._depth:
            return
        if self._before is None:
            return
        label, before = self._before
        self._before = None
        (masters, slides), w, h, footer, _cur = before
        if masters == self.pres.masters and slides == self.pres.slides and (w, h) == (self.pres.width, self.pres.height) \
                and footer == self.pres.footer:
            return
        self.undo_stack.append((label, before))
        del self.undo_stack[:-60]
        self.redo_stack.clear()
        self.changed()

    def changed(self, structure: bool = False):
        self.modified = True
        if structure:
            self.rebuild_lists()
        else:
            self.thumb_timer.start()
            self.outline_timer.start()
        self.view.refresh()
        self._update_status()
        self.update_text_state()
        self.update_slide_state()

    def _restore(self, state):
        (masters, slides), w, h, footer, cur = state
        self.view.end_edit() if self.view.editing is not None else None
        self.pres.masters, self.pres.slides = masters, slides
        self.pres.width, self.pres.height = w, h
        self.pres.footer = footer
        self.current = min(cur, len(slides) - 1)
        self.view.selection = []
        self.view.set_presentation(self.pres, self.renderer)
        self.rebuild_lists()
        self.go_to(self.current)
        self.modified = True

    def undo(self):
        ed = self.view.editing
        if ed is not None:
            if ed.document().isUndoAvailable():
                ed.document().undo()
                return
            self.view.end_edit()
        if not self.undo_stack:
            return
        label, state = self.undo_stack.pop()
        self.redo_stack.append((label, self.snapshot()))
        self._restore(state)

    def redo(self):
        ed = self.view.editing
        if ed is not None and ed.document().isRedoAvailable():
            ed.document().redo()
            return
        if not self.redo_stack:
            return
        label, state = self.redo_stack.pop()
        self.undo_stack.append((label, self.snapshot()))
        self._restore(state)

    # ==== state of the ribbon =======================================================================
    def selection_changed(self):
        sel = self.view.selection
        wanted = []
        if (sel and any(s.kind in ("sp", "pic", "group") for s in sel)) or self.view.editing is not None:
            if not (len(sel) == 1 and sel[0].kind == "table"):
                wanted.append("format")
        if len(sel) == 1 and sel[0].kind == "table":
            wanted += ["table_design", "table_layout"]
            self._update_table_state(sel[0])
        self._show_ctx_tabs(wanted)
        if len(sel) == 1:
            s = sel[0]
            for sp, v in ((self.h_spin, s.cy), (self.w_spin, s.cx)):
                sp.blockSignals(True)
                sp.setValue(dlg.emu_to_unit(v))
                sp.blockSignals(False)
            idx = self.anim_box.findData((s.anim or {}).get("effect", "none"))
            self.anim_box.setCurrentIndex(max(0, idx))
        self.anim_box.setEnabled(bool(sel))
        has = bool(sel)
        for a in (self.a_front, self.a_back, self.a_forward, self.a_backward, self.a_rot_left, self.a_rot_right,
                  self.a_flip_h, self.a_flip_v):
            a.setEnabled(has)
        self.a_group.setEnabled(len(sel) > 1)
        self.a_ungroup.setEnabled(any(s.kind == "group" for s in sel))
        self.update_text_state()

    def _update_table_state(self, s):
        t = s.table
        for key, cb in self.tbl_checks.items():
            cb.setChecked(bool(getattr(t, key)))
        for b in getattr(self, "tbl_style_buttons", []):
            key = b.property("style_key")
            b.setIcon(QIcon(self._table_style_pixmap(key)))
            b.setCheckable(True)
            b.setChecked(key == t.style)

    def _table_style_pixmap(self, key) -> QPixmap:
        tbl = se.new_table(4, 3, 0, 0, sm.emu(44))
        tbl.table.style = key
        tbl.table.row_heights = [sm.emu(8)] * 4
        tbl.cy = sm.emu(32)
        pm = QPixmap(44, 32)
        pm.fill(Qt.white)
        p = QPainter(pm)
        ctx = self.renderer.ctx(self.slide, tbl)
        for c in tbl.table.rows[0] + tbl.table.rows[1]:
            c.margins = (0, 0, 0, 0)
        for row in tbl.table.rows:
            for c in row:
                c.margins = (0, 0, 0, 0)
        self.renderer.paint_table(p, tbl, ctx, 44, 32)
        p.end()
        return pm

    def update_text_state(self):
        """Font, size, bold... show what is under the cursor (or in the selected shape)."""
        d = self._current_run_props()
        widgets = (self.a_bold, self.a_italic, self.a_underline, self.a_strike, self.a_sub, self.a_sup, self.a_left,
                   self.a_center, self.a_right, self.a_justify, self.a_bullets, self.a_numbering)
        if d is not None:
            run, para = d
            ctx = self.color_ctx()
            font = run.get("font")
            name = ctx.font_name(font)
            self.font_box.blockSignals(True)
            if font in ("+mj-lt", "+mn-lt", None):
                self.font_box.setCurrentIndex(0 if font == "+mj-lt" else 1)
            else:
                self.font_box.setEditText(name)
            self.font_box.blockSignals(False)
            self.size_box.blockSignals(True)
            self.size_box.setEditText(f"{float(run.get('size') or 18):g}")
            self.size_box.blockSignals(False)
            self.a_bold.setChecked(bool(run.get("bold")))
            self.a_italic.setChecked(bool(run.get("italic")))
            self.a_underline.setChecked(bool(run.get("underline")))
            self.a_strike.setChecked(bool(run.get("strike")))
            self.a_sub.setChecked((run.get("baseline") or 0) < 0)
            self.a_sup.setChecked((run.get("baseline") or 0) > 0)
            al = para.get("align") or "l"
            {"l": self.a_left, "ctr": self.a_center, "r": self.a_right, "just": self.a_justify}.get(
                al, self.a_left).setChecked(True)
            b = para.get("bullet") or {}
            self.a_bullets.setChecked("char" in b and not b.get("none"))
            self.a_numbering.setChecked("auto" in b and not b.get("none"))
        del widgets

    def _current_run_props(self):
        ed = self.view.editing
        if ed is not None:
            c = ed.textCursor()
            cf = c.charFormat()
            block = c.block()
            eff = st.block_effective(block, ed.ctx)
            run = st.run_props(st.char_expl(cf), eff)
            return run, eff
        sel = self.view.selection
        if len(sel) >= 1 and sel[0].text is not None and sel[0].kind == "sp":
            s = sel[0]
            ctx = self.renderer.ctx(self.slide, s)
            par = s.text.paragraphs[0] if s.text.paragraphs else sm.Paragraph()
            eff = st._effective(par, ctx)
            run = st.run_props(st._run_expl(par.runs[0]) if par.runs else {}, eff)
            return run, eff
        return None

    def update_slide_state(self):
        s = self.slide
        if s is None:
            return
        self.a_hide_slide.setChecked(s.hidden)
        self.a_hide_bg.setChecked(s.hide_master_shapes)
        t = s.transition
        for typ, d, b in self.trans_buttons:
            b.setChecked(typ == (t.type or "none") and (d == (t.dir or "") or (typ == "fade" and
                                                                               (d == "black") == t.through_black)))
        self.speed_box.setCurrentIndex(max(0, self.speed_box.findData(t.speed)))
        self.adv_click.setChecked(t.on_click)
        self.adv_after.setChecked(t.after_ms is not None)
        self.adv_time.setValue((t.after_ms or 0) / 1000.0)

    # ==== text formatting ===========================================================================
    def _text_bodies(self) -> list:
        out = []
        for s in self.view.selection:
            for x in sm.walk([s]):
                if x.kind == "sp" and x.text is not None:
                    out.append(x.text)
                elif x.kind == "table" and x.table is not None:
                    if self.view.cell_range is not None and self.view.cell_range[0] is x:
                        r0, c0, r1, c1 = self.view.cell_range[1]
                        for ri in range(min(r0, r1), max(r0, r1) + 1):
                            for ci in range(min(c0, c1), max(c0, c1) + 1):
                                out.append(x.table.rows[ri][ci].text)
                    else:
                        out += [c.text for row in x.table.rows for c in row]
        return out

    def set_run(self, key, value):
        ed = self.view.editing
        if ed is not None:
            st.set_run_prop(ed.textCursor(), ed.ctx, key, value)
            ed.reposition()
            ed.update()
            self.update_text_state()
            return
        bodies = self._text_bodies()
        if not bodies:
            return
        self.begin_change("Format Text")
        for body in bodies:
            for par in body.paragraphs:
                for run in par.runs:
                    setattr(run, key, value)
                if key == "size":
                    par.end_size = value
        for s in self.view.selection:
            if s.text is not None and s.text.autofit == "shape":
                self.view.autosize(s)
        self.end_change()

    def set_para(self, key, value):
        ed = self.view.editing
        if ed is not None:
            st.set_para_prop(ed.textCursor(), ed.ctx, key, value)
            ed.reposition()
            ed.update()
            self.update_text_state()
            return
        bodies = self._text_bodies()
        if not bodies:
            return
        self.begin_change("Format Paragraph")
        for body in bodies:
            for par in body.paragraphs:
                setattr(par, key, value)
        self.end_change()

    def set_anchor(self, anc):
        ed = self.view.editing
        targets = []
        if ed is not None and ed.cell is not None:
            ri, ci = ed.cell
            targets.append(("cell", ed.shape.table.rows[ri][ci]))
        elif ed is not None:
            targets.append(("shape", ed.shape))
        for s in self.view.selection:
            if s.kind == "table" and s.table is not None and ed is None:
                cells = [c for row in s.table.rows for c in row]
                if self.view.cell_range is not None and self.view.cell_range[0] is s:
                    r0, c0, r1, c1 = self.view.cell_range[1]
                    cells = [s.table.rows[r][c] for r in range(min(r0, r1), max(r0, r1) + 1)
                             for c in range(min(c0, c1), max(c0, c1) + 1)]
                targets += [("cell", c) for c in cells]
            elif s.text is not None and ed is None:
                targets.append(("shape", s))
        if not targets:
            return
        editing_shape = ed.shape if ed is not None else None
        if ed is not None:
            self.view.end_edit(keep_selection=True)
        self.begin_change("Align Text")
        for kind, t in targets:
            if kind == "cell":
                t.anchor = anc
            else:
                t.text.anchor = anc
        self.end_change()
        if editing_shape is not None and ed.cell is None:
            self.view.begin_edit(editing_shape)

    def font_chosen(self, text):
        i = self.font_box.findText(text)
        token = self.font_box.itemData(i) if i >= 0 else text
        self.set_run("font", token or text)
        self.view.setFocus()

    def size_chosen(self, text):
        try:
            v = float(text.replace(",", "."))
        except ValueError:
            return
        if 1 <= v <= 4000:
            self.set_run("size", v)
        self.view.setFocus()

    def step_size(self, d):
        run = self._current_run_props()
        cur = float((run[0].get("size") if run else 18) or 18)
        if d > 0:
            nxt = next((s for s in FONT_SIZES if s > cur), cur + 8)
        else:
            nxt = next((s for s in reversed(FONT_SIZES) if s < cur), max(1, cur - 1))
        self.set_run("size", nxt)

    def _font_color(self, c):
        if c is not None:
            self.last_color = c
            self.a_color.setIcon(sw.color_icon(self.color_ctx().color(c), "A"))
        self.set_run("color", c)

    def clear_formatting(self):
        ed = self.view.editing
        if ed is not None:
            for key in st.RUN_KEYS:
                if key not in ("link", "field"):
                    st.set_run_prop(ed.textCursor(), ed.ctx, key, None)
            ed.reposition()
            return
        bodies = self._text_bodies()
        if not bodies:
            return
        self.begin_change("Clear Formatting")
        for body in bodies:
            for par in body.paragraphs:
                for run in par.runs:
                    for key in st.RUN_KEYS:
                        if key not in ("link", "field"):
                            setattr(run, key, None if key != "baseline" else 0)
        self.end_change()

    def change_case(self, mode):
        def conv(text):
            if mode == "lower":
                return text.lower()
            if mode == "upper":
                return text.upper()
            if mode == "title":
                return text.title()
            if mode == "toggle":
                return text.swapcase()
            if mode == "sentence":
                return text[:1].upper() + text[1:].lower()
            if text.isupper():
                return text.lower()
            if text.islower():
                return text[:1].upper() + text[1:]
            return text.upper()
        ed = self.view.editing
        if ed is not None:
            c = ed.textCursor()
            if not c.hasSelection():
                c.select(QTextCursor.WordUnderCursor)
            start, end = c.selectionStart(), c.selectionEnd()
            text = c.selectedText()
            new = conv(text)
            if new != text:
                c.beginEditBlock()
                for i, ch in enumerate(new):
                    if ch != text[i]:
                        cc = QTextCursor(ed.document())
                        cc.setPosition(start + i)
                        cc.setPosition(start + i + 1, QTextCursor.KeepAnchor)
                        fmt = cc.charFormat()
                        cc.insertText(ch, fmt)
                c.endEditBlock()
                c.setPosition(start)
                c.setPosition(end, QTextCursor.KeepAnchor)
                ed.setTextCursor(c)
            return
        bodies = self._text_bodies()
        if bodies:
            self.begin_change("Change Case")
            for b in bodies:
                for par in b.paragraphs:
                    for run in par.runs:
                        run.text = conv(run.text)
            self.end_change()

    def toggle_bullets(self, kind, on):
        if kind == "bullet":
            self.set_bullet({"char": "•", "font": "Arial"} if on else {"none": True})
        else:
            self.set_bullet({"auto": "arabicPeriod", "start": 1} if on else {"none": True})

    def set_bullet(self, b: dict):
        """Bullets on/off/kind; a paragraph without its own indent gets the hanging indent."""
        ed = self.view.editing

        def apply_to_par(par: sm.Paragraph, eff: dict):
            inherited = eff.get("bullet") or {}
            if b.get("none"):
                par.bullet = {"none": True}
                if (par.marL is None and (eff.get("marL") or 0) > 0 and inherited and not inherited.get("none")):
                    pass
            else:
                par.bullet = None if (inherited and inherited.get("char") == b.get("char") and "char" in b) else dict(b)
                if (eff.get("marL") or 0) == 0 and par.marL is None:
                    par.marL = 342900
                    par.indent = -342900
        if ed is not None:
            c = ed.textCursor()
            for block in st.selected_blocks(c):
                eff = st.block_effective(block, ed.ctx)
                par = sm.Paragraph(level=int(block.blockFormat().property(st.P_LEVEL) or 0))
                expl = st._load(block.blockFormat().property(st.P_EXPL))
                for k, v in expl.items():
                    setattr(par, k, v)
                apply_to_par(par, eff)
                newexpl = st._para_expl(par)
                st.restyle_block(block, ed.ctx, newexpl, par.level)
            ed.reposition()
            ed.update()
            self.update_text_state()
            return
        if not self.view.selection:
            return
        self.begin_change("Bullets")
        for s in self.view.selection:
            if s.kind == "sp" and s.text is not None:
                ctx = self.renderer.ctx(self.slide, s)
                for par in s.text.paragraphs:
                    apply_to_par(par, st._effective(par, ctx))
        self.end_change()

    def change_level(self, step):
        if self.view.editing is not None:
            self.view.change_level(step)
            return
        if not self.view.selection:
            return
        self.begin_change("List Level")
        for b in self._text_bodies():
            for par in b.paragraphs:
                par.level = max(0, min(8, par.level + step))
        self.end_change()

    def insert_text(self, text):
        ed = self.view.editing
        if ed is not None:
            ed.textCursor().insertText(text)
            return
        if len(self.view.selection) == 1 and se.text_capable(self.view.selection[0]):
            self.view.begin_edit(self.view.selection[0])
            self.view.editing.textCursor().insertText(text)

    def insert_field(self, kind):
        ed = self.view.editing
        if ed is None:
            if len(self.view.selection) == 1 and se.text_capable(self.view.selection[0]):
                self.view.begin_edit(self.view.selection[0])
                ed = self.view.editing
            else:
                self.view.start_draw("textBox")
                QMessageBox.information(self, APP, "Click on the slide where the text should go, then choose the "
                                        "command again.")
                return
        from datetime import date
        text = str(self.current + 1) if kind == "slidenum" else date.today().strftime("%d-%m-%Y")
        c = ed.textCursor()
        cf = c.charFormat()
        expl = st.char_expl(cf)
        expl["field"] = kind
        cf.setProperty(st.C_EXPL, __import__("json").dumps(expl))
        c.insertText(text, cf)
        expl.pop("field")
        cf.setProperty(st.C_EXPL, __import__("json").dumps(expl))
        c.setCharFormat(cf)
        ed.setTextCursor(c)

    def hyperlink_dialog(self):
        ed = self.view.editing
        if ed is not None:
            c = ed.textCursor()
            if not c.hasSelection():
                c.select(QTextCursor.WordUnderCursor)
            url = st.char_expl(c.charFormat()).get("link") or ""
            d = dlg.HyperlinkDialog(c.selectedText(), url, self)
            if d.exec() != QDialog.Accepted:
                return
            if d.removed:
                st.set_run_prop(c, ed.ctx, "link", None)
                return
            if d.text.text() != c.selectedText():
                cf = c.charFormat()
                c.insertText(d.text.text(), cf)
                c.setPosition(c.position() - len(d.text.text()), QTextCursor.KeepAnchor)
            st.set_run_prop(c, ed.ctx, "link", d.url.text().strip())
            ed.update()
            return
        if len(self.view.selection) == 1:
            s = self.view.selection[0]
            d = dlg.HyperlinkDialog(s.name, s.link or "", self, text_editable=False)
            if d.exec() == QDialog.Accepted:
                self.begin_change("Hyperlink")
                s.link = None if d.removed else d.url.text().strip()
                self.end_change()
            return
        d = dlg.HyperlinkDialog("", "", self)
        if d.exec() == QDialog.Accepted and not d.removed and d.url.text().strip():
            self.begin_change("Insert Hyperlink")
            tb = sm.Shape(kind="sp", txbox=True, name="TextBox", x=sm.emu(72), y=sm.emu(72), cx=sm.emu(300),
                          cy=sm.emu(30))
            text = d.text.text() or d.url.text()
            tb.text = sm.TextBody(wrap=False, autofit="shape",
                                  paragraphs=[sm.Paragraph(runs=[sm.Run(text=text, link=d.url.text().strip())])])
            self.slide.shapes.append(tb)
            self.view.autosize(tb)
            self.end_change()
            self.view.select([tb])

    # ==== shapes ===================================================================================
    def _shape_targets(self):
        out = []
        for s in self.view.selection:
            out += [x for x in sm.walk([s]) if x.kind in ("sp", "pic")]
        if self.view.editing is not None and self.view.editing.shape not in out:
            out.append(self.view.editing.shape)
        return out

    def set_fill(self, c, fill: dict | None = "solid"):
        shapes = self._shape_targets()
        if not shapes:
            return
        if c is not None:
            self.last_fill = c
        self.begin_change("Shape Fill")
        for s in shapes:
            if se.is_line(s):
                continue
            if c is None:
                s.fill = None
            elif fill == "solid":
                s.fill = {"type": "solid", "color": c}
            else:
                s.fill = fill
        self.end_change()

    def fill_gradient(self):
        shapes = self._shape_targets()
        if not shapes:
            return
        c = self.last_fill or sm.scheme("accent1")
        light = dict(c, mods=list(c.get("mods", [])) + [["tint", 40000]])
        self.set_fill(c, {"type": "grad", "stops": [[0, light], [100000, c]], "angle": 90.0, "path": None})

    def fill_picture(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Select Picture", self._pictures_dir(),
                                            "Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp)")
        if not fn:
            return
        with open(fn, "rb") as f:
            key = self.pres.add_media(f.read(), fn.rsplit(".", 1)[-1])
        self.set_fill({"rgb": "FFFFFF"}, {"type": "pic", "image": key})

    def set_outline(self, color="keep", width=None, dash=None, head=None, tail=None):
        shapes = self._shape_targets()
        if not shapes:
            return
        self.begin_change("Shape Outline")
        for s in shapes:
            if color is None:
                s.line = None
                continue
            line = dict(s.line or {"color": sm.scheme("accent1", ("shade", 50000)), "width": 9525})
            if color != "keep" and color is not None:
                line["color"] = color
                self.last_outline = color
            if width is not None:
                line["width"] = width
            if dash is not None:
                line["dash"] = dash
            if head is not None:
                line["head"] = head
            if tail is not None:
                line["tail"] = tail
            s.line = line
        self.end_change()

    def apply_quick_style(self, key):
        row, accent = key
        fill, line, text = self._quick_style(row, accent)
        shapes = self._shape_targets()
        if not shapes:
            return
        self.begin_change("Quick Style")
        for s in shapes:
            if s.kind != "sp":
                continue
            if not se.is_line(s):
                s.fill = copy.deepcopy(fill)
            s.line = copy.deepcopy(line)
            s.style_text_color = copy.deepcopy(text)
        self.end_change()

    def arrange(self, how):
        sel = [s for s in self.view.selection if s in self.slide.shapes]
        if not sel:
            return
        self.begin_change("Arrange")
        shapes = self.slide.shapes
        if how == "front":
            for s in sel:
                shapes.remove(s)
                shapes.append(s)
        elif how == "back":
            for s in reversed(sel):
                shapes.remove(s)
                shapes.insert(0, s)
        elif how == "forward":
            for s in sorted(sel, key=shapes.index, reverse=True):
                i = shapes.index(s)
                if i < len(shapes) - 1 and shapes[i + 1] not in sel:
                    shapes[i], shapes[i + 1] = shapes[i + 1], shapes[i]
        elif how == "backward":
            for s in sorted(sel, key=shapes.index):
                i = shapes.index(s)
                if i > 0 and shapes[i - 1] not in sel:
                    shapes[i], shapes[i - 1] = shapes[i - 1], shapes[i]
        self.end_change()

    def _bbox(self, s):
        t = self.renderer.shape_transform(s, flips=False)
        pts = se._shape_poly(s, t)
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def align_shapes(self, how):
        sel = list(self.view.selection)
        if not sel:
            return
        boxes = {id(s): self._bbox(s) for s in sel}
        if len(sel) == 1:
            ref = QRectF(0, 0, sm.pt(self.pres.width), sm.pt(self.pres.height))
        else:
            ref = boxes[id(sel[0])]
            for s in sel[1:]:
                ref = ref.united(boxes[id(s)])
        self.begin_change("Align")
        if how in ("dh", "dv") and len(sel) > 2:
            key = (lambda s: boxes[id(s)].center().x()) if how == "dh" else (lambda s: boxes[id(s)].center().y())
            order = sorted(sel, key=key)
            first, last = key(order[0]), key(order[-1])
            for i, s in enumerate(order):
                target = first + (last - first) * i / (len(order) - 1)
                d = target - key(s)
                if how == "dh":
                    s.x += sm.emu(d)
                else:
                    s.y += sm.emu(d)
        else:
            for s in sel:
                b = boxes[id(s)]
                dx = dy = 0.0
                if how == "l":
                    dx = ref.left() - b.left()
                elif how == "c":
                    dx = ref.center().x() - b.center().x()
                elif how == "r":
                    dx = ref.right() - b.right()
                elif how == "t":
                    dy = ref.top() - b.top()
                elif how == "m":
                    dy = ref.center().y() - b.center().y()
                elif how == "b":
                    dy = ref.bottom() - b.bottom()
                s.x += sm.emu(dx)
                s.y += sm.emu(dy)
        for s in sel:
            s.inherit = False
        self.end_change()

    def rotate(self, deg):
        sel = self.view.selection
        if not sel:
            return
        self.begin_change("Rotate")
        for s in sel:
            s.rot = (s.rot + deg) % 360
            s.inherit = False
        self.end_change()

    def flip(self, axis):
        sel = self.view.selection
        if not sel:
            return
        self.begin_change("Flip")
        for s in sel:
            if axis == "h":
                s.flip_h = not s.flip_h
            else:
                s.flip_v = not s.flip_v
        self.end_change()

    def group(self):
        sel = [s for s in self.view.selection if s in self.slide.shapes]
        if len(sel) < 2:
            return
        self.begin_change("Group")
        box = self._bbox(sel[0])
        for s in sel[1:]:
            box = box.united(self._bbox(s))
        g = sm.Shape(kind="group", name=f"Group {len(self.slide.shapes) + 1}", x=sm.emu(box.x()), y=sm.emu(box.y()),
                     cx=sm.emu(box.width()), cy=sm.emu(box.height()))
        g.child_rect = (g.x, g.y, g.cx, g.cy)
        at = min(self.slide.shapes.index(s) for s in sel)
        for s in sorted(sel, key=self.slide.shapes.index):
            self.slide.shapes.remove(s)
            s.inherit = False
            g.children.append(s)
        self.slide.shapes.insert(at, g)
        self.end_change()
        self.view.select([g])

    def ungroup(self):
        groups = [s for s in self.view.selection if s.kind == "group" and s in self.slide.shapes]
        if not groups:
            return
        self.begin_change("Ungroup")
        new_sel = []
        for g in groups:
            at = self.slide.shapes.index(g)
            self.slide.shapes.remove(g)
            ch = g.child_rect or (g.x, g.y, g.cx, g.cy)
            sx = g.cx / ch[2] if ch[2] else 1.0
            sy = g.cy / ch[3] if ch[3] else 1.0
            gt = self.renderer.shape_transform(g)
            for c in g.children:
                c.x = int(g.x + (c.x - ch[0]) * sx)
                c.y = int(g.y + (c.y - ch[1]) * sy)
                c.cx = int(c.cx * sx)
                c.cy = int(c.cy * sy)
                if g.rot or g.flip_h or g.flip_v:
                    # turn the child's centre with the group
                    cc = QPointF(sm.pt(c.x) + sm.pt(c.cx) / 2 - sm.pt(g.x), sm.pt(c.y) + sm.pt(c.cy) / 2 - sm.pt(g.y))
                    p = gt.map(cc)
                    c.x = sm.emu(p.x() - sm.pt(c.cx) / 2)
                    c.y = sm.emu(p.y() - sm.pt(c.cy) / 2)
                    c.rot = (c.rot + g.rot) % 360
                    c.flip_h ^= g.flip_h
                    c.flip_v ^= g.flip_v
                self.slide.shapes.insert(at, c)
                at += 1
                new_sel.append(c)
        self.end_change()
        self.view.select(new_sel)

    def set_size(self, which):
        sel = self.view.selection
        if len(sel) != 1:
            return
        s = sel[0]
        v = dlg.unit_to_emu((self.h_spin if which == "h" else self.w_spin).value())
        if (s.cy if which == "h" else s.cx) == v:
            return
        self.begin_change("Size")
        if s.kind == "pic":
            k = v / max(1, s.cy if which == "h" else s.cx)
            s.cx, s.cy = int(s.cx * k), int(s.cy * k)
        elif which == "h":
            s.cy = v
        else:
            s.cx = v
        if s.kind == "table":
            self.view._scale_table(s, 1, 1)
        s.inherit = False
        self.end_change()
        self.selection_changed()

    def delete_selection(self):
        if self.view.editing is not None:
            c = self.view.editing.textCursor()
            if c.hasSelection():
                c.removeSelectedText()
            else:
                c.deleteChar()
            return
        sel = [s for s in self.view.selection if s in self.slide.shapes]
        if not sel:
            return
        self.begin_change("Delete")
        for s in sel:
            i = self.slide.shapes.index(s)
            self.slide.shapes.remove(s)
            if s.ph is not None and not (s.text is None or s.text.is_empty()) and s.kind == "sp":
                # deleting a filled placeholder empties it first (PowerPoint)
                empty = sm.placeholder_shape(sm.find_layout_placeholder(self.slide.layout, self.pres.master_of(
                    self.slide), s.ph) or s)
                empty.x, empty.y, empty.cx, empty.cy = s.x, s.y, s.cx, s.cy
                empty.inherit = s.inherit
                self.slide.shapes.insert(i, empty)
        self.end_change()
        self.view.select([])

    def duplicate(self):
        if self.view.editing is not None or not self.view.selection:
            if self.left_tabs.currentIndex() == 0 and self.slides_list.hasFocus():
                self.duplicate_slides()
            return
        self.begin_change("Duplicate")
        clones = []
        for s in self.view.selection:
            c = s.clone()
            c.x += sm.emu(18)
            c.y += sm.emu(18)
            c.inherit = False
            self.slide.shapes.append(c)
            clones.append(c)
        self.end_change()
        self.view.select(clones)

    def _shape_drawn(self):
        page = self.ctx_tabs["format"][0]
        if self.ribbon.indexOf(page) >= 0:
            self.ribbon.setCurrentWidget(page)

    # ==== pictures, tables =========================================================================
    def _pictures_dir(self):
        return self.settings.value("pictures_dir", str(Path.home() / "Pictures"))

    def picture_dialog(self):
        fns, _ = QFileDialog.getOpenFileNames(self, "Insert Picture", self._pictures_dir(),
                                              "All Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp "
                                              "*.heic *.avif *.svg);;All Files (*)")
        if fns:
            self.settings.setValue("pictures_dir", str(Path(fns[0]).parent))
            self.insert_picture_files(fns)

    def insert_picture_files(self, files, pos: QPointF | None = None):
        added = []
        self.begin_change("Insert Picture")
        for fn in files:
            ext = fn.rsplit(".", 1)[-1].lower()
            if ext in ("pptx", "ppt", "ppsx", "pps", "potx", "pptm"):
                continue
            img = QImage(fn)
            if img.isNull():
                continue
            if ext in ("png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff"):
                with open(fn, "rb") as f:
                    data = f.read()
            else:
                from PySide6.QtCore import QBuffer
                buf = QBuffer()
                buf.open(QBuffer.WriteOnly)
                img.save(buf, "PNG")
                data, ext = bytes(buf.data()), "png"
            added.append(self._add_picture(data, ext, img.width(), img.height(), pos,
                                           img.dotsPerMeterX() or 3780))
            if pos is not None:
                pos = pos + QPointF(18, 18)
        self.end_change()
        if added:
            self.view.select(added)

    def insert_image(self, img: QImage, pos: QPointF | None = None):
        from PySide6.QtCore import QBuffer
        buf = QBuffer()
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        self.begin_change("Paste Picture")
        s = self._add_picture(bytes(buf.data()), "png", img.width(), img.height(), pos, 3780)
        self.end_change()
        self.view.select([s])

    def _add_picture(self, data: bytes, ext: str, pw: int, ph: int, pos, dpm: int) -> sm.Shape:
        key = self.pres.add_media(data, ext)
        dpi = max(72.0, min(600.0, dpm * 0.0254))
        w, h = pw / dpi * 72, ph / dpi * 72
        sw_, sh_ = sm.pt(self.pres.width), sm.pt(self.pres.height)
        target = None
        sel = self.view.selection
        if len(sel) == 1 and sel[0].ph is not None and sel[0].ph.type in ("pic", "obj", "body") and \
                (sel[0].text is None or sel[0].text.is_empty()) and sel[0].kind == "sp":
            target = sel[0]
        if target is None:
            empty = [s for s in self.slide.shapes if s.ph is not None and s.ph.type == "pic" and s.kind == "sp"]
            if empty and pos is None:
                target = empty[0]
        s = sm.Shape(kind="pic", name=f"Picture {len(self.slide.shapes) + 1}", image=key)
        if target is not None:
            bw, bh = sm.pt(target.cx), sm.pt(target.cy)
            k = min(bw / w, bh / h)
            if target.ph.type == "pic":
                # a picture placeholder is filled: crop the picture to its shape
                k = max(bw / w, bh / h)
                cw, ch = (w * k - bw) / (w * k), (h * k - bh) / (h * k)
                s.crop = (int(cw / 2 * 100000), int(ch / 2 * 100000), int(cw / 2 * 100000), int(ch / 2 * 100000))
                s.x, s.y, s.cx, s.cy = target.x, target.y, target.cx, target.cy
                s.ph = copy.deepcopy(target.ph)
            else:
                s.cx, s.cy = sm.emu(w * k), sm.emu(h * k)
                s.x = target.x + (target.cx - s.cx) // 2
                s.y = target.y + (target.cy - s.cy) // 2
            i = self.slide.shapes.index(target)
            self.slide.shapes[i] = s
            return s
        k = min(1.0, sw_ * 0.8 / w, sh_ * 0.8 / h)
        w, h = w * k, h * k
        if pos is None:
            x, y = (sw_ - w) / 2, (sh_ - h) / 2
        else:
            x, y = pos.x() - w / 2, pos.y() - h / 2
        s.x, s.y, s.cx, s.cy = sm.emu(x), sm.emu(y), sm.emu(w), sm.emu(h)
        self.slide.shapes.append(s)
        return s

    def picture_double_clicked(self, s):
        if s.ph is not None and s.ph.type == "pic" and not s.image:
            self.view.select([s])
            self.picture_dialog()

    def table_dialog(self):
        d = dlg.TableDialog(self)
        if d.exec() == QDialog.Accepted:
            self.insert_table(d.rows.value(), d.cols.value())

    def insert_table(self, rows, cols):
        if self.slide is None:
            return
        w = self.pres.width - 2 * 457200
        x, y = 457200, int(self.pres.height * 0.25)
        sel = self.view.selection
        target = None
        if len(sel) == 1 and sel[0].ph is not None and sel[0].ph.type in ("obj", "body", "tbl") and \
                (sel[0].text is None or sel[0].text.is_empty()):
            target = sel[0]
        else:
            target = next((s for s in self.slide.shapes if s.ph is not None and s.ph.type in ("obj", "tbl")
                           and s.kind == "sp" and (s.text is None or s.text.is_empty())), None)
        if target is not None:
            x, y, w = target.x, target.y, target.cx
        self.view.end_edit()
        self.begin_change("Insert Table")
        t = se.new_table(rows, cols, x, y, w)
        if target is not None and target in self.slide.shapes:
            self.slide.shapes[self.slide.shapes.index(target)] = t
        else:
            self.slide.shapes.append(t)
        self.end_change()
        self.view.select([t])
        self.view.begin_edit(t, None, (0, 0))

    def _table(self):
        sel = self.view.selection
        if self.view.editing is not None and self.view.editing.cell is not None:
            return self.view.editing.shape, self.view.editing.cell
        if len(sel) == 1 and sel[0].kind == "table":
            if self.view.cell_range is not None:
                r0, c0, r1, c1 = self.view.cell_range[1]
                return sel[0], (min(r0, r1), min(c0, c1))
            return sel[0], (0, 0)
        return None, None

    def table_op(self, op):
        s, cell = self._table()
        if s is None:
            return
        t = s.table
        ri, ci = cell
        rng = self.view.cell_range[1] if self.view.cell_range is not None and self.view.cell_range[0] is s else \
            (ri, ci, ri, ci)
        r0, r1 = sorted((rng[0], rng[2]))
        c0, c1 = sorted((rng[1], rng[3]))
        self.view.end_edit(keep_selection=True)
        self.begin_change("Table")
        if op == "row_above":
            se.add_row(t, r0, below=False)
        elif op == "row_below":
            se.add_row(t, r1, below=True)
        elif op == "col_left":
            se.add_col(t, c0, right=False)
        elif op == "col_right":
            se.add_col(t, c1, right=True)
        elif op == "del_row":
            if len(t.rows) <= r1 - r0 + 1:
                op = "del_table"
            else:
                del t.rows[r0:r1 + 1]
                del t.row_heights[r0:r1 + 1]
        elif op == "del_col":
            if len(t.col_widths) <= c1 - c0 + 1:
                op = "del_table"
            else:
                del t.col_widths[c0:c1 + 1]
                for row in t.rows:
                    del row[c0:c1 + 1]
        elif op == "merge" and (r1 > r0 or c1 > c0):
            first = t.rows[r0][c0]
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    if (r, c) == (r0, c0):
                        continue
                    cell_ = t.rows[r][c]
                    if not cell_.text.is_empty():
                        first.text.paragraphs += cell_.text.paragraphs
                    cell_.text = sm.TextBody()
                    cell_.merged = True
            first.span = c1 - c0 + 1
            first.row_span = r1 - r0 + 1
        elif op == "split":
            first = t.rows[ri][ci]
            for r in range(ri, ri + first.row_span):
                for c in range(ci, ci + first.span):
                    if r < len(t.rows) and c < len(t.rows[r]):
                        t.rows[r][c].merged = False
            first.span = first.row_span = 1
        if op == "del_table":
            self.slide.shapes.remove(s)
            self.end_change()
            self.view.select([])
            return
        s.cx = sum(t.col_widths)
        s.cy = sum(t.row_heights)
        self.view.cell_range = None
        self.end_change()
        self.view.select([s])

    def set_table_flag(self, key, on):
        s, _cell = self._table()
        if s is None:
            return
        self.begin_change("Table Style Options")
        setattr(s.table, key, on)
        self.end_change()
        self._update_table_state(s)

    def set_table_style(self, key):
        s, _cell = self._table()
        if s is None:
            return
        self.begin_change("Table Style")
        s.table.style = key
        for row in s.table.rows:
            for c in row:
                c.fill = "auto"
        self.end_change()
        self._update_table_state(s)

    def set_cell_fill(self, c):
        s, cell = self._table()
        if s is None:
            return
        rng = self.view.cell_range[1] if self.view.cell_range is not None and self.view.cell_range[0] is s else \
            (cell[0], cell[1], cell[0], cell[1])
        self.begin_change("Shading")
        for r in range(min(rng[0], rng[2]), max(rng[0], rng[2]) + 1):
            for col in range(min(rng[1], rng[3]), max(rng[1], rng[3]) + 1):
                s.table.rows[r][col].fill = {"type": "solid", "color": c} if c else None
        self.end_change()

    def clear_cells(self):
        s, (r0, c0, r1, c1) = self.view.cell_range
        self.begin_change("Clear")
        for r in range(min(r0, r1), max(r0, r1) + 1):
            for c in range(min(c0, c1), max(c0, c1) + 1):
                s.table.rows[r][c].text = sm.TextBody()
        self.end_change()

    # ==== slides ===================================================================================
    def new_slide(self, layout_index):
        self.view.end_edit()
        master = self.pres.master_of(self.slide) if self.slide is not None else self.pres.master
        if layout_index is None:
            # PowerPoint: after the title slide comes "Title and Content", otherwise the same layout again
            cur = self.slide.layout if self.slide is not None else None
            if cur is None or cur.type == "title":
                lay = master.layout("obj") or master.layouts[min(1, len(master.layouts) - 1)]
            else:
                lay = cur
        else:
            lay = master.layouts[layout_index]
        self.begin_change("New Slide")
        s = sm.new_slide(self.pres, lay)
        self._apply_footers_to(s)
        self.pres.slides.insert(self.current + 1 if self.pres.slides else 0, s)
        self.current = self.current + 1 if len(self.pres.slides) > 1 else 0
        self.end_change()
        self.rebuild_lists()
        self.go_to(self.current)

    def duplicate_slides(self):
        rows = self._selected_rows()
        if not rows:
            return
        self.begin_change("Duplicate Slide")
        at = max(rows) + 1
        for i in reversed(rows):
            dup = copy.deepcopy(self.pres.slides[i])
            dup.layout = self.pres.slides[i].layout
            for s in sm.walk(dup.shapes):
                s.id = s.clone().id
            self.pres.slides.insert(at, dup)
        self.end_change()
        self.rebuild_lists()
        self.go_to(at)

    def _selected_rows(self) -> list[int]:
        lst = self.sorter if self.stack.currentWidget() is self.sorter else self.slides_list
        rows = sorted({lst.row(it) for it in lst.selectedItems()})
        return rows or ([self.current] if self.slide is not None else [])

    def delete_slides(self):
        rows = self._selected_rows()
        if not rows:
            return
        self.view.end_edit()
        self.begin_change("Delete Slide")
        for i in reversed(rows):
            del self.pres.slides[i]
        self.end_change()
        self.current = min(rows[0], len(self.pres.slides) - 1)
        self.rebuild_lists()
        self.go_to(max(0, self.current))

    def _slides_moved(self, order):
        self.begin_change("Move Slides")
        cur_slide = self.slide
        self.pres.slides = [self.pres.slides[i] for i in order]
        self.end_change()
        self.current = next((i for i, s in enumerate(self.pres.slides) if s is cur_slide), 0)
        self.rebuild_lists()
        self.go_to(self.current)

    def toggle_hide_slide(self, on=None):
        rows = self._selected_rows()
        if not rows:
            return
        self.begin_change("Hide Slide")
        val = not self.pres.slides[rows[0]].hidden if on is None else on
        for i in rows:
            self.pres.slides[i].hidden = val
        self.end_change()
        self.rebuild_lists()

    def apply_layout(self, layout_index):
        if self.slide is None:
            return
        self.view.end_edit()
        master = self.pres.master_of(self.slide)
        lay = master.layouts[layout_index]
        rows = self._selected_rows()
        self.begin_change("Layout")
        for i in rows:
            self._relayout(self.pres.slides[i], lay)
        self.end_change()
        self.view.select([])
        self.rebuild_lists()

    def _relayout(self, slide: sm.Slide, lay: sm.Layout):
        """Move the content of the slide's placeholders into the new layout's placeholders."""
        old = [s for s in slide.shapes if s.ph is not None and s.ph.type not in ("dt", "ftr", "sldNum")]
        others = [s for s in slide.shapes if s not in old]
        slide.layout = lay
        new_shapes = []
        titles = [s for s in old if s.ph.type in ("title", "ctrTitle")]
        bodies = [s for s in old if s.ph.type not in ("title", "ctrTitle")]
        for lph in lay.placeholders:
            if lph.ph.type in ("dt", "ftr", "sldNum"):
                continue
            src = None
            if lph.ph.type in ("title", "ctrTitle") and titles:
                src = titles.pop(0)
            elif lph.ph.type not in ("title", "ctrTitle") and bodies:
                src = bodies.pop(0)
            ns = sm.placeholder_shape(lph)
            if src is not None:
                if src.kind != "sp":
                    src.x, src.y, src.cx, src.cy = lph.x, lph.y, lph.cx, lph.cy
                    new_shapes.append(src)
                    continue
                ns.text = src.text
                if ns.text is not None:
                    ns.text.anchor = lph.text.anchor if lph.text else ns.text.anchor
                    ns.text.autofit = lph.text.autofit if lph.text else ns.text.autofit
                ns.id = src.id
            new_shapes.append(ns)
        for s in titles + bodies:          # content with no place in the new layout stays
            if (s.text is not None and not s.text.is_empty()) or s.kind != "sp":
                s.inherit = False
                new_shapes.append(s)
        slide.shapes = new_shapes + others

    def reset_slide(self):
        if self.slide is None:
            return
        self.view.end_edit()
        self.begin_change("Reset Slide")
        master = self.pres.master_of(self.slide)
        for s in self.slide.shapes:
            if s.ph is None:
                continue
            lph = sm.find_layout_placeholder(self.slide.layout, master, s.ph)
            if lph is not None:
                s.x, s.y, s.cx, s.cy = lph.x, lph.y, lph.cx, lph.cy
                s.rot = 0
                s.inherit = True
            s.fill, s.line = (copy.deepcopy(lph.fill), copy.deepcopy(lph.line)) if lph is not None else (None, None)
            if s.text is not None:
                for par in s.text.paragraphs:
                    for k in ("align", "marL", "indent", "bullet", "space_before", "space_after", "line_spacing"):
                        setattr(par, k, None)
                    for r in par.runs:
                        for k in ("font", "size", "bold", "italic", "underline", "strike", "color", "caps"):
                            setattr(r, k, None)
                        r.baseline = 0
                if lph is not None and lph.text is not None:
                    s.text.anchor = lph.text.anchor
                    s.text.autofit = lph.text.autofit
                s.text.font_scale, s.text.line_reduction = 1.0, 0.0
        self.slide.background = None
        self.end_change()

    def slides_menu(self, lst, pos):
        m = QMenu(self)
        m.addAction(self.a_cut)
        m.addAction(self.a_copy)
        m.addAction(self.a_paste)
        m.addSeparator()
        m.addAction(self.a_new_slide)
        m.addAction(self.a_dup_slide)
        m.addAction("Delete Slide", self.delete_slides)
        m.addSeparator()
        lm = m.addMenu("Layout")
        master = self.pres.master_of(self.slide) if self.slide else self.pres.master
        for i, lay in enumerate(master.layouts):
            lm.addAction(lay.name, lambda i=i: self.apply_layout(i))
        m.addAction("Format Background...", self.format_background)
        m.addSeparator()
        m.addAction(self.a_hide_slide)
        m.exec(lst.viewport().mapToGlobal(pos))

    # ==== design ===================================================================================
    def apply_design(self, key):
        self.view.end_edit()
        self.begin_change("Theme")
        for m in self.pres.masters:
            sd.apply_design(m, key, self.pres.width, self.pres.height)
        for s in self.pres.slides:
            s.background = None
        self.end_change()
        self.renderer.forget_images()
        self.rebuild_lists()
        self._fill_fonts()

    def set_theme_colors(self, name):
        self.begin_change("Theme Colors")
        sd.set_colors(self.pres.master_of(self.slide) if self.slide else self.pres.master, name)
        self.end_change()
        self.rebuild_lists()

    def set_theme_fonts(self, name):
        self.begin_change("Theme Fonts")
        sd.set_fonts(self.pres.master_of(self.slide) if self.slide else self.pres.master, name)
        self.end_change()
        self._fill_fonts()
        self.rebuild_lists()

    def apply_background_style(self, i):
        label, fill = sd.background_styles()[i]
        self.begin_change("Background Style")
        master = self.pres.master_of(self.slide) if self.slide else self.pres.master
        master.background = copy.deepcopy(fill)
        for lay in master.layouts:
            lay.background = None
        for s in self.pres.slides:
            s.background = None
        self.end_change()
        self.rebuild_lists()

    def format_background(self):
        if self.slide is None:
            return
        master = self.pres.master_of(self.slide)
        cur = self.slide.background or (self.slide.layout.background if self.slide.layout else None) or \
            master.background
        d = dlg.FormatBackgroundDialog(self, cur, self.slide.hide_master_shapes)
        if d.exec() != QDialog.Accepted:
            return
        self.begin_change("Format Background")
        targets = self.pres.slides if d.all else [self.slide]
        for s in targets:
            s.hide_master_shapes = d.hide.isChecked()
            s.background = None if d.reset else d.result_fill()
        self.end_change()
        self.rebuild_lists()

    def reset_background(self):
        if self.slide is not None:
            self.begin_change("Reset Background")
            self.slide.background = None
            self.end_change()

    def toggle_hide_bg(self, on):
        if self.slide is None:
            return
        self.begin_change("Hide Background Graphics")
        self.slide.hide_master_shapes = on
        self.end_change()

    def page_setup(self):
        d = dlg.PageSetupDialog(self.pres, self)
        if d.exec() == QDialog.Accepted:
            self.resize_slides(*d.size())

    def set_orientation(self, portrait):
        w, h = self.pres.width, self.pres.height
        if (portrait and w > h) or (not portrait and h > w):
            self.resize_slides(h, w)

    def resize_slides(self, w, h):
        ow, oh = self.pres.width, self.pres.height
        if (w, h) == (ow, oh):
            return
        self.view.end_edit()
        self.begin_change("Page Setup")
        kx, ky = w / ow, h / oh
        k = min(kx, ky)

        def scale(shapes, uniform=False):
            for s in shapes:
                s.x, s.y = int(s.x * kx), int(s.y * ky)
                if s.kind == "pic" or uniform:
                    cx, cy = int(s.cx * k), int(s.cy * k)
                    s.x += (int(s.cx * kx) - cx) // 2
                    s.y += (int(s.cy * ky) - cy) // 2
                    s.cx, s.cy = cx, cy
                else:
                    s.cx, s.cy = int(s.cx * kx), int(s.cy * ky)
                if s.kind == "table" and s.table is not None:
                    s.table.col_widths = [int(c * kx) for c in s.table.col_widths]
        for m in self.pres.masters:
            scale(m.shapes)
            scale(m.placeholders)
            for lay in m.layouts:
                scale(lay.shapes)
                scale(lay.placeholders)
        for sl in self.pres.slides:
            scale([s for s in sl.shapes])
        self.pres.width, self.pres.height = w, h
        self.end_change()
        self.renderer = sr.Renderer(self.pres)
        self.view.set_presentation(self.pres, self.renderer)
        self.rebuild_lists()
        self.go_to(self.current)

    def header_footer(self):
        d = dlg.HeaderFooterDialog(self.pres, self)
        if d.exec() != QDialog.Accepted:
            return
        self.begin_change("Header and Footer")
        self.pres.footer.update(d.values())
        for s in (self.pres.slides if d.all else [self.slide]):
            self._apply_footers_to(s)
        self.end_change()
        self.rebuild_lists()

    def _apply_footers_to(self, s: sm.Slide):
        f = self.pres.footer
        master = self.pres.master_of(s)
        on_title = s.layout is not None and s.layout.type == "title" and f.get("not_on_title")
        for kind, want in (("dt", f.get("date")), ("ftr", f.get("footer")), ("sldNum", f.get("number"))):
            have = [x for x in s.shapes if x.ph is not None and x.ph.type == kind]
            if not want or on_title:
                for x in have:
                    s.shapes.remove(x)
                continue
            src = sm.find_layout_placeholder(s.layout, master, sm.Placeholder(kind, {"dt": 10, "ftr": 11,
                                                                                      "sldNum": 12}[kind]))
            if src is None:
                src = next((x for x in sm.master_footers(self.pres.width, self.pres.height) if x.ph.type == kind), None)
            shape = have[0] if have else sm.placeholder_shape(src)
            shape.ph = copy.deepcopy(src.ph)
            if kind == "dt":
                run = sm.Run(text=f.get("date_text", ""), field="datetime" if f.get("date_auto") else None)
            elif kind == "ftr":
                run = sm.Run(text=f.get("footer_text", ""))
            else:
                run = sm.Run(text="‹#›", field="slidenum")
            shape.text = sm.TextBody(anchor="ctr", paragraphs=[sm.Paragraph(runs=[run])])
            if not have:
                s.shapes.append(shape)

    # ==== animations ===============================================================================
    def set_transition(self, typ, d):
        rows = self._selected_rows()
        self.begin_change("Transition")
        for i in rows:
            t = self.pres.slides[i].transition
            t.type = typ
            t.through_black = typ == "fade" and d == "black"
            t.dir = "" if t.through_black else d
        self.end_change()
        self.update_slide_state()
        self.rebuild_lists()

    def set_transition_speed(self, speed):
        self.begin_change("Transition Speed")
        for i in self._selected_rows():
            self.pres.slides[i].transition.speed = speed
        self.end_change()

    def transition_to_all(self):
        if self.slide is None:
            return
        self.begin_change("Apply To All")
        for s in self.pres.slides:
            s.transition = copy.deepcopy(self.slide.transition)
        self.end_change()
        self.rebuild_lists()

    def set_advance(self):
        self.begin_change("Advance Slide")
        for i in self._selected_rows():
            t = self.pres.slides[i].transition
            t.on_click = self.adv_click.isChecked()
            t.after_ms = int(self.adv_time.value() * 1000) if self.adv_after.isChecked() else None
        self.end_change()
        self.rebuild_lists()

    def set_animation(self, effect):
        sel = self.view.selection
        if not sel:
            return
        self.begin_change("Animation")
        orders = [s.anim.get("order", 0) for s in self.slide.shapes if s.anim]
        nxt = max(orders, default=0) + 1
        for s in sel:
            if effect == "none":
                s.anim = None
            else:
                s.anim = {"effect": effect, "trigger": "click", "order": (s.anim or {}).get("order", nxt)}
                nxt += 1
        self.end_change()

    # ==== slide show ===============================================================================
    def start_show(self, index=0, single=False):
        if not self.pres.slides:
            return
        self.view.end_edit()
        from show_slideshow import SlideShow
        o = self.show_opts
        first = o["first"] - 1 if o.get("range") else None
        last = o["last"] - 1 if o.get("range") else None
        if single:
            first = last = index
        self.slideshow = SlideShow(self.pres, index, loop=self.pres.show_loop and not single,
                                   use_timings=o.get("timings", True), first=first, last=last)
        self.slideshow.finished.connect(self._show_done)
        self.slideshow.start()

    def _show_done(self, last):
        self.slideshow = None
        if self.isVisible():
            self.go_to(last)
            self.activateWindow()
        elif not any(isinstance(w, ShowWindow) and w.isVisible() for w in QApplication.topLevelWidgets()):
            QApplication.quit()

    def setup_show(self):
        d = dlg.SetUpShowDialog(self.pres, self.show_opts, self)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            if v["loop"] != self.pres.show_loop:
                self.pres.show_loop = v["loop"]
                self.modified = True
            self.show_opts.update(v)

    # ==== view =====================================================================================
    def set_view(self, which):
        self.view.end_edit()
        self._update_current_thumb()
        if which == "sorter":
            self.stack.setCurrentWidget(self.sorter)
            if getattr(self, "_sorter_dirty", True):
                self.rebuild_lists()
            self.a_sorter.setChecked(True)
            self.sorter.setCurrentRow(self.current)
        else:
            self.stack.setCurrentWidget(self.normal)
            self.a_normal.setChecked(True)
            self.go_to(self.current)

    def toggle_grid(self, on):
        self.view.grid = on
        self.view.refresh()

    def toggle_spelling(self, on):
        self.settings.setValue("spelling", on)
        if self.view.speller is not None:
            self.view.speller.enabled = on
            if self.view.speller.document() is not None:
                self.view.speller.rehighlight()

    def zoom_dialog(self):
        d = dlg.ZoomDialog(self.view.zoom_percent(), self)
        if d.exec() == QDialog.Accepted:
            if d.fit.isChecked():
                self.view.zoom_fit()
            else:
                self.view.set_zoom_percent(d.pct.value())

    def _zoom_changed(self, _z):
        pct = self.view.zoom_percent()
        self.zoom_label.setText(f"{pct}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(pct)
        self.zoom_slider.blockSignals(False)

    def _zoom_slider(self, v):
        self.view.set_zoom_percent(v)

    # ==== clipboard ================================================================================
    def copy(self):
        ed = self.view.editing
        if ed is not None:
            c = ed.textCursor()
            if c.hasSelection():
                QApplication.clipboard().setText(c.selectedText().replace(" ", "\n").replace(" ", "\n"))
            return
        if self.slides_list.hasFocus() or self.stack.currentWidget() is self.sorter:
            self.copy_slides()
            return
        sel = self.view.selection
        if not sel:
            return
        shapes = copy.deepcopy(sel)
        media = {}
        for s in sm.walk(shapes):
            for key in (s.image, (s.fill or {}).get("image") if isinstance(s.fill, dict) else None):
                if key and key in self.pres.media:
                    media[key] = self.pres.media[key]
        md = QMimeData()
        md.setData(MIME_SHAPES, QByteArray(pickle.dumps({"shapes": shapes, "media": media})))
        texts = [s.text.plain() for s in sm.walk(sel) if s.text is not None and not s.text.is_empty()]
        if texts:
            md.setText("\n".join(texts).replace("\v", "\n"))
        if len(sel) == 1 and sel[0].kind == "pic":
            img = self.renderer.image(sel[0].image)
            if not img.isNull():
                md.setImageData(img)
        QApplication.clipboard().setMimeData(md)

    def copy_slides(self):
        rows = self._selected_rows()
        if not rows:
            return
        slides = copy.deepcopy([self.pres.slides[i] for i in rows])
        media = dict(self.pres.media)
        for s in slides:
            s.layout_name = s.layout.name if s.layout else ""
            s.layout = None
        md = QMimeData()
        md.setData(MIME_SLIDES, QByteArray(pickle.dumps({"slides": slides, "media": media})))
        QApplication.clipboard().setMimeData(md)

    def cut(self):
        ed = self.view.editing
        if ed is not None:
            self.copy()
            ed.textCursor().removeSelectedText()
            return
        self.copy()
        if self.slides_list.hasFocus() or self.stack.currentWidget() is self.sorter:
            self.delete_slides()
        else:
            self.delete_selection()

    def paste(self):
        md = QApplication.clipboard().mimeData()
        if md is None:
            return
        ed = self.view.editing
        if ed is not None:
            if md.hasImage() and not md.hasText():
                self.view.end_edit()
                self.insert_image(QImage(md.imageData()))
                return
            text = md.text().replace("\r\n", "\n")
            if text:
                c = ed.textCursor()
                c.insertText(text.replace("\n", " ") if "\n" not in text else "")
                if "\n" in text:
                    lines = text.split("\n")
                    for i, line in enumerate(lines):
                        if i:
                            c.insertBlock()
                        c.insertText(line)
                ed.setTextCursor(c)
            return
        if md.hasFormat(MIME_SLIDES):
            data = pickle.loads(bytes(md.data(MIME_SLIDES)))
            self.begin_change("Paste Slides")
            master = self.pres.master_of(self.slide) if self.slide else self.pres.master
            at = self.current + 1
            for s in data["slides"]:
                s.layout = master.layout(getattr(s, "layout_name", "")) or master.layout("obj") or master.layouts[0]
                for k, v in data["media"].items():
                    self.pres.media.setdefault(k, v)
                for x in sm.walk(s.shapes):
                    x.id = x.clone().id
                self.pres.slides.insert(at, s)
                at += 1
            self.end_change()
            self.rebuild_lists()
            self.go_to(at - 1)
            return
        if md.hasFormat(MIME_SHAPES) and self.slide is not None:
            data = pickle.loads(bytes(md.data(MIME_SHAPES)))
            self.begin_change("Paste")
            for k, v in data["media"].items():
                self.pres.media.setdefault(k, v)
            new = []
            existing = {(s.x, s.y, s.cx, s.cy) for s in self.slide.shapes}
            for s in data["shapes"]:
                c = s.clone()
                c.inherit = False
                while (c.x, c.y, c.cx, c.cy) in existing:
                    c.x += sm.emu(18)
                    c.y += sm.emu(18)
                self.slide.shapes.append(c)
                new.append(c)
            self.end_change()
            self.view.select(new)
            return
        if md.hasImage():
            self.insert_image(QImage(md.imageData()))
            return
        if md.hasUrls():
            files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            if files:
                self.insert_picture_files(files)
                return
        if md.hasText() and self.slide is not None:
            self.paste_text()

    def paste_text(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        ed = self.view.editing
        if ed is not None:
            ed.textCursor().insertText(text.replace("\r\n", "\n").replace("\n", " "))
            return
        self.begin_change("Paste")
        tb = sm.Shape(kind="sp", txbox=True, name="TextBox", x=sm.emu(72), y=sm.emu(108),
                      cx=self.pres.width - sm.emu(144), cy=sm.emu(40))
        tb.text = sm.TextBody(wrap=True, autofit="shape",
                              paragraphs=[sm.Paragraph(runs=[sm.Run(text=line)]) for line in text.splitlines() or [""]])
        self.slide.shapes.append(tb)
        self.view.autosize(tb)
        self.end_change()
        self.view.select([tb])

    def format_painter(self, on):
        if not on:
            self.painter_format = None
            return
        run = self._current_run_props()
        sel = self.view.selection
        shape = sel[0] if len(sel) == 1 else None
        self.painter_format = {"run": {k: v for k, v in (run[0] if run else {}).items()
                                       if k in ("font", "size", "bold", "italic", "underline", "color")},
                               "fill": copy.deepcopy(shape.fill) if shape else None,
                               "line": copy.deepcopy(shape.line) if shape else None,
                               "text_color": copy.deepcopy(shape.style_text_color) if shape else None,
                               "shape": shape is not None and self.view.editing is None}
        self.view.selectionChanged.connect(self._apply_painter)

    def _apply_painter(self):
        try:
            self.view.selectionChanged.disconnect(self._apply_painter)
        except (RuntimeError, TypeError):
            pass
        pf = self.painter_format
        self.painter_format = None
        self.a_painter.setChecked(False)
        if not pf or not self.view.selection:
            return
        QTimer.singleShot(0, lambda: self._paint_format(pf))

    def _paint_format(self, pf):
        if pf.get("shape"):
            self.begin_change("Format Painter")
            for s in self.view.selection:
                if s.kind == "sp":
                    s.fill, s.line = copy.deepcopy(pf["fill"]), copy.deepcopy(pf["line"])
                    s.style_text_color = copy.deepcopy(pf["text_color"])
            self.end_change()
        for k, v in pf["run"].items():
            if v is not None:
                self.set_run(k, v)

    # ==== find =====================================================================================
    def show_find(self, replace):
        if self.find_dialog is None:
            self.find_dialog = dlg.FindDialog(self, replace)
        self.find_dialog.set_mode(replace)
        self.find_dialog.show()
        self.find_dialog.raise_()

    def _find_iter(self, start_slide, start_shape):
        n = len(self.pres.slides)
        for k in range(n + 1):
            si = (start_slide + k) % n
            shapes = [s for s in self.pres.slides[si].shapes if s.kind == "sp" and s.text is not None]
            for j, s in enumerate(shapes):
                if k == 0 and j < start_shape:
                    continue
                yield si, s

    def find_next(self, d) -> bool:
        from PySide6.QtGui import QTextDocument
        what = d.what.text()
        if not what or not self.pres.slides:
            return False
        flags = QTextDocument.FindFlag(0)
        if d.case.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if d.whole.isChecked():
            flags |= QTextDocument.FindWholeWords
        ed = self.view.editing
        if ed is not None:
            found = ed.document().find(what, ed.textCursor(), flags)
            if not found.isNull():
                ed.setTextCursor(found)
                return True
            cur_shape = ed.shape
            self.view.end_edit(keep_selection=True)
        else:
            cur_shape = None
        shapes = self.slide.shapes if self.slide else []
        start_shape = (shapes.index(cur_shape) + 1) if cur_shape in shapes else 0
        start_shape = len([s for s in shapes[:start_shape] if s.kind == "sp" and s.text is not None])
        for si, s in self._find_iter(self.current, start_shape):
            txt = s.text.plain()
            if (what in txt) if d.case.isChecked() else (what.lower() in txt.lower()):
                self.go_to(si)
                self.view.select([s], emit=False)
                self.view.begin_edit(s)
                ed = self.view.editing
                c = QTextCursor(ed.document())
                found = ed.document().find(what, c, flags)
                if not found.isNull():
                    ed.setTextCursor(found)
                    return True
                self.view.end_edit()
        QMessageBox.information(self, APP, "PowerPoint has finished searching the presentation. "
                                "The search item wasn't found." .replace("PowerPoint", APP))
        return False

    def replace_one(self, d):
        ed = self.view.editing
        if ed is not None and ed.textCursor().hasSelection():
            sel = ed.textCursor().selectedText()
            match = sel == d.what.text() if d.case.isChecked() else sel.lower() == d.what.text().lower()
            if match:
                ed.textCursor().insertText(d.with_.text())
        self.find_next(d)

    def replace_all(self, d):
        what, with_ = d.what.text(), d.with_.text()
        if not what:
            return
        self.view.end_edit()
        import re
        pat = re.compile((r"\b%s\b" if d.whole.isChecked() else "%s") % re.escape(what),
                         0 if d.case.isChecked() else re.IGNORECASE)
        n = 0
        self.begin_change("Replace All")
        for s in self.pres.slides:
            for sh in sm.walk(s.shapes):
                bodies = [sh.text] if sh.text is not None else []
                if sh.kind == "table" and sh.table is not None:
                    bodies += [c.text for row in sh.table.rows for c in row]
                for b in bodies:
                    for par in b.paragraphs:
                        for r in par.runs:
                            new, k = pat.subn(with_, r.text)
                            if k:
                                r.text = new
                                n += k
        self.end_change()
        self.rebuild_lists()
        QMessageBox.information(self, APP, f"{APP} replaced {n} item(s).")

    # ==== context menu =============================================================================
    def context_menu(self, pos):
        m = QMenu(self)
        m.addAction(self.a_cut)
        m.addAction(self.a_copy)
        m.addAction(self.a_paste)
        sel = self.view.selection
        if self.view.editing is not None:
            m.addSeparator()
            m.addAction(self.a_link)
            ed = self.view.editing
            sp = self.view.speller
            if sp is not None and sp.enabled:
                c = ed.textCursor()
                c.select(QTextCursor.WordUnderCursor)
                word = c.selectedText()
                if word and not sp.ok(word):
                    m.addSeparator()
                    for sug in sp.suggest(word)[:6]:
                        m.addAction(sug, lambda sug=sug, c=QTextCursor(c): (c.insertText(sug), ed.update()))
                    m.addAction("Add to Dictionary", lambda w=word: sp.add(w))
        elif sel:
            m.addSeparator()
            if len(sel) > 1:
                m.addAction(self.a_group)
            if any(s.kind == "group" for s in sel):
                m.addAction(self.a_ungroup)
            om = m.addMenu("Order")
            for a in (self.a_front, self.a_back, self.a_forward, self.a_backward):
                om.addAction(a)
            m.addAction(self.a_link)
            if len(sel) == 1 and sel[0].kind == "pic":
                m.addAction("Change Picture...", self.change_picture)
                m.addAction("Save as Picture...", self.save_picture)
            if len(sel) == 1 and sel[0].kind == "table":
                tm = m.addMenu("Table")
                for label, op in (("Insert Rows Above", "row_above"), ("Insert Rows Below", "row_below"),
                                  ("Insert Columns to the Left", "col_left"), ("Insert Columns to the Right", "col_right"),
                                  ("Delete Rows", "del_row"), ("Delete Columns", "del_col"), ("Merge Cells", "merge"),
                                  ("Split Cells", "split")):
                    tm.addAction(label, lambda op=op: self.table_op(op))
            m.addSeparator()
            m.addAction(self.a_delete)
        else:
            m.addSeparator()
            lm = m.addMenu("Layout")
            master = self.pres.master_of(self.slide) if self.slide else self.pres.master
            for i, lay in enumerate(master.layouts):
                lm.addAction(lay.name, lambda i=i: self.apply_layout(i))
            m.addAction(self.a_reset)
            m.addSeparator()
            m.addAction(self.a_grid)
            m.addAction("Format Background...", self.format_background)
        m.exec(pos)

    def change_picture(self):
        sel = self.view.selection
        if len(sel) != 1 or sel[0].kind != "pic":
            return
        fn, _ = QFileDialog.getOpenFileName(self, "Insert Picture", self._pictures_dir(),
                                            "Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp)")
        if not fn:
            return
        img = QImage(fn)
        if img.isNull():
            return
        with open(fn, "rb") as f:
            key = self.pres.add_media(f.read(), fn.rsplit(".", 1)[-1])
        s = sel[0]
        self.begin_change("Change Picture")
        s.image = key
        s.crop = (0, 0, 0, 0)
        k = min(s.cx / max(1, img.width()), s.cy / max(1, img.height()))
        cx, cy = int(img.width() * k), int(img.height() * k)
        s.x += (s.cx - cx) // 2
        s.y += (s.cy - cy) // 2
        s.cx, s.cy = cx, cy
        self.end_change()

    def save_picture(self):
        sel = self.view.selection
        if len(sel) != 1 or sel[0].kind != "pic" or sel[0].image not in self.pres.media:
            return
        ext = sel[0].image.rsplit(".", 1)[-1]
        fn, _ = QFileDialog.getSaveFileName(self, "Save As Picture", str(Path.home() / f"Picture.{ext}"),
                                            f"{ext.upper()} (*.{ext})")
        if fn:
            Path(fn).write_bytes(self.pres.media[sel[0].image])

    # ==== files ====================================================================================
    def maybe_save(self) -> bool:
        if not self.modified:
            return True
        name = Path(self.path).name if self.path else self.untitled
        ans = QMessageBox.question(self, APP, f"Do you want to save the changes you made to {name}?",
                                   QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if ans == QMessageBox.Yes:
            return self.file_save()
        return ans == QMessageBox.No

    def is_blank(self) -> bool:
        return not self.modified and self.path is None and len(self.pres.slides) == 1 and \
            all(s.text is None or s.text.is_empty() for s in self.pres.slides[0].shapes)

    def file_new(self):
        w = ShowWindow()
        w.show()

    def file_open(self):
        start = str(Path(self.path).parent) if self.path else str(Path.home() / "Documents")
        fn, _ = QFileDialog.getOpenFileName(self, "Open", start, OPEN_FILTER)
        if fn:
            self.open_maybe_new(fn)

    def open_maybe_new(self, path):
        if self.is_blank():
            self.open_path(path)
        else:
            w = ShowWindow(path)
            w.show()

    def open_path(self, path: str, start_show: bool = False):
        ext = Path(path).suffix.lower()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if ext in (".ppt", ".pps", ".pot") or _is_ole(path):
                import show_ppt
                pres = show_ppt.read_ppt(path)
                self.path = None
                self.untitled = Path(path).stem
                self.converted_from = path
            else:
                pres = spx.read_pptx(path)
                self.path = path if ext in (".pptx", ".pptm", ".ppsx", ".ppsm") else None
                if ext in (".potx", ".potm"):
                    self.untitled = Path(path).stem
                self.save_kind = "show" if ext in (".ppsx", ".ppsm") else "pres"
        except Exception as e:   # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP, f"{APP} can't open {Path(path).name}.\n\n{e}")
            return
        QApplication.restoreOverrideCursor()
        if not pres.slides:
            pres.slides.append(sm.new_slide(pres, pres.master.layout("title") or pres.master.layouts[0]))
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.current = 0
        self.load_presentation(pres)
        self.modified = False
        self._add_recent(path)
        self._update_title()
        if ext in (".pptm", ".ppsm", ".potm"):
            self.statusBar().showMessage("Macros in this file are not run, and are not kept when you save.", 8000)
        if start_show or ext in (".ppsx", ".pps", ".ppsm"):
            QTimer.singleShot(200, lambda: self.start_show(0))

    def file_save(self) -> bool:
        if self.path is None:
            return self.file_save_as()
        return self.write_to(self.path)

    def file_save_as(self, ext: str | None = None) -> bool:
        filters = ";;".join(label for label, _e in SAVE_TYPES)
        chosen = next((label for label, e in SAVE_TYPES if e == ext), SAVE_TYPES[0][0])
        base = Path(self.path).stem if self.path else self.untitled
        folder = Path(self.path).parent if self.path else Path.home() / "Documents"
        fn, flt = QFileDialog.getSaveFileName(self, "Save As", str(folder / (base + (ext or ".pptx"))), filters, chosen)
        if not fn:
            return False
        ext = next((e for label, e in SAVE_TYPES if label == flt), None) or Path(fn).suffix.lower() or ".pptx"
        if not fn.lower().endswith(ext):
            fn += ext
        if ext in (".pdf",):
            return self.export_pdf(fn)
        if ext in (".png", ".jpg"):
            return self.export_pictures(fn, ext)
        ok = self.write_to(fn, kind={".ppsx": "show", ".potx": "template"}.get(ext, "pres"))
        if ok and ext in (".pptx", ".ppsx"):
            self.path = fn
            self.save_kind = "show" if ext == ".ppsx" else "pres"
            self._update_title()
            self._add_recent(fn)
        return ok

    def write_to(self, path: str, kind: str | None = None) -> bool:
        self.view.end_edit(keep_selection=True)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            spx.write_pptx(self.pres, path, kind or self.save_kind)
        except Exception as e:   # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP, f"The presentation couldn't be saved.\n\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        self.modified = False
        self.statusBar().showMessage(f"Saved {Path(path).name}", 4000)
        return True

    def export_pdf(self, path: str, indexes: list | None = None) -> bool:
        from PySide6.QtPrintSupport import QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPageSize(QSizeF(sm.pt(self.pres.width), sm.pt(self.pres.height)), QPageSize.Point,
                                      "Slide"))
        printer.setPageOrientation(QPageLayout.Portrait)
        printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
        printer.setFullPage(True)
        printer.setDocName(Path(path).stem)
        p = QPainter()
        if not p.begin(printer):
            QMessageBox.warning(self, APP, "The PDF file couldn't be written.")
            return False
        first = True
        for i in indexes if indexes is not None else range(len(self.pres.slides)):
            s = self.pres.slides[i]
            if s.hidden and indexes is None:
                continue
            if not first:
                printer.newPage()
            first = False
            page = printer.pageRect(QPrinter.DevicePixel)
            k = page.width() / sm.pt(self.pres.width)
            p.save()
            p.scale(k, k)
            self.renderer.paint_slide(p, s, i + 1)
            p.restore()
        p.end()
        self.statusBar().showMessage(f"Saved {Path(path).name}", 4000)
        return True

    def export_pictures(self, path: str, ext: str) -> bool:
        ans = QMessageBox.question(self, APP, "Do you want to export every slide in the presentation or only the "
                                   "current slide?", QMessageBox.YesAll | QMessageBox.Yes | QMessageBox.Cancel)
        if ans == QMessageBox.Cancel:
            return False
        width = 1280
        if ans == QMessageBox.Yes:
            self.renderer.thumbnail(self.slide, width, self.current + 1).save(path)
            return True
        folder = Path(path).with_suffix("")
        folder.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(self.pres.slides):
            self.renderer.thumbnail(s, width, i + 1).save(str(folder / f"Slide{i + 1}{ext}"))
        QMessageBox.information(self, APP, f"Each slide in your presentation has been saved as a separate file in "
                                f"the folder {folder}.")
        return True

    def send_by_mail(self, ext=".pptx"):
        tmpdir = Path(tempfile.mkdtemp(prefix="classic7-show-"))
        name = (Path(self.path).stem if self.path else self.untitled) + ext
        target = str(tmpdir / name)
        ok = self.export_pdf(target) if ext == ".pdf" else self.write_to(target)
        if ext != ".pdf":
            self.modified = True if self.path is None else self.modified
        if not ok:
            return
        mail = shutil.which("classic7-mail") or "classic7-mail"
        try:
            subprocess.Popen([mail, "--compose", "--attach", target], start_new_session=True)
        except OSError as e:
            QMessageBox.warning(self, APP, f"Mail couldn't be started.\n\n{e}")

    # ==== printing =================================================================================
    def file_print(self):
        d = dlg.PrintDialog(self.pres, self.current, self)
        if d.exec() != QDialog.Accepted:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(Path(self.path).stem if self.path else self.untitled)
        if d.what.currentIndex() == 0 and self.pres.width > self.pres.height:
            printer.setPageOrientation(QPageLayout.Landscape)
        pd = QPrintDialog(printer, self)
        if pd.exec() != QDialog.Accepted:
            return
        self.print_document(printer, d)

    def file_preview(self):
        from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
        d = dlg.PrintDialog(self.pres, self.current, self, "Print Preview")
        if d.exec() != QDialog.Accepted:
            return
        printer = QPrinter(QPrinter.HighResolution)
        if d.what.currentIndex() == 0 and self.pres.width > self.pres.height:
            printer.setPageOrientation(QPageLayout.Landscape)
        pv = QPrintPreviewDialog(printer, self)
        pv.paintRequested.connect(lambda pr: self.print_document(pr, d))
        pv.resize(1000, 800)
        pv.exec()

    def print_document(self, printer, d):
        from PySide6.QtPrintSupport import QPrinter
        idx = [i for i in d.indexes() if d.hidden.isChecked() or not self.pres.slides[i].hidden or
               d.r_current.isChecked()]
        what = d.what.currentIndex()
        gray = d.color.currentIndex()
        p = QPainter()
        if not p.begin(printer):
            return
        page = QRectF(printer.pageRect(QPrinter.DevicePixel))
        page.moveTo(0, 0)
        sw_, sh_ = sm.pt(self.pres.width), sm.pt(self.pres.height)

        def slide_img(i, w_px):
            img = self.renderer.thumbnail(self.pres.slides[i], int(w_px), i + 1)
            if gray:
                img = img.convertToFormat(QImage.Format_Grayscale8)
                if gray == 2:
                    img = img.convertToFormat(QImage.Format_Mono, Qt.ThresholdDither)
            return img

        def place(i, box: QRectF):
            k = min(box.width() / sw_, box.height() / sh_)
            r = QRectF(box.center().x() - sw_ * k / 2, box.center().y() - sh_ * k / 2, sw_ * k, sh_ * k)
            if gray:
                p.drawImage(r, slide_img(i, min(2400, r.width())))
            else:
                p.save()
                p.translate(r.topLeft())
                p.scale(k, k)
                self.renderer.paint_slide(p, self.pres.slides[i], i + 1)
                p.restore()
            if d.frame.isChecked() or what != 0:
                p.setPen(QPen(Qt.black, max(1.0, page.width() / 1500)))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
            return r
        first = True

        def new_page():
            nonlocal first
            if not first:
                printer.newPage()
            first = False
        if what == 0:
            for i in idx:
                new_page()
                place(i, page)
        elif what == 1:
            n = d.per_page.currentData()
            cols, rows = {1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 2), 6: (2, 3), 9: (3, 3)}[n]
            margin = page.width() * 0.06
            area = page.adjusted(margin, margin, -margin, -margin)
            for start in range(0, len(idx), n):
                new_page()
                for j, i in enumerate(idx[start:start + n]):
                    c, r = (j % cols, j // cols) if n != 3 else (0, j)
                    cw = area.width() / (cols if n != 3 else 2)
                    ch = area.height() / rows
                    box = QRectF(area.left() + c * cw, area.top() + r * ch, cw, ch).adjusted(8, 8, -8, -8)
                    rr = place(i, box)
                    if n == 3:
                        p.setPen(QPen(QColor("#808080"), 1))
                        x0 = area.left() + cw + 16
                        for k in range(1, 7):
                            y = rr.top() + rr.height() * k / 7
                            p.drawLine(QPointF(x0, y), QPointF(area.right(), y))
        elif what == 2:
            margin = page.width() * 0.08
            for i in idx:
                new_page()
                top = QRectF(page.left() + margin, page.top() + margin, page.width() - 2 * margin, page.height() * 0.42)
                place(i, top)
                f = QFont("Calibri")
                f.setPointSizeF(12)
                p.setFont(f)
                p.setPen(Qt.black)
                body = QRectF(top.left(), top.bottom() + margin / 2, top.width(), page.height() - top.bottom() - margin)
                p.drawText(body, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.pres.slides[i].notes)
                p.drawText(QRectF(page.left(), page.bottom() - margin * 0.8, page.width() - margin, margin * 0.6),
                           Qt.AlignRight | Qt.AlignVCenter, str(i + 1))
        else:
            from PySide6.QtGui import QTextDocument
            self.left_tabs.setCurrentIndex(1)
            self.refresh_outline()
            doc = QTextDocument()
            doc.setHtml(self.outline.toHtml())
            doc.print_(printer)
        p.end()

    # ==== closing ==================================================================================
    def closeEvent(self, ev):
        self.view.end_edit()
        if not self.maybe_save():
            ev.ignore()
            return
        ev.accept()


def _is_ole(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    except OSError:
        return False


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("classic7-show")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-show")
    from write_model import FONT_SUBSTITUTES
    for fam, subs in FONT_SUBSTITUTES.items():
        QFont.insertSubstitutions(fam, subs)
    show = "--show" in argv or "/s" in argv
    files = [a for a in argv if not a.startswith("-") and a != "/s"]
    files = [QUrl(f).toLocalFile() if f.startswith("file://") else f for f in files]
    if show and files:
        try:
            import show_ppt
            pres = show_ppt.read_ppt(files[0]) if _is_ole(files[0]) else spx.read_pptx(files[0])
        except Exception as e:   # noqa: BLE001
            QMessageBox.warning(None, APP, f"{APP} can't open {Path(files[0]).name}.\n\n{e}")
            return 1
        from show_slideshow import SlideShow
        ss = SlideShow(pres, 0)
        ss.finished.connect(lambda _i: app.quit())
        ss.start()
        return app.exec()
    windows = []
    for f in files or [None]:
        w = ShowWindow(f)
        w.show()
        windows.append(w)
    return app.exec()
