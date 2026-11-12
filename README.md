# Browser

App, die eine Webseite anzeigt und gezielt Text daraus kopiert – als **Web-Version** (`index.html`,
läuft direkt im Browser) und als **Desktop-Version** (`browser_app.py`, Python + Qt).

## Web-Version

Link: **https://linda-efe.github.io/Browser/**

Optional lässt sich ein Link direkt mitgeben: `https://linda-efe.github.io/Browser/?url=https://example.com`

Einmalig einrichten: Auf GitHub unter *Settings → Pages* bei *Source* „Deploy from a branch“,
Branch `main`, Ordner `/ (root)` wählen und speichern. Nach ca. 1 Minute ist der Link erreichbar.

Hinweise zur Web-Version:
- Jede Seite wird **zuerst direkt** geladen – ohne fremden Dienst. Das klappt bei Seiten, die es
  erlauben (z.B. `karlsruhe.de`). Eingaben ohne `https://` und `www.` werden automatisch ergänzt.
- Viele Seiten verbieten das direkte Laden. Dann geht es nur über einen öffentlichen
  Weiterleitungsdienst, den man unter *Einstellungen* wählen kann (Standard: keiner). Dieser Dienst
  sieht die abgerufene Adresse und deine IP-Adresse (bei abgeschickten Suchformularen auch den
  Suchbegriff) – keine Seiten mit Login oder privaten Daten verwenden. Die kostenlosen Dienste sind
  oft überlastet. Selektoren, kopierter Text und Abläufe bleiben immer im Browser.
- Die App lädt keine externen Schriften oder Skripte (keine Google Fonts).
- Skripte der geladenen Seite werden nicht ausgeführt. Seiten, die ihren Inhalt erst per JavaScript
  nachladen, erscheinen evtl. leer – dafür die Desktop-Version nutzen.
- Abläufe werden im Browser gespeichert und lassen sich als JSON speichern/öffnen
  (gleiches Format wie die Desktop-Version).

## Desktop-Version

### Installation

```bash
pip install -r requirements.txt
```

### Starten

```bash
python browser_app.py                      # leer starten
python browser_app.py https://example.com  # direkt mit Link starten
```

## Bedienung (beide Versionen)

1. **Link übergeben:** Link oben in die Adresszeile eintragen → *Laden* (oder Enter).
2. **Webseite ansehen:** Die Seite erscheint im Hauptfenster (◀ ▶ ⟳ zum Navigieren).
3. **Sagen, wohin die App soll** (Bereich *Steuerung* rechts):
   - **🎯 Element im Fenster auswählen** → mit der Maus auf den gewünschten Text in der
     Webseite klicken (orange Markierung). Der Text wird sofort in die Zwischenablage
     kopiert, der passende Selektor wird eingetragen. `Esc` bricht ab.
   - **oder Selektor eingeben**, z.B.
     - CSS: `h1`, `#preis`, `.produkt .titel`, `table tr:nth-of-type(2) td`
     - XPath (beginnt mit `/`): `//div[@class='inhalt']/p[2]`

     *Zeigen* markiert das Element grün, *📋 Text kopieren* kopiert den Text.

### Ablauf (mehrere Schritte)

Für Texte, die erst nach Klicks erreichbar sind, lassen sich Schritte zusammenstellen:

| Aktion          | Ziel                     | Beispiel                     |
|-----------------|--------------------------|------------------------------|
| Öffnen          | URL                      | `https://example.com`        |
| Klicken         | Selektor Link/Button     | `#weiter`                    |
| Eingeben        | Selektor Feld + Text     | `#suche` ← `Berlin`          |
| Warten          | Dauer in ms              | `1000`                       |
| Text kopieren   | Selektor des Textes      | `//h2[1]`                    |

*▶ Ablauf starten* spielt die Schritte ab. Die App wartet automatisch (bis zu 10 s), bis
ein Element auf der Seite auftaucht. Alle kopierten Texte landen (zeilenweise) in der
Zwischenablage und im Feld *Kopierter Text*. Abläufe können als JSON gespeichert und
wieder geöffnet werden, z.B.:

```json
[
  {"action": "open",  "target": "https://example.com", "value": ""},
  {"action": "click", "target": "a", "value": ""},
  {"action": "copy",  "target": "h1", "value": ""}
]
```
