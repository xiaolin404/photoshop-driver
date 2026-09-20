# The `.psjs` channel: runtime rules and the report round trip

A `.psjs` file is a UXP script — one JavaScript file executed by Photoshop's
modern scripting host (Photoshop 23.5+ `[documented]`, confirmed working on
27.10). It has no ES3 ceiling, it can `await`, and it reaches commands the
ExtendScript engine never got. The constraint that shapes the channel is that
**it has no return value**: whatever the script wants the outside world to
know must be written down from inside. This page describes the runtime
constraints and the readback protocol `psx.py psjs` implements.

## The report round trip

This is the core mechanism of the channel:

```
agent writes script.psjs          script calls console.log(...)
        |                                 |
        v                                 v
psx.py psjs launches it   -->   UXP host writes a UXPLogs_*.log line
        ^                                 |
        |                                 v
psx.py tails the newest log <--- marker lines frame the JSON payload
        |
        v
{"ok": true, "channel": "psjs", "json": <parsed payload>, "console": <raw text>}
```

The protocol a script must follow:

```js
console.log("UXP_REPORT_BEGIN");
console.log(JSON.stringify({ ok: true, layers: doc.layers.length }));
console.log("UXP_REPORT_END");
```

Two details that matter:

- **Markers sit on their own lines.** `psx.py` matches the marker lines
  exactly (whole line, whitespace-tolerant) and slices the report by line
  position — a lazy regex would eat the payload, because the BEGIN and END
  markers share a prefix. A line that merely mentions `UXP_REPORT_BEGIN`
  inside other text is ignored.
- **Log early, log unconditionally.** The two failure signatures for "nothing
  came back": the script threw before its first `console.log`, or every
  `console.log` sits inside a branch that never executed.

What `psx.py` does on its side: records the size of the newest
`%APPDATA%\Adobe\Adobe Photoshop *\Logs\UXPLogs_*.log` if one exists yet (on
a first run there is none, and the launched script creates it), starts the
script through the Windows shell association, then polls that log (it
handles rotation to a newer file) until `REPORT_END` appears or the total
timeout is reached. Before any `REPORT_BEGIN`, a few seconds of silence end
the wait early — after it, a long Photoshop operation between the markers is
waited out. Photoshop's own chatter is filtered out — lines starting
`[DP] ` (typically IMS token noise when no Adobe account is signed in) — and
the timestamp/pid prefixes on `[console]` lines are stripped. You get back
both the parsed JSON and the remaining console text.

The command exits non-zero unless the marker-framed JSON report arrives
intact: a missing `REPORT_BEGIN`, a missing `REPORT_END`, or unparsable
payload JSON is a failure, not a success with an empty payload. A payload
that itself carries `"ok": false` is propagated as a failure too — the
command's exit status covers the whole run, transport and task, and the full
payload is attached to the error output for diagnosis.

## Runtime constraints

Four properties of the UXP script host shape every script. Each is stated with
its consequence and its symptom.

1. **Modal context is granted, not requested.** Script code talks to the DOM
   and `batchPlay` directly; the `core.executeAsModal` wrapper that plugin code
   must use is neither needed nor valid here. A wrapper copied from a plugin
   sample produces "Photoshop is busy" / modal-state errors, or operations that
   quietly do not happen.

2. **No dialog may ever appear.** `core.showAlert`, `alert`, `confirm`,
   `prompt` — all forbidden. An unattended run has no one to dismiss a dialog;
   it blocks this script and everything queued behind it. Scripts report
   through `console.log` only, and batchPlay descriptors should carry
   `_options: { dialogOptions: "dontDisplay" }` `[documented]`.

3. **Sequencing is promise-based.** UXP operations return promises; skipping
   the `await` means ordering is left to chance, which usually looks like
   "the operation did nothing". Chain explicitly. The scripting slot is also
   exclusive: while one script runs, no other script starts, and a script
   cannot spawn another.

4. **Some DOM surface is absent.** `app.version` reads as `undefined` in a
   script — take the version from the host object instead:

   ```js
   const uxp = require("uxp");
   console.log(uxp.host.version);   // e.g. "27.10.0"
   ```

   `action.recordAction` also does nothing here `[verified]`: recording needs a
   plugin environment to hold the function declaration.

## How scripts get launched

There is no Photoshop CLI for scripts. `psx.py psjs` invokes the Windows shell
association registered for `.psjs`, so the same code path fires as when a user
double-clicks the file. Manual alternatives — File > Scripts > Browse,
dragging the file onto the canvas, an Action that references the script — do
the same thing by hand.

Consequences for automation design:

- Photoshop must be up, with its UI. There is no local headless mode for this
  channel.
- Launches are serial by nature: a running script holds the scripting slot, so launches queue and nothing re-enters.
- Anything that leaves a dialog standing on screen stalls the channel until a
  human clears it (constraint 2 above).

## Choosing between the two channels

| Reach for `.psjs` | Reach for ExtendScript (`psx.py jsx`) |
|---|---|
| Modern native commands: `selectSky`, `selectPeople`, `colorRange`, raw batchPlay | A build sequence that must complete in one synchronous call |
| Pixel and mask data via the Imaging API | Jobs that need the result value inline to decide the next step |
| `addNotificationListener` to observe what Photoshop does | Older Photoshop installs without a UXP scripting host |

Division of labour in an isolation job: `.psjs` produces or fetches the matte;
ExtendScript builds the document (duplicates, masks, exports, save) in a
single round trip. Both channels feed the same verification loop described in
`verify-loop.md`.

## UXP platform boundaries worth knowing

Facts imposed by the UXP sandbox `[documented]`; symptoms confirmed locally
where noted:

- **Filesystem access is picker-gated.** Only the temp folder and the script's
  own folder are writable without a prompt. Any other path makes UXP raise an
  interactive file picker — which, in an unattended run, nobody will ever
  answer, so the run hangs. Descriptors that reference a file (place, save to
  path) need a session token obtained via `fs.createSessionToken(entry)`.
