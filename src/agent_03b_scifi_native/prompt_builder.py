from __future__ import annotations

import json
from typing import Any


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


def build_general_sam_prompt(
    base_prompt: str,
    req_json: dict[str, Any] | None,
    input_manifest: dict[str, Any] | None,
    *,
    attempt: int,
    max_attempts: int,
    review_feedback: dict[str, Any] | None = None,
) -> str:
    """Render a task-agnostic SAM prompt from the Green task request."""
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
            "The previous attempt failed deterministic review. Fix every concrete "
            "item below before returning the next bundle.\n\n"
            "```json\n"
            f"{_json_dump(review_feedback)}\n"
            "```\n"
        )

    return "\n".join(
        [
            "---",
            "Rank: 3b",
            "Skills: scientific_analysis, bundle_contract_review, runtime_tool_execution",
            "---",
            "",
            f"# AgentBeats HEPEx Submission Bundle: {_task_label(req_json)}",
            "",
            "## Context",
            f"Native SciFi general loop attempt {attempt} of {max_attempts}.",
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
            feedback_block,
            "",
            "## Todo",
            "1. Read the task prompt, contract, manifest, and runtime constraints.",
            "2. Inspect the provided input files and identify the required data fields.",
            "3. Write and run analysis code under the solver work directory.",
            "4. Build every required artifact from computed results.",
            "5. Return exactly one `submission_bundle_v1` JSON object through `done`.",
            "",
            "## Expect",
            "- The final response is parseable JSON, not markdown.",
            "- Top-level JSON has `status` and `artifacts`.",
            "- `artifacts` contains every required canonical filename and no undeclared names.",
            "- JSON artifacts are JSON objects; markdown artifacts are strings.",
            "- Required schema fields and trace fields from the contract are present.",
            "- Numeric results, generated files, and provenance claims are internally consistent.",
            "- Any task-specific physics or data-analysis claims are supported by the computation.",
        ]
    ).strip()

