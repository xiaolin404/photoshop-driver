# Command catalog — Photoshop 27.10 capability test record

This catalog records Action Manager commands tested on the reference build:
Windows 11, Photoshop 2026 **v27.10**. To verify behavior on another
build, re-run the probe:

```
python scripts/psx.py jsx scripts/probe_commands.jsx
```

Every entry below is a snapshot of the reference build. Entries in the
selection families reproduce from `probe_commands.jsx`'s default candidate
list; the rest (`deselect`, `make`, `groupEvent`, `placedLayerReplaceContents`,
the clipboard commands, …) were probed ad hoc with the same `executeAction`
method — add those names to the candidate list to re-verify them.

---

## How to read a probe result

The probe calls `executeAction(name, <empty descriptor>)` and uses the
returned error text as a practical heuristic to classify command availability.
On English installs, Photoshop's wording distinguishes three cases:

| Error text | Meaning |
|---|---|
| no error | the command ran with defaults |
| `The command "<unknown>" is not currently available.` | **not an Action Manager command name** |
| `The command "Replace Contents" is not currently available.` | the name **resolved** — the message prints the localized command name; the arguments were wrong |

The third form establishes existence: the localized name in the message
confirms the identifier resolved, and the failure is in the arguments. The
sentence ends in "not currently available", which invites the wrong
classification — check for the `<unknown>` placeholder before concluding a
name is absent.

Because classification relies on error strings from an empty-descriptor call,
treat it as an empirical heuristic rather than a formal proof. Two caveats
apply before classifying anything:

- **"not an AM name" ≠ "impossible".** DOM methods live in a different namespace:
  `selectAll` is not an AM action name, but `doc.selection.selectAll()` is a DOM
  method and works. Check the DOM too.
- The probe passes an **empty** descriptor. A command that only works from a modal
  UI, or that validates its args before anything else, can look absent.

---

## Callable with no arguments — ran as-is

```
autoCutout    selectPeople   selectSky    colorRange    refineSelectionEdge
removeBackground   copyEvent   paste   imageSize   inverse
```

Resolvable but needing arguments (the error names the real localized command,
which establishes existence): `grow`, `similar`, `expand`,
`contract`, `border`, `feather`, `copyMerged`,
`placeEvent`, `skyReplacement`, `neuralGalleryFilters`.

Notes:

- **`selectSky`, `selectPeople`, `colorRange`, `removeBackground` all ran on
  this build.**
- **`refineSelectionEdge` resolved** — see the case study below; existence
  and headless usability are separate questions.
- **"Callable" was established on a blank 64×64 scratch document.** That
  proves the command is *recognised and invocable*; it does **not** prove it
  produces a useful result on real content. A blank document has no sky and
  no people. Test on real content and inspect the output before relying on
  it.

`autoCutout` (Select Subject) is the one command confirmed on real content:
repeated runs produced identical selection bounds, and it selects **all**
subjects at once — multiple distinct foreground objects together in one selection.
Splitting them is a downstream step (see `selection-and-masking.md`).

## Resolved — name exists, empty arguments rejected

```
skyReplacement              -> Sky Replacement
neuralGalleryFilters        -> Neural Filters
similar                     -> Similar
deselect                    -> Deselect
feather                     -> (exists; cancelled rather than rejecting)
make                        -> Make
groupEvent                  -> Create Clipping Mask
placedLayerReplaceContents  -> Replace Contents
```

## Not an Action Manager command name on this build

```
refineEdge   selectAndMask   objectSelection   objectSelectionRefine
magicWand    lasso           polygon           selectColorRange
selectSubject   selectSubjectV5   selectSubjectOnDevice
selectPortrait  bodyParsing   instanceMaskPrediction   stuffMaskGenerator
selectBackground  selectFocus  skySegmentation   skySelect
smooth       threshold       selectAll        saveSelection   loadSelection
depthPrediction  depthBlur    neuralFilter     harmonization
superZoom    colorize        multiGet

// parameter KEYS, not commands -- they only make sense inside a descriptor:
refineEdgeParameters  refineEdgeBorderRadius  refineEdgeBorderContrast
refineEdgeSmooth  refineEdgeFeatherRadius  refineEdgeChoke
refineEdgeDecontaminate  refineEdgeDeconWeight  refineEdgeAutoRadius
refineEdgeOutput
```

