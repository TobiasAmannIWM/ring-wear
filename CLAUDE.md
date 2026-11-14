# CLAUDE.md – Projekt ring-wear

## Zweck
Einheitliche, automatische Abschätzung der **hellen (eingeglätteten) Verschleißfläche**
auf Ring-Stirnflächen aus Lichtmikroskopbildern (Tribologie, Fraunhofer IWM).
Ausgabe: Flächenanteil am Ring, Overlay-Bilder, CSV und Excel für viele Bilder.

Nutzer: Tribologe / Data Scientist. Antworten und Kommentare auf Deutsch.
**CLI-Texte, CSV-/Excel-Spalten, Flag-Meldungen und alle Ausgabedaten auf Englisch.**
Code-Bezeichner englisch.

## Arbeitsweise (verbindlich)
- Vor Änderungen den relevanten Code und Datenfluss vollständig lesen.
- Modular, testbar, einfach. Keine unnötige Komplexität, keine neuen schweren
  Abhängigkeiten ohne Rückfrage (erlaubt: numpy, opencv-python, pillow, pytest;
  scipy/scikit-image nur mit Begründung).
- **Nach jeder Änderung `pytest -q` ausführen.** Regressionstests dürfen nicht
  stillschweigend angepasst werden. Wenn sich Referenzwerte ändern müssen:
  begründen und in `CHANGELOG.md` dokumentieren.
- Nach Änderungen Smoke-Test: `python ring_wear.py data/worn -o out --panel`
  und die Overlays in `out/` ansehen (Read-Tool auf PNG).
- Annahmen, Unsicherheiten und Grenzen explizit benennen. Keine Scheingenauigkeit:
  Ergebnisse sind Abschätzungen, keine Messungen.
- Fehler je Bild abfangen, Batch nie abbrechen; Probleme als `flags` ausgeben.
- Dateien in `data/` niemals verändern oder löschen.

## Konventionen
- **Alle Parameter in physikalischen Einheiten (µm, µm²)**, Umrechnung über µm/px
  aus dem Maßstabsbalken. Keine festen Pixelwerte → unabhängig von Vergrößerung
  und Bildgröße.
- CSV: Semikolon, Dezimalkomma, UTF-8-BOM (Excel-DE).
- Verwendete Parameter immer als JSON neben die Ergebnisse schreiben.
- Overlay-Farben: rot = verschlissen, blau = Auswertegrenzen, gelb = Naht.

## Verfahren (Ist-Stand in `ring_wear.py`)
1. `load_image`: einfarbige Ränder (Folienüberschrift, Streifen) abschneiden;
   Alpha auf Weiß.
2. `annotation_mask`: rote/blaue Markierungen erkennen → inpainten + ausschließen.
3. `detect_scale_bar`: weißes Kästchen unten rechts, längster dunkler Balken
   (belichtungsunabhängig über Weißwert). Balkenlänge = `--bar-um` (500 µm).
4. `detect_geometry`: Bohrung = dunkler kompakter Fleck nahe Bildmitte; radiale
   Abtastung über 360°: Bohrungskante = max. Gradient, äußere Nut = Minimum im
   Bereich 2,3–3,3 × r_Bohrung; robuster Kasa-Kreisfit.
5. `detect_seam`: **Naht** = Wechsel der Schleifrichtung, ca. 0,26·r_außen links
   der Mitte, bei allen bisherigen Ringen an gleicher Stelle (Fertigungsmerkmal).
   Links der Naht ist die Fläche reflexionsbedingt heller → **kein Verschleiß**.
   Erkennung: Helligkeitssprung hell→dunkel oberhalb und unterhalb der Bohrung.
6. Helligkeit glätten (normierte Faltung nur über Ringpixel, damit Nut/Bohrung
   nicht abdunkeln), je Ringhälfte auf Median normieren → `rel`.
7. Kriterium: `rel > T` ODER (`lokaler Kontrast > 1,15` UND `rel > 1` UND im
   äußeren 200-µm-Randband) – das Randband-Kriterium erfasst schmale Bänder
   (110–150 µm breit) am Außenrand.
8. Schwelle: `adaptive` (Standard): T = 1 + 1,38·σ_rob, σ_rob = 1,4826·MAD(rel);
   k = 1,38 wurde so gewählt, dass T ≈ +20 % bei Ring 1/2. `fixed`: T vorgegeben.
9. Morphologie (open 22 µm, close 37 µm), Mindestfläche 5000 µm².

## Referenzwerte (Regression, `tests/test_regression.py`)
Dateinamenschema: `T{N}_{Material}_{Force}N_{Area}mm2_ring.jpg`

