#!/usr/bin/env python
"""psx -- minimal, self-contained Photoshop executor for the photoshop-driver skill.

Two channels, both proven on Windows + Photoshop 2026 (v27.10):

  jsx   ExtendScript via COM (win32com.client). SYNCHRONOUS: whatever the script
        returns comes back as a string. Use for multi-step work in one call
        (build N layers + export M files + save a PSD in a single round trip).
        Needs: pywin32. Photoshop must be running.

  psjs  UXP script (.psjs) via the Windows shell file association. There is NO
        return channel, so results come back through console.log -> UXPLogs.
        Use for modern commands and anything UXP-only. Needs no extra packages.

  selftest  Runs both channels end to end on a throwaway scratch document and
        reports PASS/FAIL per capability. Run this when setting up an unfamiliar
        machine, or when either channel needs diagnosis.

  export    Flattened PNG of the canvas without saving the document.

The jsx channel wraps your script in an IIFE + try/catch AUTOMATICALLY. That is
not a style preference -- it is the fix for a major silent-failure mode in
this stack: DoJavaScript returns an empty string with NO error both when the
script uses a top-level `return` and when it throws an uncaught exception. An
unwrapped script therefore fails completely silently. The wrapper converts both
into visible output, so you get either your value or a real error message.

Convention for jsx bodies: `return` a string (or build one and return it). If you
forget, psx says so explicitly instead of handing you a silent empty string.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

try:
    import win32com.client
except ImportError:
    win32com = None

try:
    import winreg          # Windows-only; the ExtendScript channel is too
except ImportError:
    winreg = None


def emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def fail(msg, extra=None):
    out = {"ok": False, "error": msg}
    if extra:
        out.update(extra)
    emit(out, 1)


# --------------------------------------------------------------------------
# ExtendScript channel (COM)
# --------------------------------------------------------------------------

def com_app():
    if win32com is None:
        return None, "pywin32 not installed (pip install pywin32)"
    try:
        return win32com.client.GetActiveObject("Photoshop.Application"), None
    except Exception as e:
        return None, ("could not attach to Photoshop via COM: %s\n"
                      "This command does not auto-launch Photoshop; use `psx launch` "
                      "if needed. PS can also exit on its own, so re-check with "
                      "`psx ping`." % e)


def _first_token(body):
    """Strip leading whitespace and comments so we can see the first real token."""
    s = body.lstrip()
    while True:
        if s.startswith("//"):
            nl = s.find("\n")
            if nl == -1:
                return ""
            s = s[nl + 1:].lstrip()
        elif s.startswith("/*"):
            end = s.find("*/")
            if end == -1:
                return s
            s = s[end + 2:].lstrip()
        elif s.startswith("<!--"):
            end = s.find("-->")
            if end == -1:
                return s
            s = s[end + 3:].lstrip()
        else:
            return s


def find_photoshop_exe():
    """Locate Photoshop.exe, without assuming a default install path.

    Resolution order:
      1. the PHOTOSHOP_PATH environment variable
                                     -- explicit override (file or directory)
      2. COM registration         -- HKCR\\Photoshop.Application\\CLSID ->
                                     <clsid>\\LocalServer32 -> the real exe path
      3. default install globs    -- %ProgramFiles%\\Adobe\\Adobe Photoshop *\\

    Step 2 is preferred because it reflects the registered COM server path:
    attaching to Photoshop goes through that CLSID, so the registry entry is
    authoritative for the active installation.
    Returns (exe_or_None, how_it_was_found).
    """
    env = os.environ.get("PHOTOSHOP_PATH")
    if env:
        p = os.path.join(env, "Photoshop.exe") if os.path.isdir(env) else env
        if os.path.isfile(p):
            return p, "PHOTOSHOP_PATH environment variable"
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Photoshop.Application\CLSID") as k:
                clsid = winreg.QueryValueEx(k, "")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                                r"CLSID\%s\LocalServer32" % clsid) as k:
                raw = winreg.QueryValueEx(k, "")[0]
            # value looks like:  "C:\Path\To\Photoshop.exe" /Automation   (quotes optional)
            exe = raw.split('"')[1] if raw.startswith('"') else raw.split(" /")[0]
            exe = exe.strip().strip('"')
            if os.path.isfile(exe):
                return exe, "COM CLSID %s LocalServer32" % clsid
        except OSError:
            pass
    for pat in (r"%ProgramFiles%\Adobe\Adobe Photoshop *\Photoshop.exe",
                r"%ProgramFiles%\Adobe\Adobe Photoshop CC *\Photoshop.exe",
                r"%ProgramFiles(x86)%\Adobe\Adobe Photoshop *\Photoshop.exe"):
        hits = sorted(glob.glob(os.path.expandvars(pat)), reverse=True)
        if hits:
            return hits[0], "default install glob (%s)" % pat
    return None, None


def cmd_whereis():
    exe, how = find_photoshop_exe()
    app, _ = com_app()
    running = app is not None
    if exe is None:
        fail("could not locate Photoshop.exe. Set the PHOTOSHOP_PATH "
             "environment variable to override.",
             {"running": running})
    emit({"ok": True, "exe": exe, "resolvedVia": how, "exists": os.path.isfile(exe),
          "running": running})


def cmd_launch(wait=180):
    """Start Photoshop if it is not already up, then wait for COM to attach.

    `psx` deliberately does not launch Photoshop for every command, but a fresh
    session needs *some* way to bring it up -- otherwise "Photoshop must already be
    running" is a dead end. PS can also quit on its own mid-session, so this doubles
    as the recovery step.
    """
    app, _ = com_app()
    if app is not None:
        exe, how = find_photoshop_exe()
        emit({"ok": True, "alreadyRunning": True, "exe": exe, "resolvedVia": how})
    exe, how = find_photoshop_exe()
    if exe is None:
        fail("could not locate Photoshop.exe; set the PHOTOSHOP_PATH "
             "environment variable to the exe or its folder")
    try:
        subprocess.Popen([exe])
    except Exception as e:
        fail("failed to start %s: %s" % (exe, e))
    started = time.time()
    deadline = started + wait
    while time.time() < deadline:
        time.sleep(3)
        app, _ = com_app()
        if app is not None:
            version = None
            try:
                version = str(app.Version)
            except Exception:
                pass
            emit({"ok": True, "launched": True, "exe": exe, "resolvedVia": how,
                  "version": version, "seconds": round(time.time() - started, 1)})
    fail("started %s but COM did not attach within %ss" % (exe, wait))


def wrap_jsx(body):
    """IIFE + try/catch. See the module docstring for why this is mandatory.

    Accepts two body styles, because both are natural to write:
      * a statement list ending in `return <string>`   -> wrapped as-is
      * an already self-contained IIFE expression      -> wrapped as `return (<expr>)`
    Without the second branch, wrapping an IIFE in another IIFE swallows its
    return value and you get a silent `undefined` -- which is exactly the class of
    bug this whole module exists to eliminate.
    """
    head = _first_token(body)
    err = ("'__PSX_ERROR__ ' + (e && e.message ? e.message : String(e))"
           " + ' [line ' + (e && e.line ? e.line : '?') + ']'")
    if head.startswith("(function") or head.startswith("(async function"):
        return ("(function(){\ntry {\nreturn (\n"
                + body.rstrip().rstrip(";")
                + "\n);\n} catch (e) {\n  return " + err + ";\n}\n})()")
    return ("(function(){\ntry {\n" + body + "\n} catch (e) {\n  return "
            + err + ";\n}\n})()")


def jsx_str(s):
    """Quote a Python string as an ExtendScript string literal.

    Paths reach JSX through interpolated literals; an unescaped quote in a
    user path (e.g. "User's work") would otherwise produce a syntax error
    far from its cause.
    """
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def run_jsx(body):
    app, err = com_app()
    if app is None:
        return None, err
    try:
        raw = str(app.DoJavaScript(wrap_jsx(body)))
    except Exception as e:
        return None, "DoJavaScript failed: %s" % e
    if raw.startswith("__PSX_ERROR__"):
        return None, raw[len("__PSX_ERROR__"):].strip()
    if raw in ("", "undefined", "null"):
        return None, ("script returned %r -- it probably never called `return`. "
                      "Have the body build a string and `return` it." % raw)
    return raw, None


def cmd_jsx(source):
    if source == "-" or source is None:
        body = sys.stdin.read()
    else:
        if not os.path.isfile(source):
            fail("script not found: %s" % source)
        with open(source, encoding="utf-8") as f:
            body = f.read()
    if not body.strip():
        fail("empty script")
    raw, err = run_jsx(body)
    if err:
        fail(err)
    emit({"ok": True, "channel": "jsx", "result": raw})


def cmd_ping():
    app, err = com_app()
    if app is None:
        fail(err)
    version = None
    try:
        version = str(app.Version)
    except Exception:
        pass
    n_docs = None
    try:
        n_docs = int(app.Documents.Count)
    except Exception:
        pass
    emit({"ok": True, "channel": "jsx", "running": True,
          "version": version, "openDocuments": n_docs})


def cmd_export(path):
    abspath = os.path.abspath(path).replace("\\", "/")
    parent = os.path.dirname(abspath)
    if parent and not os.path.isdir(parent):
        fail("target directory does not exist: %s" % parent)
    body = """
