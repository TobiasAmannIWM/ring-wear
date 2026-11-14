# Arbeitsanweisung — Bildaufnahme für automatische Verschleißauswertung

**Für:** Versuchsingenieur  
**Ziel:** Lichtmikroskopbilder der Ringe aufnehmen, die der Code automatisch auswertet.

---

## Was der Code automatisch macht

- Verschleißfläche am Ring erkennen und als Prozent ausgeben
- Excel-Tabelle, HTML-Bericht und PowerPoint erzeugen
- Unsicherheitsband berechnen (wie stark hängt das Ergebnis von Einstellungen ab)

**Du musst nur:** Bilder aufnehmen, richtig benennen, in den richtigen Ordner legen, Skript starten.

---

## Schritt 1 — Mikroskop einstellen

- **Vergrößerung:** so wählen, dass der komplette Ring mit Maßstabsbalken sichtbar ist
- **Beleuchtung:** koaxial (Auflicht), gleichmäßig, kein Überbelichten
- **Maßstabsbalken:** muss im Bild unten rechts sichtbar sein — er wird automatisch erkannt
- **Format:** JPG oder TIFF, Mindestauflösung 1 MP

> ⚠️ Den Maßstabsbalken nie abschneiden oder überdecken. Der Code braucht ihn zur Kalibrierung.

---

## Schritt 2 — Welche Bilder aufnehmen

### Pro Versuch (verschlissener Ring):

| Aufnahme | Anzahl | Wann |
|---|---|---|
| Verschlissener Ring | **mindestens 1**, besser 3 | nach dem Versuch |
| Neue Probe (unverschlissen, gleiches Material) | **1** | einmalig pro Material |

### Wenn 3 Aufnahmen pro Ring gemacht werden (empfohlen):
1. Ring einlegen → Bild aufnehmen
2. Ring **kurz entnehmen und neu einlegen** → Bild aufnehmen
3. Nochmals entnehmen und einlegen → Bild aufnehmen

> Das gibt eine Aussage über die Messgenauigkeit (wie sehr streut das Ergebnis durch Neupositionieren).

---

## Schritt 3 — Dateien benennen

**Schema:** `T{Nr}_{Material}_{Kraft}N_{Fläche}mm2_ring_r{Wiederholung}.jpg`

| Platzhalter | Bedeutung | Beispiel |
|---|---|---|
| `{Nr}` | Versuchsnummer | `11` |
| `{Material}` | Werkstoff (kein Leerzeichen) | `INC718` |
| `{Kraft}` | Normalkraft in Newton | `810` |
| `{Fläche}` | Nennfläche in mm² | `43` |
| `{Wiederholung}` | 1, 2 oder 3 (Aufnahme-Nr.) | `1` |

**Beispiele:**

```
T11_INC718_810N_43mm2_ring_r1.jpg   ← 1. Aufnahme, Versuch 11
T11_INC718_810N_43mm2_ring_r2.jpg   ← 2. Aufnahme (neupositioniert)
T11_INC718_810N_43mm2_ring_r3.jpg   ← 3. Aufnahme (neupositioniert)
```

Wenn nur **eine** Aufnahme gemacht wird, einfach `_r1` weglassen:
```
T11_INC718_810N_43mm2_ring.jpg
```

**Neuprobe** (unvermessener Ring, gleiches Material):
```
INC718_neu.jpg   ← beliebiger Name, Ordner ist entscheidend (siehe Schritt 4)
```

---

## Schritt 4 — Dateien ablegen

```
ring-wear/
  data/
    worn/               ← HIER: alle verschlissenen Ringe (r1, r2, r3)
      T11_INC718_810N_43mm2_ring_r1.jpg
      T11_INC718_810N_43mm2_ring_r2.jpg
      T11_INC718_810N_43mm2_ring_r3.jpg
      (alle bisherigen T1–T10 bleiben hier liegen)

    neu/                ← HIER: Neuproben, sortiert nach Material
      INC718/
        INC718_neu.jpg
      INC625M/
        INC625M_neu.jpg
```

> ⚠️ Keine Dateien in `data/` umbenennen oder löschen, die schon dort liegen.

---

## Schritt 5 — Auswertung starten

Doppelklick auf `run_analysis.bat` im Hauptordner.

Das Skript läuft automatisch durch:
1. Alle verschlissenen Ringe in `data/worn/` werden ausgewertet
2. Falls mehrere Aufnahmen pro Ring vorhanden sind (r1, r2, r3), wird die Wiederholbarkeit **automatisch mitberechnet**

Danach öffnen sich `results.xlsx` und `results.html` automatisch.

**Fertig.** Alle Ergebnisse liegen im Ordner `ring_wear_out/`:

| Datei | Inhalt |
|---|---|
| `results.xlsx` | Verschleißfläche aller Ringe |
| `results.html` | Bericht mit Bildern |
| `results.pptx` | PowerPoint-Präsentation |
| `repeat_report.csv` | Wiederholbarkeit (nur wenn r1/r2/r3 vorhanden) |

---

## Häufige Fehler

| Problem | Ursache | Lösung |
|---|---|---|
| „Maßstabsbalken nicht gefunden" | Balken abgeschnitten oder zu dunkel | Bild neu aufnehmen, Balken vollständig sichtbar lassen |
| Verschleißfläche = 0 % | Bild zu dunkel, Ring nicht erkannt | Beleuchtung prüfen, ggf. `--um-per-px 3.378` angeben |
| Datei erscheint nicht in Excel | Falscher Ordner oder falscher Dateiname | Benennung mit Schema oben vergleichen |
| Ergebnis springt stark zwischen r1/r2/r3 | Ring sehr unterschiedlich eingelegt | Einlegeprozedur standardisieren (Referenzkerbe nutzen) |

---

## Zusammenfassung auf einen Blick

```
Aufnehmen  →  Benennen          →  Ablegen              →  Doppelklick
1–3 Bilder     T11_INC718_       data/worn/                run_analysis.bat
pro Ring       810N_43mm2_
               ring_r1.jpg
```
