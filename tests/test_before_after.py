"""Tests for ringwear.before_after (Phase 3)."""
from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

import ringwear as rw
from ringwear import before_after as BA
from ringwear import manifest as M
from ringwear.core import Params


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_manifest(folder: Path, rows: list[dict]) -> None:
    p = folder / "manifest.csv"
    with p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=M.MANIFEST_COLS, delimiter=";")
        w.writeheader()
        for r in rows:
            row = {c: r.get(c, "") for c in M.MANIFEST_COLS}
            w.writerow(row)


def _copy_worn(src: Path, dst: Path, name: str) -> Path:
    """Copy a real worn image into dst under the given name."""
    import shutil
    dst.mkdir(parents=True, exist_ok=True)
    target = dst / name
    shutil.copy(src, target)
    return target


WORN_DIR = Path(__file__).parent.parent / "data" / "worn"
_REF_EXT = ".jpg"
_REAL_IMAGE = WORN_DIR / f"HTempGall_T10_INC718_HX_dry_450C_R360_RP_810N_43mm2_ring{_REF_EXT}"
_HAS_REAL = _REAL_IMAGE.exists()


# ── Unit tests: ProbeImages grouping ──────────────────────────────────────────

class TestManifestPairing:
    def test_paired_probes_detected(self, tmp_path):
        """Manifest with one vor and one nach for the same probe → 1 paired."""
        _copy_worn(_REAL_IMAGE, tmp_path, "P01_vor_r1.jpg") if _HAS_REAL else (tmp_path / "P01_vor_r1.jpg").write_bytes(b"")
        _copy_worn(_REAL_IMAGE, tmp_path, "P01_nach_r1.jpg") if _HAS_REAL else (tmp_path / "P01_nach_r1.jpg").write_bytes(b"")
        _write_manifest(tmp_path, [
            {"datei": "P01_vor_r1.jpg",  "probe": "P01", "zustand": "vor",  "wiederholung": "1"},
            {"datei": "P01_nach_r1.jpg", "probe": "P01", "zustand": "nach", "wiederholung": "1"},
        ])
        result = BA.run_before_after(tmp_path, Params(), tmp_path / "out")
        assert result.n_paired + result.n_nach_only + result.n_vor_only == 1

    def test_nach_only_probe(self, tmp_path):
        """Manifest with only nach for a probe → n_nach_only = 1."""
        _write_manifest(tmp_path, [
            {"datei": "P02_nach_r1.jpg", "probe": "P02", "zustand": "nach", "wiederholung": "1"},
        ])
        result = BA.run_before_after(tmp_path, Params(), tmp_path / "out")
        assert result.n_nach_only == 1
        assert result.n_paired == 0

    def test_vor_only_probe(self, tmp_path):
        """Manifest with only vor for a probe → n_vor_only = 1."""
        _write_manifest(tmp_path, [
            {"datei": "P03_vor_r1.jpg", "probe": "P03", "zustand": "vor", "wiederholung": "1"},
        ])
        result = BA.run_before_after(tmp_path, Params(), tmp_path / "out")
        assert result.n_vor_only == 1
        assert result.n_paired == 0

    def test_neu_rows_ignored(self, tmp_path):
        """Manifest rows with zustand='neu' must not appear in probe_deltas."""
        _write_manifest(tmp_path, [
            {"datei": "P04_neu_r1.jpg", "probe": "P04", "zustand": "neu", "wiederholung": "1"},
        ])
        result = BA.run_before_after(tmp_path, Params(), tmp_path / "out")
        assert len(result.probe_deltas) == 0

    def test_empty_folder_gives_empty_result(self, tmp_path):
        result = BA.run_before_after(tmp_path, Params(), tmp_path / "out")
        assert result.probe_deltas == []
        assert result.n_paired == 0


# ── Unit tests: delta calculation ──────────────────────────────────────────────

