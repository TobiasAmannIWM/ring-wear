# ring_wear.py – Verschleißfläche auf Ring-Stirnflächen

Automatische, einheitliche Abschätzung der hellen (eingeglätteten) Fläche aus
Lichtmikroskopbildern mit Maßstabsbalken unten rechts.

## Start mit Claude Code (VS Code)

1. Ordner `ring-wear` in VS Code öffnen, Terminal: `python -m venv .venv`,
   aktivieren, `pip install -r requirements.txt`, `pytest -q` (10 Tests grün).
2. Optional: `git init && git add . && git commit -m "Ausgangsstand"` –
   dann sind alle Änderungen von Claude Code nachvollziehbar.
3. Claude Code öffnen und die Prompts der Reihe nach einfügen:
   `prompts/00_start.md` → `01_refactoring.md` → `02_kalibrierung.md`
   → (optional) `03_referenzkarte.md`. Nach jedem Schritt Ergebnis prüfen.
4. Bilder unverschlissener Neuproben in `data/neu/` ablegen.

`CLAUDE.md` wird von Claude Code automatisch gelesen und enthält Verfahren,
Konventionen, Referenzwerte und offene Punkte.

## Installation

```bash
pip install -r requirements.txt
```

## Benutzung

```bash
# ganzer Ordner, Standardeinstellungen (adaptive Schwelle, Naht automatisch)
python ring_wear.py bilder/ -o ergebnisse

# Referenzbilder dieses Projekts
python ring_wear.py data/reference -o out --panel

# mit Variantenbildern (Schwellen +10/+15/+20/+25 %)
python ring_wear.py bilder/ -o ergebnisse --panel

# feste Schwelle – empfohlen, wenn alle Bilder mit identischen
# Mikroskopeinstellungen aufgenommen wurden
python ring_wear.py bilder/ -o ergebnisse --threshold-mode fixed --threshold 1.20

# Nennfläche des Rings (für mm²-Spalte), 0 = aus
python ring_wear.py bilder/ --nominal-area 43.2
```

Weitere Optionen: `python ring_wear.py -h`
(`--bar-um`, `--um-per-px`, `--seam none|prior`, `--seam-offset`,
`--inner-margin-um`, `--outer-margin-um`, `--k-sigma`, `--keep-annotations`).

## Ausgabe

| Datei | Inhalt |
|---|---|
| `results.csv` | eine Zeile je Bild (Semikolon, Dezimalkomma → Excel-DE) |
| `<bild>_overlay.png` | rot = als verschlissen klassifiziert, blau = Auswertegrenzen, gelb = Naht |
| `<bild>_varianten.png` | nur mit `--panel`: vier Schwellen nebeneinander |
| `params.json` | alle verwendeten Parameter (Reproduzierbarkeit) |

Wichtige Spalten in `results.csv`:

- `wear_fraction` – Anteil der hellen Fläche an der ausgewerteten Ringfläche
- `wear_area_nominal_mm2` – Anteil × Nennfläche (`--nominal-area`)
- `wear_area_from_scale_mm2` – Anteil × Ringfläche aus Maßstabsbalken
- `frac_T110 … frac_T125` – Sensitivität gegenüber der Schwelle
- `threshold`, `spread` – verwendete Schwelle, robuste Helligkeitsstreuung
- `seam_status` – erkannt / teilweise / Vorgabe (nicht erkannt)
- `share_in_rim_band` – Anteil der Verschleißfläche im äußeren 200-µm-Band
- `flags` – Warnungen (Kreisfit ungenau, Ring angeschnitten, Markierungen …)

## Verfahren (Kurzfassung)

1. Einfarbige Ränder abschneiden; rote/blaue Markierungen ausblenden.
2. Maßstabsbalken → µm/px. Alle Parameter sind in µm definiert und damit
   unabhängig von Vergrößerung und Bildgröße.
3. Bohrung (dunkler runder Fleck) → Bohrungskante und äußere dunkle Nut per
   radialer Abtastung über 360° und robustem Kreisfit.
4. Naht der Schleifrichtung (Helligkeitssprung links der Mitte) suchen;
   Helligkeit je Ringhälfte auf den Median normieren.
5. Hell = rel. Helligkeit > T; zusätzlich im äußeren Randband lokaler
   Kontrast > 1,15 (schmale Randbänder). Adaptive Schwelle
   T = 1 + 1,38 · σ_rob (kalibriert: entspricht +20 % bei den Referenzringen).
6. Morphologische Bereinigung, Mindestfläche 5000 µm².

## Validierung (Referenzbilder)

| Bild | manuell | Skript |
|---|---|---|
| Ring 1 | ~19 % | 19,5 % |
| Ring 2 | ~13 % | 13,7 % |
| Ring 3 | ~9 % | 8,6 % |
| Ring 4 | ~5 % | 4,3 % |

Robustheit (Ring 1 / Ring 3): Belichtung ×0,8, JPEG, Skalierung ×0,7 und ×1,5
ändern das Ergebnis um ≤ 0,6 Prozentpunkte; Gamma 0,8 um ≤ 0,6 Prozentpunkte.
Bilder mit roten Markierungen weichen ≤ 0,5 Prozentpunkte ab.

## Grenzen – bitte beachten

- **Hell ≠ verschlissen.** Riefenrichtung, Beleuchtung, Fasen, Anlauffarben
  und Ablagerungen beeinflussen die Helligkeit. Abrasive Kratzer ohne
  Einglättung werden kaum erfasst. Ergebnis = Abschätzung, keine Messung.
- **Adaptive Schwelle** gleicht Belichtungsunterschiede aus, verkleinert aber
  echte Unterschiede zwischen Proben (stärker verschlissene Proben streuen
  stärker → höhere Schwelle). Bei standardisierter Aufnahme besser
  `--threshold-mode fixed` verwenden.
- **Overlays immer sichten**, besonders bei Einträgen in `flags` und bei
  `seam_status` ≠ „erkannt“.
- Annahme: Ringgeometrie wie bei den Referenzproben (Nut-/Bohrungsradius
  ≈ 2,3–3,3). Für andere Geometrien die Suchbereiche in `detect_geometry`
  anpassen.
- Maßstab der Referenzbilder ergibt eine Ringfläche von ~7 mm² statt der
  angegebenen 43,2 mm² – bitte klären, welche Angabe stimmt.
- Belastbare Verschleißquantifizierung: Topographie (CLSM/WLI) mit
  Höhendifferenz zur Referenzebene.
