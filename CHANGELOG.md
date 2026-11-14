# Changelog

## 0.3.0 – 2026-11-14
- **Methodenband (systematische Unsicherheit)**: neues Modul `ringwear/sensitivity.py`
  mit einem 54-fachen Parameter-Grid-Sweep (k_sigma × tex_low_thr × tex_min_rel).
  Bildmerkmale werden einmalig berechnet; nur die Entscheidungsstufe variiert.
  Neue Ergebnisspalten: `wear_fraction_min`, `wear_fraction_max`, `method_band_pp`.
  Das Methodenband wird GETRENNT vom inter-experimentellen ±std dargestellt — niemals
  quadratisch kombiniert.
- **Rang-Stabilität**: `sensitivity.rank_stability()` prüft paarweise, ob die
  Rangordnung der Versuche (nach Verschleißanteil) bei allen 54 Kombinationen gleich
  bleibt. Ausgabe: STABLE / UNSTABLE mit Liste der instabilen Paare.
- **Balkendiagramm**: gestricheltes graues Rechteck für Methodenband-Min/Max;
  solider Fehlerbalken für ±std bleibt separat.
- **Streudiagramm**: pro Versuchspunkt gestrichelte graue vertikale Linie für das
  Methodenband der resultierenden Kontaktpressung (rp_lo = F/(fmax·A), rp_hi = F/(fmin·A)).
- **CLI**: `--sensitivity-grid JSON` und `--no-sensitivity`; Grid wird automatisch aus
  `sensitivity_grid.json` neben dem Bildordner geladen, falls vorhanden.
- **CSV-Filterfix**: `_`-Präfix-Schlüssel (intern, z. B. `_fracs_grid`, `_worn_abspath`)
  werden nicht mehr in die CSV-Feldliste aufgenommen.
- **`sensitivity_grid.json`** im Repo-Root als Standardkonfiguration angelegt
  (Annahme — Bereiche nach Wiederholmessungen, Prompt 04, zu validieren).
- Neue Tests: `test_sensitivity_method_band` (fmin ≤ frac ≤ fmax für alle 4
  Referenzbilder) und `test_sensitivity_ranking_stable` (T10 > T9 > T7 > T3 in
  allen 54 Kombinationen stabil).
- **Monolith→Paket (Phase 0)**: `ring_wear.py` ist jetzt ein dünner Shim;
  Logik in `ringwear/` (core.py, stats.py, report.py, cli.py).
  Nullverhalten-Change: CSV-Diff = 0 für alle 9 Referenzbilder.

## 0.2.2 – 2026-11-14
- **Regressionsgerade durch Ursprung** im Scatter-Plot (p = k·F):
  gestrichelt eingezeichnet, Formel und R²-Koeffizient in Legende (HTML) bzw.
  als Textbox unterhalb des Diagramms (PPTX).
- **Drei Bilder pro Experiment** in HTML und PPTX:
  ① Neue Probe (unvermessen), ② Verschlissene Probe, ③ Overlay mit markiertem Verschleißbereich.
  Neue Probe wird aus `data/neu/{Material}/` automatisch gefunden (alternativ `--neu-dir`).
- **Mittelwert ± Std für Wiederholungsversuche**: Balkendiagramm zeigt bei
  n ≥ 2 Messungen gleicher (Material, Kraft) Kombination einen ±std-Fehlerbalken
  und die Beschriftung "mean±std". Fehlerbalken auch im Scatter-Plot.
- Neue Hilfsfunktionen: `_group_stats()`, `_regression_through_origin()`,
  `_find_new_probe()`, `_copy_image_to_outdir()`.

## 0.2.1 – 2026-11-14
- **Texturkriterium hinzugefügt** (k_sigma 1.38 → 1.30, `tex_low_thr=0.42`,
  `tex_min_rel=0.70`):
  Verschleiß wird jetzt zusätzlich zur Helligkeit auch über die lokale
  Grauwert-Standardabweichung (Fenstergröße `tex_sigma_um=44 µm`) erkannt.
  Flächen mit niedriger lokaler Std-Dev (`tex_rel < 0.42` des Ringmedians)
  gelten als eingeglättet und werden als verschlissen markiert.
- **Adaptive Schwelle abgesenkt**: k_sigma von 1.38 auf 1.30 gesenkt.
  Ergebnis: T1/T2/T4/T5 werden jetzt besser erfasst (+1.0 bis +1.4 pp),
  alle 10 Regressionstests bleiben innerhalb der ±1.5-pp-Toleranz.
