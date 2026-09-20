// hello.jsx -- the smallest useful ExtendScript round trip.
//
// Run:  python scripts/psx.py jsx examples/hello.jsx
//
// ExtendScript is ES3: no let/const, no arrow functions. psx.py wraps the
// body in an IIFE + try/catch, so this top-level `return` is what hands the
// value back through COM. Without a `return`, psx reports an explicit error
// instead of a silent empty string.
app.displayDialogs = DialogModes.NO;
var doc = app.documents.add(UnitValue(64, 'px'), UnitValue(64, 'px'), 72,
                            'PSX_DEMO', NewDocumentMode.RGB, DocumentFill.WHITE);
return 'created ' + doc.name;
