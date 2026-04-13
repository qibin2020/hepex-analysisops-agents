from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part, TaskState, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from bundle_runtime import (
    build_minimal_submission_bundle,
    error_response,
    is_submission_bundle_request,
    load_input_manifest,
    parse_task_request,
    request_mode,
    should_mock_submission_bundle,
)

logger = logging.getLogger(__name__)


class PurpleAgent:
    def __init__(self):
        self.app_name = "hepex_analysisops"
        try:
            with open("./AGENTS.md", "r", encoding="utf-8") as f:
                self.system_prompt = f.read().strip()
        except Exception as e:
            logger.error(f"Failed to read ./AGENTS.md: {e}")
            self.system_prompt = "You are a physics analysis agent."

    @staticmethod
    def _debug_log(blocks: list[tuple[str, str]]) -> None:
        with open("debug_oh_output.log", "a", encoding="utf-8") as f:
            for title, content in blocks:
                f.write(f"{title}:\n{content}\n")
            f.write("=" * 40 + "\n")

    @staticmethod
    def _json_dump(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _build_bundle_prompt(
        self,
        prompt: str,
        req_json: dict[str, Any],
        input_manifest: dict[str, Any] | None,
    ) -> str:
        contract = req_json.get("submission_contract", {})
        data_info = req_json.get("data", {})
        constraints = req_json.get("constraints", {})
        mode = request_mode(req_json)

        sections = [
            prompt.strip(),
            "",
            "Additional runtime context from the benchmark:",
            f"- request_mode: {mode}",
            f"- task_id: {req_json.get('task_id', '')}",
            f"- task_type: {req_json.get('task_type', '')}",
            "",
            "You must return exactly one JSON object with this top-level shape:",
            '{',
            '  "status": "ok" | "error",',
            '  "artifacts": { "canonical_filename": <json-object-or-markdown-string>, ... }',
            '}',
            "",
            "Hard requirements:",
            "- Do not wrap the final JSON in markdown fences.",
            "- The artifact keys must exactly match submission_contract.required_outputs[*].canonical_filename.",
            "- JSON artifacts must be JSON objects, and markdown artifacts must be plain strings.",
            "- If the task cannot be completed, return a JSON object with status=\"error\" and an explanatory error field.",
            "",
            "submission_contract JSON:",
            self._json_dump(contract),
            "",
            "request.data JSON:",
            self._json_dump(data_info),
            "",
            "request.constraints JSON:",
            self._json_dump(constraints),
        ]

        if input_manifest is not None:
            sections.extend(
                [
                    "",
                    "Resolved input_manifest JSON:",
                    self._json_dump(input_manifest),
                ]
            )

        return "\n".join(sections).strip()

    def _prepare_request(
        self, input_payload: str
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None, str | None]:
        req_json = parse_task_request(input_payload, logger)
        if req_json is None:
            return None, input_payload, None, None

        prompt = req_json.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            logger.warning("Received request without a usable 'prompt' field")
            prompt = input_payload

        input_manifest = None
        if is_submission_bundle_request(req_json):
            manifest_path = req_json.get("data", {}).get("input_manifest_path")
            if isinstance(manifest_path, str) and manifest_path.strip():
                try:
                    input_manifest = load_input_manifest(req_json)
                except Exception as exc:
                    return (
                        req_json,
                        prompt,
                        None,
                        self._json_dump(error_response(str(exc))),
                    )
            elif should_mock_submission_bundle(req_json):
                return (
                    req_json,
                    prompt,
                    None,
                    self._json_dump(
                        error_response(
                            "Missing required data.input_manifest_path for submission_bundle_v1 request."
                        )
                    ),
                )

            if should_mock_submission_bundle(req_json):
                bundle = build_minimal_submission_bundle(req_json, input_manifest or {})
                return req_json, prompt, input_manifest, self._json_dump(bundle)

            prompt = self._build_bundle_prompt(prompt, req_json, input_manifest)

        return req_json, prompt, input_manifest, None

    async def _run_oh(self, prompt: str, req_json: dict[str, Any] | None) -> str:
        retry_delay = 2.0
        max_retries = 5
        final_text = None

        for attempt in range(max_retries):
            try:
                cmd = [
                    "oh",
                    "--permission-mode",
                    "full_auto",
                    "--dangerously-skip-permissions",
                    "--system-prompt",
                    self.system_prompt,
                    "--print",
                    prompt,
                ]

                self._debug_log(
                    [
                        ("--- Request Metadata ---", self._json_dump(req_json or {})),
                        ("--- Attempt ---", str(attempt + 1)),
                        ("--- Prompt ---", prompt),
                    ]
                )

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await process.communicate()
                stdout_text = stdout.decode(errors="replace")
                stderr_text = stderr.decode(errors="replace")

                self._debug_log(
                    [
                        ("--- Attempt Result ---", str(attempt + 1)),
                        ("STDOUT", stdout_text),
                        ("STDERR", stderr_text),
                    ]
                )

                if process.returncode == 0:
                    final_text = stdout_text.strip()
                    break

                err_str = stderr_text.strip()
                is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                if is_rate_limit and attempt < max_retries - 1:
                    logger.warning(
                        "WhiteAgent: Rate limit hit. Retrying %s/%s...",
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30.0)
                    continue

                final_text = self._json_dump(
                    {
                        "status": "error",
                        "error": f"OpenHarness failed with exit code {process.returncode}: {err_str}",
                    }
                )
                break

            except Exception as e:
                if attempt == max_retries - 1:
                    final_text = self._json_dump(
                        {
                            "status": "error",
                            "error": f"Agent run failed: {type(e).__name__}: {e}",
                        }
                    )
                await asyncio.sleep(retry_delay)

        if final_text is None:
            final_text = self._json_dump(
                {"status": "error", "error": "No final response from OpenHarness wrapper"}
            )

        logger.debug("Output from OpenHarness:\n%s", final_text)
        return final_text

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        input_payload = get_message_text(message)
        req_json, prompt, input_manifest, early_response = self._prepare_request(input_payload)

        status_text = "Running analysis agent via OpenHarness..."
        if req_json and is_submission_bundle_request(req_json):
            bundle_mode = request_mode(req_json)
            if early_response is not None and should_mock_submission_bundle(req_json):
                status_text = "Preparing deterministic submission_bundle_v1 response..."
            else:
                manifest_note = ""
                if input_manifest is not None:
                    manifest_note = f" ({len(input_manifest.get('files', []))} manifest file(s) visible)"
                status_text = f"Running submission_bundle_v1 request via OpenHarness [{bundle_mode}]{manifest_note}..."

        await updater.update_status(
            TaskState.working,
            new_agent_text_message(status_text),
        )

        try:
            final_text = early_response if early_response is not None else await self._run_oh(prompt, req_json)

            await updater.add_artifact(
                parts=[Part(root=TextPart(kind="text", text=final_text))],
                name="submission_trace",
            )
            await updater.update_status(TaskState.completed, new_agent_text_message("Done."))

        except Exception as e:
            err = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            await updater.add_artifact(
                parts=[Part(root=TextPart(kind="text", text=self._json_dump(err)))],
                name="submission_trace",
            )
            await updater.update_status(TaskState.failed, new_agent_text_message(err["error"]))


WhiteAgent = PurpleAgent
