# Prompt 03 – Referenzkarte des Neuzustands (optional, erst nach Prompt 02)

Nur sinnvoll, wenn Ringe **reproduzierbar ausgerichtet** unter dem Mikroskop liegen
und die Beleuchtung identisch ist. Erst prüfen, dann bauen.

## Idee
Die reflexionsbedingte Helligkeitsverteilung (Naht, Riefenrichtung, Beleuchtungs-
richtung) ist bei Neuproben systematisch. Eine gemittelte Karte in Polarkoordinaten
ersetzt die grobe Hälften-Normierung:
rel_ref(r, φ) = Helligkeit / Referenzkarte(r, φ).

## Schritte
1. **Machbarkeitsprüfung (zuerst!)**: Polartransformation (r normiert 0…1 zwischen
   Bohrungskante und Nut, φ relativ zur Naht) für alle Neuproben. Kennzahl:
   Korrelation der Karten zwischen Proben und Variationskoeffizient je Zelle.
   Nur wenn die Karten deutlich ähnlicher sind als zufällig, weitermachen. Ergebnis
   mit Abbildung berichten und auf mein OK warten.
2. Referenzkarte = robuster Mittelwert (Median) je Zelle, geglättet; Streukarte
   (MAD) mitspeichern.
3. Analyse: Normierung durch Referenzkarte, Schwelle als z-Wert relativ zur
   Streukarte, Kalibrierung (Prompt 02) mit dieser Normierung wiederholen.
4. Vergleich Hälften-Normierung vs. Referenzkarte über Leave-one-out: Fehlalarme
   auf Neuproben und Trennschärfe auf Verschleißproben (Ring 1–4).
5. Als Option `--normalization halves|refmap` einbauen; Standard bleibt `halves`,
   bis der Vergleich eindeutig ist.

## Ausblick (nicht implementieren, nur vorbereiten)
Abgleich mit Topographie (CLSM/WLI) an 3–4 Ringen: Ist „hell“ tatsächlich
Materialabtrag? Schnittstelle vorsehen, um eine Höhenkarte zu registrieren und
Konfusionsmatrix hell/nicht-hell vs. abgetragen/nicht-abgetragen zu berechnen.