var d = app.activeDocument;
var o = new PNGSaveOptions(); o.compression = 9;
d.saveAs(new File(%s), o, true);
return 'saved ' + d.width + 'x' + d.height + ' saved=' + d.saved;
""" % jsx_str(abspath)
    raw, err = run_jsx(body)
    if err:
        fail(err)
    emit({"ok": True, "channel": "jsx", "path": abspath, "detail": raw})


# --------------------------------------------------------------------------
# UXP channel (.psjs)
# --------------------------------------------------------------------------

CONSOLE_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}_[^\]]*\]\[\d+\]\[[^\]]*\]\s*\[console\]\s?")


def newest_uxp_log():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    logs = []
    for d in glob.glob(os.path.join(appdata, "Adobe", "Adobe Photoshop *", "Logs")):
        logs.extend(glob.glob(os.path.join(d, "UXPLogs_*.log")))
    return max(logs, key=os.path.getmtime) if logs else None


def slice_psjs_report(collected):
    """Slice the marker-framed JSON report out of raw UXP log output.

    The BEGIN/END markers share a prefix, so the report is cut by LINE
    position, not by a lazy regex (which would swallow the payload).
    Returns (parsed_json_or_None, console_lines, error_or_None).
    """
    lines = [_clean_log_line(ln) for ln in collected.splitlines()]
    # Photoshop writes its own chatter (e.g. IMS token errors when not signed in).
    lines = [ln for ln in lines if not ln.startswith("[DP] ")]

    begin = end = None
    for idx, ln in enumerate(lines):
        if begin is None:
            if ln.strip() == "UXP_REPORT_BEGIN":
                begin = idx
        elif ln.strip() == "UXP_REPORT_END":
            end = idx
            break
    if begin is None:
        return None, lines, "no UXP_REPORT_BEGIN line in the console output"
    if end is None:
        return None, lines, ("UXP_REPORT_BEGIN seen but no UXP_REPORT_END line "
                             "(each marker must be on its own line)")
    try:
        return json.loads("\n".join(lines[begin + 1:end])), lines, None
    except ValueError as e:
        return None, lines, "invalid JSON between the UXP report markers: %s" % e


def _clean_log_line(line):
    """Strip the UXP log prefix (timestamp/pid/tag + [console]) from a line.

    The single normalizer for log lines: both the live marker check in
    run_psjs and the final slice in slice_psjs_report go through it, so the
    two can never disagree about what a line says.
    """
    m = CONSOLE_RE.match(line)
    return line[m.end():] if m else line


def _has_marker_line(text, marker):
    """True when text contains marker as a whole (stripped) log line.

    Same strictness as slice_psjs_report: prefixes are cleaned first, and a
    line that merely mentions the marker text inside other content does not
    count.
    """
    return any(_clean_log_line(ln).strip() == marker for ln in text.splitlines())


def run_psjs(path, timeout=90, quiet_secs=3.0):
    """Launch a .psjs via the shell association and collect its UXP report.

    The single production path for running a .psjs -- `psx psjs` and the
    selftest both go through it, so the readback contract is exercised in
    exactly one place. Returns (parsed_json_or_None, console_text, log_path,
    error); error is None only when the marker-framed JSON report arrived
    intact.

    Timing: after UXP_REPORT_BEGIN is seen, the collector waits for END until
    the total timeout -- a long Photoshop operation between the markers is
    normal. Before any BEGIN, quiet_secs of silence ends the wait early
    (nothing more is coming). A first run may have no UXP log yet; the
    launched script itself creates it.
    """
    log = newest_uxp_log()
    offset = 0
    if log is not None:
        try:
            offset = os.path.getsize(log)
        except OSError:
            offset = 0
    try:
        os.startfile(os.path.abspath(path))          # Windows shell association
    except Exception as e:
        return (None, "", None,
                "could not launch the .psjs (is the .psjs association registered?): %s" % e)

    deadline = time.time() + timeout
    collected, last_change = "", None
    while time.time() < deadline:
        time.sleep(1.0)
        cur = newest_uxp_log()
        if cur is not None and cur != log:           # first log appeared / rotation
            log, offset = cur, 0
        if log is None:
            continue
        try:
            size = os.path.getsize(log)
        except OSError:
            continue
        if size < offset:
            offset = 0
        if size > offset:
            with open(log, encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                chunk = f.read()
            offset = size
            # A log write can split a single console line. Keep every chunk;
            # filtering happens after the complete marker-framed report is
            # collected, so a continuation without a fresh prefix is not lost.
            collected += chunk
            if "[console]" in chunk:
                last_change = time.time()
            if _has_marker_line(collected, "UXP_REPORT_END"):
                break
        elif (collected and not _has_marker_line(collected, "UXP_REPORT_BEGIN")
              and last_change and time.time() - last_change > quiet_secs):
            break    # chatter but no BEGIN -- nothing more is coming

    if not collected:
        if log is None:
            return (None, "", None,
                    "no Photoshop UXP log appeared under "
                    "%APPDATA%\\Adobe\\Adobe Photoshop *\\Logs within %ss" % timeout)
        return (None, "", log,
                "no console output reached the UXP log within %ss "
                "(does the script call console.log? did it throw before logging?)" % timeout)
    parsed, lines, err = slice_psjs_report(collected)
    if err:
        return None, "\n".join(lines), log, err
    return parsed, "\n".join(lines), log, None


def cmd_psjs(path, timeout=90):
    """Run a .psjs and read back what it logged.

    Contract for the script (see references/psjs-contract.md):
      * do NOT call core.showAlert -- a modal dialog blocks all later automation
      * do NOT wrap work in core.executeAsModal -- a standalone .psjs
        already executes inside Photoshop's scripting modal context
      * report with console.log, and wrap JSON in UXP_REPORT_BEGIN / UXP_REPORT_END

    psx psjs exits non-zero unless the marker-framed JSON report arrives
    intact: missing BEGIN, missing END, or unparsable payload JSON are all
    failures, not a silent ok:true with json:null. A payload that itself
    carries "ok": false is propagated as a command failure too, so the
    outer ok covers the whole run -- transport and task.
    """
    if not os.path.isfile(path):
        fail("script not found: %s" % path)
    parsed, console, log, err = run_psjs(path, timeout=timeout)
    if err:
        extra = {"log": log}
        if console:
            extra["console"] = console
        fail(err, extra)
    if isinstance(parsed, dict) and parsed.get("ok") is False:
        # The report arrived intact and the script itself reported failure:
        # propagate it, so the outer ok covers the whole run -- transport and
        # task. The full payload rides along for diagnosis.
        fail("psjs reported failure", {"json": parsed, "console": console, "log": log})
    emit({"ok": True, "channel": "psjs", "json": parsed,
          "console": console, "log": log})


# --------------------------------------------------------------------------
# selftest -- the smoke test, so nobody has to reinvent it per session
# --------------------------------------------------------------------------

SELFTEST_JSX = r"""
function sTID(s){return stringIDToTypeID(s);}
function cTID(s){return charIDToTypeID(s);}
function hasMaskAM(){
  var r=new ActionReference(), a=new ActionDescriptor();
  r.putProperty(cTID('Prpr'), cTID('UsrM'));
  r.putEnumerated(cTID('Lyr '), cTID('Ordn'), cTID('Trgt'));
  a.putReference(cTID('null'), r);
  try { return executeAction(cTID('getd'), a, DialogModes.NO).hasKey(cTID('UsrM')); }
  catch(e){ return false; }
}
function makeLayerMask(mode){
  var d=new ActionDescriptor(), r=new ActionReference();
  d.putClass(sTID('new'), sTID('channel'));
  r.putEnumerated(sTID('channel'), sTID('channel'), sTID('mask'));
  d.putReference(sTID('at'), r);
  d.putEnumerated(sTID('using'), sTID('userMaskEnabled'), sTID(mode));
  executeAction(sTID('make'), d, DialogModes.NO);
}
// Capability probe: run each command with an empty descriptor and classify
// by response -- the probe_commands.jsx method, on a smaller candidate list.
// A resolved type id alone proves nothing: stringIDToTypeID succeeds for
// plenty of strings that are not executable commands.
function probeAction(name){
  try {
    executeAction(sTID(name), new ActionDescriptor(), DialogModes.NO);
    return 'callable';
  } catch(e) {
    var m = String(e && e.message ? e.message : e);
    if (/unknown/i.test(m) || /<[^>]+>/.test(m)) { return 'not-an-am-command'; }
    return 'resolved-needs-args';
  }
}
app.displayDialogs = DialogModes.NO;
var out=[];
var doc=null;
try {
  doc=app.documents.add(UnitValue(64,'px'),UnitValue(64,'px'),72,'PSX_SELFTEST',
                        NewDocumentMode.RGB, DocumentFill.WHITE);
  out.push('createDocument=ok');
} catch(e){ out.push('createDocument=FAIL:'+e.message); }

