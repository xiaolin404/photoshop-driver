# The verification loop

How to establish that an executed edit took effect. Success status alone
does not establish it.

## Why success status is insufficient

In this environment the following have all been observed `[verified]`:

- a fill issued against an empty layer reports success and changes nothing
- `layer.hasLayerMask` answers `undefined` — falsy, so inverted conditionals
  test nothing
- a property write onto a Lock-All layer either throws or is silently
  normalised away when the file is saved (gotchas.md #3, #4)
- `DoJavaScript` returns `""` for both a failed script and a script that
  produced nothing (gotchas.md #1)

The working procedure: run **one** parameterised change, export the result,
inspect that export, correct what the inspection showed, and export again.
Parameterised means the next pass is a one-line edit; non-destructive means a
bad pass costs nothing to discard.

## Inspecting the export — and the resolution limit

A full-canvas preview is scaled down before it reaches your eyes. At that
scale gross structure and obvious breakage are visible; edges are not. When
the outcome hinges on a boundary, build the view with the required
resolution:

- **1:1 crops** of the deciding region, small margin, composited on black and
  on white — this exposes a rim or a missed sliver.
- **Nearest-neighbour upscaling** (3×) for hairlines and other thin features.
- **Contact sheets** — each part alone on a neutral background, labelled — so
  material dragged in from the wrong region stands out.

State which view a claim is based on. "No halo visible" from a scaled-down
preview is a weak statement; a measured edge profile is a stronger one.
Prefer the numeric result when the two disagree.

## Numeric checks (numpy, cheap, catch what eyes miss)

```python
# 1. the partition invariant (for no-base-layer full partitions).
# Widen before summing: uint8 addition wraps modulo 256 on overflow.
total = sum(a.astype(np.uint32) for a in alphas)   # one (H,W) array per part
print((total == 255).mean())              # want exactly 1.0

# 2. cross-contamination -- detects overlapping foreground masks
overlap = (alpha_subject_a > 128) & (alpha_subject_b > 128)
print(overlap.sum())                      # want 0

# 3. hollow-result check -- catches a thin contour where a filled region was expected
fill = on.sum() / ((ys.max()-ys.min()+1) * (xs.max()-xs.min()+1))
# heuristic: a compact filled subject is often ~0.3-0.6 (shape-dependent); a 2px outline is typically <0.05

# 4. recomposite exactness -- the headline claim
diff = np.abs(recomposed.astype(int) - original.astype(int))
print(diff.max(), (diff.max(axis=2) > 2).mean())          # want 0 and 0.0
```

Two additional prints catch common failures: per-part coverage and bounding
box. A bbox that suddenly spans the whole canvas usually means an operation
did nothing at all; a part covering most of the image usually means a
threshold collapsed.

## Verify the saved artefact

- **Read the saved file back.** Open the written PSD and report every layer's
  name, visibility, lock state, and mask presence. This check exposed the
  locked-layer normalisation in gotchas.md #4: memory said "hidden", the file
  on disk said "visible". State read before saving says nothing about what
  saving wrote.
- **Quantify the claim.** "12% of the canvas, one connected component, bbox
  (x0,y0)-(x1,y1)" is a checkable statement; "a region on the right" is
  not.

## The source file stays whole

- Hash the input first; re-check the hash at the end.
- Write to a copy: `asCopy = true` keeps the working document unsaved, or
  save to a new path.
- Keep the untouched original as its own locked layer so the stack can be
  audited against the source.
- Locking and hiding that reference layer are mutually exclusive on saved PSDs
  (gotchas.md #4) — pick based on whether the user wants a locked reference
  or a hidden one, and state which. When the visible layers above it sum to
  full opacity across the canvas, the rendered composite is unaffected either
  way.

## Reporting residue

Partial success is the normal outcome of matte work. Name what is still
wrong, with sizes:

- "soft gradient transitions near the threshold can fall on either side of the
  partition boundary"
- "a 1px stroke crossing a low-contrast background region may be only partially
  captured"
- "a few sub-100px isolated components remain near textured edges"

Tag each statement: **verified** (measured here) or **inferred** (assumed,
not measured).
