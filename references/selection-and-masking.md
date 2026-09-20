# Selection & masking

Techniques verified on Windows 11 + Photoshop 2026 (v27.10) for multi-layer
scene decomposition and matte isolation.

---

## Getting a mask in: two routes, both preserve 8-bit softness

A layer mask is the non-destructive way to isolate something: keep the original
pixels intact and let the mask decide what shows. The hard part is getting a
*computed* matte (from an algorithm, or from Python) into that mask.

**Route 2 — paste straight into the mask channel. Prefer this one.** It is fewer
steps and leaves no clutter in the Channels panel.

```js
// 1. open the grayscale matte (same canvas size), copy it, close it again
var md = app.open(new File(maskPngPath));
md.selection.selectAll();
md.selection.copy();
md.close(SaveOptions.DONOTSAVECHANGES);
app.activeDocument = doc;            // doc = the target document

// 2. put it into the layer's mask
doc.activeLayer = partLayer;
makeLayerMask('revealAll');          // see gotchas.md #9 for the exact descriptor
selectMaskChannel();                 // AM: Chnl/Chnl/Msk , MkVs = true
doc.paste();
doc.activeChannels = doc.componentChannels;   // back to RGB
```

**Route 1 — via an alpha channel**, if you also need the matte as a channel:

```
channels.add() -> activeChannels = [ch] -> paste() -> activeChannels = componentChannels
-> selection.load(ch, SelectionType.REPLACE) -> makeLayerMask('revealSelection')
```