if (doc) {
  try {
    var lay=doc.artLayers.add(); lay.name='T';
    doc.selection.select([[8,8],[56,8],[56,56],[8,56]]);
    makeLayerMask('revealSelection');
    doc.selection.deselect();
    out.push('layerMask_revealSelection='+(hasMaskAM()?'ok':'FAIL'));
  } catch(e){ out.push('layerMask_revealSelection=FAIL:'+e.message); }

  try {
    var v=null; try{ v=String(doc.layers[0].hasLayerMask); }catch(e){ v='throws'; }
    out.push('layer.hasLayerMask_reads_as='+v+' (expected undefined -> use hasMaskAM)');
  } catch(e){ out.push('hasLayerMask_read=FAIL:'+e.message); }

  try {
    doc.layers[0].visible=false;
    out.push('set_visible_false=ok(reads '+doc.layers[0].visible+')');
    doc.layers[0].visible=true;              // restore before the probes below
  } catch(e){ out.push('set_visible_false=FAIL:'+e.message); }

  // capability probes run with the scratch document still open
  out.push('action.autoCutout='+probeAction('autoCutout'));
  out.push('action.selectSky='+probeAction('selectSky'));
  out.push('action.selectPeople='+probeAction('selectPeople'));
  out.push('action.colorRange='+probeAction('colorRange'));

  try { doc.close(SaveOptions.DONOTSAVECHANGES); out.push('closeScratch=ok'); }
  catch(e){ out.push('closeScratch=FAIL:'+e.message); }
}

