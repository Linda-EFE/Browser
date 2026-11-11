# Browser

Desktop-App (Python + Qt), die eine Webseite anzeigt und gezielt Text daraus kopiert.

## Installation

```bash
pip install -r requirements.txt
```

## Starten

```bash
python browser_app.py                      # leer starten
python browser_app.py https://example.com  # direkt mit Link starten
```

## Bedienung

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
