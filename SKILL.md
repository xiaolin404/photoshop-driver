---
name: photoshop-driver
description: >-
  A machine-verified driver for controlling Adobe Photoshop from an AI agent on
  Windows: psx.py runs ExtendScript through COM and UXP .psjs scripts, reads
  results back, and verifies them with task-appropriate evidence. Use it for any Photoshop scripting
  or .psd/.psb work — assembling layers and masks from computed mattes,
  isolating subjects or regions, background removal, batch exports, native
  commands such as selectSky / selectPeople / colorRange, or raw batchPlay
  descriptors. Capability probing establishes what the installed build
  supports. Load it when a Photoshop call reports success but nothing visibly
  changed, when a script returns empty output without an error, or when a
  selection or matte comes back empty, hollow, or contaminated.
---

# photoshop-driver

A control layer between an AI agent and a running Photoshop. The agent runs
scripts through `psx.py`; Photoshop executes them through one of two script
channels; results flow back as return values, log output, and rendered files
that the agent verifies with evidence appropriate to the task.

Unless marked `[documented]`, behaviour described here was reproduced locally
on **Windows 11 + Photoshop 2026 (v27.10)**. See `README.md` for
the labelling scheme.

**Platform scope.** macOS is untested. In principle a port mainly replaces the
launcher, the install-discovery, and the COM transport layers, while the
Photoshop-side UXP/`.psjs` logic carries over largely unchanged — unverified.

## Shape of the system

```
AI / CLI agent
   |
   v
psx.py                        the executor: one Python file, stdlib + pywin32
   |  selftest / ping / whereis / launch        (session control)
   |
   +-- jsx  --> COM (Photoshop.Application)  --> ExtendScript engine
   |             synchronous; the script's return value comes straight back
   |
   +-- psjs --> shell .psjs association --> UXP script host
                 no return value; the script reports through console.log
                 and psx.py reads the newest UXPLogs_*.log
   |
   v
Photoshop (must be running with a UI; it can exit on its own mid-session)
   |
   v
return value | UXP log | exported PNGs | saved PSD
   |
   v
agent inspects the results, corrects, re-runs
```

## Workflow

Start by identifying the requested Photoshop operation and its acceptance
criteria. Then choose only the checks and channel needed for that operation:

1. **Check the session when needed.** Use `psx ping` for a running-session
   check. Use `selftest` for first-time setup or channel troubleshooting; it
   exercises both channels on a throwaway document. If Photoshop is down, use
   `whereis` and `launch` to locate and start it.
2. **Choose the channel.** Use ExtendScript for synchronous DOM/Action Manager
   sequences that need an inline return value. Use `.psjs` for modern UXP
   commands, batchPlay, or pixel and mask data. Probe a command only when its
   availability or headless behavior is uncertain.
3. **Run the smallest useful operation.** Keep scripts dialog-free and use the
   report protocol for `.psjs`. Read the returned value, log report, or saved
   artifact before deciding whether another pass is needed.
4. **Verify the requested result.** Inspect rendered output for image edits,
   reopen saved PSDs when on-disk state matters, and use the numeric checks in
   `references/verify-loop.md` for decomposition or matte work. These checks
   are task-specific, not prerequisites for every Photoshop call.

```bash
python /path/to/photoshop-driver/scripts/psx.py ping
python /path/to/photoshop-driver/scripts/psx.py selftest
python /path/to/photoshop-driver/scripts/psx.py whereis   # locate the exe
python /path/to/photoshop-driver/scripts/psx.py launch    # start, wait for COM
```

Replace the path with the directory where this Skill is installed.