Both were measured against a 200×200 grayscale ramp: **200 distinct levels
survived, max error 1/255** (that single step is just the ramp's own quantisation).
So soft, anti-aliased mattes are safe through either route — you are not forced
into binary masks. Route 1 additionally allows `selection.load(...)` to drive
`revealSelection` directly, reusing one primitive for everything.

```js
function selectMaskChannel() {
  var d = new ActionDescriptor(), r = new ActionReference();
  r.putEnumerated(cID('Chnl'), cID('Chnl'), cID('Msk '));
  d.putReference(cID('null'), r);
  d.putBoolean(cID('MkVs'), true);
  executeAction(cID('slct'), d, DialogModes.NO);
}
```

---

## Splitting a multi-subject selection by measured geometry

`autoCutout` selects **all** detected foreground subjects at once into a single
union selection.

Splitting multi-subject masks with an unmeasured vertical or horizontal line
chosen by eye is error-prone: when two subjects overlap along one axis (for
example, one component reaching `x=480` while an adjacent component extends to
`x=500`), a vertical cut at `x=520` clips a sliver of one object into the other's
layer.

Measure the connected-component geometry first (illustrative example):

```
subject_a  bbox (100,400)-(500,700)
subject_b  bbox (480, 50)-(900,300)
rows y=310..390 contain ZERO foreground pixels
```

Here the x-ranges overlap (480–500) while the **y-ranges are disjoint**, so a
horizontal cut through the empty band separates them cleanly. Two rules follow:

- **Find an axis with a verified zero-pixel gap**, rather than a line chosen by eye.
  Compute component bounding boxes, or scan row/column profiles for an empty band.
- **Derive the remaining subject by subtraction**, not by intersecting two boxes:
  `subject_a = combined_subject − subject_b`. Subtraction cannot drop boundary
  pixels between two clipping boxes.

Implement the split with selection boolean modes (`INTERSECT` / `SUBTRACT`) against
a rectangle, then make the mask. `CpTL` ignores the selection
entirely (gotchas.md #8), so the clipboard route is the reliable one.

## Choke the matte when the backdrop is bright

A subject's silhouette pixels are blends of subject and background. If the
background is bright sky, keeping those blend pixels at full opacity bakes a light
rim into a dark subject. Push the boundary slightly *inward* by thresholding the
coverage above 50% — e.g. `> 62%` — rather than at exactly 128.

Against a bright backdrop, thresholding a soft matte above 50% (for example, around 60%, or ~150–160 on a 0–255 scale) produces a cleaner silhouette
**without a bright rim on either a black or a white background**. Verify the
cutoff per image; the optimal threshold depends on backdrop contrast.

## Fringe inspection

Composite each result on **black**, on **white**, and ideally mid-grey, then
inspect them. Visual inspection on these backgrounds complements the numeric
checks for edge artifacts: rims, missed slivers, and hollow results show up
here.

---

## Strict partition: why "each pixel in exactly one layer" matters

In a standalone decomposition model where every layer carries the original RGB
pixels over transparency (with **no** full-canvas opaque base layer beneath them),
independent soft mattes will not reconstruct the original image exactly. Standard
alpha compositing of top layer `a` over bottom layer `b` gives:

```
result_alpha = a + b(1-a)
```

With `a=0.7, b=0.3` both carrying the original colour over transparency, the
composite is only 79% opaque — semi-transparent seams wash out wherever soft
mattes overlap. Under this no-base-layer partition model, exact reconstruction
requires **`alpha = 1` in exactly one layer per pixel**, i.e. a hard assignment.

So: compute one soft *score* per region, then assign each pixel to exactly one part
by priority. That makes `sum(alphas) == 255` everywhere a checkable invariant —
worth asserting, because it catches an entire class of mistakes at once:

```python
total = sum(a.astype(np.uint32) for a in alphas)   # widen first: uint8 wraps modulo 256 on overflow
assert (total == 255).all()           # 100% of pixels, no tolerance needed
```

Two consequences to state up front rather than discover later:

- A hard partition means the parts' own edges are not anti-aliased. The blended
  edge colour is baked into whichever part owns it. Choking mitigates the worst of
  it; residual hardness is inherent.
- **Additive elements cause double-counting.** A glow or light beam sits *over* the
  scene. If you copy it into its own layer without removing it from the layers
  beneath, the recomposite is brighter than the original. Give the additive part
  higher priority so it *takes* those pixels from the layers below — the
  "remaining" layers then have holes there, which is the correct outcome.

(If exact reconstruction is *not* required, the opposite layout is also valid and
reconstructs perfectly too: a full-canvas opaque base with soft mattes on top. Pick
based on whether you want a true partition or natural-looking individual layers —
and say which you chose.)

---

## Recovering a hairline

A 1px coloured line is the hardest common case: too few pixels for a colour-range
matte, and it crosses backgrounds of varying colour. Two cheap detectors, unioned:

1. **Hue + brightness threshold.** Constrain to the target hue band, minimum
   saturation, and minimum value to isolate high-confidence pixels along the
   stroke.
2. **Local ridge.** `luminance − median_filter(luminance, k) > delta`, restricted
   to the same colour band. Catches dimmer stretches where the thin stroke crosses
   darker regions.

Take their union and drop isolated specks by connected-component area. **Verify by
rendering the result enlarged** — a 1px line cannot be judged at full-frame
scale.

Point-seeded selection tools (such as Magic Wand) are unsuitable here: a click
provides a single seed point rather than a continuous per-pixel ridge boundary.

## Splitting broad regions by appearance (textured vs smooth backdrop)

When no native segmentation command targets a domain-specific split, combine a
continuous per-pixel discriminator with spatial cleanup:

1. Pick a discriminating channel or property (such as saturation or colour
   distance in a perceptual space).
2. Compute a **continuous soft score**, not an immediate boolean mask.
3. **Smooth the score before thresholding.** Without spatial smoothing,
   transitional gradients near the threshold flicker pixel-to-pixel and produce
   speckle noise. Applying a median filter to the continuous score before
   thresholding yields coherent region contours.
4. Despeckle by connected-component area (drop components below N pixels, fill
   holes below M). Implement with `np.bincount` over the label array, not a
   per-component Python loop.
5. Place the threshold pivot outside transitional bands so mid-tone gradients do
   not straddle the cutoff.

## Isolating a broad illumination or glow field

Do **not** use local high-pass contrast (`luminance − blur`) to isolate a broad
glow. High-pass filtering fires on every sharp bright edge, producing fragmented
patches around high-contrast foreground boundaries.

Use the **low-frequency illumination field itself**: apply a wide Gaussian blur
(for example, radius 50–100px depending on canvas scale) to luminance, then
threshold. That isolates a smooth, contiguous region around the light source that
is straightforward to despeckle.

---

## Preserve source pixels

Keep every part as a duplicate of the original layer with a mask attached;
the original's pixels remain unedited. The work stays inspectable,
reversible, and reproducible, and recomposite comparison against the source
stays meaningful. When a matte needs correcting, correct the matte
computation rather than filling, brushing, or deleting pixels.
