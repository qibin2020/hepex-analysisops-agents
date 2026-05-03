# Bundle Contract Review Skill

Before returning, check the bundle as if another agent will reject it:

- The top-level value is JSON with an `artifacts` object.
- Required artifact names are present and no undeclared artifact names appear.
- JSON artifacts are objects and markdown artifacts are strings.
- Required schema fields are present.
- Declared field types are respected.
- Contract constraints such as array alignment, minimum lengths, and
  `contains_all` are satisfied.
- `submission_trace.json` lists the generated required outputs when the
  contract asks for `output_files_generated`.
- `interpretation.md` is consistent with the computed artifacts and trace.
