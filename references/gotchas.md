# Gotchas

Fourteen behaviours that cost real debugging time here. Most fail **silently**
— no exception, no dialog, just a wrong or empty result. Scan this list before
debugging anything strange, and before writing ExtendScript that touches
layers or masks.

Legend: **[verified]** = reproduced on Windows 11 + Photoshop 2026
(v27.10). **[documented]** = stated in Adobe's own API
documentation.

---

## 1. `DoJavaScript` fails silently in two different ways [verified]

`app.DoJavaScript(code)` returns `""` **with no error** when either:

- the script uses a top-level `return`, or
- the script throws an exception that nothing catches.

So a completely broken script and a script that legitimately returns nothing look
identical. `psx.py jsx` wraps every body in an IIFE + `try/catch` to convert both
into visible output -- use it rather than calling COM directly, and make your
script `return` a string.

The same behaviour applies one level up: an uncaught throw **inside** your IIFE returns
`""` too. If you write your own wrapper, wrap the *body*, not just the outer call.

## 2. `layer.hasLayerMask` returns `undefined`, not `false` [verified]

`undefined` is falsy, so `if (!layer.hasLayerMask)` looks like it works -- but
`!undefined === true` means you cannot tell "no mask" from "property missing", and
inverted logic silently passes. Ask the Action Manager instead:

```js
function hasMaskAM() {
  var r = new ActionReference(), a = new ActionDescriptor();
  r.putProperty(cID('Prpr'), cID('UsrM'));
  r.putEnumerated(cID('Lyr '), cID('Ordn'), cID('Trgt'));
  a.putReference(cID('null'), r);
  try { return executeAction(cID('getd'), a, DialogModes.NO).hasKey(cID('UsrM')); }
  catch (e) { return false; }
}
```

## 3. A Lock-All layer rejects property writes [verified]

Setting any property on a layer with `allLocked === true` **throws**. You must
unlock first, change, then re-lock:

```js
L.allLocked = false;
L.visible = false;      // or whatever you needed
L.allLocked = true;     // plan to lock LAST, after all duplication
```

Duplicate layers inherit the lock, and a locked layer cannot take a mask -- so do
all your duplication *before* locking.

## 4. Locking and hiding are mutually exclusive on saved pixel layers [verified]

On the tested build (v27.10), Photoshop does not preserve `visible = false`
on a normal layer with Lock-All (`allLocked = true`) when saving to PSD. It
accepts `visible = false` in memory, but saving the PSD **normalises the
locked layer back to visible**.

Minimal reproduction (same document, two layers, save, reopen):

```
HIDDEN_LOCKED {visible=true, locked=true}     <- hidden+locked came back VISIBLE
FORMER_BG     {visible=false, locked=false}   <- hidden+unlocked stayed hidden
```

If you need both, you cannot have both. Decide which matters and say so in your
report; do not claim a layer is hidden when the file on disk says otherwise.
Verify visibility by **reopening the saved file**, not by reading it back before
saving.

## 5. A Background layer must be converted before you can hide it [verified]

`layer.isBackgroundLayer === true` for a layer opened from a flat file. Note the
name is localised on non-English installs -- always test the flag, never the
string. Unlocking it converts it to a normal layer. Clear the flag explicitly if
you rely on it later.

## 6. `doc.selection.bounds` throws when nothing is selected [verified]

Throws a "no such element" error when no selection exists, so it cannot be used directly as a presence test. Guard
with try/catch and treat a throw as "no selection".

## 7. `doc.selection.selectSubject()` does not exist [verified]

On v27.10 it throws
`TypeError: doc.selection.selectSubject is not a function`. Use the Action Manager instead:

```js
var d = new ActionDescriptor();
d.putBoolean(sTID('sampleAllLayers'), false);
executeAction(sTID('autoCutout'), d, DialogModes.NO);
```

Repeated runs produced identical selection bounds.

## 8. Layer via Copy (`CpTL`) ignores the selection [verified]

With a sub-canvas selection rectangle, the produced layer's bounds were the **full
canvas** -- it degenerates into "duplicate the whole layer". Use the clipboard
instead, which honours the selection exactly:

```js
doc.selection.copy();
var ly = doc.artLayers.add();
doc.activeLayer = ly;
doc.paste();               // paste() leaves the pasted layer active
```

## 9. Creating a layer mask: two identifiers must be right [verified]

The widely-copied snippet fails on this build with a "Make is not currently available" error. Both
of these are independently required:

- the reference key must be `stringIDToTypeID('new')` -- **not** `charIDToTypeID('null')`
- `using` must be the enum `userMaskEnabled` + `<mode>` -- **not** a boolean

```js
function makeLayerMask(mode) {          // 'revealSelection' | 'revealAll' | 'hideAll'
  var d = new ActionDescriptor(), r = new ActionReference();
  d.putClass(sTID('new'), sTID('channel'));
  r.putEnumerated(sTID('channel'), sTID('channel'), sTID('mask'));
  d.putReference(sTID('at'), r);
  d.putEnumerated(sTID('using'), sTID('userMaskEnabled'), sTID(mode));
  executeAction(sTID('make'), d, DialogModes.NO);
}
```

## 10. `layer.duplicate()` inserts the copy directly ABOVE the source [verified]

Duplicating the *bottom* layer repeatedly therefore builds the stack in reverse.
If you duplicate `ORIGINAL` six times expecting them in the order you wrote them,
you get the opposite. Either duplicate in the order you want top-to-bottom, or
reorder explicitly with `layer.move(...)` -- and log the resulting stack by name
to check, because `doc.layers[0]` is the TOP layer.

## 11. Opacity quantises to 1/255 [verified]

Setting `opacity = 65` reads back as `65.0980392156863` (integer 166 underneath).
Identical across the COM DOM, UXP DOM and batchPlay. Do not assume set == get.

## 12. `app.displayDialogs = DialogModes.NO` on every script [verified]

Without it, an illegal operation pops a native error dialog on the user's screen.
Your `try/catch` catches the exception, but the dialog is already up and will block
later automation.

## 13. Photoshop can exit on its own — and the executable is discoverable [verified]

Mid-session, with no action from the agent, the process disappeared --
`GetActiveObject` then failed with an "Operation unavailable" COM error and no document was
available to any caller.
Any in-memory document is gone (files on disk are fine). Re-check with
`psx ping` first, and avoid building a workflow whose only copy of a result
lives in an unsaved document.

A fresh session also needs a way to bring Photoshop up, because attaching
requires it to already be running. `psx whereis` resolves the executable and
`psx launch` starts it and waits for COM to attach.

**The executable path is resolvable through the registry.** COM attachment
itself goes through the class id, and the same table records the real
executable location:

```
HKCR\Photoshop.Application\CLSID              -> {2682BB05-0A88-430F-8614-EE4E60E6D916}
HKCR\CLSID\{2682BB05-...}\LocalServer32       -> C:\Path\To\Adobe Photoshop 2026\Photoshop.exe /Automation
```

The registry chain resolves the registered executable path from the same
table Windows uses to start the COM server.

`psx.find_photoshop_exe()` resolves in this order, which is worth reusing:

1. the `PHOTOSHOP_PATH` environment variable — explicit override (a file or a folder)
2. **the COM CLSID chain above** — authoritative for the actual install
3. default install globs under `%ProgramFiles%` — last resort

## 14. Layer names are localised [verified]

Default layer names are translated on non-English installs (not always `Background`). Never match on
English names; prefer indexes, `isBackgroundLayer`, or names you set yourself.