- **Bekannte Grenze Texturkriterium**: Das Texturkriterium (lokale Std-Dev)
  erkennt zuverlässig *eingeglättete* (polierte) Bereiche. Bei moderatem
  Verschleiß (T4, T5) bleibt eine Kreuzschraffur-Zone (bidirektionale Rillen,
  Verschleiß durch Richtungsänderung) unerkannt, weil diese Zone weder glatt
  noch deutlich heller ist als der unvermessene Bereich. JPEG-Kompression (8×8
  DCT-Blöcke ≈ 27 µm bei 3.378 µm/px) verhindert eine zuverlässige
  Textur-Richtungsanalyse bei der aktuellen Bildqualität.
  Abhilfe: TIFF/PNG-Bilder ohne Kompression liefern echt glatte verschlissene
  Bereiche → tex_rel ≪ 0.42 → zuverlässige Erkennung.
- CLI-Fehler korrigiert: `--k-sigma` hatte hartcodierten `default=1.38` statt
  des Dataclass-Standardwerts → führte zu Abweichungen zwischen CLI und Python-API.

## 0.2.0 – 2026-11-13
- Blaue Kreise in Overlay-Bildern korrigiert: werden jetzt auf den detektierten
  Grenzen gezeichnet (`rh` und `ro`), nicht mehr mit ±100 µm Sicherheitsabstand
  versetzt. Die Kreise liegen nun direkt auf den schwarzen Bereichen (Bohrungskante
  innen, Außennut/Fase außen), wie vom Nutzer vorgegeben.

