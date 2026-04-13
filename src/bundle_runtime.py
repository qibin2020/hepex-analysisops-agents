from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


SUPPORTED_BUNDLE_OUTPUTS = {
    "diphoton_mass_spectrum.json",
    "diphoton_fit_summary.json",
    "data_minus_background.json",
    "interpretation.md",
    "submission_trace.json",
}


def error_response(message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "error", "error": message}
    if details:
        payload["details"] = details
    return payload


def parse_task_request(input_text: str, logger: logging.Logger) -> dict[str, Any] | None:
    try:
        payload = json.loads(input_text)
    except json.JSONDecodeError:
        logger.warning("Received non-JSON request")
        logger.debug(f"Raw input text:\n{input_text}")
        return None

    if not isinstance(payload, dict):
        logger.warning("Received JSON request that is not an object")
        return None

    logger.info("Received request")
    logger.debug(f"Request payload:\n{json.dumps(payload, indent=2)}")
    return payload


def extract_required_output_names(req_json: dict[str, Any]) -> list[str]:
    contract = req_json.get("submission_contract", {})
    required_outputs = contract.get("required_outputs", [])
    names: list[str] = []
    for entry in required_outputs:
        if isinstance(entry, dict):
            name = entry.get("canonical_filename")
            if isinstance(name, str):
                names.append(name)
    return names


def is_submission_bundle_request(req_json: dict[str, Any]) -> bool:
    return (
        req_json.get("role") == "task_request"
        and req_json.get("constraints", {}).get("response_format") == "submission_bundle_v1"
    )


def request_mode(req_json: dict[str, Any]) -> str:
    mode = req_json.get("mode")
    return mode if isinstance(mode, str) and mode else "call_white"


def should_mock_submission_bundle(req_json: dict[str, Any]) -> bool:
    return is_submission_bundle_request(req_json) and request_mode(req_json) == "mock"


def load_input_manifest(req_json: dict[str, Any]) -> dict[str, Any] | None:
    data_info = req_json.get("data", {})
    input_manifest_path = data_info.get("input_manifest_path")
    if not isinstance(input_manifest_path, str) or not input_manifest_path.strip():
        return None

    manifest_path = Path(input_manifest_path)
    if not manifest_path.exists() or not manifest_path.is_file():
        raise FileNotFoundError(f"Input manifest does not exist: {manifest_path}")

    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Input manifest is not valid JSON: {manifest_path}") from exc

    if not isinstance(raw_manifest, dict):
        raise ValueError(f"Input manifest must be a JSON object: {manifest_path}")

    return raw_manifest


def build_minimal_submission_bundle(
    req_json: dict[str, Any],
    input_manifest: dict[str, Any],
) -> dict[str, Any]:
    required_names = extract_required_output_names(req_json)
    required_name_set = set(required_names)
    unsupported = sorted(required_name_set - SUPPORTED_BUNDLE_OUTPUTS)
    if unsupported:
        return error_response(
            "Unsupported submission bundle contract for minimal purple agent.",
            details={"unsupported_outputs": unsupported},
        )

    manifest_path = req_json.get("data", {}).get("input_manifest_path")
    shared_input_dir = input_manifest.get("shared_input_dir") or req_json.get("data", {}).get("shared_input_dir")
    manifest_files = input_manifest.get("files", [])
    if not isinstance(manifest_files, list):
        manifest_files = []
    file_names = [
        entry.get("logical_name") or Path(str(entry.get("path", ""))).name
        for entry in manifest_files
        if isinstance(entry, dict)
    ]
    file_names = [name for name in file_names if isinstance(name, str) and name]
    file_summary = ", ".join(file_names[:3]) if file_names else "no ROOT files listed"

    interpretation = (
        "Minimal placeholder submission generated after confirming shared-input visibility "
        f"through manifest {manifest_path}. Manifest reports {len(manifest_files)} file(s) "
        f"under {shared_input_dir}; sample entries: {file_summary}. A placeholder Higgs-like "
        "excess is reported near 125.1 GeV for protocol validation only."
    )

    submission_trace = {
        "workflow_stages": [
            {"stage_id": "task_request_parsed", "order_index": 1, "status": "ok"},
            {"stage_id": "input_manifest_loaded", "order_index": 2, "status": "ok"},
            {"stage_id": "deterministic_bundle_emitted", "order_index": 3, "status": "ok"},
        ],
        "cuts_applied": [
            {"cut_id": "shared_input_manifest_available", "value": True, "applied": True},
        ],
        "observable_constructed": {
            "name": "m_yy",
            "inputs": ["shared_input_manifest"],
        },
        "fit_model_family_used": {
            "signal": "gaussian",
            "background": "polynomial",
            "background_order": 4,
            "fit_range_GeV": [100.0, 160.0],
            "weighting_scheme": "deterministic_placeholder",
        },
        "output_files_generated": required_names,
        "reported_result": {
            "signal_peak_position": 125.1,
        },
        "baseline_assumptions_used": [
            "This is a minimal deterministic placeholder bundle for protocol validation.",
            f"input_manifest_path={manifest_path}",
            f"shared_input_dir={shared_input_dir}",
            f"n_manifest_files={len(manifest_files)}",
        ],
        "object_definition": {
            "type": "diphoton_candidate",
            "multiplicity": 2,
            "ordering_principle": "placeholder_ordering",
        },
        "derived_observables": [
            {"name": "m_yy", "depends_on": ["shared_input_manifest"]},
        ],
        "primary_observable": {
            "name": "m_yy",
            "inputs": ["shared_input_manifest"],
            "construction": "deterministic_placeholder_from_manifest_metadata",
        },
        "histogram_definition": {
            "observable": "m_yy",
            "range": [100.0, 160.0],
            "bin_width": 1.0,
            "uncertainty_model": "placeholder_statistical_uncertainty",
        },
    }

    artifact_payloads: dict[str, Any] = {
        "diphoton_mass_spectrum.json": {
            "bin_edges": [100.0, 110.0, 120.0, 130.0],
            "bin_counts": [3, 8, 5],
            "bin_uncertainties": [1.732, 2.828, 2.236],
        },
        "diphoton_fit_summary.json": {
            "signal_model_family": "gaussian",
            "background_model_family": "polynomial",
            "fit_range": [100.0, 160.0],
            "signal_peak_position": 125.1,
        },
        "data_minus_background.json": {
            "bin_centers": [115.0, 125.0, 135.0],
            "residual_counts": [0.1, 1.4, -0.2],
            "residual_uncertainties": [0.4, 0.6, 0.5],
        },
        "interpretation.md": interpretation,
        "submission_trace.json": submission_trace,
    }

    artifacts = {name: artifact_payloads[name] for name in required_names}
    return {"status": "ok", "artifacts": artifacts}
