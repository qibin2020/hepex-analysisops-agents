import json
import asyncio
import logging
import os
from typing import Any
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from tools.root_tools import inspect_root_schema_tool, load_kinematics_tool
from tools.physics_tools import calc_dilepton_mass_tool, calc_system_invariant_mass_tool
from tools.fitting_tools import fit_peak_tool
from tools.data_tools import download_atlas_data_tool as raw_download_atlas_data_tool, list_local_root_files_tool
from bundle_runtime import (
    build_minimal_submission_bundle,
    error_response,
    is_submission_bundle_request,
    load_input_manifest,
    parse_task_request,
    should_mock_submission_bundle,
)



logger = logging.getLogger(__name__)


class PurpleAgent:
    def __init__(self):
        self._request_download_defaults: dict[str, Any] = {}
        self._download_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        model_name = os.getenv("HEPEX_AGENT_MODEL") or os.getenv("HEPEX_OPENAI_MODEL") or "openai/gpt-5"
        self.agent = Agent(
            name="hepex_purple_agent",
            model=LiteLlm(model=model_name),
            description="General-purpose physics analysis agent using tools.",
            instruction=(
                "You are a physics analysis agent.\n"
                "- Use provided tools; do not do low-level ROOT I/O yourself.\n"
                "- If data files are not accessible at the provided paths (e.g. running on a separate server), use download_atlas_data_tool to download them locally.\n"
                "- When the task request provides release, dataset, skim, or max_files, treat those as fixed task inputs and do not invent replacements.\n"
                "- If schema is unknown, inspect first.\n"
                "- Make decisions explicitly and do sanity checks.\n"
                "- If the request asks for submission_bundle_v1, return exactly one JSON object with top-level keys status and artifacts.\n"
                "- Output a single JSON object in the task-required format.\n"
            ),
            tools=[
                # Data access tools
                self.download_atlas_data_tool,
                list_local_root_files_tool,
                # ROOT analysis tools
                inspect_root_schema_tool,
                load_kinematics_tool,
                calc_dilepton_mass_tool,
                calc_system_invariant_mass_tool,
                fit_peak_tool,
            ],
        )
        self.session_service = InMemorySessionService()
        self.app_name = "hepex_analysisops"
        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )

    def _set_request_download_defaults(self, req_json: dict[str, Any]) -> None:
        data_info = req_json.get("data", {}) or {}
        defaults: dict[str, Any] = {
            "release": data_info.get("release"),
            "dataset": data_info.get("dataset"),
            "skim": data_info.get("skim"),
            "protocol": data_info.get("protocol"),
            "max_files": data_info.get("max_files"),
            "shared_input_dir": data_info.get("shared_input_dir"),
            "input_manifest_path": data_info.get("input_manifest_path"),
        }
        self._request_download_defaults = defaults
        self._download_cache.clear()

    def download_atlas_data_tool(
        self,
        skim: str = "2muons",
        release: str = "2025e-13tev-beta",
        dataset: str = "data",
        protocol: str = "https",
        output_dir: str = "",
        max_files: int = 1,
        workers: int = 4,
    ) -> dict[str, Any]:
        defaults = self._request_download_defaults or {}
        if defaults.get("shared_input_dir") or defaults.get("input_manifest_path"):
            logger.info("PurpleAgent: download_atlas_data_tool called despite shared input; returning no-op.")
            return {
                "status": "ok",
                "local_paths": [],
                "n_ok": 0,
                "n_fail": 0,
                "n_requested": 0,
                "output_dir": None,
                "release": defaults.get("release"),
                "dataset": defaults.get("dataset"),
                "skim": defaults.get("skim"),
                "notes": "Shared input is already available for this request; skipping download.",
            }

        effective_release = defaults.get("release") or release
        effective_dataset = defaults.get("dataset") or dataset
        effective_skim = defaults.get("skim") or skim
        effective_protocol = defaults.get("protocol") or protocol
        effective_max_files = defaults.get("max_files")
        if effective_max_files is None:
            effective_max_files = max_files

        if (
            effective_release != release
            or effective_dataset != dataset
            or effective_skim != skim
            or effective_protocol != protocol
            or effective_max_files != max_files
        ):
            logger.info(
                "PurpleAgent: Overriding download request to task-scoped defaults: "
                "release=%s dataset=%s skim=%s protocol=%s max_files=%s",
                effective_release,
                effective_dataset,
                effective_skim,
                effective_protocol,
                effective_max_files,
            )

        cache_key = (
            effective_release,
            effective_dataset,
            effective_skim,
            effective_protocol,
            output_dir,
            effective_max_files,
            workers,
        )
        if cache_key in self._download_cache:
            logger.info(
                "PurpleAgent: Reusing cached download result for %s/%s/%s max_files=%s.",
                effective_release,
                effective_dataset,
                effective_skim,
                effective_max_files,
            )
            return dict(self._download_cache[cache_key])

        result = raw_download_atlas_data_tool(
            skim=effective_skim,
            release=effective_release,
            dataset=effective_dataset,
            protocol=effective_protocol,
            output_dir=output_dir,
            max_files=effective_max_files,
            workers=workers,
        )
        self._download_cache[cache_key] = dict(result)
        return result

    async def _emit_final_json(self, updater: TaskUpdater, payload: dict) -> None:
        final_text = json.dumps(payload, ensure_ascii=False)
        await updater.add_artifact(
            parts=[Part(root=TextPart(kind="text", text=final_text))],
            name="submission_trace",
        )
        await updater.update_status(TaskState.completed, new_agent_text_message("Done."))

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        input_text = get_message_text(message)

        req_json = parse_task_request(input_text, logger)
        self._set_request_download_defaults(req_json or {})
        if req_json is not None and req_json.get("role") == "task_request":
            data_info = req_json.get("data", {})
            release = data_info.get("release")
            dataset = data_info.get("dataset")
            skim = data_info.get("skim")
            shared_input_dir = data_info.get("shared_input_dir")
            input_manifest_path = data_info.get("input_manifest_path")
            max_files = data_info.get("max_files")

            if should_mock_submission_bundle(req_json):
                try:
                    input_manifest = load_input_manifest(req_json)
                    if input_manifest is None:
                        bundle = error_response(
                            "Missing required data.input_manifest_path for submission_bundle_v1 request."
                        )
                    else:
                        bundle = build_minimal_submission_bundle(req_json, input_manifest)
                except Exception as exc:
                    bundle = error_response(str(exc))

                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message("Preparing deterministic submission bundle..."),
                )
                await self._emit_final_json(updater, bundle)
                return
            if is_submission_bundle_request(req_json):
                logger.info("PurpleAgent: submission_bundle_v1 request in call_white mode; delegating to LLM runner.")

            if shared_input_dir or input_manifest_path:
                logger.info(
                    "PurpleAgent: Shared input detected (shared_input_dir=%s, input_manifest_path=%s); skipping local data download.",
                    shared_input_dir,
                    input_manifest_path,
                )
            elif release and dataset and skim:
                logger.info(f"PurpleAgent: Checking data environment for {release}/{dataset}/{skim}...")
                try:
                    res = self.download_atlas_data_tool(
                        release=release,
                        dataset=dataset,
                        skim=skim,
                        max_files=max_files if isinstance(max_files, int) else 1,
                    )

                    logger.debug(f"PurpleAgent: Data check result: {res}")

                    if res['status'] == 'ok':
                        logger.info(f"PurpleAgent: Data check passed. Local paths: {res['local_paths']}")
                    elif res["status"] == "partial":
                        logger.warning(
                            "PurpleAgent: Data check partially succeeded. ok=%s fail=%s output_dir=%s failed=%s",
                            res.get("n_ok"),
                            res.get("n_fail"),
                            res.get("output_dir"),
                            res.get("failed"),
                        )
                    else:
                        logger.warning(f"PurpleAgent: Data check warning: {res.get('notes')}")
                except Exception as e:
                    logger.error(f"PurpleAgent: Data check failed with error: {e}")

        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Running analysis agent..."),
        )

        user_id = "a2a_user"
        # Use context_id as session_id to enable multi-turn conversations
        session_id = message.context_id or message.message_id

        # Create session if it doesn't exist
        try:
            await self.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception:
            # session may already exist
            pass

        content = types.Content(role="user", parts=[types.Part(text=input_text)])
        
        final_text = None
        try:
            retry_delay = 2.0
            max_retries = 5
            
            for attempt in range(max_retries):
                try:
                    async for event in self.runner.run_async(
                        user_id=user_id,
                        session_id=session_id,
                        new_message=content,
                    ):
                        if event.is_final_response():
                            if event.content and event.content.parts:
                                # Extract text from all parts, filtering to text parts only
                                text_parts = []
                                for part in event.content.parts:
                                    if hasattr(part, 'text') and part.text:
                                        text_parts.append(part.text)
                                final_text = "\n".join(text_parts) if text_parts else None
                            if not final_text:
                                final_text = event.error_message or "No final response text."
                            break
                    
                    # If we got here successfully, break out of retry loop
                    break
                    
                except Exception as e:
                    err_str = str(e)
                    is_last_attempt = (attempt == max_retries - 1)
                    # Check for rate limits (429 or RESOURCE_EXHAUSTED)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    
                    if is_rate_limit and not is_last_attempt:
                        logger.warning(f"PurpleAgent: Rate limit hit (429). Retrying {attempt+1}/{max_retries} in {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, 30.0)
                        continue
                    else:
                        # Non-retryable or retries exhausted
                        final_text = json.dumps(
                            {"status": "error", "error": f"Agent run failed: {type(e).__name__}: {e}"},
                            ensure_ascii=False,
                        )
                        break

            if final_text is None:
                final_text = json.dumps(
                    {"status": "error", "error": "No final response from runner"},
                    ensure_ascii=False,
                )

            # Add artifact BEFORE marking task as completed
            # A2A closes the stream on terminal states, so artifacts must come first
            await updater.add_artifact(
                parts=[Part(root=TextPart(kind="text", text=final_text))],
                name="submission_trace",
            )
            await updater.update_status(TaskState.completed, new_agent_text_message("Done."))

        except Exception as e:
            err = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            # Add artifact BEFORE marking task as failed
            await updater.add_artifact(
                parts=[Part(root=TextPart(kind="text", text=json.dumps(err, ensure_ascii=False)))],
                name="submission_trace",
            )
            await updater.update_status(TaskState.failed, new_agent_text_message(err["error"]))


WhiteAgent = PurpleAgent
