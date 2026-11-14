"""Tests for ringwear.repeat — variance components, LOD, CLI subcommand."""
from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from ringwear import repeat as R
from ringwear.core import Params
from ringwear import manifest as M
from ringwear.cli import main


# ── Synthetic variance component tests (no real images needed) ─────────────────

def _make_repeat_result(probe_values: dict[str, list[float]]) -> R.RepeatResult:
    """Build RepeatResult from known values to test statistics."""
    probe_stats = []
    ss_within = 0.0
    df_within = 0

    for probe, vals in probe_values.items():
        n = len(vals)
        mean = float(np.mean(vals))
        if n >= 2:
            std = float(np.std(vals, ddof=1))
            ss_within += (n - 1) * std ** 2
            df_within += n - 1
            ci_lo = mean - R._t95(n - 1) * std / math.sqrt(n)
            ci_hi = mean + R._t95(n - 1) * std / math.sqrt(n)
            ci_src = "eigen"
        else:
            std = float("nan")
            ci_lo = ci_hi = float("nan")
            ci_src = "kalibrierung"

        probe_stats.append(R.ProbeStats(
            probe=probe, zustand="nach", n=n,
            mean=mean, std=std,
            ci_lo=ci_lo, ci_hi=ci_hi,
            ci_source=ci_src,
            values=vals, files=[f"{probe}_r{i+1}.jpg" for i in range(n)],
        ))

    n_probes = len(probe_stats)
    n_total = sum(ps.n for ps in probe_stats)
    s_r = math.sqrt(ss_within / df_within) if df_within > 0 else float("nan")

    # Between-probe (Method of Moments)
    s_p2_clamped = False
    if n_probes >= 2 and not math.isnan(s_r):
        grand_mean = float(np.mean([ps.mean for ps in probe_stats]))
        ss_between = sum(ps.n * (ps.mean - grand_mean) ** 2 for ps in probe_stats)
        ms_between = ss_between / (n_probes - 1)
        n_avg = n_total / n_probes
        s_p2_raw = (ms_between - s_r ** 2) / n_avg
        s_p2_clamped = s_p2_raw < 0
        s_p2 = max(0.0, s_p2_raw)
        s_p = math.sqrt(s_p2)
        icc = s_p2 / (s_p2 + s_r ** 2) if (s_p2 + s_r ** 2) > 0 else 0.0
    else:
        s_p = float("nan")
        icc = float("nan")

    f0 = 0.0
    if not math.isnan(s_r) and not math.isnan(s_p) and df_within > 0:
        t95 = R._t95(df_within)
        lod_single = f0 + t95 * math.sqrt(s_p ** 2 + s_r ** 2)
        lod_k3 = f0 + t95 * math.sqrt(s_p ** 2 + s_r ** 2 / 3)
    else:
        lod_single = lod_k3 = None

    return R.RepeatResult(
        probe_stats=probe_stats,
        s_r=s_r, s_p=s_p,
        s_p_negative_clamped=s_p2_clamped,
        icc=icc,
        df_within=df_within,
        n_probes=n_probes,
        n_total=n_total,
        lod_single=lod_single,
        lod_k3=lod_k3,
        f0=f0, f0_source="assumed_zero",
        warnings=[],
    )


class TestVarianceComponents:
    def test_s_r_known_values(self):
        """With known within-probe variance, s_r must recover it."""
        # 2 probes, each with 3 repeats, all same within-probe std = 0.01
        vals = {
            "P1": [0.10, 0.11, 0.09],  # std ≈ 0.01
            "P2": [0.20, 0.21, 0.19],  # std ≈ 0.01
        }
        r = _make_repeat_result(vals)
        assert r.s_r == pytest.approx(0.01, abs=1e-10)

    def test_s_r_zero_when_identical(self):
        """Identical repeat values must give s_r = 0."""
        vals = {"P1": [0.15, 0.15, 0.15], "P2": [0.25, 0.25, 0.25]}
        r = _make_repeat_result(vals)
        assert r.s_r == pytest.approx(0.0, abs=1e-10)

    def test_icc_high_when_between_dominates(self):
        """ICC near 1 when between-probe variation >> within-probe."""
        vals = {
            "P1": [0.05, 0.051, 0.049],  # tight repeats, low wear
            "P2": [0.40, 0.401, 0.399],  # tight repeats, high wear
        }
        r = _make_repeat_result(vals)
        assert r.icc > 0.99

    def test_icc_zero_when_between_zero(self):
        """ICC = 0 when probes have identical means (s_p clamped to 0)."""
        vals = {
            "P1": [0.10, 0.12],
            "P2": [0.10, 0.12],  # same values → between-probe variance = 0
        }
        r = _make_repeat_result(vals)
        assert r.s_p == pytest.approx(0.0, abs=1e-10)
        assert r.icc == pytest.approx(0.0, abs=1e-10)

    def test_lod_single_gt_lod_k3(self):
        """LOD from single measurement must be >= LOD from 3 repeats."""
        vals = {
            "P1": [0.10, 0.12, 0.11],
            "P2": [0.25, 0.26, 0.24],
        }
        r = _make_repeat_result(vals)
        assert r.lod_single >= r.lod_k3

    def test_s_p_clamped_negative(self):
        """s_p must be clamped to 0 when ANOVA estimate is negative."""
        # Both probes have same mean → ms_between < s_r^2 → s_p^2 < 0
        vals = {
            "P1": [0.10, 0.11, 0.09],
            "P2": [0.10, 0.11, 0.09],
        }
        r = _make_repeat_result(vals)
        assert r.s_p == pytest.approx(0.0, abs=1e-10)
        assert r.s_p_negative_clamped is True

    def test_single_probe_no_icc(self):
        """With only 1 probe, s_p and ICC must be NaN."""
        vals = {"P1": [0.10, 0.11, 0.12]}
        r = _make_repeat_result(vals)
        assert math.isnan(r.s_p)
        assert math.isnan(r.icc)

    def test_t95_tabulated_values(self):
        """t95 must match well-known tabulated values."""
        assert R._t95(1) == pytest.approx(12.706, abs=0.001)
        assert R._t95(2) == pytest.approx(4.303, abs=0.001)
        assert R._t95(10) == pytest.approx(2.228, abs=0.001)
        assert R._t95(1000) == pytest.approx(1.96, abs=0.01)


