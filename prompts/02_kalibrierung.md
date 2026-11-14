# Prompt 02 – Nullpunkt-Kalibrierung mit Neuproben

## Hintergrund
Auch unverschlissene Ringe haben helle Bereiche (Riefenorientierung, Beleuchtung,
Fasen, Fertigungsstreuung). Die Methode findet dort scheinbaren Verschleiß. Bisher
ist die Schwelle eine Expertenschätzung (+20 % bzw. adaptiv k = 1,38). Mit Bildern
**unverschlissener Neuproben** in `data/neu/` (gleiche Fertigung, gleiche
Aufnahmebedingungen, n ≥ 5, möglichst 8–10; einige doppelt aufgenommen mit
Neupositionierung) sollen Schwelle, Nullwert und Nachweisgrenze **gemessen** werden.

Voraussetzung: Prompt 01 ist umgesetzt (`compute_features` / `segment` getrennt).

## Umfang dieses Auftrags: Weg 1 + 2 (Weg 3 = Prompt 03, nicht jetzt)

### Neuer Unterbefehl `calibrate`
```
python ring_wear.py calibrate data/neu -o calibration.json [--fp-target 0.01]
```
1. Für jede Neuprobe `compute_features` (identische Pipeline!).
2. Schwellen-Sweep T = 1,05 … 1,40 (Schritt 0,005), Randband-Kriterium unverändert
   mitlaufen lassen. Je Bild und T: Fehlalarm-Anteil FP(T) = erkannte Fläche /
   Ringfläche.
3. **Weg 1 – Schwelle:** T_cal = kleinstes T, bei dem der **Mittelwert** von FP(T)
   über alle Neuproben ≤ `fp-target` (Standard 1 %). Zusätzlich ausgeben: T, bei
   dem das **Maximum** ≤ fp-target (konservativ).
4. **Weg 2 – Nullwert & Nachweisgrenze** bei T_cal:
   f0 = Mittelwert FP, s0 = Standardabweichung, n;
   LOD = f0 + t(0,95; n−1)·s0·√(1+1/n) (einseitiges Prognoseintervall; bei n<5
   Warnung). Optional zusätzlich LOD_3s = f0 + 3·s0 zum Vergleich.
5. **Leave-one-out-Kreuzvalidierung:** T_cal ohne Bild i bestimmen, FP auf Bild i
   messen → realistische Fehlalarmrate ausgeben (verhindert Überanpassung).
6. **Wiederholbarkeit:** Wenn Dateinamen Doppelaufnahmen kennzeichnen
   (Konvention festlegen, z. B. `probeX_a.png` / `probeX_b.png`), Differenz der
   FP-Werte je Paar ausgeben.
7. **Aufnahme-Fingerabdruck** speichern: µm/px (Mittel, Streuung), Bildgröße,
   Weißwert des Maßstabskästchens, Median-Helligkeit des Rings und der Fläche
   außerhalb des Rings, robuste Streuung σ_rob.
8. `calibration.json`: T_cal, T_cal_max, f0, s0, n, LOD, LOO-Ergebnis, Fingerabdruck,
   Parameter, Liste der Bilder, Software-Version/Git-Hash, Datum.
   Zusätzlich `calibration_report.png`: FP(T)-Kurven je Bild + Mittelwert, markiertes
   T_cal; und Overlays der Neuproben bei T_cal (zeigen, wo Fehlalarme liegen).

### Analyse mit Kalibrierung
```
python ring_wear.py analyse bilder/ -o out --calibration calibration.json
```
- Schwelle = T_cal (fixed), adaptive Schwelle wird ignoriert (Hinweis ausgeben).
- Neue CSV-Spalten: `wear_fraction_raw`, `wear_fraction_corr = max(raw − f0, 0)`,
  `above_lod` (raw > LOD), `lod`, `calibration_file`.
- **Plausibilitätsprüfung gegen den Fingerabdruck**: Warnung in `flags`, wenn µm/px
  > 2 % abweicht, Weißwert oder Außenhelligkeit > 10 % abweicht, Bildgröße anders.
  (Kalibrierung gilt nur für identische Aufnahmebedingungen.)

### Tests
- Mechanik-Tests mit `data/reference` als **Pseudo-Neuproben** (physikalisch nicht
  sinnvoll, nur für Programmlogik): Monotonie FP(T) fallend, T_cal erfüllt
  fp-target, JSON-Schema vollständig, Analyse mit Kalibrierung liefert neue Spalten.
- Synthetischer Test: Bild mit bekanntem hellem Fleck definierter Fläche auf
  homogenem, verrauschtem Ring → korrigierte Fläche ≈ Sollfläche (±10 %).
- Bestehende Regressionstests bleiben grün (Analyse ohne `--calibration` unverändert).

### Dokumentation
README-Abschnitt „Kalibrierung“: Aufnahmeprotokoll (gleiche Vergrößerung,
Beleuchtung, Belichtung, Bildgröße, keine Markierungen, Ring zentriert,
Naht-Orientierung möglichst gleich), Mindestanzahl, Interpretation von LOD.

## Offene Fragen an mich, bevor du startest
- Gibt es bereits Neuproben-Bilder in `data/neu/`? Falls nein: Implementierung und
  Tests mit Pseudo-Neuproben, echte Kalibrierung später.
- Dateinamenskonvention für Doppelaufnahmen.
