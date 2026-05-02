# HEPEx AnalysisOps Agents

This repository contains the reference AgentBeats Purple Agent for HEPEx
AnalysisOps. It receives public benchmark task requests from the Green Agent,
runs a solver backend, and returns a `submission_bundle_v1` JSON response.

The current default solver backend is:

```text
agent_1_oh
```

`agent_1_oh` runs OpenHarness inside the Purple Agent container. The code is
structured so additional solver backends can be registered without rewriting
the A2A transport layer.

## Repository Role

This repo owns the participant side of the benchmark:

1. Receive an A2A message from the Green Agent.
2. Parse the task request payload.
3. Load any runtime input manifest supplied by the Green Agent.
4. Build the final solver prompt with public contract and runtime context.
5. Select a solver backend.
6. Run the backend.
7. Return one text artifact containing the final `submission_bundle_v1` JSON.

The Purple Agent does not score submissions. Scoring belongs to the Green Agent.

## Architecture

```text
src/server.py
  A2A HTTP server

src/executor.py
  A2A executor adapter

src/agent.py
  Transport-facing Purple Agent:
  - parse message
  - prepare bundle prompt
  - select solver backend
  - emit A2A statuses and final artifact

src/solver_backends.py
  Solver backend registry:
  - agent_1_oh / openharness / oh
  - OpenHarness subprocess execution
  - retry handling
  - debug log writing
  - backend progress status

src/agent_01_oh/
  Backend-owned OpenHarness assets:
  - AGENTS.md system prompt
  - sm-ana-aod OpenHarness skills submodule
  Docker copies these assets into the locations expected by OpenHarness.

src/bundle_runtime.py
  Request parsing, input manifest loading, deterministic mock bundle helpers
```

## Public Request Contract

The Green Agent sends a JSON task payload with:

```json
{
  "role": "task_request",
  "task_id": "t002_hyy_v5_l1",
  "task_type": "hyy_l1",
  "mode": "call_white",
  "solver_backend": "agent_1_oh",
  "prompt": "...",
  "submission_contract": {},
  "data": {
    "input_strategy": "shared_manifest",
    "shared_input_dir": "/shared/hepex/input/2025e-13tev-beta/data/GamGam",
    "input_manifest_path": "/shared/hepex/input/2025e-13tev-beta/data/GamGam/input_manifest.json",
    "work_dir": "/home/agent/output/runs/<run_id>/<task_id>/solver_work",
    "output_dir": "/home/agent/output/runs/<run_id>/<task_id>/solver_work"
  },
  "constraints": {
    "response_format": "submission_bundle_v1",
    "solver_backend": "agent_1_oh",
    "allow_purple_network": false
  }
}
```

The Purple Agent must return:

```json
{
  "status": "ok",
  "artifacts": {
    "canonical_filename.json": {},
    "canonical_filename.md": "markdown text"
  }
}
```

Do not wrap the final JSON in Markdown fences. Artifact keys must match the
Green-supplied `submission_contract.required_outputs[*].canonical_filename`.

## Solver Backends

Backends are selected from the request by checking, in order:

1. `payload.solver_backend`
2. `payload.solver_agent`
3. `payload.constraints.solver_backend`
4. `payload.constraints.solver_agent`
5. default `agent_1_oh`

Registered names today:

- `agent_1_oh`
- `openharness`
- `oh`

The `agent_1_oh` backend's prompt and skill assets live under
`src/agent_01_oh/`. Keep backend-specific assets there so future backends can
ship their own prompts, skills, configs, or tool adapters without changing the
transport layer.

The OpenHarness skill pack is a Git submodule:

```bash
git submodule update --init --recursive
```

Current submodule path:

```text
src/agent_01_oh/skills/sm-ana-aod
```

To add a new backend:

1. Add a class implementing the `SolverBackend` protocol in
   `src/solver_backends.py`.
2. Implement `run(prompt, req_json, system_prompt, status, input_manifest,
   work_dir) -> str`.
3. Register it in `_BACKENDS`, for example:

   ```python
   _BACKENDS["agent_2_xxx"] = MySolverBackend()
   ```

4. Add tests in `tests/test_submission_bundle_agent.py`.
5. Run `uv run pytest -q`.

Backend code should return a final JSON string. It should not call the Green
scorer and should not write leaderboard result files.

## Development Setup

Prerequisites:

- `uv`
- Docker, for container testing
- `OPENAI_API_KEY` for OpenHarness/OpenAI-backed runs

Install dependencies:

```bash
uv sync
```

Run local tests that do not require a live server:

```bash
uv run pytest tests/test_submission_bundle_agent.py \
  tests/test_agent.py::test_submission_bundle_request_returns_minimal_valid_bundle \
  tests/test_agent.py::test_submission_bundle_request_returns_error_for_missing_manifest \
  tests/test_agent.py::test_submission_bundle_request_returns_error_for_invalid_manifest_json \
  -q
```

Run the full local test suite when a Purple server is already running on
`http://localhost:9009`:

```bash
uv run pytest -q --agent-url http://localhost:9009
```

Run the agent locally:

```bash
export OPENAI_API_KEY="..."
uv run src/server.py --host 0.0.0.0 --port 9009
```

Build the Docker image:

```bash
docker build -t hepex-purple-agent:local .
```

Run the container:

```bash
docker run --rm -p 9009:9009 \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -v "$PWD/../hepex-analysisops-leaderboard/output:/home/agent/output" \
  hepex-purple-agent:local \
  --host 0.0.0.0 --port 9009 --card-url http://localhost:9009
```

## Runtime Observability

The Purple Agent emits A2A working statuses for:

- parsed task id, task type, mode, and solver backend
- submission contract output list
- input manifest file count and size
- solver work directory
- OpenHarness attempt start/end
- stdout/stderr character counts
- retry decisions
- final bundle status and artifact list

OpenHarness debug logs are written under the task work directory:

```text
<solver_work>/debug_oh_output.log
```

The backend may also create analysis scripts and logs under the same
`solver_work` directory. Those files are useful for local debugging but are not
the public submission interface.

## Local Full-Data E2E

The preferred way to test this Purple Agent against the Green Agent is from the
leaderboard repository:

```bash
cd ../hepex-analysisops-leaderboard
python3 scripts/local_shared_submit.py \
  --host-input-dir ../hepex-analysisops-benchmark/shared_input/2025e-13tev-beta/data/GamGam \
  --max-files 16 \
  --mode call_white \
  --solver-backend agent_1_oh \
  --build-local-images \
  --no-commit
```

That wrapper builds this repo's Docker image, builds the Green Agent image,
mounts local ROOT files into both containers, runs Compose, and archives the
result into `output/runs/<run_id>/results.json`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | yes for real OpenHarness runs | OpenAI API key used by the backend |
| `HEPEX_AGENT_MODEL` | no | Optional model override used by solver tooling when supported |
| `HEPEX_OPENAI_MODEL` | no | Fallback OpenAI model setting |
| `HEPEX_SOLVER_WORK_DIR` | set by backend | Per-task solver working directory |
| `HEPEX_OUTPUT_DIR` | set by backend | Alias for the solver output directory |

## Common Failure Modes

- `Unknown solver_backend`: Green requested a backend name that is not
  registered in `src/solver_backends.py`.
- Empty OpenHarness stdout: backend returns a structured error bundle and may
  retry if stderr looks transient.
- Missing input manifest: mock bundle requests require
  `data.input_manifest_path`; real shared-manifest requests should receive it
  from Green.
- Output contract failure: inspect the Green run directory, especially
  `purple_request.json`, `purple_response_raw.txt`, and `judge_output.json`.

## License

See `LICENSE`.
