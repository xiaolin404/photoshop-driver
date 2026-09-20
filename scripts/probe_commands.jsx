// probe_commands.jsx -- which native Photoshop action names actually exist HERE?
//
// Run:  python scripts/psx.py jsx scripts/probe_commands.jsx
//
// Why this exists: Photoshop capabilities vary by build. Probe the installed
// build directly instead of relying on any packaged capability list.
//
// Method: executeAction with an intentionally empty descriptor, then classify by
// the error TEXT. Photoshop distinguishes the two cases for us:
//     The command "<unknown>" is not currently available.  -> not a command at all
//     The command "Similar" is not currently available.    -> the name RESOLVED (it even prints the real
//                                    localized name); our args were just wrong
// That second form establishes existence, not absence -- don't misread it.
//
// Safety: runs on a throwaway scratch document. Generative / credit-consuming
// commands (syntheticFill, generateBackground, generative*) are DELIBERATELY
// excluded -- probing them can spend money or mutate pixels.
//
// ---------------------------------------------------------------------------
// EDIT THIS LIST to probe something new. Names come from Adobe's terminology
// header (pluginsdk/photoshopapi/photoshop/PIStringTerminology.h) or from
// recording an Action: Actions panel -> record -> do the thing -> read the
// steps as JavaScript ("Copy as JavaScript" in some builds), or use
// addNotificationListener(['all']) in UXP while performing the operation by hand.
// ---------------------------------------------------------------------------
// Body style: a plain statement list ending in `return`. `psx.py jsx` wraps it in
// an IIFE + try/catch itself -- do NOT add your own IIFE, or the inner return is
// swallowed. (psx accepts an IIFE body too, but plain is the clearer contract.)
app.displayDialogs = DialogModes.NO;
var sTID = function (s) { return stringIDToTypeID(s); };
var log = [];

    var CANDS = [
        // --- selection: subject / people / sky / colour -------------------
        'autoCutout', 'selectPeople', 'selectSky', 'colorRange',
        // --- Refine Edge family. These strings appear in Adobe's
        // terminology header; probe whether this build resolves them as
        // executable commands. ---
        'refineSelectionEdge', 'refineEdgeParameters', 'refineEdgeBorderRadius',
        'refineEdgeBorderContrast', 'refineEdgeSmooth', 'refineEdgeFeatherRadius',
        'refineEdgeChoke', 'refineEdgeDecontaminate', 'refineEdgeDeconWeight',
        'refineEdgeAutoRadius', 'refineEdgeOutput',
        // --- selection modify ---------------------------------------------
        'grow', 'similar', 'expand', 'contract', 'border', 'inverse',
        'smooth', 'feather',
        // --- modern / misc ------------------------------------------------
        // copyEvent / copyMerged / paste touch the system clipboard, which a
        // scratch document does not isolate. Probe them ad hoc only if you
        // accept that side effect.
        'removeBackground', 'skyReplacement', 'neuralGalleryFilters',
        'multiGet', 'placeEvent', 'imageSize'
    ];

    var scratch = null;
    try {
        scratch = app.documents.add(UnitValue(64, 'px'), UnitValue(64, 'px'), 72,
                                    'PROBE_SCRATCH', NewDocumentMode.RGB, DocumentFill.WHITE);
        log.push('scratchDoc=ok');
    } catch (e) {
        return 'scratchDoc=FAIL:' + e.message;
    }

    var ran = [], needsArgs = [], absent = [];
    for (var i = 0; i < CANDS.length; i++) {
        var nm = CANDS[i], msg = '', threw = false;
        try {
            executeAction(sTID(nm), new ActionDescriptor(), DialogModes.NO);
        } catch (e) {
            threw = true;
            msg = (e && e.message) ? e.message : String(e);
        }
        if (!threw) { ran.push(nm); continue; }
        if (/unknown/i.test(msg) || /<[^>]+>/.test(msg)) {
            absent.push(nm);
        } else {
            var m = msg.match(/"([^"]+)"/);
            needsArgs.push(nm + '  (resolved as "' + (m ? m[1] : '?') + '")');
        }
    }

    log.push('');
    log.push('CALLABLE_AS_IS (' + ran.length + ')  -- exists and ran with no args:');
    log.push('  ' + ran.join(', '));
    log.push('');
    log.push('EXISTS_BUT_NEEDS_ARGS (' + needsArgs.length + ')  -- name resolved, args/state wrong:');
    for (var a = 0; a < needsArgs.length; a++) { log.push('  ' + needsArgs[a]); }
    log.push('');
    log.push('DOES_NOT_EXIST (' + absent.length + ')  -- "<unknown>" = not a command on this build:');
    log.push('  ' + absent.join(', '));

    try { scratch.close(SaveOptions.DONOTSAVECHANGES); log.push(''); log.push('scratchClosed=ok'); }
    catch (e2) { log.push('scratchClosed=FAIL:' + e2.message); }

    return log.join('\n');
