# photoshop-driver

A verified Photoshop automation driver for AI agents, bridging Windows
COM / ExtendScript and Photoshop UXP `.psjs` — with results read back and
verified using task-appropriate evidence; rendered output is inspected when
visual output matters.

## Why this project exists

This project lets an AI agent inspect, execute, verify, and iterate against a
running Photoshop without a human in the loop. Photoshop's success reports are
not always reliable: operations that change nothing can return success,
scripts that throw can return empty output, and property reads can return
`undefined` where a boolean is expected. The executor, the result-readback
protocol, and the verification procedure in this repository close that gap.

The documentation distinguishes locally verified behavior from behavior
established by Adobe's documentation:

| Label | Meaning |
|---|---|
| `[verified]` | reproduced on Windows 11 with Adobe Photoshop 2026 (v27.10) |
| `[documented]` | stated in Adobe's own API documentation |

## Architecture

```
AI / CLI agent
   |
   v
psx.py                          one-file executor (stdlib + pywin32)
   |
   |-- session control:  ping | whereis | launch | selftest
   |
   |-- jsx  ---> COM: Photoshop.Application --> ExtendScript engine
   |             synchronous; script's return value comes back inline
   |
   |-- psjs ---> Windows .psjs shell association --> UXP script host
   |             no return value; script reports via console.log
   |             psx.py tails the newest UXPLogs_*.log and extracts
   |             the JSON payload between UXP_REPORT_BEGIN / _END
   |
   v
Photoshop (running, with UI)
   |
   v
return value / UXP log / exported PNG / saved PSD
   |
   v
agent inspects the results, corrects, re-runs
```

## Features

- **Two execution channels, chosen per task.** ExtendScript (COM) for
  synchronous multi-step builds with an inline result; `.psjs` (UXP) for
  modern native commands, batchPlay descriptors, and pixel/mask data.
- **Install discovery through the COM registration.** `psx whereis` resolves
  the registered executable via the `Photoshop.Application` CLSID →
  `LocalServer32` chain;
  the `PHOTOSHOP_PATH` environment variable overrides, and `%ProgramFiles%`
  globs are the fallback.
- **Silent-failure handling.** The ExtendScript channel wraps every script in
  an IIFE + try/catch automatically, because `DoJavaScript` returns `""` with
  no error for both a top-level `return` and an uncaught throw. A script that
  omits `return` gets an explicit message instead of a silent empty result.
- **The `.psjs` report round trip.** UXP scripts have no return channel, so
  `psx.py` implements one: frame a JSON payload with
  `UXP_REPORT_BEGIN` / `UXP_REPORT_END` marker lines, then read it out of the
  newest Photoshop UXP log — with rotation handling and Adobe chatter
  filtered.
- **Capability probing.** `scripts/probe_commands.jsx` asks the installed
  build which Action Manager command names exist, classifying by Photoshop's
  own localized error text. The catalog in `references/` records what was
  found on the reference build, including native segmentation commands
  (`selectSky`, `selectPeople`, `colorRange`) and a case study distinguishing
  command existence from headless usability.
- **A measured gotcha catalogue.** Fourteen behaviours that fail quietly,
  each reproduced with its symptom and a working alternative — from
  `layer.hasLayerMask` returning `undefined` to saved-PSD normalisation
  silently re-showing locked layers.
- **A verification method.** Render-and-inspect procedure (1:1 crops,
  contact sheets), numeric checks (partition invariant, cross-contamination,
  hollow-result, recomposite diff), and reopening the saved file to audit
  what reached disk.

## Requirements

- **Windows 11** — the tested platform
- **Adobe Photoshop** — verified on 2026 (v27.10); the UXP `.psjs` channel
  needs 23.5+ `[documented]`
- **Python 3.8+** — and `pywin32` for the ExtendScript channel
  (`pip install pywin32`)
- Photoshop must be **running with its UI** for either channel; there is no
  local headless mode

## Quick start

```bash
pip install pywin32                      # ExtendScript channel only

python scripts/psx.py selftest           # probe both channels + key capabilities
python scripts/psx.py ping               # version + open document count
python scripts/psx.py whereis            # where does Photoshop.exe live
python scripts/psx.py launch             # start Photoshop if it is not up

# one synchronous ExtendScript round trip
python scripts/psx.py jsx examples/hello.jsx

# a UXP script: reports through the log, not a return value
python scripts/psx.py psjs examples/hello.psjs

# flattened PNG of the active canvas, document stays unsaved
python scripts/psx.py export out.png
```

The same commands work in PowerShell and CMD.

## Commands

| Command | What it does |
|---|---|
| `psx ping` | attach via COM, report version and open-document count |
| `psx whereis` | resolve the Photoshop.exe path and how it was found |
| `psx launch [secs]` | start Photoshop if needed, wait for COM to attach |
| `psx jsx <file.jsx\|->` | run ExtendScript synchronously, return its value (`-` = stdin) |
| `psx psjs <file.psjs> [secs]` | run a UXP script and read back its console report |
| `psx export <out.png>` | PNG of the active canvas; the document stays unsaved |
| `psx selftest [secs]` | exercise both channels end to end on a scratch document |

All output is JSON on stdout; failures exit non-zero with an `error` field.
The `PHOTOSHOP_PATH` environment variable (exe or folder) overrides install
discovery, e.g. in PowerShell:

```powershell
$env:PHOTOSHOP_PATH = "C:\Path\To\Adobe Photoshop 2026"
```

## Documentation

| File | Contents |
|---|---|
| `SKILL.md` | agent-facing entry point: architecture, ground rules, channel choice |
| `references/psjs-contract.md` | the `.psjs` channel end to end: runtime constraints, the report-marker protocol, launch mechanics, platform boundaries |
| `references/command-catalog.md` | Action Manager capability test record for the reference build, probe classification, the `refineSelectionEdge` case study |
| `references/gotchas.md` | fourteen silent-failure behaviours with fixes |
| `references/selection-and-masking.md` | computed mattes → layer masks, partition discipline, hairlines, additive light |
| `references/verify-loop.md` | inspection method, numeric checks, residual-defect reporting |

## Platform and limitations

- Windows 11 — the tested platform.
- macOS is untested. In principle a port mainly replaces the launcher,
  install-discovery, and transport layers; the Photoshop-side UXP/`.psjs`
  logic should carry over largely unchanged. Not verified.
- Photoshop with a UI must be running for either channel; the application can
  also exit on its own mid-session — `psx ping` re-checks the session state.
- The `.psjs` channel is read-by-log only: reports are line-framed JSON, and
  a script that fails before logging returns nothing (the failure is
  reported explicitly).
- Capability claims are snapshots of the build they were probed on; re-probe
  on yours.

## Related work

- Related project:
  [LissaGreense/photoshop-uxp](https://github.com/LissaGreense/photoshop-uxp)
  explores agent-driven Photoshop scripting through UXP, with a
  temp-folder-artifact readback architecture.

## License

[MIT](LICENSE)