`whereis` walks the COM registration
(`HKCR\Photoshop.Application\CLSID` → `CLSID\{…}\LocalServer32`) to resolve
the registered executable path.
`%ProgramFiles%` globbing is the fallback (see `references/gotchas.md` #13).
Both channels attach to a live application; neither runs headless.

## Ground rules

**Verify operations from the evidence appropriate to the task.**
Photoshop reports success for operations that did nothing: fills on empty
layers, writes to locked layers that are quietly normalised away, property
reads that answer `undefined`. For image edits, run a change, inspect the
export, and correct what the inspection showed. For saved documents, reopen
the file when its on-disk state matters. `references/verify-loop.md` has the
inspection method and optional numeric checks.

**ExtendScript must `return`, and `psx` must do the wrapping.** Through COM,
`DoJavaScript` answers `""` without complaint both for a top-level `return`
and for an uncaught throw — a broken script and a deliberately empty one are
indistinguishable. `psx.py jsx` wraps every body in an IIFE with a try/catch
that converts both cases into readable output. Do not bypass it by calling COM
yourself.

**Use masks for matte corrections so source pixels remain intact.** Isolation
work attaches masks to duplicate layers, so the original pixels survive
untouched and recomposite comparison against the source stays meaningful.

**Preserve the user's file when the task requires it.** For isolation or
decomposition work, hash the source and save with `asCopy = true` or to a
fresh path. If the user explicitly asks to edit in place, follow that scope.

**Suppress dialogs in every script.** `app.displayDialogs = DialogModes.NO`
goes at the top of each ExtendScript; a `.psjs` must not call `alert` /
`showAlert` / `confirm`. One illegal operation otherwise raises a native
dialog on the user's screen, and that dialog parks Photoshop for every later
call.

**Two namespaces, two vocabularies.** Action Manager command strings and DOM
method names are separate namespaces: `selectAll` is not an AM command, while
`doc.selection.selectAll()` works. `references/command-catalog.md` explains
how to probe both.

## Choosing a channel

| | `psx.py jsx` — ExtendScript via COM | `psx.py psjs` — UXP script |
|---|---|---|
| Round trip | one synchronous call, value returned inline | launch + log readback via report markers |
| Best at | multi-step DOM/Action Manager builds with an inline result | modern native commands, batchPlay descriptors, pixel/mask data through the Imaging API |
| Language limits | ES3 | modern JavaScript, `await` allowed |
| Dependencies | `pywin32` | none beyond the installed app |

A decomposition job typically combines them: the `.psjs` channel computes or
fetches a matte, ExtendScript assembles the document in one round trip.

## Documentation index

- `references/command-catalog.md` — what is callable on the reference build,
  how to classify a probe result, and the `refineSelectionEdge` case study: a
  command whose name resolves can still be unusable headlessly. Read before
  concluding a command is unavailable.
- `references/selection-and-masking.md` — computed matte → layer mask without
  losing 8-bit softness; splitting multi-subject selections by measured
  geometry; choke; strict partitions; hairlines; additive light.
- `references/gotchas.md` — fourteen behaviours that fail quietly, each with
  its measured symptom and working alternative.
- `references/verify-loop.md` — what inspection means at each scale, the
  numeric checks that catch what eyes miss, and how to report what is still
  wrong.
- `references/psjs-contract.md` — the `.psjs` channel end to end: runtime
  constraints, the report-marker protocol, launch mechanics, UXP platform
  boundaries.
- `scripts/probe_commands.jsx` — asks the installed build which Action
  Manager names exist. Edit its candidate list to probe more.
- `scripts/psx.py` — the executor (`ping`, `whereis`, `launch`, `jsx`, `psjs`,
  `export`, `selftest`).

## Worked pattern: flat illustration → layered document

1. **Hash the source; open a copy.** The original is never written.
2. **Measure first.** Bounding boxes, connected components, row/column
   profiles — computed before any split line is chosen. A split line chosen
   by eye can clip an overlapping bounding-box corner and carry a sliver of
   one subject into another's layer.
3. **Spend native commands where they exist.** `autoCutout` returns every
   subject in one selection; `selectSky` / `selectPeople` / `colorRange`
   cover their domains. Confirm against the catalog, then inspect the output.
4. **Compute what no command does** — hairlines, additive glows, semantic
   splits — from the source pixels with numpy.
5. **Partition.** Assign each pixel to exactly one part by
   priority so the recomposite reconstructs the original bit-exactly. The one
   layout where this does not apply, and why: `selection-and-masking.md`.
6. **One part = one duplicate layer + mask.** Originals untouched throughout.
7. **Inspect every part**: alone on black and on white, plus the partition,
   contamination, hollow, and recomposite-diff checks.
8. **Save the PSD, reopen it**, and read back the layer stack to confirm what
   reached disk.
9. **Report residue with numbers.** Matte work retains residual defects; the
   sizes of what remains wrong belong in the deliverable.

## Task-specific checklist

```
- [ ] session/channel check performed when needed
- [ ] dialogs suppressed in every script (DialogModes.NO / no alert calls)
- [ ] command availability probed when uncertain
- [ ] returned value, rendered output, or saved artifact inspected
- [ ] source preserved when the task requires non-destructive work
- [ ] decomposition/matte checks run when that is the requested deliverable
- [ ] verified facts separated from inferences in the report
```
