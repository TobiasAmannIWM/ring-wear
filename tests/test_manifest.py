"""Tests for ringwear.manifest — parsing, validation, init, CLI subcommand."""
from __future__ import annotations

import csv
import io
import textwrap
from pathlib import Path

import pytest

from ringwear import manifest as M
from ringwear.cli import main
from ringwear.core import _parse_stem as _core_parse_stem


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_manifest(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "manifest.csv"
    p.write_text(content, encoding="utf-8-sig")
    return p


def _make_images(folder: Path, names: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"\xff")  # minimal non-empty dummy


# ── ManifestRow parsing from CSV ───────────────────────────────────────────────

class TestLoadCsv:
    def test_basic_roundtrip(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "P017_vor_r2.tif;P017;vor;2;0;2026-11-01;\n"
        content += "P003_neu_r1.tif;P003;neu;1;0;2026-11-01;ref\n"
        _write_manifest(tmp_path, content)
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 2
        assert rows[0].probe == "P017"
        assert rows[0].zustand == "vor"
        assert rows[0].wiederholung == 2
        assert rows[1].zustand == "neu"
        assert rows[1].bemerkung == "ref"
        assert not warnings

    def test_decimal_comma_in_winkel(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "img.jpg;P001;neu;1;2,5;;\n"
        _write_manifest(tmp_path, content)
        rows, _ = M.load_manifest(tmp_path)
        assert rows[0].winkel_deg == pytest.approx(2.5)

    def test_missing_datei_skipped(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += ";P001;neu;1;0;;\n"
        _write_manifest(tmp_path, content)
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 0
        assert any("empty 'datei'" in w for w in warnings)

    def test_unknown_zustand_reported(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "img.jpg;P001;roh;1;0;;\n"
        _write_manifest(tmp_path, content)
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1  # still parsed
        assert any("unknown zustand" in w for w in warnings)

    def test_source_field_is_manifest(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "img.jpg;P001;neu;1;0;;\n"
        _write_manifest(tmp_path, content)
        rows, _ = M.load_manifest(tmp_path)
        assert rows[0]._source == "manifest"


# ── Filename fallback parsing ──────────────────────────────────────────────────

class TestFilenameFallback:
    def test_new_pattern(self, tmp_path):
        _make_images(tmp_path, ["P017_vor_r2.tif"])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.probe == "P017"
        assert r.zustand == "vor"
        assert r.wiederholung == 2
        assert r.winkel_deg == 0.0
        assert r._source == "filename"
        assert not warnings

    def test_new_pattern_with_rotation(self, tmp_path):
        _make_images(tmp_path, ["P003_neu_r1_rot+2.tif"])
        rows, _ = M.load_manifest(tmp_path)
        assert rows[0].winkel_deg == pytest.approx(2.0)
        assert rows[0].zustand == "neu"

    def test_new_pattern_negative_rotation(self, tmp_path):
        _make_images(tmp_path, ["P003_neu_r1_rot-5.tif"])
        rows, _ = M.load_manifest(tmp_path)
        assert rows[0].winkel_deg == pytest.approx(-5.0)

    def test_old_convention(self, tmp_path):
        _make_images(tmp_path, ["T10_INC718_810N_43mm2_ring.jpg"])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.probe == "T10"
        assert r.zustand == "nach"
        assert r._source == "old_convention"
        assert not warnings

    def test_unknown_pattern_warns(self, tmp_path):
        _make_images(tmp_path, ["random_image_name.jpg"])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        assert rows[0].probe == "random_image_name"
        assert any("does not match" in w for w in warnings)

    def test_all_reference_images_parse(self, tmp_path):
        """All 4 reference images must parse without 'does not match' warnings."""
        ref_names = [
            "T10_INC718_810N_43mm2_ring.jpg",
            "T9_INC625M_810N_43mm2_ring.jpg",
            "T7_INC718_270N_43mm2_ring.jpg",
            "T3_INC625M_270N_43mm2_ring.jpg",
        ]
        _make_images(tmp_path, ref_names)
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 4
        assert all(r.probe.startswith("T") for r in rows)
        # No "does not match" warnings
        assert not any("does not match" in w for w in warnings)

    def test_old_convention_with_condition_before_area(self, tmp_path):
        """Ring with condition token BEFORE area (actual file convention on disk)."""
        _make_images(tmp_path, ["T8_INC718_1620N_grinded_43mm2_ring.jpg"])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.probe == "T8"
        assert r.zustand == "nach"
        assert r.filetype == "ring"
        assert "grinded" in r.bemerkung
        assert not any("does not match" in w for w in warnings)

    def test_old_convention_with_condition_after_ring(self, tmp_path):
        """Ring with condition token AFTER ring (alternative renaming convention)."""
        _make_images(tmp_path, ["T8_INC718_1620N_43mm2_ring_grinded.jpg"])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.probe == "T8"
        assert r.filetype == "ring"
        assert "grinded" in r.bemerkung
        assert not any("does not match" in w for w in warnings)

    def test_old_convention_with_condition_and_rep(self, tmp_path):
        """Ring with condition-before-area + repeat suffix."""
        _make_images(tmp_path, ["T8_INC718_1620N_grinded_43mm2_ring_r2.jpg"])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.probe == "T8"
        assert r.wiederholung == 2
        assert "grinded" in r.bemerkung
        assert not any("does not match" in w for w in warnings)

    def test_plate_image_parsed(self, tmp_path):
        """Plate image (T{N}…_plate.jpg) must parse as filetype='plate'."""
        _make_images(tmp_path, ["T1_INC625M_6480N_plate.jpg"])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.probe == "T1"
        assert r.filetype == "plate"
        assert r.zustand == "nach"
        assert "plate_image" in r.bemerkung
        assert not any("does not match" in w for w in warnings)

    def test_ring_and_plate_same_probe_no_duplicate_error(self, tmp_path):
        """Ring T10 + plate T10 must not trigger a 'Duplicate measurement key' error."""
        _make_images(tmp_path, [
            "T10_INC718_810N_43mm2_ring.jpg",
            "T10_INC718_810N_plate.jpg",
        ])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 2
        filetypes = {r.filetype for r in rows}
        assert filetypes == {"ring", "plate"}
        errors = M.validate(rows, tmp_path)
        assert not any("Duplicate" in e for e in errors)


# ── Validation ─────────────────────────────────────────────────────────────────

class TestValidate:
    def test_clean_manifest_no_errors(self, tmp_path):
        _make_images(tmp_path, ["img1.jpg", "img2.jpg"])
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "img1.jpg;P001;neu;1;0;;\n"
        content += "img2.jpg;P002;nach;1;0;;\n"
        _write_manifest(tmp_path, content)
        rows, _ = M.load_manifest(tmp_path)
        errors = M.validate(rows, tmp_path)
        assert errors == []

    def test_duplicate_datei_detected(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "img1.jpg;P001;neu;1;0;;\n"
        content += "img1.jpg;P001;neu;2;0;;\n"
        _write_manifest(tmp_path, content)
        rows, _ = M.load_manifest(tmp_path)
        errors = M.validate(rows)
        assert any("Duplicate file entry" in e for e in errors)

    def test_duplicate_measurement_key_detected(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "img1.jpg;P001;neu;1;0;;\n"
        content += "img2.jpg;P001;neu;1;0;;\n"
        _write_manifest(tmp_path, content)
        rows, _ = M.load_manifest(tmp_path)
        errors = M.validate(rows)
        assert any("Duplicate measurement key" in e for e in errors)

    def test_missing_file_on_disk_detected(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "ghost.jpg;P001;neu;1;0;;\n"
        _write_manifest(tmp_path, content)
        rows, _ = M.load_manifest(tmp_path)
        errors = M.validate(rows, tmp_path)
        assert any("not found on disk" in e for e in errors)

    def test_unknown_zustand_in_validate(self):
        rows = [M.ManifestRow("img.jpg", "P001", "fertig", 1, 0.0, "", "")]
        errors = M.validate(rows)
        assert any("unknown zustand" in e for e in errors)


# ── Init generator ─────────────────────────────────────────────────────────────

class TestInitManifest:
    def test_creates_manifest_csv(self, tmp_path):
        _make_images(tmp_path, ["T10_INC718_810N_43mm2_ring.jpg"])
        out, warnings = M.init_manifest(tmp_path)
        assert out.exists()
        assert out.name == "manifest.csv"

    def test_manifest_has_correct_columns(self, tmp_path):
        _make_images(tmp_path, ["T10_INC718_810N_43mm2_ring.jpg"])
        out, _ = M.init_manifest(tmp_path)
        with open(out, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            assert list(reader.fieldnames) == M.MANIFEST_COLS

    def test_does_not_overwrite_existing(self, tmp_path):
        _write_manifest(tmp_path, "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n")
        with pytest.raises(FileExistsError):
            M.init_manifest(tmp_path)

    def test_no_images_no_crash(self, tmp_path):
        out, warnings = M.init_manifest(tmp_path)
        assert out.exists()
        assert any("No image files found" in w for w in warnings)

    def test_all_reference_images_in_output(self, tmp_path):
        ref_names = [
            "T10_INC718_810N_43mm2_ring.jpg",
            "T9_INC625M_810N_43mm2_ring.jpg",
        ]
        _make_images(tmp_path, ref_names)
        out, _ = M.init_manifest(tmp_path)
        with open(out, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter=";"))
        filenames = [r["datei"] for r in rows]
        assert set(filenames) == set(ref_names)


# ── CLI subcommand integration ─────────────────────────────────────────────────

class TestManifestCLI:
    def test_manifest_init_cli(self, tmp_path):
        _make_images(tmp_path, ["T10_INC718_810N_43mm2_ring.jpg"])
        with pytest.raises(SystemExit) as exc:
            main(["manifest", "init", str(tmp_path)])
        assert exc.value.code == 0
        assert (tmp_path / "manifest.csv").exists()

    def test_manifest_validate_clean(self, tmp_path):
        _make_images(tmp_path, ["img.jpg"])
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "img.jpg;P001;neu;1;0;;\n"
        _write_manifest(tmp_path, content)
        with pytest.raises(SystemExit) as exc:
            main(["manifest", "validate", str(tmp_path)])
        assert exc.value.code == 0

    def test_manifest_validate_with_errors(self, tmp_path):
        content = "datei;probe;zustand;wiederholung;winkel_deg;sitzung;bemerkung\n"
        content += "ghost.jpg;P001;neu;1;0;;\n"
        _write_manifest(tmp_path, content)
        with pytest.raises(SystemExit) as exc:
            main(["manifest", "validate", str(tmp_path)])
        assert exc.value.code == 1

    def test_no_inputs_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1


# ── Rich filename convention ───────────────────────────────────────────────────

class TestRichConvention:
    """Tests for the rich new filename convention:
    {method}_{probe}_{ring}_{plate}_{cond}_{temp}C_{rot}_{geom}_{force}N_{area}mm2_ring
    """

    def test_rich_ring_parsed(self, tmp_path):
        """Full rich ring filename must parse correctly."""
        name = "HTempGall_T1_INC625M_HX_dry_450C_R360_RP_6480N_43mm2_ring.jpg"
        _make_images(tmp_path, [name])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.probe == "T1"
        assert r.zustand == "nach"
        assert r.filetype == "ring"
        assert r.bemerkung == "rich_convention"
        assert not any("does not match" in w for w in warnings)

    def test_rich_plate_parsed(self, tmp_path):
        """Full rich plate filename must parse as filetype='plate'."""
        name = "HTempGall_T1_INC625M_HX_dry_450C_R360_RP_6480N_plate.jpg"
        _make_images(tmp_path, [name])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.probe == "T1"
        assert r.filetype == "plate"
        assert r.zustand == "nach"
        assert not any("does not match" in w for w in warnings)

    def test_rich_ring_with_rep(self, tmp_path):
        """Rich ring with repeat suffix must capture rep number."""
        name = "HTempGall_T2_INC718_HX_dry_450C_R360_RP_6480N_43mm2_ring_r2.jpg"
        _make_images(tmp_path, [name])
        rows, _ = M.load_manifest(tmp_path)
        assert rows[0].probe == "T2"
        assert rows[0].wiederholung == 2
        assert rows[0].filetype == "ring"

    def test_rich_ring_and_rich_plate_same_probe_no_duplicate(self, tmp_path):
        """Rich ring T1 + rich plate T1 must not cause duplicate-key error."""
        _make_images(tmp_path, [
            "HTempGall_T1_INC625M_HX_dry_450C_R360_RP_6480N_43mm2_ring.jpg",
            "HTempGall_T1_INC625M_HX_dry_450C_R360_RP_6480N_plate.jpg",
        ])
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 2
        filetypes = {r.filetype for r in rows}
        assert filetypes == {"ring", "plate"}
        errors = M.validate(rows, tmp_path)
        assert not any("Duplicate" in e for e in errors)


# ── core._parse_stem: rich convention metadata fields ─────────────────────────

class TestCoreParseStemRich:
    """Verify that core._parse_stem() extracts all metadata from the rich convention."""

    def test_rich_fields_extracted(self):
        stem = "HTempGall_T1_INC625M_HX_dry_450C_R360_RP_6480N_43mm2_ring"
        p = _core_parse_stem(stem)
        assert p["test"] == "T1"
        assert p["material"] == "INC625M"
        assert p["plate_material"] == "HX"
        assert p["condition"] == "dry"
        assert p["temperature_C"] == pytest.approx(450.0)
        assert p["rotation_deg"] == pytest.approx(360.0)
        assert p["geometry"] == "RP"
        assert p["force_N"] == pytest.approx(6480.0)
        assert p["area_mm2"] == pytest.approx(43.0)
        assert p["method_name"] == "HTempGall"

    def test_old_convention_fields_absent(self):
        """Old convention: new metadata fields must be None."""
        stem = "T10_INC718_810N_43mm2_ring"
        p = _core_parse_stem(stem)
        assert p["test"] == "T10"
        assert p["material"] == "INC718"
        assert p["force_N"] == pytest.approx(810.0)
        assert p["plate_material"] is None
        assert p["condition"] is None
        assert p["temperature_C"] is None
        assert p["rotation_deg"] is None
        assert p["method_name"] is None

    def test_rich_negative_temperature(self):
        """Negative temperature values must parse correctly."""
        stem = "CryoTest_T5_Steel_HX_dry_-50C_R360_RP_1000N_43mm2_ring"
        p = _core_parse_stem(stem)
        assert p["temperature_C"] == pytest.approx(-50.0)
        assert p["method_name"] == "CryoTest"