A name in this list means the identifier did not resolve as an AM command on
this build. Before concluding the capability itself is unavailable, check:

- some are **DOM methods**, a different namespace — `selectAll` is not an AM command,
  but `doc.selection.selectAll()` works
- some are **parameter keys** rather than commands (the whole `refineEdge*` family)
- some are **tool modes** in the UI with no headless equivalent
- the probe passes an *empty* descriptor, so a command that demands args before
  doing anything can look absent

---

## Not callable headlessly (as of this snapshot)

| Capability | Status |
|---|---|
| **Refine Edge / Select and Mask** | **Name resolves, headless usability not established.** The command is `refineSelectionEdge` — *not* `refineEdge` or `selectAndMask`, which is why an earlier probe wrongly classified the whole capability as absent. It does not behave like a headless command: see the case study below. |
| **Magic Wand / Object Selection as headless commands** | Present on this build only as *tool modes* in the UI, not as callable commands. A recorded Action may reveal a usable descriptor — a route worth trying with the Actions panel. |
| **Depth Blur** | A Neural Filter. Locally only `sendDataToNeuralGallery` exists (opens the UI). Not automatable through tested routes. |

## Case study: `refineSelectionEdge` — name resolution is not usability

An example where an initial conclusion was wrong, and how the probe data
corrected it.

`refineSelectionEdge` runs with no error. The `refineEdgeParameters`,
`refineEdgeFeatherRadius`, `refineEdgeChoke`, `refineEdgeSmooth`,
`refineEdgeDecontaminate` … names all report `<unknown>` — because
**they are parameter keys, not commands**. Probing `refineEdge` (the wrong
name) initially produced "this capability does not exist", which was
incorrect.

So the command exists. Does it work? Seven descriptor shapes were tried on a
scratch document with a live rectangular selection:

| Descriptor | Result |
|---|---|
| empty | accepted |
| nested `refineEdgeParameters{…}` object | accepted |
| flat `refineEdge*` unit-double keys | accepted |
| flat plain integers | accepted |
| a single `refineEdgeFeatherRadius` | accepted |
| `refineEdgeOutput` enum | accepted |
| `refineEdgeSmooth` = 10, checking for effect | accepted |

Every shape was accepted — **including nonsense keys** — and after every call
`doc.selection.bounds` threw a "no such element" error, i.e. **the selection was gone and no
new one existed**. A parameterised command normally validates its
arguments or reports unknown keys. Accepting anything, then consuming the
selection and producing nothing, matches the behaviour of a **modal /
UI-opening command** rather than a headless operation.

Conclusion: the name resolves; headless usability is not established. A
scriptable alternative for edge refinement: build it from mask compositing
and pixel operations — `feather`, `contract`, `expand`, `smooth`, and
reading/writing mask data through the `.psjs` Imaging API.

Practical rule from this case: **probe for existence, then probe for
effect.** An accepted call establishes little on its own; check
`doc.selection.bounds` (or an equivalent) afterwards.

## Finding names not in this catalog

In rough order of usefulness:

1. **Probe.** `probe_commands.jsx` covers AM names on the build it runs on.
2. **Record an Action.** Actions panel → record → perform the operation by hand →
   inspect the recorded steps (and "Copy as JavaScript" where available). This is
   how you get the descriptor for anything the UI can do.
3. **Listen to the notification stream.** In UXP,
   `action.addNotificationListener(['all'], cb)` while you perform the operation by
   hand prints the descriptors Photoshop itself used.
4. **Introspect.** `_obj: "get"` / `multiGet` to read properties back.
5. **Adobe's terminology header** — `PIStringTerminology.h` in the Photoshop C++
   SDK lists command and parameter strings. This is where the `refineEdge*`
   family came from. It establishes that a name *exists in the vocabulary*;
   confirm with a probe that this build accepts it.
