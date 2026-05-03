from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_02_scifi_oh.loop import SciFiLoop
from agent_02_scifi_oh.prompt_builder import build_sam_prompt, detect_task_level
from agent_02_scifi_oh.review import extract_prompt_requirements, review_submission_bundle
from solver_backends import get_solver_backend


L1_STAGE_IDS = [
    "data_loading",
    "event_selection",
    "diphoton_mass_construction",
    "spectrum_histogramming",
    "uncertainty_assignment",
    "spectrum_fitting",
    "signal_interpretation",
]

L1_CUT_IDS = {
    "at_least_two_photons",
    "leading_photon_tight_id",
    "subleading_photon_tight_id",
    "leading_photon_pt",
    "subleading_photon_pt",
    "leading_photon_isolation",
    "subleading_photon_isolation",
    "leading_photon_eta_transition_veto",
    "subleading_photon_eta_transition_veto",
    "diphoton_mass_nonzero",
    "leading_photon_pt_over_m_yy",
    "subleading_photon_pt_over_m_yy",
}


def _l1_contract() -> dict:
    return {
        "version": 2,
        "level": "l1",
        "required_outputs": [
            {"canonical_filename": "diphoton_mass_spectrum.json", "type": "json"},
            {"canonical_filename": "diphoton_fit_summary.json", "type": "json"},
            {"canonical_filename": "data_minus_background.json", "type": "json"},
            {"canonical_filename": "interpretation.md", "type": "markdown"},
            {"canonical_filename": "submission_trace.json", "type": "json"},
        ],
        "schemas": {
            "diphoton_mass_spectrum.json": {
                "required_fields": ["bin_edges", "bin_counts", "bin_uncertainties"]
            },
            "diphoton_fit_summary.json": {
                "required_fields": [
                    "signal_model_family",
                    "background_model_family",
                    "fit_range",
                    "signal_peak_position",
                ]
            },
            "data_minus_background.json": {
                "required_fields": ["bin_centers", "residual_counts", "residual_uncertainties"]
            },
            "interpretation.md": {"constraints": {"non_empty": True, "min_characters": 20}},
            "submission_trace.json": {
                "required_fields": [
                    "workflow_stages",
                    "cuts_applied",
                    "observable_constructed",
                    "fit_model_family_used",
                    "output_files_generated",
                    "reported_result",
                    "baseline_assumptions_used",
                    "object_definition",
                    "derived_observables",
                    "primary_observable",
                    "histogram_definition",
                    "input_files_used",
                    "input_file_count",
                    "selected_events_total",
                    "cutflow_summary",
                ]
            },
        },
    }


def _l1_request(tmp_path: Path | None = None) -> dict:
    data = {
        "work_dir": str(tmp_path / "solver_work") if tmp_path is not None else "",
        "output_dir": str(tmp_path / "solver_work") if tmp_path is not None else "",
        "input_manifest_path": str(tmp_path / "input_manifest.json") if tmp_path is not None else "",
    }
    return {
        "role": "task_request",
        "task_id": "t002_hyy_v5_l1",
        "task_type": "hyy_l1",
        "mode": "call_white",
        "prompt": "Run strict L1 Hyy.",
        "submission_contract": _l1_contract(),
        "data": data,
        "constraints": {"response_format": "submission_bundle_v1", "solver_backend": "agent_2_scifi_oh"},
    }


