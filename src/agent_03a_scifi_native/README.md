# agent_03a_scifi_native

`agent_03a_scifi_native` is a SciFi-style solver backend for the HEPEx
AnalysisOps Purple Agent that does not depend on OpenHarness.

It starts from the `agent_02_scifi_oh` design:

```text
Green Agent task
  -> SAM prompt builder
  -> worker
  -> independent deterministic review
  -> retry with review feedback, or final submission_bundle_v1
```

The difference is the worker execution layer. `agent_02_scifi_oh` calls
`oh --print ...`. This backend runs a small native Python tool loop inspired by
SciFi's `F/driver.py`: a model receives the SAM prompt, calls deterministic
tools for shell and file operations, and must call `done` with the final bundle.

This is still intentionally smaller than the upstream SciFi runtime. It does
not vendor Apptainer, Pam, Cam, global memory, evolution, model ranking, or the
full recursive subagent scheduler. The Green/Purple A2A contract remains the
runtime boundary.

Registered backend names:

- `agent_3a_scifi_native`
- `agent_03a_scifi_native`
- `scifi_native`
- `native_scifi`

Useful environment variables:

- `SCIFI_NATIVE_MODEL`: model for the native worker, default `HEPEX_AGENT_MODEL`
  or `HEPEX_OPENAI_MODEL` or `gpt-5`.
- `SCIFI_NATIVE_BASE_URL`: optional OpenAI-compatible API base URL.
- `SCIFI_NATIVE_MAX_ITERATIONS`: max tool-loop iterations per worker attempt,
  default `30`.
- `SCIFI_NATIVE_MAX_BASH_SECONDS`: max seconds for one bash tool call, default
  `300`.
- `SCIFI_NATIVE_MAX_TOOL_CHARS`: max characters retained from one tool result,
  default `12000`.
- `SCIFI_NATIVE_MAX_RETRIES`: max independent-review attempts, default `2`.

Debug log:

```text
<solver_work>/debug_scifi_native_output.log
```
