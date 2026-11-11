#!/usr/bin/env python3
"""
Browser-App: Webseite laden, anzeigen und gezielt Text kopieren.

Ablauf:
  1. Link (URL) oben eingeben und "Laden" drücken.
  2. Die Webseite wird im Fenster angezeigt.
  3. Rechts im Bereich "Steuerung" sagen, wohin die App gehen soll:
       - per Klick: "Element im Fenster auswählen" und dann auf den
         gewünschten Text in der Webseite klicken, oder
       - per Selektor: CSS-Selektor (z.B. "h1", "#preis", ".titel")
         oder XPath (z.B. "//div[@class='inhalt']/p[2]") eintragen.
     "Text kopieren" legt den Text in die Zwischenablage.
  4. Optional: Mehrere Schritte (Öffnen, Klicken, Warten, Eingeben,
     Text kopieren) als Ablauf zusammenstellen, abspielen und als JSON
     speichern/laden.

Start:  python browser_app.py [URL]
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass

from PyQt6.QtCore import QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView

PICK_PREFIX = "__BROWSERAPP_PICK__"

# ---------------------------------------------------------------------------
# JavaScript-Bausteine
# ---------------------------------------------------------------------------

# Findet ein Element per CSS-Selektor oder XPath (beginnt mit "/" oder "(").
JS_FIND = """
function __baFind(sel) {
  sel = (sel || '').trim();
  if (!sel) return null;
  try {
    if (sel.startsWith('/') || sel.startsWith('(')) {
      return document.evaluate(sel, document, null,
        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    }
    return document.querySelector(sel);
  } catch (e) { return null; }
}
"""

# Auswahlmodus: Element unter der Maus hervorheben, Klick meldet Selektor + Text.
JS_PICKER = """
(function() {
  if (window.__baPickerActive) return;
  window.__baPickerActive = true;
  let last = null, lastOutline = '';

  function cssPath(el) {
    if (!(el instanceof Element)) return '';
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.documentElement) {
      if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
      let part = el.tagName.toLowerCase();
      const parent = el.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(c => c.tagName === el.tagName);
        if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
      }
      parts.unshift(part);
      el = parent;
    }
    return parts.join(' > ');
  }
  function unmark() { if (last) { last.style.outline = lastOutline; last = null; } }
  function over(e) {
    unmark();
    last = e.target; lastOutline = last.style.outline;
    last.style.outline = '3px solid #e8590c';
  }
  function stop() {
    unmark();
    document.removeEventListener('mouseover', over, true);
    document.removeEventListener('click', click, true);
    document.removeEventListener('keydown', key, true);
    window.__baPickerActive = false;
  }
  function click(e) {
    e.preventDefault(); e.stopPropagation();
    const el = e.target;
    stop();
    console.log('""" + PICK_PREFIX + """' + JSON.stringify({
      selector: cssPath(el),
      text: (el.innerText || el.textContent || '').trim()
    }));
  }
  function key(e) {
    if (e.key === 'Escape') {
      stop();
      console.log('""" + PICK_PREFIX + """' + JSON.stringify({cancel: true}));
    }
  }
  window.__baStopPicker = stop;
  document.addEventListener('mouseover', over, true);
  document.addEventListener('click', click, true);
  document.addEventListener('keydown', key, true);
})();
"""


def js_get_text(selector: str) -> str:
    return JS_FIND + f"""