return out.join('\n');
"""

SELFTEST_PSJS = r"""
const { app } = require("photoshop");
const uxp = require("uxp");
console.log("UXP_REPORT_BEGIN");
console.log(JSON.stringify({
  hostVersion: uxp.host && uxp.host.version ? uxp.host.version : "unknown",
  appVersion: String(app.version),
  documents: app.documents.length
}));
console.log("UXP_REPORT_END");
"""


def cmd_selftest(seconds=90):
    report = {}
    jsx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_selftest_tmp.jsx")
    psjs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_selftest_tmp.psjs")
    try:
        with open(jsx_path, "w", encoding="utf-8") as f:
            f.write(SELFTEST_JSX)
        raw, err = run_jsx(SELFTEST_JSX)
        if err is not None:
            report["jsx"] = {"ok": False, "detail": err}
        elif "=FAIL" in raw:
            # DoJavaScript itself succeeded, but an in-script capability
            # check failed -- the channel is alive, the capability is not.
            report["jsx"] = {"ok": False, "detail": raw,
                             "error": "in-script capability check(s) reported FAIL"}
        else:
            report["jsx"] = {"ok": True, "detail": raw}
    except Exception as e:
        report["jsx"] = {"ok": False, "detail": str(e)}
    try:
        with open(psjs_path, "w", encoding="utf-8") as f:
            f.write(SELFTEST_PSJS)
        parsed, _console, log, err = run_psjs(psjs_path, timeout=seconds)
        if err is not None:
            report["psjs"] = {"ok": False, "log": log, "detail": err}
        else:
            report["psjs"] = {"ok": True, "log": log, "detail": parsed}
    except Exception as e:
        report["psjs"] = {"ok": False, "detail": str(e)}
    finally:
        for p in (jsx_path, psjs_path):
            try:
                os.remove(p)
            except OSError:
                pass
    report["ok"] = bool(report["jsx"]["ok"] and report["psjs"]["ok"])
    report["note"] = ("jsx is the primary channel; if psjs failed, check that the "
                      ".psjs file association is registered to Photoshop.")
    emit(report, 0 if report["ok"] else 1)


USAGE = """psx -- Photoshop executor

  psx ping                      attach via COM, report version + open doc count
  psx whereis                   resolve where Photoshop.exe actually lives
  psx launch [secs]             start Photoshop if needed, wait for COM to attach
  psx jsx <file.jsx|->          run ExtendScript, return its value ('-' = stdin)
  psx psjs <file.psjs> [secs]   run a UXP script, read back console output
  psx export <out.png>          PNG of the active canvas, document stays unsaved
  psx selftest [secs]           probe both channels + key capabilities

