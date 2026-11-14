# Prompt 01 – Refactoring ohne Verhaltensänderung

Ziel: `ring_wear.py` in ein kleines, testbares Paket überführen, **ohne die
Ergebnisse zu verändern**. Die Regressionstests sind das Sicherheitsnetz.

## Zielstruktur (Vorschlag, begründet anpassen erlaubt)
```
ringwear/
  __init__.py
  params.py       # Params-Dataclass, Laden/Speichern als JSON
  io.py           # load_image, annotation_mask, Rand-Trimmen
  scale.py        # detect_scale_bar
  geometry.py     # fit_circle, robust_circle, detect_geometry
  seam.py         # detect_seam
  features.py     # norm_blur, rel-/loc-Karten, Ring-/Sektormasken  (-> wird für Kalibrierung wiederverwendet)
  segment.py      # Schwelle, Kriterien, Morphologie, segment()
  report.py       # Overlay, Variantenpanel, CSV/JSON
  cli.py          # argparse mit Unterbefehlen: analyse (heute), später calibrate
ring_wear.py      # dünner Wrapper -> ringwear.cli.main (Rückwärtskompatibilität)
```

## Anforderungen
- Trenne **Merkmalsberechnung** (Geometrie, Naht, `rel`, `loc`, Masken) von der
  **Entscheidung** (Schwelle → Maske). Eine Funktion `compute_features(path, params)`
  soll ein Datenobjekt (Dataclass) mit allen Karten und Metadaten liefern; `segment()`
  arbeitet nur darauf. Das ist die Voraussetzung, damit die Kalibrierung mit
  Neuproben dieselben Merkmale nutzt.
- Keine Logikänderung, keine neuen Abhängigkeiten. Bekannte Bugs, die dir auffallen,
  nur notieren, nicht still mitkorrigieren.
- Typannotationen und kurze deutsche Docstrings.
- Neue Unit-Tests für: Kreisfit (synthetischer Kreis mit Rauschen, Ausreißer),
  Maßstabsbalken (synthetisches Bild), `norm_blur` (Maske verhindert Abdunkeln am Rand).
- `pytest -q` grün, CLI-Aufruf `python ring_wear.py data/reference -o out` liefert
  identische `results.csv` (Vergleich vorher/nachher per Skript, Abweichung 0).
- `CHANGELOG.md` anlegen.

Arbeite in kleinen Schritten und führe nach jedem Schritt die Tests aus.
