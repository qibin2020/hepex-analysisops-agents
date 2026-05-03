from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent / "skills"


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def detect_task_level(req_json: dict[str, Any] | None) -> str:
    if not isinstance(req_json, dict):
        return "generic"
    contract = req_json.get("submission_contract", {})
    level = contract.get("level") if isinstance(contract, dict) else None
    if isinstance(level, str) and level.lower() in {"l1", "l2", "l3"}:
        return level.lower()
    task_type = str(req_json.get("task_type") or "").lower()
    task_id = str(req_json.get("task_id") or "").lower()
    combined = f" {task_type} {task_id} "
    for value in ("l1", "l2", "l3"):
        if f"_{value}" in combined or f"-{value}" in combined or f" {value} " in combined:
            return value
    return "generic"


def _load_skill(name: str) -> str:
    path = SKILL_DIR / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


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


def _artifact_summary(contract: dict[str, Any], section: str) -> list[dict[str, Any]]:
    values = contract.get(section, [])
    if not isinstance(values, list):
        return []
    summary: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        name = item.get("canonical_filename")
        if isinstance(name, str):
            summary.append(
                {
                    "canonical_filename": name,
                    "type": item.get("type", "json"),
                    "machine_readable": item.get("machine_readable"),
                }
            )
    return summary


def build_contract_summary(req_json: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(req_json, dict):
        return {"required_outputs": [], "optional_outputs": [], "schemas": {}}
    contract = req_json.get("submission_contract", {})
    if not isinstance(contract, dict):
        return {"required_outputs": [], "optional_outputs": [], "schemas": {}}

    schemas = contract.get("schemas", {})
    schema_summary: dict[str, Any] = {}
    if isinstance(schemas, dict):
        for name, schema in schemas.items():
            if not isinstance(schema, dict):
                continue
            schema_summary[str(name)] = {
                "required_fields": schema.get("required_fields", []),
                "nested_required_fields": list((schema.get("nested_required_fields") or {}).keys())
                if isinstance(schema.get("nested_required_fields"), dict)
                else [],
                "constraints": schema.get("constraints", {}),
            }

    return {
        "version": contract.get("version"),
        "level": contract.get("level"),
        "required_outputs": _artifact_summary(contract, "required_outputs"),
        "optional_outputs": _artifact_summary(contract, "optional_outputs"),
        "schemas": schema_summary,
    }


def build_sam_prompt(
    base_prompt: str,
    req_json: dict[str, Any] | None,
    input_manifest: dict[str, Any] | None,
    *,
    attempt: int,
    max_attempts: int,
    review_feedback: dict[str, Any] | None = None,
) -> str:
    """Render a SciFi-style SAM prompt from the Green task request."""
    task_level = detect_task_level(req_json)
    required_outputs = _required_output_names(req_json)
    data_info = req_json.get("data", {}) if isinstance(req_json, dict) else {}
    contract = req_json.get("submission_contract", {}) if isinstance(req_json, dict) else {}
    constraints = req_json.get("constraints", {}) if isinstance(req_json, dict) else {}

    skills = [
        _load_skill("contract_driven_analysis.md"),
        _load_skill("scientific_trace.md"),
        _load_skill("evidence_consistency.md"),
        _load_skill("bundle_contract_review.md"),
    ]

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

    manifest_block = ""
    if input_manifest is not None:
        manifest_block = (
            "\n### Resolved Input Manifest\n"
            "```json\n"
            f"{_json_dump(input_manifest)}\n"
            "```\n"
        )

    return "\n".join(
        [
            "---",
            "Rank: 2",
            "Skills: contract_driven_analysis, scientific_trace, evidence_consistency, bundle_contract_review",
            "---",
            "",
            f"# AgentBeats HEPEx {task_level.upper()} Submission Bundle",
            "",
            "## Context",
            f"SciFi-OH loop attempt {attempt} of {max_attempts}.",
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
                    "detected_task_level": task_level,
                    "required_outputs": required_outputs,
                }
            ),
            "```",
            "",
            "### Extracted Contract Summary",
            "```json",
            _json_dump(build_contract_summary(req_json)),
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
            "### SciFi-OH Skills",
            "\n\n".join(skill for skill in skills if skill),
            feedback_block,
            "",
            "## Todo",
            "1. Use the runtime manifest and task instructions to run the requested analysis.",
            "2. Generate any scripts, logs, plots, and intermediate files under the solver work directory.",
            "3. Build every required artifact from actual computation over the provided input files.",
            "4. Return exactly one `submission_bundle_v1` JSON object on stdout.",
            "",
            "## Expect",
            "- The final stdout is parseable JSON, not markdown.",
            "- Top-level JSON has `status` and `artifacts`.",
            "- `artifacts` contains every required canonical filename and no undeclared names.",
            "- JSON artifacts are JSON objects; markdown artifacts are strings.",
            "- Required schema fields, nested fields, field types, and contract constraints are satisfied.",
            "- `submission_trace.json`, numeric artifacts, and `interpretation.md` tell the same story.",
        ]
    ).strip()
