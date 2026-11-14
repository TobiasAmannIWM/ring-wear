# Wear Detection Method — Technical Description

## Overview

The ring-wear tool estimates the fraction of a ring face that has been
brightened by wear. Worn contact surfaces are optically smoother than
the original ground surface, increasing their reflectance under coaxial
incident light. The algorithm quantifies this brightness increase relative
to the unworn reference area on the same image.

## Processing Pipeline

### 1. Scale Calibration
A white reference box containing a dark horizontal bar is located in the
bottom-right quadrant of each image. The pixel length of the dark bar is
measured and converted to physical units using the nominal bar length
(default: 500 µm), yielding a calibration factor in µm/px. This value
is used for all subsequent geometry calculations.

### 2. Ring Geometry Detection
The inner bore and the outer ring boundary are located by finding the
two largest connected dark regions in the image (bore shadow and
background). Radii are measured in pixels and converted to µm. An
annular evaluation mask is constructed by shrinking both boundaries by a
user-defined margin (default: 100 µm on each side) to exclude edge
artefacts.

### 3. Seam Removal
The ring is mounted with a visible seam (weld or clamping line) that
causes a localised bright reflection independent of wear. The seam is
detected automatically as the angular position of the brightest
continuous arc in the annular mask. A wedge-shaped exclusion zone
(default: ±15°) is applied before any wear calculation. This step
prevents the seam reflection from being counted as wear.

### 4. Sector-Normalised Brightness
The annular evaluation area is divided into the two half-rings on either
side of the seam. Each pixel's greyscale value is divided by the median
greyscale of its own half-ring. This normalisation (called `rel`) cancels
systematic illumination gradients and camera vignetting, so that only
local brightness changes relative to the surrounding unworn surface are
evaluated.

### 5. Adaptive Wear Threshold
The threshold is set adaptively per image:

```
T = 1 + k_sigma × σ_rob
```

where σ_rob is the robust standard deviation (IQR/1.35) of `rel` values
in the annular mask. The factor k_sigma (default: 1.30) controls
sensitivity. Pixels with `rel > T` are classified as potentially worn.

The threshold is clipped to a minimum of 1.08 and a maximum of 1.35 to
prevent extreme values in images with unusual contrast.

### 6. Texture Criterion
Polished wear surfaces are locally smoother than ground surfaces.
A local standard deviation map (window radius: ~44 µm) is computed and
normalised by the ring median to give a relative texture value `tex_rel`.
Pixels with `tex_rel < 0.42` (less than 42 % of the median local
roughness) are classified as worn by the texture criterion.

The final wear mask is the union of the brightness criterion and the
texture criterion, followed by morphological opening and closing
(kernel radius ≈ 10 µm) to remove isolated pixels and fill small gaps.

### 7. Wear Fraction
The wear fraction is defined as:

```
wear_fraction = (worn pixels in evaluation mask) / (total pixels in evaluation mask)
```

If a nominal ring area is provided (from the filename or the
`--nominal-area` parameter), the absolute worn area in mm² is also
reported as `wear_fraction × nominal_area`.

## Uncertainty Quantification

### Method Band (Systematic Uncertainty)
The sensitivity of the result to the choice of algorithm parameters is
quantified by a 54-combination grid sweep over three parameters:

| Parameter | Range |
|---|---|
| k_sigma | 1.15 – 1.40 |
| tex_low_thr | 0.35 – 0.50 |
| tex_min_rel | 0.60 – 0.80 |

Image features (brightness normalisation, texture map) are computed once;
only the thresholding step is repeated for each combination. The result
is reported as a method band [min, max] across all 54 combinations.
This band represents **systematic uncertainty** due to parameter choice
and is shown as a dashed rectangle in bar charts — separate from random
measurement uncertainty.

Typical method band width: 2 – 6 percentage points.

### Rank Stability
Pairwise ordering of specimens is checked across all 54 parameter
combinations. A pair is marked **unstable** if its ranking reverses in
at least one combination. Unstable pairs are specimens too close in wear
fraction to be reliably ranked with the current algorithm.

### Repeatability (Random Uncertainty)
When the same specimen is imaged multiple times with repositioning
between measurements, the within-specimen standard deviation s_r
(repeatability standard deviation) is estimated by one-way ANOVA.
The 95 % confidence interval for a single measurement is
`mean ± t(0.95, df) × s_r`. This random uncertainty is shown as a
solid error bar — never added in quadrature to the method band.

## Limitations

- **JPEG compression** (8×8 DCT blocks ≈ 27 µm at 3.4 µm/px) limits
  texture resolution. TIFF or PNG images without lossy compression
  improve texture-based detection reliability.
- The texture criterion reliably detects **polished** (smoothed) wear.
  Cross-hatched wear zones with bi-directional grooves may be
  underdetected because they are neither smooth nor distinctly brighter
  than the unworn surface.
- The brightness criterion and adaptive threshold assume that the
  **majority of the evaluation area is unworn**. Specimens with wear
  fractions above ~60 % may show threshold drift.
- The method band ranges are **assumptions** pending validation from
  repeat measurement experiments. They will be updated once s_r data
  from real repositioning measurements is available.
