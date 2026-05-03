# Scientific Trace Skill

`submission_trace.json` is the audit record. It should make the result
reconstructable by another reviewer:

- input files or samples actually used
- workflow stages actually executed
- object/event selection or filtering decisions
- observables or spectra constructed
- inference, fitting, counting, or comparison method
- validation checks and limitations
- generated output filenames

Use the exact trace field names required by the submission contract. When the
prompt explicitly names exact stage IDs, cut IDs, sample names, or output names,
record those values in machine-readable fields.