## 0.1.9 – 2026-11-13
- Punktdiagramm „Resulting Contact Pressure vs. Normal Force" in HTML (SVG)
  und PPTX (nativer XY-Scatter-Chart) hinzugefügt.
  Achsen: Normalkraft (N) auf x-Achse, resultierende Kontaktpressung (MPa) auf
  y-Achse. Beide Materialien in einem Diagramm mit Okabe-Ito-Farben
  (INC718 blau #0072B2, INC625M orange #E69F00). Jeder Punkt = ein Versuch,
  beschriftet mit Test-ID. Beschriftung kippt nach links wenn Punkt nahe dem
  rechten Rand ist.

## 0.1.8 – 2026-11-13
- Gruppiertes Säulendiagramm „Resulting Wear Area by Material and Normal Force"
  in HTML und PPTX integriert.
  Achsen: Normalkraft (N) als x-Gruppe, Verschleißfläche (mm²) = Verschleißanteil
  × Nennfläche 43,2 mm² als y-Wert. Zwei Säulen pro Kraft-Gruppe, je eine je
  Material (INC718 blau, INC625M orange, Okabe-Ito-Farbschema). Mehrfachversuche
  pro Kraft×Material-Kombination werden gemittelt. Fehlende Gruppen (Material
  nicht getestet bei dieser Last) erzeugen keine Säule.
- HTML: inline SVG (stdlib), responsiv (max-width 100 %, viewBox-Skalierung),
  Wertbeschriftung über den Säulen, Legende rechts, Hinweistext unter dem Bild.
- PPTX: native Diagramm-Folie (python-pptx ChartData), Farbzuweisung per Serie,
  Y-Achse beginnt bei 0, Legende unten. Fehler beim Diagramm → Warnung, Rest
  der Präsentation wird trotzdem erzeugt.

## 0.1.7 – 2026-11-13
- Neue Ausgabedateien: `results.html` (stdlib, keine neuen Abhängigkeiten) und
  `results.pptx` (neue Abhängigkeit `python-pptx>=0.6.21`).
- HTML: Zusammenfassungstabelle sortiert nach Verschleißanteil + Detail-Kachel
  pro Experiment mit Overlay-Bild (relative Pfade, kein Base64). Farbkodierung
  der Verschleißquote (rot/orange/grün). Vollständig englisch.
- PPTX 16:9 (1333×750 pt): Titelfolie (dunkelblau), eine Folie pro Experiment
  (Overlay-Bild links, Kennwerte rechts), Abschluss-Zusammenfassung als Tabelle
  sortiert nach Verschleißanteil. Vollständig englisch.
- Beide Funktionen tolerieren fehlendes Overlay-Bild und fehlgeschlagene
  Einzelbilder; Batch wird nie abgebrochen. `python-pptx` fehlt → Warnung,
  CSV/Excel/HTML werden trotzdem erzeugt.
- `run_analysis.bat`: öffnet nach der Analyse zusätzlich `results.html`.

## 0.1.6 – 2026-11-13
- Ringflächen-Vergleich im Output: nominale Ringfläche π/4·(OD²–ID²) = 43,2 mm²
  aus Params (OD=8mm, ID=3mm) wird gegen den Dateinamen-Wert (43mm²) gestellt.
  Neue Params: `inner_diam_mm=3.0`, `outer_diam_mm=8.0`; neue CLI-Args
  `--inner-diam-mm` und `--outer-diam-mm`.
- Erkenntnis: Bilder bei aktueller Vergrößerung zeigen nur die Bohrungsnahzone
  (~6mm²), nicht die volle 43mm²-Kontaktfläche. Die Außengrenze im Bild
  entspricht dem Bohrungsrand (~3,3mm Ø), nicht dem Ring-Außenrand (8mm Ø).
  `ring_area_analyzed_mm2` = ausgewerteter Bildausschnitt (~6mm²);
  `ring_area_nominal_mm2` = Nennfläche aus OD/ID (43,2mm²).
- Resultat-Dict: `groove_diameter_mm`+`hole_diameter_mm`+`ring_area_from_scale_mm2`
  ersetzt durch `ring_area_nominal_mm2`, `ring_area_analyzed_mm2`,
  `bore_diameter_measured_mm`, `wear_area_mm2`.
- Regressionswerte neu kalibriert: T10=17,8%, T9=12,9%, T7=7,9%, T3=4,2%.
  Dritter Toleranzwert ist nun `ring_area_analyzed_mm2` (±0,30mm²) statt `groove_diameter_mm`.

## 0.1.5 – 2026-11-13
- Neue Dateinamen-Konvention: `T{N}_{Material}_{Force}N_{Area}mm2_ring`
  (z. B. `T10_INC718_810N_43mm2_ring.jpg`).
  Alle Dateien in `data/reference/`, `data/annotated/` und `data/neu/` umbenannt.
- Kraft und Nennfläche werden aus dem Dateinamen geparst; `_parse_stem()` im
  Helpers-Abschnitt unterstützt altes Muster `ring{N}_{Material}_{TX}` als
  Rückwärtskompatibilität.
- Excel-Ausgabe (`write_excel`) erweitert: neue Spalten Force (N),
  Sample area (mm²), Geometric contact pressure (MPa),
  Resulting contact pressure (MPa). Doppelter `_parse_stem`-Block entfernt.
- Geometric contact pressure = Force / Sample area (MPa).
  Resulting contact pressure = Force / (wear_fraction × Sample area) (MPa).
- `run_analysis.bat` hinzugefügt: startet Analyse mit Miniforge-Python,
  öffnet `results.xlsx` automatisch.
- Regressionstests auf neue Dateinamen umgestellt; alle 10 Tests bestehen.

## 0.1.4 – 2026-11-13
- Regressionswerte auf echte Original-Mikroskopbilder (JPEG) neu kalibriert.
  Alle vier Bilder haben 3,378 µm/px (höhere Auflösung als frühere PNG-Platzhalter).
  Neue Referenzwerte: ring1 19,6 %, ring2 13,6 %, ring3 7,9 %, ring4 4,5 %.
  Ranking und Toleranzen (±1,5 pp) unverändert.

## 0.1.3 – 2026-11-13
- Alle Ausgabe-Strings ins Englische übersetzt (Flag-Meldungen, Seam-Status,
  CLI-Ausgabe). CLAUDE.md entsprechend aktualisiert.
- Excel-Ausgabe hinzugefügt (`results.xlsx`): Spalten File, Ring, Material, Test,
  Wear fraction (%), Wear area (mm²), µm/px, Threshold, Seam status, Flags.
  Material und Versuchskennung werden automatisch aus dem Dateinamen
  (`ring{N}_{Material}_{TX}`) extrahiert.
- Neue Abhängigkeit: `openpyxl>=3.1`.

## 0.1.2 – 2026-11-13
- Material in Dateinamen der Referenzbilder ergänzt:
  `ring{N}_{Material}_{TX}.jpg` (z. B. `ring1_INC718_T10.jpg`).
  Materialzuordnung: Ring 1+3 → INC718, Ring 2+4 → INC625M.
  Endung von .png auf .jpg geändert (Nutzer hat Dateien so gespeichert).
  **Achtung**: Regressionswerte müssen nach `pytest -q` bestätigt werden —
  JPEG-Kompression kann die Helligkeitswerte leicht verschieben.
  Wenn Werte außerhalb ±1,5 pp: Toleranz begründet anpassen und hier eintragen.

## 0.1.1 – 2026-11-13
- Referenzbilder in `data/reference/` vom Nutzer umbenannt (Versuchskennung im
  Dateinamen, z. B. `ring1_T10.png` = Ring 1, Test 10). Regressionstests in
  `tests/test_regression.py` auf neue Dateinamen aktualisiert. Referenzwerte
  (wear_fraction, µm/px, Nut-Ø) und Toleranzen unverändert.

## 0.1.0 – 2026-11-13
- Ausgangsstand: Analyse-Pipeline (Maßstab, Geometrie, Naht, Hälften-Normierung,
  adaptive Schwelle, Randband-Kriterium), Regressionstests mit Ring 1–4.