Run `selftest` first on an unfamiliar machine; run `launch` when Photoshop is not up
(it can also quit on its own mid-session).
"""


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    cmd, rest = argv[1].lower(), argv[2:]

    def seconds_at(index, default, label):
        if len(rest) <= index:
            return default
        try:
            value = int(rest[index])
        except (TypeError, ValueError):
            fail("invalid %s: %s (expected an integer)" % (label, rest[index]))
        if value <= 0:
            fail("invalid %s: %s (expected a positive integer)" % (label, rest[index]))
        return value

    if cmd == "ping":
        cmd_ping()
    elif cmd == "whereis":
        cmd_whereis()
    elif cmd == "launch":
        cmd_launch(seconds_at(0, 180, "launch timeout"))
    elif cmd == "jsx":
        cmd_jsx(rest[0] if rest else "-")
    elif cmd == "psjs":
        if not rest:
            fail("usage: psx psjs <file.psjs> [timeout_seconds]")
        cmd_psjs(rest[0], seconds_at(1, 90, "psjs timeout"))
    elif cmd == "export":
        if not rest:
            fail("usage: psx export <out.png>")
        cmd_export(rest[0])
    elif cmd == "selftest":
        cmd_selftest(seconds_at(0, 90, "selftest timeout"))
    else:
        fail("unknown command: %s" % cmd, {"usage": USAGE})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
