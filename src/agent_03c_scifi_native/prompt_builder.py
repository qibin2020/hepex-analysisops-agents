from __future__ import annotations

import json
from typing import Any


COMMON_ENV_GUIDANCE = """\
## SciFi dev_max_bench_v2 Environment Skill

Use shared environments only when the built-in Purple scientific stack is not
enough for the task.

1. Call `list_shared_envs` to discover reusable environments.
2. Call `read_env_manifest` on a plausible candidate.
3. Call `activate_env` once before running commands that need it.
4. If no suitable shared env exists, prefer the built-in Python stack first. If
   a new env is truly needed, create it under the solver work directory unless a
   writable shared env root is available.
5. Never modify an existing shared env. Reuse it as-is or create a new one.
"""


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _required_output_names(req_json: dict[str, Any] | None) -> list[str]:
    if not isinstance(req_json, dict):
        return []
    contract = req_json.get("submission_contract", {})
    outputs = contract.get("required_outputs", []) if isinstance(contract, dict) else []
    names: list[str] = []
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict) and isinstance(item.get("canonical_filename"), str):
                names.append(item["canonical_filename"])
    return names


def _task_label(req_json: dict[str, Any] | None) -> str:
    if not isinstance(req_json, dict):
        return "generic"
    task_type = req_json.get("task_type")
    task_id = req_json.get("task_id")
    contract = req_json.get("submission_contract", {})
    level = contract.get("level") if isinstance(contract, dict) else None
    parts = [str(part) for part in (task_type, level, task_id) if part]
    return " / ".join(parts) if parts else "generic"


def build_v2_sam_prompt(
    base_prompt: str,
    req_json: dict[str, Any] | None,
    input_manifest: dict[str, Any] | None,
    *,
    attempt: int,
    max_attempts: int,
    review_feedback: dict[str, Any] | None = None,
) -> str:
    """Render a dev_max_bench_v2-style task-agnostic SAM prompt."""
    data_info = req_json.get("data", {}) if isinstance(req_json, dict) else {}
    contract = req_json.get("submission_contract", {}) if isinstance(req_json, dict) else {}
    constraints = req_json.get("constraints", {}) if isinstance(req_json, dict) else {}
    required_outputs = _required_output_names(req_json)

    manifest_block = ""
    if input_manifest is not None:
        manifest_block = (
            "\n### Resolved Input Manifest\n"
            "```json\n"
            f"{_json_dump(input_manifest)}\n"
            "```\n"
        )

    feedback_block = ""
    if review_feedback:
        feedback_block = (
            "\n## Independent Review Feedback From Previous Attempt\n"
            "The previous attempt failed review. Treat this as authoritative "
            "runtime evidence and fix every concrete item before returning.\n\n"
            "```json\n"
            f"{_json_dump(review_feedback)}\n"
            "```\n"
        )

    return "\n".join(
        [
            "---",
            "Rank: 3c",
            "SourceBranch: scifi/dev_max_bench_v2",
            "Skills: scientific_analysis, bundle_contract_review, common_env, runtime_tool_execution",
            "---",
            "",
            f"# AgentBeats HEPEx SAM: {_task_label(req_json)}",
            "",
            "## Context",
            f"SciFi native v2 loop attempt {attempt} of {max_attempts}.",
            "This backend adapts the SciFi dev_max_bench_v2 SAM driver style to "
            "AgentBeats: Prescan prompt, native tool execution, independent review, retry.",
            "",
            "### Green/Purple Prepared Prompt",
            base_prompt.strip(),
            "",
            "### Request Metadata",
            "```json",
            _json_dump(
                {
                    "task_id": req_json.get("task_id") if isinstance(req_json, dict) else None,
                    "task_type": req_json.get("task_type") if isinstance(req_json, dict) else None,
                    "required_outputs": required_outputs,
                }
            ),
            "```",
            "",
            "### Submission Contract",
            "```json",
            _json_dump(contract),
            "```",
            "",
            "### Runtime Data",
            "```json",
            _json_dump(data_info),
            "```",
            manifest_block,
            "",
            "### Runtime Constraints",
            "```json",
            _json_dump(constraints),
            "```",
            "",
            COMMON_ENV_GUIDANCE,
            feedback_block,
            "",
            "## Todo",
            "1. Understand the task prompt, contract, input manifest, and constraints.",
            "2. Inspect the available inputs and choose a minimal auditable analysis plan.",
            "3. Use tools to compute the required outputs from the provided data.",
            "4. Verify required artifact names, types, schema fields, and trace consistency.",
            "5. Return exactly one `submission_bundle_v1` JSON object through `done`.",
            "",
            "## Expect",
            "- The final response is parseable JSON, not markdown.",
            "- Top-level JSON has `status` and `artifacts`.",
            "- `artifacts` contains every required canonical filename and no undeclared names.",
            "- JSON artifacts are JSON objects; markdown artifacts are strings.",
            "- Numeric results and provenance claims are backed by tool execution.",
            "- Any scripts, logs, and intermediate files live under the solver work directory.",
            "- If a shared environment is activated, later bash calls use that same env.",
        ]
    ).strip()