(function() {{
  const el = __baFind({json.dumps(selector)});
  if (!el) return null;
  if (el.value !== undefined && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'))
    return el.value;
  return (el.innerText || el.textContent || '').trim();
}})();
"""


def js_click(selector: str) -> str:
    return JS_FIND + f"""
(function() {{
  const el = __baFind({json.dumps(selector)});
  if (!el) return false;
  el.scrollIntoView({{block: 'center'}});
  el.click();
  return true;
}})();
"""


def js_type(selector: str, text: str) -> str:
    return JS_FIND + f"""
(function() {{
  const el = __baFind({json.dumps(selector)});
  if (!el) return false;
  el.focus();
  el.value = {json.dumps(text)};
  el.dispatchEvent(new Event('input', {{bubbles: true}}));
  el.dispatchEvent(new Event('change', {{bubbles: true}}));
  return true;
}})();
"""


def js_highlight(selector: str) -> str:
    return JS_FIND + f"""
(function() {{
  const el = __baFind({json.dumps(selector)});
  if (!el) return false;
  el.scrollIntoView({{block: 'center', behavior: 'smooth'}});
  const old = el.style.outline;
  el.style.outline = '3px solid #2b8a3e';
  setTimeout(() => {{ el.style.outline = old; }}, 1500);
  return true;
}})();
"""


# ---------------------------------------------------------------------------
# Webseite mit Rückkanal für den Auswahlmodus
# ---------------------------------------------------------------------------

class BrowserPage(QWebEnginePage):
    picked = pyqtSignal(dict)

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if message.startswith(PICK_PREFIX):
            try:
                self.picked.emit(json.loads(message[len(PICK_PREFIX):]))
            except json.JSONDecodeError:
                pass


# ---------------------------------------------------------------------------
# Ablauf (Schritte)
# ---------------------------------------------------------------------------

STEP_TYPES = {
    "open": "Öffnen (URL)",
    "click": "Klicken (Selektor)",
    "type": "Eingeben (Selektor + Text)",
    "wait": "Warten (ms)",
    "copy": "Text kopieren (Selektor)",
}


@dataclass
class Step:
    action: str
    target: str = ""
    value: str = ""

    def label(self) -> str:
        name = STEP_TYPES.get(self.action, self.action)
        if self.action == "wait":
            return f"{name}: {self.value or self.target} ms"
        if self.action == "type":
            return f"{name}: {self.target}  ←  \"{self.value}\""
        return f"{name}: {self.target}"


class StepRunner:
    """Spielt die Schritte nacheinander ab (asynchron, Qt-Timer-basiert)."""

    ELEMENT_TIMEOUT_MS = 10000
    POLL_MS = 250

    def __init__(self, window: "MainWindow"):
        self.w = window
        self.steps: list[Step] = []
        self.index = 0
        self.waited = 0
        self.results: list[str] = []
        self.running = False
        self._waiting_for_load = False

    def start(self, steps: list[Step]):
        if not steps:
            return
        self.steps = list(steps)
        self.index = 0
        self.results = []
        self.running = True
        self.w.log("▶ Ablauf gestartet")
        self._next()

    def stop(self, msg: str = "■ Ablauf gestoppt"):
        if self.running:
            self.running = False
            self._waiting_for_load = False
            self.w.log(msg)
            self.w.on_run_finished(self.results)

    def on_load_finished(self, ok: bool):
        if self.running and self._waiting_for_load:
            self._waiting_for_load = False
            self._advance()

    def _advance(self):
        self.index += 1
        QTimer.singleShot(0, self._next)

    def _next(self):
        if not self.running:
            return
        if self.index >= len(self.steps):
            self.running = False
            self.w.log("✔ Ablauf fertig")
            self.w.on_run_finished(self.results)
            return
        step = self.steps[self.index]
        self.w.steps_list.setCurrentRow(self.index)
        self.w.log(f"  Schritt {self.index + 1}: {step.label()}")
        self.waited = 0

        if step.action == "open":
            self._waiting_for_load = True
            self.w.load_url(step.target)
        elif step.action == "wait":
            try:
                ms = int(step.value or step.target or 0)
            except ValueError:
                ms = 0
            QTimer.singleShot(max(ms, 0), self._advance)
        elif step.action in ("click", "copy", "type"):
            self._try_element(step)
        else:
            self.stop(f"✖ Unbekannte Aktion: {step.action}")

    def _try_element(self, step: Step):
        if not self.running:
            return
        if step.action == "click":
            script = js_click(step.target)
        elif step.action == "type":
            script = js_type(step.target, step.value)
        else:
            script = js_get_text(step.target)

        def done(result):
            if not self.running:
                return
            found = result is not None and result is not False
            if found:
                if step.action == "copy":
                    text = str(result)
                    self.results.append(text)
                    self.w.log(f"    kopiert: {text[:80]!r}")
                # Nach einem Klick kurz warten, damit evtl. Navigation startet.
                QTimer.singleShot(400 if step.action == "click" else 0, self._advance)
                return
            self.waited += self.POLL_MS
            if self.waited >= self.ELEMENT_TIMEOUT_MS:
                self.stop(f"✖ Element nicht gefunden: {step.target}")
                return
            QTimer.singleShot(self.POLL_MS, lambda: self._try_element(step))

        self.w.page.runJavaScript(script, done)


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, start_url: str = ""):
        super().__init__()
        self.setWindowTitle("Browser-App – Text kopieren")
        self.resize(1400, 900)

        # Webansicht
        self.view = QWebEngineView()
        self.page = BrowserPage(self.view)
        self.view.setPage(self.page)
        self.page.picked.connect(self.on_picked)
        self.view.urlChanged.connect(lambda u: self.url_edit.setText(u.toString()))
        self.view.titleChanged.connect(
            lambda t: self.setWindowTitle(f"{t} – Browser-App" if t else "Browser-App"))
        self.view.loadFinished.connect(self.on_load_finished)
        self.setCentralWidget(self.view)

        self.runner = StepRunner(self)
        self.steps: list[Step] = []

        self._build_toolbar()
        self._build_control_panel()
        self.statusBar().showMessage("Bitte einen Link eingeben und auf „Laden“ klicken.")

        if start_url:
            self.load_url(start_url)
        else:
            self.url_edit.setFocus()

    # ----- Oberfläche -------------------------------------------------------

    def _build_toolbar(self):
        tb = QToolBar("Navigation")
        tb.setMovable(False)
        self.addToolBar(tb)

        back = QAction("◀", self, toolTip="Zurück", triggered=self.view.back)
        fwd = QAction("▶", self, toolTip="Vor", triggered=self.view.forward)
        reload_ = QAction("⟳", self, toolTip="Neu laden", triggered=self.view.reload)
        back.setShortcut(QKeySequence.StandardKey.Back)
        fwd.setShortcut(QKeySequence.StandardKey.Forward)
        reload_.setShortcut(QKeySequence.StandardKey.Refresh)
        for a in (back, fwd, reload_):
            tb.addAction(a)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Webseite-Link, z.B. https://example.com")
        self.url_edit.returnPressed.connect(lambda: self.load_url(self.url_edit.text()))
        tb.addWidget(self.url_edit)

        load_btn = QPushButton("Laden")
        load_btn.clicked.connect(lambda: self.load_url(self.url_edit.text()))
        tb.addWidget(load_btn)

    def _build_control_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # --- Ziel festlegen & kopieren ---
        target_box = QGroupBox("1. Wohin? – Element festlegen")
        tl = QVBoxLayout(target_box)

        self.pick_btn = QPushButton("🎯 Element im Fenster auswählen")
        self.pick_btn.setToolTip("Danach in der Webseite auf den gewünschten Text klicken "
                                 "(Esc bricht ab).")
        self.pick_btn.clicked.connect(self.start_picker)
        tl.addWidget(self.pick_btn)

        tl.addWidget(QLabel("…oder Selektor eingeben (CSS oder XPath):"))
        self.selector_edit = QLineEdit()
        self.selector_edit.setPlaceholderText("z.B.  h1   |   #preis   |   //table//tr[2]/td[3]")
        self.selector_edit.returnPressed.connect(self.copy_text)
        tl.addWidget(self.selector_edit)

        row = QHBoxLayout()
        show_btn = QPushButton("Zeigen")
        show_btn.setToolTip("Element in der Webseite markieren")
        show_btn.clicked.connect(self.highlight_selector)
        copy_btn = QPushButton("📋 Text kopieren")
        copy_btn.clicked.connect(self.copy_text)
        row.addWidget(show_btn)
        row.addWidget(copy_btn)
        tl.addLayout(row)
        layout.addWidget(target_box)

        # --- Ablauf ---
        flow_box = QGroupBox("2. Ablauf (mehrere Schritte steuern)")
        fl = QVBoxLayout(flow_box)

        form = QFormLayout()
        self.action_combo = QComboBox()
        for key, name in STEP_TYPES.items():
            self.action_combo.addItem(name, key)
        self.action_combo.currentIndexChanged.connect(self._update_step_inputs)
        self.step_target = QLineEdit()
        self.step_value = QLineEdit()
        self.step_wait = QSpinBox()
        self.step_wait.setRange(0, 600000)
        self.step_wait.setSingleStep(500)
        self.step_wait.setValue(1000)
        self.step_wait.setSuffix(" ms")
        form.addRow("Aktion:", self.action_combo)
        form.addRow("Ziel:", self.step_target)
        form.addRow("Text:", self.step_value)
        form.addRow("Dauer:", self.step_wait)
        fl.addLayout(form)
        self._form = form

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Schritt")
        add_btn.clicked.connect(self.add_step)
        use_sel_btn = QPushButton("Selektor übernehmen")
        use_sel_btn.setToolTip("Selektor aus Bereich 1 als Ziel eintragen")
        use_sel_btn.clicked.connect(lambda: self.step_target.setText(self.selector_edit.text()))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(use_sel_btn)
        fl.addLayout(btn_row)

        self.steps_list = QListWidget()
        fl.addWidget(self.steps_list)

        edit_row = QHBoxLayout()
        for text, slot in (("▲", lambda: self.move_step(-1)),
                           ("▼", lambda: self.move_step(1)),
                           ("Entfernen", self.remove_step),
                           ("Leeren", self.clear_steps)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            edit_row.addWidget(b)
        fl.addLayout(edit_row)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton("▶ Ablauf starten")
        self.run_btn.clicked.connect(self.run_steps)
        stop_btn = QPushButton("■ Stopp")
        stop_btn.clicked.connect(lambda: self.runner.stop())
        run_row.addWidget(self.run_btn)
        run_row.addWidget(stop_btn)
        fl.addLayout(run_row)

        io_row = QHBoxLayout()
        save_btn = QPushButton("Speichern…")
        save_btn.clicked.connect(self.save_steps)
        load_btn = QPushButton("Öffnen…")
        load_btn.clicked.connect(self.load_steps)
        io_row.addWidget(save_btn)
        io_row.addWidget(load_btn)
        fl.addLayout(io_row)
        layout.addWidget(flow_box)

        # --- Ergebnis ---
        result_box = QGroupBox("Kopierter Text")
        rl = QVBoxLayout(result_box)
        self.result_edit = QPlainTextEdit()
        self.result_edit.setPlaceholderText("Hier erscheint der kopierte Text.")
        rl.addWidget(self.result_edit)
        recopy = QPushButton("In Zwischenablage kopieren")
        recopy.clicked.connect(lambda: self._to_clipboard(self.result_edit.toPlainText()))
        rl.addWidget(recopy)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(120)
        self.log_edit.setPlaceholderText("Protokoll")
        rl.addWidget(self.log_edit)
        layout.addWidget(result_box, 1)

        dock = QDockWidget("Steuerung", self)
        dock.setWidget(panel)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setMinimumWidth(380)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._update_step_inputs()

    def _update_step_inputs(self):
        action = self.action_combo.currentData()
        placeholders = {
            "open": "https://…",
            "click": "Selektor des Links/Buttons",
            "type": "Selektor des Eingabefelds",
            "copy": "Selektor des Textes",
        }
        show_target = action != "wait"
        self._form.setRowVisible(self.step_target, show_target)
        self._form.setRowVisible(self.step_value, action == "type")
        self._form.setRowVisible(self.step_wait, action == "wait")
        self.step_target.setPlaceholderText(placeholders.get(action, ""))

    # ----- Navigation -------------------------------------------------------

    @staticmethod
    def normalize_url(text: str) -> QUrl:
        text = text.strip()
        if not text:
            return QUrl()
        url = QUrl.fromUserInput(text)
        return url

    def load_url(self, text: str):
        url = self.normalize_url(text)
        if not url.isValid() or url.isEmpty():
            self.statusBar().showMessage("Ungültiger Link.")
            return
        self.url_edit.setText(url.toString())
        self.statusBar().showMessage(f"Lade {url.toString()} …")
        self.view.load(url)

    def on_load_finished(self, ok: bool):
        self.statusBar().showMessage("Seite geladen." if ok else "Seite konnte nicht geladen werden.")
        self.runner.on_load_finished(ok)

    # ----- Auswahl & Kopieren ----------------------------------------------

    def start_picker(self):
        self.statusBar().showMessage("Auswahlmodus: Auf den gewünschten Text in der Webseite "
                                     "klicken (Esc = abbrechen).")
        self.pick_btn.setEnabled(False)
        self.page.runJavaScript(JS_PICKER)
        self.view.setFocus()

    def on_picked(self, data: dict):
        self.pick_btn.setEnabled(True)
        if data.get("cancel"):
            self.statusBar().showMessage("Auswahl abgebrochen.")
            return
        selector = data.get("selector", "")
        text = data.get("text", "")
        self.selector_edit.setText(selector)
        self.step_target.setText(selector)
        self.result_edit.setPlainText(text)
        self._to_clipboard(text)
        self.log(f"Ausgewählt: {selector}")
        self.statusBar().showMessage("Element ausgewählt – Text wurde in die Zwischenablage kopiert.")

    def copy_text(self):
        selector = self.selector_edit.text().strip()
        if not selector:
            self.statusBar().showMessage("Bitte zuerst einen Selektor eingeben oder ein Element auswählen.")
            return

        def done(result):
            if result is None:
                self.statusBar().showMessage(f"Kein Element gefunden für: {selector}")
                return
            text = str(result)
            self.result_edit.setPlainText(text)
            self._to_clipboard(text)
            self.statusBar().showMessage(f"{len(text)} Zeichen in die Zwischenablage kopiert.")

        self.page.runJavaScript(js_get_text(selector), done)

    def highlight_selector(self):
        selector = self.selector_edit.text().strip()
        if selector:
            self.page.runJavaScript(
                js_highlight(selector),
                lambda ok: self.statusBar().showMessage(
                    "Element markiert." if ok else f"Kein Element gefunden für: {selector}"))

    def _to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)

    def log(self, msg: str):
        self.log_edit.appendPlainText(msg)

    # ----- Ablauf ----------------------------------------------------------

    def _refresh_steps(self):
        self.steps_list.clear()
        for i, s in enumerate(self.steps, 1):
            self.steps_list.addItem(f"{i}. {s.label()}")

    def add_step(self):
        action = self.action_combo.currentData()
        if action == "wait":
            step = Step(action, value=str(self.step_wait.value()))
        else:
            target = self.step_target.text().strip()
            if not target:
                self.statusBar().showMessage("Bitte ein Ziel angeben.")
                return
            step = Step(action, target, self.step_value.text() if action == "type" else "")
        self.steps.append(step)
        self._refresh_steps()

    def remove_step(self):
        row = self.steps_list.currentRow()
        if 0 <= row < len(self.steps):
            del self.steps[row]
            self._refresh_steps()

    def move_step(self, delta: int):
        row = self.steps_list.currentRow()
        new = row + delta
        if 0 <= row < len(self.steps) and 0 <= new < len(self.steps):
            self.steps[row], self.steps[new] = self.steps[new], self.steps[row]
            self._refresh_steps()
            self.steps_list.setCurrentRow(new)

    def clear_steps(self):
        self.steps.clear()
        self._refresh_steps()

    def run_steps(self):
        if self.runner.running:
            return
        if not self.steps:
            self.statusBar().showMessage("Keine Schritte vorhanden.")
            return
        self.run_btn.setEnabled(False)
        self.runner.start(self.steps)

    def on_run_finished(self, results: list[str]):
        self.run_btn.setEnabled(True)
        if results:
            text = "\n".join(results)
            self.result_edit.setPlainText(text)
            self._to_clipboard(text)
            self.statusBar().showMessage(f"{len(results)} Text(e) in die Zwischenablage kopiert.")

    def save_steps(self):
        path, _ = QFileDialog.getSaveFileName(self, "Ablauf speichern", "ablauf.json",
                                              "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump([asdict(s) for s in self.steps], f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(f"Gespeichert: {path}")

    def load_steps(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ablauf öffnen", "", "JSON (*.json)")
        if path:
            try:
                self.steps = load_steps_file(path)
            except (OSError, ValueError, TypeError) as e:
                QMessageBox.warning(self, "Fehler", f"Datei konnte nicht gelesen werden:\n{e}")
                return
            self._refresh_steps()
            self.statusBar().showMessage(f"Geladen: {path}")


def load_steps_file(path: str) -> list[Step]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    steps = [Step(**d) for d in data]
    for s in steps:
        if s.action not in STEP_TYPES:
            raise ValueError(f"Unbekannte Aktion: {s.action}")
    return steps


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Browser-App")
    start_url = sys.argv[1] if len(sys.argv) > 1 else ""
    win = MainWindow(start_url)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
