# Prompt 00 – Einstieg (zuerst in Claude Code einfügen)

Lies `CLAUDE.md`, `README.md`, `ring_wear.py` und `tests/test_regression.py` vollständig.
Führe dann `pip install -r requirements.txt` (falls nötig) und `pytest -q` aus und
erzeuge mit `python ring_wear.py data/reference -o out --panel` die Overlays.
Sieh dir mindestens `out/ring1_overlay.png` und `out/ring4_overlay.png` an.

Ändere noch keinen Code. Gib mir danach:
1. Eine kurze Zusammenfassung des Verfahrens und Datenflusses in eigenen Worten
   (max. 15 Zeilen), damit ich prüfen kann, ob du es richtig verstanden hast.
2. Testergebnis und ob die Overlays plausibel aussehen.
3. Die 3–5 größten technischen Schwachstellen des aktuellen Codes
   (Robustheit, Wartbarkeit, versteckte Annahmen), jeweils mit Begründung.
4. Einen Vorschlag für die Modulstruktur des Refactorings (siehe
   `prompts/01_refactoring.md`), bevor du damit beginnst.