| Bild | wear_fraction | µm/px | analyzed area (mm²) |
|---|---|---|---|
| T10_INC718_810N_43mm2_ring | 0,178 | 3,378 | 6,04 |
| T9_INC625M_810N_43mm2_ring | 0,129 | 3,378 | 6,08 |
| T7_INC718_1620N_43mm2_ring | 0,079 | 3,378 | 5,95 |
| T3_INC625M_1620N_43mm2_ring | 0,042 | 3,378 | 5,96 |

Toleranz ±1,5 Prozentpunkte, ±2 % für µm/px, ±0,30 mm² für analyzed area.
Annotierte Bilder (`data/annotated`) müssen ±1 pp mit den sauberen Bildern übereinstimmen.

**Hinweis nominale vs. analysierte Fläche:**
- `ring_area_nominal_mm2` = π/4·(OD²–ID²) = π/4·(8²–3²) = **43,2 mm²** — Nennfläche aus Zeichnung (Params `outer_diam_mm=8`, `inner_diam_mm=3`)
- `ring_area_analyzed_mm2` ≈ **6 mm²** — tatsächlich im Bild ausgewerteter Ausschnitt
- Ursache: Bei aktueller Vergrößerung (3,378 µm/px, Bildbreite ~1226 px) entspricht das ~2 mm Radius vom Zentrum. Der Ringaußenrand (R=4 mm = 1184 px) liegt außerhalb des Bildausschnitts. Die Außengrenze im Bild (~3,3 mm Ø) ist der Bohrungsrand, nicht der Ring-Außenrand.
- Falls die volle 43 mm²-Kontaktfläche analysiert werden soll, sind Bilder bei geringerer Vergrößerung erforderlich.

## Bekannte Grenzen / offene Punkte
- **Hell ≠ verschlissen**: Riefenrichtung, Beleuchtung, Fasen, Anlauffarben
  (brauner Halbring um die Bohrung), Ablagerungen. Abrasive Kratzer ohne
  Einglättung werden kaum erfasst.
- **Kreuzschraffur-Verschleiß nicht erkennbar** (T4, T5): Bei moderatem
  Verschleiß (mittlere bis hohe Normalkraft) entsteht eine Zone, in der die
  ursprünglichen parallelen Schleifrillen durch bidirektionale Rillen
  (Kreuzschraffur) ersetzt werden. Dieses Verschleißbild ist weder glatt noch
  deutlich heller als der unvermessene Bereich → weder das Helligkeits- noch
  das Texturkriterium greift. Zuverlässige Erkennung erfordert
  Textur-Richtungsanalyse (Gabor-Filter) oder CLSM-Topographie.
- **Texturkriterium begrenzt durch JPEG-Kompression**: JPEG 8×8-DCT-Blöcke
  (≈ 27 µm bei 3.378 µm/px) liegen im selben Größenbereich wie die Schleifrillen
  (20–80 µm). Das Rauschen der JPEG-Kompression macht selbst glatte verschlissene
  Bereiche scheinbar texturiert → tex_rel erreicht kaum Werte < 0.42 in ann_eval.
  Mit unkomprimierten TIFF/PNG-Bildern würde das Texturkriterium deutlich besser
  funktionieren.
- **Nullpunkt unkalibriert**: Schwelle ist Expertenschätzung → Aufgabe:
  Kalibrierung mit Neuproben (`prompts/02_kalibrierung.md`).
- Adaptive Schwelle kompensiert Belichtung, verkleinert aber echte Unterschiede
  (stärker verschlissene Proben streuen stärker).
- **Flächen-Inkonsistenz geklärt**: Nominale Ringfläche 43,2 mm² (OD=8 mm, ID=3 mm)
  ist korrekt; die im Bild analysierte Fläche (~6 mm²) ist kleiner, weil bei
  aktueller Vergrößerung nur der Bohrungsnahbereich sichtbar ist (siehe Referenzwerte-
  Abschnitt). Beide Werte werden korrekt ausgegeben: `ring_area_nominal_mm2` und
  `ring_area_analyzed_mm2`.
- Geometrie-Suchbereiche sind auf diese Ringgeometrie abgestimmt.
- Ground Truth fehlt: Abgleich mit CLSM/WLI-Topographie wäre nötig.

## Projektstruktur
```
ring_wear.py            # aktueller Monolith (CLI + Pipeline) – Refactoring: prompts/01_refactoring.md
data/worn/         # saubere Referenzbilder Ring 1–4 (nicht verändern)
data/annotated/         # dieselben Bilder mit roten Markierungen (Testfälle)
data/neu/               # Bilder unverschlissener Neuproben (vom Nutzer zu füllen)
tests/                  # pytest-Regressionstests
prompts/                # Arbeitsaufträge für Claude Code
```

## Befehle
```bash
pip install -r requirements.txt
pytest -q
python ring_wear.py data/worn -o out --panel
```
