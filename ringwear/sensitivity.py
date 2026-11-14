"""ringwear.sensitivity — method band: systematic uncertainty from parameter grid sweep.

The 'method band' shows how much the detected wear fraction changes when the three
key decision parameters are varied across physically plausible ranges:
  - k_sigma:     threshold multiplier (controls brightness criterion sensitivity)
  - tex_low_thr: texture-low threshold (controls smoothness criterion sensitivity)
  - tex_min_rel: texture-min-rel threshold (minimum brightness for texture criterion)

The band is NOT an error bar in the statistical sense — it is a systematic uncertainty
estimate. It is shown SEPARATELY from the inter-experiment std (random uncertainty).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import cv2
import numpy as np

DEFAULT_GRID: dict[str, list[float]] = {
    "k_sigma":     [1.15, 1.20, 1.25, 1.30, 1.35, 1.40],
    "tex_low_thr": [0.35, 0.42, 0.50],
    "tex_min_rel": [0.60, 0.70, 0.80],
}
DEFAULT_BEST: dict[str, float] = {
    "k_sigma": 1.30,
    "tex_low_thr": 0.42,
    "tex_min_rel": 0.70,
}


@dataclass
class SensitivityResult:
    fracs: list[float]   # one value per grid combination
    best_frac: float     # fraction at DEFAULT_BEST / best params
    min_frac: float
    max_frac: float
    n_combos: int


def load_grid(path: Path) -> tuple[dict, dict]:
    """Load grid and best dicts from a JSON file. Returns (grid, best)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    grid = {k: v for k, v in data.items() if not k.startswith("_")}
    best_raw = data.get("_best", {})
    best: dict[str, float] = {k: float(v) for k, v in best_raw.items()}
    for k, vals in grid.items():
        if k not in best:
            best[k] = float(vals[len(vals) // 2])
    return grid, best


def sweep(
    *,
    rel: np.ndarray,
    tex_rel: np.ndarray,
    loc: np.ndarray,
    rim: np.ndarray,
    ann_eval: np.ndarray,
    spread: float,
    local_contrast_thr: float,
    k_open: np.ndarray,
    k_close: np.ndarray,
    min_px: float,
    t_min: float,
    t_max: float,
    grid: dict[str, list[float]],
    best: dict[str, float],
) -> SensitivityResult:
    """Run segmentation for each grid combination.

    Image features (rel, tex_rel, loc, rim) are computed once by the caller;
    only the decision-stage parameters vary. This keeps runtime proportional to
    n_combos, not n_combos × image_preprocessing.
    """
    ann_u8 = ann_eval.astype(np.uint8)
    total_px = max(int(ann_eval.sum()), 1)

    def _segment_one(k_sig: float, tex_lt: float, tex_mr: float) -> float:
        t = float(np.clip(1.0 + k_sig * spread, t_min, t_max))
        smooth_worn = (tex_rel < tex_lt) & (rel > tex_mr) & ann_eval
        m = (((rel > t) | ((loc > local_contrast_thr) & (rel > 1.0) & rim) | smooth_worn) & ann_eval)
        m = m.astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k_open)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k_close)
        m &= ann_u8
        n, lab, st, _ = cv2.connectedComponentsWithStats(m)
        keep = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= min_px])
        return float(keep.sum() / total_px)

    k_sigma_vals = grid.get("k_sigma", DEFAULT_GRID["k_sigma"])
    tex_low_vals = grid.get("tex_low_thr", DEFAULT_GRID["tex_low_thr"])
    tex_min_vals = grid.get("tex_min_rel", DEFAULT_GRID["tex_min_rel"])

    fracs: list[float] = [
        _segment_one(float(ks), float(tlt), float(tmr))
        for ks, tlt, tmr in product(k_sigma_vals, tex_low_vals, tex_min_vals)
    ]

    best_frac = _segment_one(
        float(best.get("k_sigma", DEFAULT_BEST["k_sigma"])),
        float(best.get("tex_low_thr", DEFAULT_BEST["tex_low_thr"])),
        float(best.get("tex_min_rel", DEFAULT_BEST["tex_min_rel"])),
    )

    return SensitivityResult(
        fracs=fracs,
        best_frac=best_frac,
        min_frac=float(min(fracs)),
        max_frac=float(max(fracs)),
        n_combos=len(fracs),
    )


def rank_stability(rows: list[dict], key: str = "_fracs_grid") -> dict:
    """Check whether the ranking of experiments by wear_fraction is stable across all combos.

    Returns dict with keys:
      stable (bool), n_combos (int), unstable_pairs (list[str]), n_pairs (int).
    """
    valid = [
        (r.get("test_id") or r.get("file", ""), r[key], r["wear_fraction"])
        for r in rows
        if isinstance(r.get(key), list) and isinstance(r.get("wear_fraction"), float)
    ]
    if len(valid) < 2:
        return {"stable": True, "n_combos": 0, "unstable_pairs": [], "n_pairs": 0}

    n_combos = len(valid[0][1])
    unstable: list[str] = []
    pairs = [(valid[a], valid[b]) for a in range(len(valid)) for b in range(a + 1, len(valid))]

    for (id_i, fi, bf_i), (id_j, fj, bf_j) in pairs:
        ref_gt = bf_i > bf_j
        for ci in range(n_combos):
            if (fi[ci] > fj[ci]) != ref_gt:
                unstable.append(f"{id_i} vs {id_j}")
                break

    return {
        "stable": len(unstable) == 0,
        "n_combos": n_combos,
        "unstable_pairs": unstable,
        "n_pairs": len(pairs),
    }