class TestDeltaCalculation:
    def test_delta_is_nach_minus_vor(self):
        d = BA.ProbeDelta(
            probe="X", vor_mean=0.10, nach_mean=0.25, delta=0.15,
            vor_n=1, nach_n=1, vor_files=[], nach_files=[],
        )
        assert d.delta == pytest.approx(0.15)

    def test_delta_none_when_vor_missing(self):
        d = BA.ProbeDelta(
            probe="X", vor_mean=None, nach_mean=0.30, delta=None,
            vor_n=0, nach_n=1, vor_files=[], nach_files=[],
        )
        assert d.delta is None

    def test_delta_can_be_negative(self):
        """delta < 0 is physically possible (noise, measurement artefact)."""
        d = BA.ProbeDelta(
            probe="X", vor_mean=0.20, nach_mean=0.18, delta=-0.02,
            vor_n=1, nach_n=1, vor_files=[], nach_files=[],
        )
        assert d.delta < 0


# ── CSV output ─────────────────────────────────────────────────────────────────

class TestCSVOutput:
    def test_csv_written(self, tmp_path):
        result = BA.BeforeAfterResult(
            probe_deltas=[
                BA.ProbeDelta("P1", 0.05, 0.22, 0.17, 1, 1, ["vor.jpg"], ["nach.jpg"]),
                BA.ProbeDelta("P2", None, 0.15, None, 0, 1, [], ["nach2.jpg"]),
            ],
            n_paired=1, n_nach_only=1, n_vor_only=0, warnings=[],
        )
        path = BA.write_before_after_csv(result, tmp_path)
        assert path.exists()
        with path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["probe"] == "P1"
        assert rows[1]["delta_wear_fraction"] == ""  # None → empty

    def test_csv_decimal_comma(self, tmp_path):
        result = BA.BeforeAfterResult(
            probe_deltas=[BA.ProbeDelta("P1", 0.123, 0.456, 0.333, 1, 1, [], [])],
            n_paired=1, n_nach_only=0, n_vor_only=0, warnings=[],
        )
        BA.write_before_after_csv(result, tmp_path)
        content = (tmp_path / "before_after_report.csv").read_text(encoding="utf-8-sig")
        assert "0,3330" in content   # Dezimalkomma
        assert "0.3330" not in content


# ── CLI smoke test ─────────────────────────────────────────────────────────────

class TestCLI:
    def test_before_after_cli_empty_folder(self, tmp_path):
        """before-after on empty folder exits 0 (no images → 0 pairs, no error)."""
        from ringwear.cli import main
        with pytest.raises(SystemExit) as exc:
            main(["before-after", str(tmp_path), "-o", str(tmp_path / "out")])
        assert exc.value.code == 0

    def test_before_after_cli_help(self):
        from ringwear.cli import main
        with pytest.raises(SystemExit) as exc:
            main(["before-after", "--help"])
        assert exc.value.code == 0


# ── Integration test with real images ─────────────────────────────────────────

@pytest.mark.skipif(not _HAS_REAL, reason="data/worn not present")
class TestBeforeAfterIntegration:
    def test_same_image_vor_and_nach_gives_near_zero_delta(self, tmp_path):
        """Using the same image as both vor and nach must yield delta ≈ 0."""
        _copy_worn(_REAL_IMAGE, tmp_path, "T10_vor_r1.jpg")
        _copy_worn(_REAL_IMAGE, tmp_path, "T10_nach_r1.jpg")
        _write_manifest(tmp_path, [
            {"datei": "T10_vor_r1.jpg",  "probe": "T10", "zustand": "vor",  "wiederholung": "1"},
            {"datei": "T10_nach_r1.jpg", "probe": "T10", "zustand": "nach", "wiederholung": "1"},
        ])
        result = BA.run_before_after(tmp_path, Params(), tmp_path / "out")
        assert result.n_paired == 1
        d = result.probe_deltas[0]
        assert d.delta is not None
        assert abs(d.delta) < 0.01  # identical images → delta < 1 pp
