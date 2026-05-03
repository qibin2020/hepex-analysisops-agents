# Vectorized ROOT Analysis Skill

Use this skill when the task reads ROOT files, especially full-sample ATLAS Open Data workflows.

Prefer chunked, array-oriented analysis:

- Read ROOT trees with `uproot.iterate(...)` or chunked `tree.arrays(...)`; do not load all full-sample branches into memory at once unless the manifest is tiny.
- Select only the branches needed for the contract outputs and trace evidence.
- For jagged lepton/photon/jet collections, use `awkward` masks, sorting, combinations, and reductions instead of a main Python event loop.
- Compute invariant masses with `vector` behaviors or equivalent vectorized four-vector formulas over arrays.
- Fill spectra with `np.histogram(..., weights=...)` or an equivalent vectorized weighted histogram operation.
- Accumulate MC histogram variances with `np.histogram(..., weights=weights * weights)` and report bin uncertainties as `sqrt(sum(w^2))`.
- Keep per-sample and per-chunk counters for files, events, selected events, candidates, histogram entries, and skipped/problematic chunks.

Avoid plain per-event main loops such as `for i in range(len(events))` for the full ROOT workflow. Small loops for candidate bookkeeping are acceptable only when awkward/vectorized logic would be unclear; if you use one, explain the exception in `submission_trace.json` and keep the heavy I/O, masking, mass computation, and histogram filling vectorized.

Write analysis scripts, lightweight logs, and any intermediate summaries under the solver work directory so the execution path can be audited.
