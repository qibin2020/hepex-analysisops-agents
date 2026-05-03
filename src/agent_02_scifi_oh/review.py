from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any


JSON_TYPES = {"json", "table_json", "image_ref"}
TEXT_TYPES = {"markdown", "text"}


@dataclass
class ReviewResult:
    passed: bool
    feedback: dict[str, Any]
    bundle: dict[str, Any] | None = None

    @property
    def summary(self) -> str:
        if self.passed:
            return "PASS"
        counts = {
            key: len(value)
            for key, value in self.feedback.items()
            if isinstance(value, list) and value
        }
        return "FAIL " + ", ".join(f"{key}={value}" for key, value in counts.items())


def _artifact_entries(contract: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for section in ("required_outputs", "optional_outputs"):
        values = contract.get(section, [])
        if isinstance(values, list):
            entries.extend(item for item in values if isinstance(item, dict))
    return entries


def _required_names(contract: dict[str, Any]) -> list[str]:
    outputs = contract.get("required_outputs", [])
    if not isinstance(outputs, list):
        return []
    return [
        item["canonical_filename"]
        for item in outputs
        if isinstance(item, dict) and isinstance(item.get("canonical_filename"), str)
    ]


def _declared_type_map(contract: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in _artifact_entries(contract):
        name = item.get("canonical_filename")
        if isinstance(name, str):
            mapping[name] = str(item.get("type", "json"))
    return mapping


def _get_path(payload: Any, path: str) -> Any:
    if isinstance(payload, dict) and path in payload:
        return payload[path]
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _is_type(value: Any, type_name: str) -> bool:
    type_name = type_name.lower()
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return not isinstance(value, bool) and isinstance(value, int)
    if type_name in {"float", "number"}:
        return _is_number(value)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "array_object":
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)
    if type_name == "array_string":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if type_name == "array_int":
        return isinstance(value, list) and all(not isinstance(item, bool) and isinstance(item, int) for item in value)
    if type_name == "array_float" or type_name == "array_number":
        return isinstance(value, list) and all(_is_number(item) for item in value)
    if type_name == "array_float_len_2" or type_name == "array_number_len_2":
        return isinstance(value, list) and len(value) == 2 and all(_is_number(item) for item in value)
    return True


def _check_required_schema_fields(
    artifact_name: str,
    artifact: Any,
    schema: dict[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(artifact, dict):
        return
    required = schema.get("required_fields", [])
    if isinstance(required, list):
        for field in required:
            if isinstance(field, str) and field not in artifact:
                errors.append(f"{artifact_name} missing required field {field}")

    nested = schema.get("nested_required_fields", {})
    if not isinstance(nested, dict):
        return
    for field_path, nested_schema in nested.items():
        if not isinstance(field_path, str) or not isinstance(nested_schema, dict):
            continue
        target = _get_path(artifact, field_path)
        nested_required = nested_schema.get("required_fields", [])
        if target is None:
            errors.append(f"{artifact_name}.{field_path} missing required object")
            continue
        if not isinstance(nested_required, list):
            continue
        if isinstance(target, list):
            for idx, value in enumerate(target):
                if not isinstance(value, dict):
                    errors.append(f"{artifact_name}.{field_path}[{idx}] must be an object")
                    continue
                for nested_field in nested_required:
                    if isinstance(nested_field, str) and nested_field not in value:
                        errors.append(
                            f"{artifact_name}.{field_path}[{idx}] missing required field {nested_field}"
                        )
        elif isinstance(target, dict):
            for nested_field in nested_required:
                if isinstance(nested_field, str) and nested_field not in target:
                    errors.append(f"{artifact_name}.{field_path} missing required field {nested_field}")
        else:
            errors.append(f"{artifact_name}.{field_path} must be an object or list of objects")


def _check_field_types(
    artifact_name: str,
    artifact: Any,
    schema: dict[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(artifact, dict):
        return
    field_types = schema.get("field_types", {})
    if isinstance(field_types, dict):
        for field_path, type_name in field_types.items():
            if not isinstance(field_path, str) or not isinstance(type_name, str):
                continue
            value = _get_path(artifact, field_path)
            if value is not None and not _is_type(value, type_name):
                errors.append(f"{artifact_name}.{field_path} must match field type {type_name}")

    nested = schema.get("nested_required_fields", {})
    if not isinstance(nested, dict):
        return
    for field_path, nested_schema in nested.items():
        if not isinstance(field_path, str) or not isinstance(nested_schema, dict):
            continue
        target = _get_path(artifact, field_path)
        nested_types = nested_schema.get("field_types", {})
        if not isinstance(nested_types, dict):
            continue
        targets = target if isinstance(target, list) else [target]
        for idx, value in enumerate(targets):
            if not isinstance(value, dict):
                continue
            label = f"{artifact_name}.{field_path}[{idx}]" if isinstance(target, list) else f"{artifact_name}.{field_path}"
            for nested_field, type_name in nested_types.items():
                if not isinstance(nested_field, str) or not isinstance(type_name, str):
                    continue
                nested_value = _get_path(value, nested_field)
                if nested_value is not None and not _is_type(nested_value, type_name):
                    errors.append(f"{label}.{nested_field} must match field type {type_name}")


def _check_array_alignment(
    artifact_name: str,
    artifact: Any,
    schema: dict[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(artifact, dict):
        return
    constraints = schema.get("constraints", {})
    if not isinstance(constraints, dict):
        return
    for rule in constraints.get("array_alignment", []) or []:
        if not isinstance(rule, dict):
            continue
        fields = rule.get("fields", [])
        relation = rule.get("relation")
        if not isinstance(fields, list) or len(fields) != 2:
            continue
        left = _get_path(artifact, str(fields[0]))
        right = _get_path(artifact, str(fields[1]))
        if not isinstance(left, list) or not isinstance(right, list):
            continue
        if relation == "edges_equals_counts_plus_one" and len(left) != len(right) + 1:
            errors.append(
                f"{artifact_name} array alignment failed: {fields[0]} must be one longer than {fields[1]}"
            )
        if relation == "same_length" and len(left) != len(right):
            errors.append(
                f"{artifact_name} array alignment failed: {fields[0]} and {fields[1]} must have same length"
            )


def _check_field_constraints(
    artifact_name: str,
    artifact: Any,
    schema: dict[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(artifact, dict):
        return
    constraints = schema.get("constraints", {})
    if not isinstance(constraints, dict):
        return
    for field, rule in constraints.items():
        if field == "array_alignment" or not isinstance(rule, dict):
            continue
        value = _get_path(artifact, field)
        if "min_length" in rule:
            try:
                min_length = int(rule["min_length"])
            except Exception:
                min_length = 0
            if not hasattr(value, "__len__") or len(value) < min_length:
                errors.append(f"{artifact_name}.{field} must have length at least {min_length}")
        contains_all = rule.get("contains_all")
        if isinstance(contains_all, list):
            actual = {str(item) for item in value} if isinstance(value, list) else set()
            missing = sorted(str(item) for item in contains_all if str(item) not in actual)
            if missing:
                errors.append(f"{artifact_name}.{field} missing required value(s): {missing}")


def _check_interpretation_constraints(
    artifact_name: str,
    payload: Any,
    schema: dict[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(payload, str):
        return
    constraints = schema.get("constraints", {}) if isinstance(schema, dict) else {}
    if not isinstance(constraints, dict):
        return
    text = payload.strip()
    if constraints.get("non_empty") and not text:
        errors.append(f"{artifact_name} must be non-empty")
    if "min_characters" in constraints:
        try:
            min_chars = int(constraints["min_characters"])
        except Exception:
            min_chars = 1
        if len(text) < min_chars:
            errors.append(f"{artifact_name} must be at least {min_chars} characters")


def _check_contract_schemas(
    artifacts: dict[str, Any],
    contract: dict[str, Any],
    errors: list[str],
) -> None:
    schemas = contract.get("schemas", {})
    if not isinstance(schemas, dict):
        return
    for name, schema in schemas.items():
        if name not in artifacts or not isinstance(schema, dict):
            continue
        payload = artifacts[name]
        _check_required_schema_fields(name, payload, schema, errors)
        _check_field_types(name, payload, schema, errors)
        _check_array_alignment(name, payload, schema, errors)
        _check_field_constraints(name, payload, schema, errors)
        _check_interpretation_constraints(name, payload, schema, errors)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _bullet_values_after(prompt: str, header_pattern: str) -> list[str]:
    values: list[str] = []
    lines = prompt.splitlines()
    header_re = re.compile(header_pattern, re.IGNORECASE)
    in_section = False
    collected = False
    for line in lines:
        if not in_section:
            if header_re.search(line):
                in_section = True
            continue
        stripped = line.strip()
        if collected and (not stripped or stripped.startswith("#") or stripped.lower().startswith("for `")):
            break
        if not stripped.startswith("-"):
            continue
        collected = True
        ticks = re.findall(r"`([^`]+)`", stripped)
        if ticks:
            values.extend(ticks)
            continue
        value = stripped.lstrip("-").strip()
        if value:
            values.append(value)
    return values


def extract_prompt_requirements(prompt: str) -> dict[str, list[str]]:
    """Extract only explicit, machine-checkable requirements from a public prompt."""
    stage_ids = re.findall(r'"stage_id"\s*:\s*"([^"]+)"', prompt)
    cut_ids = re.findall(r'"cut_id"\s*:\s*"([^"]+)"', prompt)
    stage_ids.extend(
        _bullet_values_after(prompt, r"workflow_stages.*exact stage ids")
    )
    cut_ids.extend(
        _bullet_values_after(prompt, r"cuts_applied.*exact.*cut_id")
    )
    sample_names = _bullet_values_after(prompt, r"sample names exactly")
    return {
        "stage_ids": _dedupe(stage_ids),
        "cut_ids": _dedupe(cut_ids),
        "sample_names": _dedupe(sample_names),
    }


def _values_from_object_list(values: Any, *keys: str) -> set[str]:
    found: set[str] = set()
    if not isinstance(values, list):
        return found
    for item in values:
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = item.get(key)
            if isinstance(value, str):
                found.add(value)
    return found


def _check_trace_output_files(
    artifacts: dict[str, Any],
    required: set[str],
    errors: list[str],
) -> None:
    trace = artifacts.get("submission_trace.json")
    if not isinstance(trace, dict):
        return
    generated = trace.get("output_files_generated")
    if generated is None:
        return
    if not isinstance(generated, list):
        errors.append("submission_trace.json.output_files_generated must be a list")
        return
    generated_names = {str(item) for item in generated}
    missing_generated = sorted(required - generated_names)
    if missing_generated:
        errors.append(
            f"submission_trace.json.output_files_generated missing required artifact(s): {missing_generated}"
        )


def _check_prompt_requirements(
    artifacts: dict[str, Any],
    prompt: str,
    errors: list[str],
) -> None:
    trace = artifacts.get("submission_trace.json")
    if not isinstance(trace, dict):
        return
    requirements = extract_prompt_requirements(prompt)
    if requirements["stage_ids"]:
        actual = _values_from_object_list(trace.get("workflow_stages"), "stage_id", "stage_label")
        missing = sorted(set(requirements["stage_ids"]) - actual)
        if missing:
            errors.append(f"submission_trace.json.workflow_stages missing prompt-declared stage id(s): {missing}")
    if requirements["cut_ids"]:
        actual = _values_from_object_list(trace.get("cuts_applied"), "cut_id")
        missing = sorted(set(requirements["cut_ids"]) - actual)
        if missing:
            errors.append(f"submission_trace.json.cuts_applied missing prompt-declared cut id(s): {missing}")
    if requirements["sample_names"]:
        actual = _values_from_object_list(trace.get("input_samples_used"), "sample_name")
        missing = sorted(set(requirements["sample_names"]) - actual)
        if missing:
            errors.append(f"submission_trace.json.input_samples_used missing prompt-declared sample name(s): {missing}")


def _walk_values(payload: Any):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield key, value
            yield from _walk_values(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_values(value)


def _check_scientific_consistency(artifacts: dict[str, Any], warnings: list[str]) -> None:
    interpretation = artifacts.get("interpretation.md")
    if not isinstance(interpretation, str):
        return
    lower_text = interpretation.lower()
    overclaim_terms = (
        "discovery",
        "clear excess",
        "clear higgs",
        "observed higgs",
        "definitive",
        "significant excess",
    )
    if not any(term in lower_text for term in overclaim_terms):
        return

    for key, value in _walk_values(artifacts):
        key_lower = str(key).lower()
        if key_lower in {"excess_observed", "fit_success", "success"} and value is False:
            warnings.append(
                f"interpretation may overclaim while {key}=false in the returned artifacts"
            )
            return
        if "significance" in key_lower and _is_number(value) and float(value) < 1.0:
            warnings.append(
                f"interpretation may overclaim while {key}={value} is a low significance proxy"
            )
            return


def _feedback(
    missing: list[str],
    schema_errors: list[str],
    trace_errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    retry_parts = []
    if missing:
        retry_parts.append("add every missing required artifact")
    if schema_errors:
        retry_parts.append("fix JSON/markdown types, required fields, field types, constraints, and array alignment")
    if trace_errors:
        retry_parts.append("fix submission_trace consistency and prompt-declared exact evidence")
    retry_instruction = (
        "; ".join(retry_parts)
        if retry_parts
        else "independent review passed; no retry required"
    )
    return {
        "missing_required_artifacts": missing,
        "schema_or_type_errors": schema_errors,
        "trace_consistency_errors": trace_errors,
        "scientific_consistency_warnings": warnings,
        "retry_instruction": retry_instruction,
    }


def review_submission_bundle(
    req_json: dict[str, Any] | None,
    final_text: str,
    input_manifest: dict[str, Any] | None = None,
    work_dir: Any | None = None,
) -> ReviewResult:
    del input_manifest, work_dir
    missing: list[str] = []
    schema_errors: list[str] = []
    trace_errors: list[str] = []
    warnings: list[str] = []

    try:
        bundle = json.loads(final_text.strip())
    except Exception as exc:
        schema_errors.append(f"solver response is not parseable JSON: {exc}")
        return ReviewResult(False, _feedback(missing, schema_errors, trace_errors, warnings))

    if not isinstance(bundle, dict):
        schema_errors.append("submission bundle must be a JSON object")
        return ReviewResult(False, _feedback(missing, schema_errors, trace_errors, warnings))

    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        schema_errors.append("submission bundle requires an artifacts object")
        return ReviewResult(False, _feedback(missing, schema_errors, trace_errors, warnings), bundle=bundle)

    contract = req_json.get("submission_contract", {}) if isinstance(req_json, dict) else {}
    if not isinstance(contract, dict):
        contract = {}
    required = set(_required_names(contract))
    declared_types = _declared_type_map(contract)
    declared = set(declared_types)

    missing.extend(sorted(required - set(artifacts)))
    unknown = sorted(set(artifacts) - declared)
    if unknown:
        schema_errors.append(f"bundle contains undeclared artifact(s): {unknown}")

    for name, payload in artifacts.items():
        art_type = declared_types.get(name, "json")
        if art_type in TEXT_TYPES:
            if not isinstance(payload, str):
                schema_errors.append(f"{name} must be a string for {art_type} output")
        elif art_type in JSON_TYPES:
            if not isinstance(payload, dict):
                schema_errors.append(f"{name} must be a JSON object for {art_type} output")

    _check_contract_schemas(artifacts, contract, schema_errors)
    _check_trace_output_files(artifacts, required, trace_errors)

    prompt = str(req_json.get("prompt") or "") if isinstance(req_json, dict) else ""
    _check_prompt_requirements(artifacts, prompt, trace_errors)
    _check_scientific_consistency(artifacts, warnings)

    passed = not missing and not schema_errors and not trace_errors
    return ReviewResult(
        passed=passed,
        feedback=_feedback(missing, schema_errors, trace_errors, warnings),
        bundle=bundle,
    )