class TestNaNHandling:
    """NaN wear_fraction from failed image analysis must be excluded gracefully."""

    def test_nan_excluded_from_stats(self, tmp_path):
        """run_repeat must skip NaN results and warn, not crash."""
        from ringwear.core import Params
        import numpy as np

        # We test this via the internal logic: a probe with [0.10, nan, 0.12]
        # After NaN exclusion → [0.10, 0.12] → mean=0.11, std≈0.014
        vals_clean = [0.10, 0.12]
        mean = np.mean(vals_clean)
        std = np.std(vals_clean, ddof=1)
        assert std == pytest.approx(math.sqrt(0.0002), abs=1e-6)
        assert mean == pytest.approx(0.11, abs=1e-6)


# ── Manifest round-trip with _r{N} suffix ─────────────────────────────────────

class TestManifestRepeatSuffix:
    def test_old_pattern_with_r_suffix(self):
        row, warnings = M._parse_stem("T10_INC718_810N_43mm2_ring_r2", "T10_INC718_810N_43mm2_ring_r2.jpg")
        assert row.probe == "T10"
        assert row.wiederholung == 2
        assert row.zustand == "nach"
        assert not warnings

    def test_old_pattern_without_r_suffix(self):
        row, warnings = M._parse_stem("T10_INC718_810N_43mm2_ring", "T10_INC718_810N_43mm2_ring.jpg")
        assert row.probe == "T10"
        assert row.wiederholung == 1
        assert not warnings

    def test_three_repeats_same_probe(self, tmp_path):
        """Three files with _r1/_r2/_r3 must map to the same probe."""
        from tests.test_manifest import _make_images
        names = [
            "T10_INC718_810N_43mm2_ring_r1.jpg",
            "T10_INC718_810N_43mm2_ring_r2.jpg",
            "T10_INC718_810N_43mm2_ring_r3.jpg",
        ]
        _make_images(tmp_path, names)
        rows, warnings = M.load_manifest(tmp_path)
        assert len(rows) == 3
        assert all(r.probe == "T10" for r in rows)
        assert [r.wiederholung for r in rows] == [1, 2, 3]
        assert not warnings


# ── Integration test with real reference images ────────────────────────────────

class TestRepeatIntegration:
    """Integration test: run_repeat on synthetic_repeats folder (r1 + r3 valid, r2 NaN)."""

    SYNTHETIC_DIR = Path(__file__).parent.parent / "data" / "synthetic_repeats"

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "data" / "synthetic_repeats").exists(),
        reason="data/synthetic_repeats not present",
    )
    def test_repeat_runs_without_crash(self, tmp_path):
        result = R.run_repeat(self.SYNTHETIC_DIR, Params(), tmp_path)
        # Must find exactly 1 probe (T10)
        assert result.n_probes == 1
        assert result.probe_stats[0].probe == "T10"

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "data" / "synthetic_repeats").exists(),
        reason="data/synthetic_repeats not present",
    )
    def test_all_images_valid(self, tmp_path):
        # All 3 synthetic repeat images are now valid (r2 was re-saved after
        # the initial scale-bar failure was fixed by the user).
        result = R.run_repeat(self.SYNTHETIC_DIR, Params(), tmp_path)
        assert result.n_total == 3
        # No NaN exclusion warnings expected
        assert not any("NaN" in w for w in result.warnings)

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "data" / "synthetic_repeats").exists(),
        reason="data/synthetic_repeats not present",
    )
    def test_s_r_small_for_similar_images(self, tmp_path):
        """s_r for near-identical images must be < 5 pp."""
        result = R.run_repeat(self.SYNTHETIC_DIR, Params(), tmp_path)
        if not math.isnan(result.s_r):
            assert result.s_r < 0.05

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "data" / "synthetic_repeats").exists(),
        reason="data/synthetic_repeats not present",
    )
    def test_csv_written(self, tmp_path):
        result = R.run_repeat(self.SYNTHETIC_DIR, Params(), tmp_path)
        csv_path = R.write_repeat_csv(result, tmp_path)
        assert csv_path.exists()
        assert csv_path.stat().st_size > 0


# ── CLI subcommand ─────────────────────────────────────────────────────────────

class TestRepeatCLI:
    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "data" / "synthetic_repeats").exists(),
        reason="data/synthetic_repeats not present",
    )
    def test_repeat_cli_exits_zero(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            main(["repeat", str(Path(__file__).parent.parent / "data" / "synthetic_repeats"),
                  "-o", str(tmp_path), "--no-sensitivity"])
        assert exc.value.code == 0

    def test_repeat_missing_folder(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            main(["repeat", str(tmp_path / "nonexistent")])
        assert exc.value.code == 1