def _manifest(tmp_path: Path) -> dict:
    root_file = tmp_path / "events.root"
    root_file.write_text("placeholder", encoding="utf-8")
    manifest = {
        "shared_input_dir": str(tmp_path),
        "input_manifest_path": str(tmp_path / "input_manifest.json"),
        "files": [{"logical_name": "events.root", "path": str(root_file), "size_bytes": 11}],
        "read_only_for_solver": True,
    }
    (tmp_path / "input_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _mc_manifest(tmp_path: Path) -> dict:
    root_file = tmp_path / "mc.root"
    root_file.write_text("placeholder", encoding="utf-8")
    return {
        "shared_input_dir": str(tmp_path),
        "files": [
            {
                "logical_name": "mc.root",
                "path": str(root_file),
                "size_bytes": root_file.stat().st_size,
                "sample_role": "background",
                "is_mc": True,
                "weight_policy": "weighted",
            }
        ],
        "read_only_for_solver": True,
    }


def _valid_l1_artifacts() -> dict:
    output_names = [
        "diphoton_mass_spectrum.json",
        "diphoton_fit_summary.json",
        "data_minus_background.json",
        "interpretation.md",
        "submission_trace.json",
    ]
    return {
        "diphoton_mass_spectrum.json": {
            "bin_edges": [100.0, 101.0],
            "bin_counts": [1],
            "bin_uncertainties": [1.0],
        },
        "diphoton_fit_summary.json": {
            "signal_model_family": "gaussian",
            "background_model_family": "polynomial",
            "fit_range": [100.0, 160.0],
            "signal_peak_position": 125.0,
        },
        "data_minus_background.json": {
            "bin_centers": [100.5],
            "residual_counts": [0.0],
            "residual_uncertainties": [1.0],
        },
        "interpretation.md": "A computed L1 spectrum reports a modest localized feature near 125 GeV.",
        "submission_trace.json": {
            "workflow_stages": [
                {"stage_id": stage_id, "order_index": idx + 1, "status": "ok"}
                for idx, stage_id in enumerate(L1_STAGE_IDS)
            ],
            "cuts_applied": [
                {"cut_id": cut_id, "value": True, "applied": True}
                for cut_id in sorted(L1_CUT_IDS)
            ],
            "observable_constructed": {"name": "m_yy", "inputs": ["photon_pt", "photon_eta"]},
            "fit_model_family_used": {
                "signal": "gaussian",
                "background": "polynomial",
                "background_order": 4,
                "fit_range_GeV": [100.0, 160.0],
                "weighting_scheme": "inverse_sqrt_bin_count",
            },
            "output_files_generated": output_names,
            "reported_result": {"signal_peak_position": 125.0},
            "baseline_assumptions_used": ["strict L1 test"],
            "object_definition": {
                "type": "photon_pair",
                "multiplicity": 2,
                "ordering_principle": "leading_subleading_photon_pair",
            },
            "derived_observables": [{"name": "m_yy"}],
            "primary_observable": {"name": "m_yy", "inputs": ["photon_pt"], "construction": "test"},
            "histogram_definition": {
                "observable": "m_yy",
                "range": [100.0, 160.0],
                "bin_width": 1.0,
                "uncertainty_model": "sqrt_n_statistical_uncertainty",
            },
            "input_files_used": ["events.root"],
            "input_file_count": 1,
            "selected_events_total": 1,
            "cutflow_summary": {"input_events": 1, "selected_events": 1},
        },
    }


def _bundle(artifacts: dict) -> str:
    return json.dumps({"status": "ok", "artifacts": artifacts})


def _zpeak_contract() -> dict:
    return {
        "version": 2,
        "required_outputs": [
            {"canonical_filename": "fit_summary.json", "type": "json"},
            {"canonical_filename": "interpretation.md", "type": "markdown"},
            {"canonical_filename": "submission_trace.json", "type": "json"},
        ],
        "schemas": {
            "fit_summary.json": {
                "required_fields": ["task_id", "status", "fit_result", "fit_method"],
                "field_types": {
                    "task_id": "string",
                    "status": "string",
                    "fit_result": "object",
                    "fit_method": "object",
                },
                "nested_required_fields": {
                    "fit_result": {"required_fields": ["mu", "sigma", "gof"]},
                    "fit_result.gof": {"required_fields": ["p_value", "chi2_ndof"]},
                    "fit_method": {
                        "required_fields": [
                            "model",
                            "fit_range",
                            "binned_or_unbinned",
                            "optimizer",
                            "initial_params",
                            "uncertainties_method",
                        ]
                    },
                },
            },
            "interpretation.md": {"constraints": {"non_empty": True, "min_characters": 20}},
            "submission_trace.json": {
                "required_fields": ["task_id", "status", "workflow_stages", "output_files_generated"],
                "field_types": {
                    "workflow_stages": "array_object",
                    "output_files_generated": "array_string",
                },
                "nested_required_fields": {
                    "workflow_stages": {"required_fields": ["stage_id", "order_index", "status"]}
                },
            },
        },
    }


def _zpeak_request(tmp_path: Path | None = None) -> dict:
    return {
        "role": "task_request",
        "task_id": "t001_zpeak_fit",
        "task_type": "zpeak_fit",
        "mode": "call_white",
        "prompt": "Run a Z to dimuon fit using the public prompt and contract.",
        "submission_contract": _zpeak_contract(),
        "data": {"work_dir": str(tmp_path) if tmp_path else ""},
        "constraints": {"response_format": "submission_bundle_v1", "solver_backend": "agent_2_scifi_oh"},
    }


def _valid_zpeak_artifacts() -> dict:
    return {
        "fit_summary.json": {
            "task_id": "t001_zpeak_fit",
            "status": "ok",
            "fit_result": {"mu": 91.2, "sigma": 2.1, "gof": {"p_value": 0.4, "chi2_ndof": 1.1}},
            "fit_method": {
                "model": "gaussian_plus_background",
                "fit_range": [70.0, 110.0],
                "binned_or_unbinned": "binned",
                "optimizer": "scipy.curve_fit",
                "initial_params": {"mu": 91.0},
                "uncertainties_method": "covariance",
            },
            "comments": "computed from a test spectrum",
        },
        "interpretation.md": "The dimuon mass fit reports a Z peak near 91 GeV using scipy.curve_fit.",
        "submission_trace.json": {
            "task_id": "t001_zpeak_fit",
            "status": "ok",
            "workflow_stages": [
                {"stage_id": "data_loading", "order_index": 1, "status": "ok"},
                {"stage_id": "z_peak_fit", "order_index": 2, "status": "ok"},
            ],
            "output_files_generated": ["fit_summary.json", "interpretation.md", "submission_trace.json"],
        },
    }


def _hzz_l1_contract() -> dict:
    return {
        "version": 1,
        "level": "l1",
        "required_outputs": [
            {"canonical_filename": "four_lepton_mass_spectrum.json", "type": "json"},
            {"canonical_filename": "four_lepton_inference_summary.json", "type": "json"},
            {"canonical_filename": "interpretation.md", "type": "markdown"},
            {"canonical_filename": "submission_trace.json", "type": "json"},
        ],
        "schemas": {
            "four_lepton_mass_spectrum.json": {
                "required_fields": ["observable_name", "bin_edges_gev", "data_counts"]
            },
            "four_lepton_inference_summary.json": {
                "required_fields": ["region_of_interest_gev", "significance_proxy", "excess_observed"]
            },
            "interpretation.md": {"constraints": {"non_empty": True, "min_characters": 20}},
            "submission_trace.json": {
                "required_fields": [
                    "workflow_stages",
                    "input_samples_used",
                    "cuts_applied",
                    "observable_constructed",
                    "fit_model_family_used",
                    "output_files_generated",
                ],
                "nested_required_fields": {
                    "input_samples_used": {
                        "required_fields": ["sample_name", "sample_role", "files_used"]
                    }
                },
            },
        },
    }


def _hzz_l1_request(tmp_path: Path | None = None) -> dict:
    return {
        "role": "task_request",
        "task_id": "t005_hzz4l_l1",
        "task_type": "hzz4l_l1",
        "mode": "call_white",
        "prompt": "Run HZZ four-lepton L1 with skim exactly4lep.",
        "submission_contract": _hzz_l1_contract(),
        "data": {"work_dir": str(tmp_path) if tmp_path else ""},
        "constraints": {"response_format": "submission_bundle_v1", "solver_backend": "agent_2_scifi_oh"},
    }


def _valid_hzz_l1_artifacts() -> dict:
    return {
        "four_lepton_mass_spectrum.json": {
            "observable_name": "m4l",
            "bin_edges_gev": [80.0, 82.5],
            "data_counts": [1],
        },
        "four_lepton_inference_summary.json": {
            "region_of_interest_gev": [122.5, 130.0],
            "significance_proxy": 1.2,
            "excess_observed": True,
        },
        "interpretation.md": "The four-lepton spectrum has a Higgs-like feature near 125 GeV.",
        "submission_trace.json": {
            "workflow_stages": [
                {"stage_id": "sample_assembly", "status": "completed", "order_index": 1}
            ],
            "input_samples_used": [
                {"sample_name": "Data", "sample_role": "data", "files_used": ["data.root"]},
                {"sample_name": "Signal ($m_H$ = 125 GeV)", "sample_role": "signal", "files_used": ["signal.root"]},
            ],
            "cuts_applied": [{"cut_id": "event_trigger_requirement", "applied": True}],
            "observable_constructed": {"name": "m4l"},
            "fit_model_family_used": {"signal": "histogram_template", "background": "histogram_template"},
            "output_files_generated": [
                "four_lepton_mass_spectrum.json",
                "four_lepton_inference_summary.json",
                "interpretation.md",
                "submission_trace.json",
            ],
        },
    }


def _hzz_l2_contract() -> dict:
    return {
        "version": 1,
        "level": "l2",
        "required_outputs": [
            {"canonical_filename": "four_lepton_mass_spectrum.json", "type": "json"},
            {"canonical_filename": "four_lepton_excess_summary.json", "type": "json"},
            {"canonical_filename": "interpretation.md", "type": "markdown"},
            {"canonical_filename": "submission_trace.json", "type": "json"},
        ],
        "schemas": {
            "four_lepton_mass_spectrum.json": {
                "required_fields": [
                    "observable",
                    "bin_edges",
                    "data_counts",
                    "total_background_counts",
                    "total_background_uncertainty",
                    "signal_counts",
                ]
            },
            "four_lepton_excess_summary.json": {
                "required_fields": [
                    "method_type",
                    "signal_region",
                    "window_background_yield",
                    "window_numerator_yield",
                    "significance_proxy",
                ]
            },
            "interpretation.md": {"constraints": {"non_empty": True, "min_characters": 20}},
            "submission_trace.json": {
                "required_fields": [
                    "workflow_stages",
                    "scientific_decisions",
                    "input_samples_used",
                    "observable_constructed",
                    "inference_strategy",
                    "output_files_generated",
                ],
                "nested_required_fields": {
                    "workflow_stages": {"required_fields": ["stage_label", "status"]},
                    "input_samples_used": {
                        "required_fields": ["sample_name", "sample_role", "files_used"]
                    },
                    "observable_constructed": {"required_fields": ["name"]},
                    "inference_strategy": {"required_fields": ["method_family"]},
                },
            },
        },
    }


def _hzz_l2_request(tmp_path: Path | None = None) -> dict:
    return {
        "role": "task_request",
        "task_id": "t006_hzz4l_l2",
        "task_type": "hzz4l_l2",
        "mode": "call_white",
        "prompt": "Run HZZ four-lepton L2 with skim exactly4lep and the manifest samples.",
        "submission_contract": _hzz_l2_contract(),
        "data": {"work_dir": str(tmp_path) if tmp_path else ""},
        "constraints": {"response_format": "submission_bundle_v1", "solver_backend": "agent_2_scifi_oh"},
    }


def _valid_hzz_l2_artifacts() -> dict:
    output_names = [
        "four_lepton_mass_spectrum.json",
        "four_lepton_excess_summary.json",
        "interpretation.md",
        "submission_trace.json",
    ]
    return {
        "four_lepton_mass_spectrum.json": {
            "observable": "m4l",
            "bin_edges": [80.0, 82.5, 85.0],
            "data_counts": [1, 2],
            "total_background_counts": [0.9, 1.8],
            "total_background_uncertainty": [0.3, 0.4],
            "signal_counts": [0.01, 0.02],
        },
        "four_lepton_excess_summary.json": {
            "method_type": "sideband_subtracted_window_count",
            "signal_region": [120.0, 130.0],
            "window_background_yield": 2.7,
            "window_numerator_yield": 1.0,
            "significance_proxy": 0.6,
        },
        "interpretation.md": "The four-lepton spectrum is interpreted with a cautious window-counting excess estimate.",
        "submission_trace.json": {
            "workflow_stages": [
                {"stage_label": "assemble manifest samples", "status": "completed"},
                {"stage_label": "select four-lepton candidates", "status": "completed"},
                {"stage_label": "construct m4l spectrum", "status": "completed"},
            ],
            "scientific_decisions": [
                "Use manifest-declared data, background, and signal samples only."
            ],
            "input_samples_used": [
                {"sample_name": "Data", "sample_role": "data", "files_used": ["data.root"]},
                {
                    "sample_name": "Background $Z,t\\bar{t},t\\bar{t}+V,VVV$",
                    "sample_role": "background",
                    "files_used": ["ztt.root"],
                },
                {"sample_name": "Background $ZZ^{*}$", "sample_role": "background", "files_used": ["zz.root"]},
                {"sample_name": "Signal ($m_H$ = 125 GeV)", "sample_role": "signal", "files_used": ["signal.root"]},
            ],
            "observable_constructed": {"name": "m4l", "inputs": ["lep_pt", "lep_eta", "lep_phi", "lep_E"]},
            "inference_strategy": {"method_family": "window_counting_with_mc_background"},
            "output_files_generated": output_names,
        },
    }


def test_scifi_oh_backend_registry_accepts_names():
    assert get_solver_backend("agent_2_scifi_oh").name == "agent_2_scifi_oh"
    assert get_solver_backend("scifi_oh").name == "agent_2_scifi_oh"


def test_unsuffixed_scifi_names_are_reserved_for_future_backend():
    with pytest.raises(ValueError, match="Unknown solver_backend 'agent_2_scifi'"):
        get_solver_backend("agent_2_scifi")
    with pytest.raises(ValueError, match="Unknown solver_backend 'scifi'"):
        get_solver_backend("scifi")


def test_scifi_prompt_builder_renders_sam_sections(tmp_path):
    req = _l1_request(tmp_path)
    manifest = _manifest(tmp_path)
    prompt = build_sam_prompt(
        "Base benchmark prompt",
        req,
        manifest,
        attempt=1,
        max_attempts=2,
    )

    assert "## Context" in prompt
    assert "## Todo" in prompt
    assert "## Expect" in prompt
    assert "Base benchmark prompt" in prompt
    assert "submission_bundle_v1" in prompt
    assert "events.root" in prompt
    assert "contract_driven_analysis" in prompt
    assert "Contract-Driven Analysis Skill" in prompt
    assert "Scientific Trace Skill" in prompt
    assert "Evidence Consistency Skill" in prompt
    assert "Hyy L1 Strict Skill" not in prompt
    assert "MC Weighting Skill" not in prompt


def test_scifi_prompt_builder_is_contract_driven_for_hzz_l1(tmp_path):
    req = _hzz_l1_request(tmp_path)
    prompt = build_sam_prompt(
        "Base HZZ benchmark prompt",
        req,
        None,
        attempt=1,
        max_attempts=2,
    )

    assert detect_task_level(req) == "l1"
    assert "contract_driven_analysis" in prompt
    assert "Hyy L1 Strict Skill" not in prompt
    assert "requested analysis" in prompt


def test_scifi_prompt_builder_injects_mc_weighting_skill_for_mc_manifest(tmp_path):
    req = _hzz_l2_request(tmp_path)
    prompt = build_sam_prompt(
        "Compare Data to weighted MC backgrounds and signal.",
        req,
        _mc_manifest(tmp_path),
        attempt=1,
        max_attempts=2,
    )

    assert "mc_weighting" in prompt
    assert "MC Weighting Skill" in prompt
    assert "sum_of_weights" in prompt
    assert "lumi_fb_inv * 1000" in prompt
    assert "Data events must remain unweighted" in prompt
    assert "sqrt(sum(w^2))" in prompt
    assert "vectorized_root_analysis" in prompt
    assert "Vectorized ROOT Analysis Skill" in prompt
    assert "uproot.iterate" in prompt
    assert "awkward" in prompt
    assert "np.histogram" in prompt
    assert "for i in range(len(events))" in prompt


def test_scifi_prompt_builder_injects_vectorized_root_skill_for_root_manifest(tmp_path):
    req = _zpeak_request(tmp_path)
    prompt = build_sam_prompt(
        "Fit a peak in observed data.",
        req,
        _manifest(tmp_path),
        attempt=1,
        max_attempts=2,
    )

    assert "vectorized_root_analysis" in prompt
    assert "Vectorized ROOT Analysis Skill" in prompt
    assert "uproot.iterate" in prompt
    assert "awkward" in prompt
    assert "np.histogram" in prompt
    assert "vector" in prompt


def test_scifi_prompt_builder_does_not_inject_vectorized_root_skill_for_non_root_manifest(tmp_path):
    req = _zpeak_request(tmp_path)
    csv_file = tmp_path / "events.csv"
    csv_file.write_text("mass\n91.2\n", encoding="utf-8")
    manifest = {
        "shared_input_dir": str(tmp_path),
        "files": [{"logical_name": "events.csv", "path": str(csv_file), "format": "csv"}],
        "read_only_for_solver": True,
    }
    prompt = build_sam_prompt(
        "Fit a peak in observed tabular data.",
        req,
        manifest,
        attempt=1,
        max_attempts=2,
    )

    assert "Vectorized ROOT Analysis Skill" not in prompt
    assert "vectorized_root_analysis" not in prompt


def test_scifi_prompt_builder_does_not_inject_mc_weighting_skill_for_data_only_manifest(tmp_path):
    req = _zpeak_request(tmp_path)
    prompt = build_sam_prompt(
        "Fit a peak in observed data.",
        req,
        _manifest(tmp_path),
        attempt=1,
        max_attempts=2,
    )

    assert "MC Weighting Skill" not in prompt
    assert "mc_weighting" not in prompt


def test_prompt_requirement_extraction_reads_exact_public_lists():
    hyy_prompt = """
    In `submission_trace.json`, encode these stages exactly as objects:
    {"stage_id": "data_loading"}
    {"stage_id": "event_selection"}
    Encode `cuts_applied` with these exact `cut_id` values and fields:
    {"cut_id": "at_least_two_photons"}
    {"cut_id": "leading_photon_pt"}
    """
    hzz_prompt = """
    Record the manifest samples used in a machine-readable way. Include the four sample names exactly:
    - `Data`
    - `Background $ZZ^{*}$`
    For `workflow_stages`, use these exact stage ids when the stage is performed:
    - `sample_assembly`
    - `event_selection`
    For `cuts_applied`, use these exact `cut_id` values:
    - `event_trigger_requirement`
    - `total_charge_requirement`
    """

    hyy = extract_prompt_requirements(hyy_prompt)
    hzz = extract_prompt_requirements(hzz_prompt)

    assert hyy["stage_ids"] == ["data_loading", "event_selection"]
    assert hyy["cut_ids"] == ["at_least_two_photons", "leading_photon_pt"]
    assert hzz["stage_ids"] == ["sample_assembly", "event_selection"]
    assert hzz["cut_ids"] == ["event_trigger_requirement", "total_charge_requirement"]
    assert hzz["sample_names"] == ["Data", "Background $ZZ^{*}$"]


def test_scifi_review_accepts_valid_l1_bundle(tmp_path):
    result = review_submission_bundle(_l1_request(tmp_path), _bundle(_valid_l1_artifacts()))

    assert result.passed
    assert result.feedback["retry_instruction"] == "independent review passed; no retry required"


def test_scifi_review_accepts_zpeak_bundle_and_rejects_missing_nested_gof(tmp_path):
    artifacts = _valid_zpeak_artifacts()
    result = review_submission_bundle(_zpeak_request(tmp_path), _bundle(artifacts))

    assert result.passed

    artifacts["fit_summary.json"]["fit_result"]["gof"].pop("p_value")
    result = review_submission_bundle(_zpeak_request(tmp_path), _bundle(artifacts))

    assert not result.passed
    assert any("fit_result.gof" in item and "p_value" in item for item in result.feedback["schema_or_type_errors"])


def test_scifi_review_accepts_hzz_l1_without_hyy_photon_checks(tmp_path):
    result = review_submission_bundle(_hzz_l1_request(tmp_path), _bundle(_valid_hzz_l1_artifacts()))

    assert result.passed
    assert result.feedback["retry_instruction"] == "independent review passed; no retry required"


def test_scifi_review_accepts_hzz_l2_contract_trace_without_hyy_scope_fields(tmp_path):
    result = review_submission_bundle(_hzz_l2_request(tmp_path), _bundle(_valid_hzz_l2_artifacts()))

    assert result.passed
    assert result.feedback["retry_instruction"] == "independent review passed; no retry required"


def test_scifi_review_rejects_missing_l1_provenance(tmp_path):
    artifacts = _valid_l1_artifacts()
    artifacts["submission_trace.json"].pop("input_files_used")

    result = review_submission_bundle(_l1_request(tmp_path), _bundle(artifacts))

    assert not result.passed
    assert any("input_files_used" in item for item in result.feedback["schema_or_type_errors"])


def test_scifi_review_checks_prompt_declared_exact_trace_values(tmp_path):
    req = _hzz_l1_request(tmp_path)
    req["prompt"] = """
    Include the four sample names exactly:
    - `Data`
    - `Signal ($m_H$ = 125 GeV)`
    For `workflow_stages`, use these exact stage ids when the stage is performed:
    - `sample_assembly`
    - `event_selection`
    For `cuts_applied`, use these exact `cut_id` values:
    - `event_trigger_requirement`
    - `total_charge_requirement`
    """
    artifacts = _valid_hzz_l1_artifacts()
    result = review_submission_bundle(req, _bundle(artifacts))

    assert not result.passed
    assert any("event_selection" in item for item in result.feedback["trace_consistency_errors"])
    assert any("total_charge_requirement" in item for item in result.feedback["trace_consistency_errors"])


def test_scifi_review_rejects_unknown_and_missing_artifacts(tmp_path):
    artifacts = _valid_l1_artifacts()
    artifacts.pop("data_minus_background.json")
    artifacts["extra.json"] = {}

    result = review_submission_bundle(_l1_request(tmp_path), _bundle(artifacts))

    assert not result.passed
    assert result.feedback["missing_required_artifacts"] == ["data_minus_background.json"]
    assert any("undeclared artifact" in item for item in result.feedback["schema_or_type_errors"])


@pytest.mark.asyncio
async def test_scifi_loop_retries_with_feedback(tmp_path):
    req = _l1_request(tmp_path)
    prompts: list[str] = []

    async def status(_: str) -> None:
        return None

    async def worker(prompt: str, attempt: int, total_attempts: int) -> str:
        assert total_attempts == 2
        prompts.append(prompt)
        artifacts = _valid_l1_artifacts()
        if attempt == 1:
            artifacts["submission_trace.json"].pop("input_files_used")
        return _bundle(artifacts)

    loop = SciFiLoop(worker=worker, status=status, max_attempts=2)
    result = await loop.run(
        base_prompt="Base prompt",
        req_json=req,
        input_manifest=None,
        work_dir=tmp_path,
    )

    assert result.review.passed
    assert result.attempts == 2
    assert len(prompts) == 2
    assert "Independent Review Feedback From Previous Attempt" in prompts[1]
    assert "input_files_used" in prompts[1]
    assert json.loads(result.final_text)["status"] == "ok"


@pytest.mark.asyncio
async def test_scifi_oh_backend_retries_invalid_l1_trace(tmp_path, monkeypatch, caplog):
    req = _l1_request(tmp_path)
    manifest = _manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    work_dir.mkdir()
    backend = get_solver_backend("agent_2_scifi_oh")
    calls = {"count": 0}
    statuses: list[str] = []
    caplog.set_level(logging.INFO, logger="solver_backends")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            calls["count"] += 1
            artifacts = _valid_l1_artifacts()
            if calls["count"] == 1:
                artifacts["submission_trace.json"].pop("input_files_used")
            return _bundle(artifacts).encode("utf-8"), b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        assert cmd[0] == "oh"
        return FakeProcess()

    async def status(text: str) -> None:
        statuses.append(text)

    monkeypatch.setattr("solver_backends.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setenv("SCIFI_OH_MAX_RETRIES", "2")

    final_text = await backend.run(
        "Base benchmark prompt",
        req,
        system_prompt="ignored",
        status=status,
        input_manifest=manifest,
        work_dir=work_dir,
    )

    assert calls["count"] == 2
    assert json.loads(final_text)["status"] == "ok"
    status_text = "\n".join(statuses)
    assert "Independent review FAIL" in status_text
    assert "retrying worker with independent review feedback" in status_text
    assert "Independent review PASS" in status_text
    assert str(work_dir / "debug_scifi_oh_output.log") in status_text
    debug_text = (work_dir / "debug_scifi_oh_output.log").read_text(encoding="utf-8")
    assert "--- Worker Executor ---" in debug_text
    assert "openharness" in debug_text
    assert "===== BEGIN debug_scifi_oh_output.log" in caplog.text
    assert "===== END debug_scifi_oh_output.log" in caplog.text
    assert not (work_dir / "debug_oh_output.log").exists()
    assert not (work_dir / "debug_scifi_output.log").exists()


@pytest.mark.asyncio
async def test_scifi_oh_backend_recovers_bundle_from_output_files(tmp_path, monkeypatch):
    req = _l1_request(tmp_path)
    manifest = _manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    work_dir.mkdir()
    backend = get_solver_backend("scifi_oh")
    artifacts = _valid_l1_artifacts()

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            output_dir = work_dir / "artifacts"
            output_dir.mkdir(parents=True, exist_ok=True)
            for name, payload in artifacts.items():
                path = output_dir / name
                if name.endswith(".md"):
                    path.write_text(payload, encoding="utf-8")
                else:
                    path.write_text(json.dumps(payload), encoding="utf-8")
            return b"non-json worker transcript", b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return FakeProcess()

    statuses: list[str] = []

    async def status(text: str) -> None:
        statuses.append(text)

    monkeypatch.setattr("solver_backends.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setenv("SCIFI_OH_MAX_RETRIES", "1")

    final_text = await backend.run(
        "Base benchmark prompt",
        req,
        system_prompt="ignored",
        status=status,
        input_manifest=manifest,
        work_dir=work_dir,
    )

    bundle = json.loads(final_text)
    assert bundle["status"] == "ok"
    assert sorted(bundle["artifacts"]) == sorted(artifacts)
    assert "recovered submission_bundle_v1 from solver output files" in "\n".join(statuses)
