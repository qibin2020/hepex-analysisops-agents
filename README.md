# HEPEx AnalysisOps Agent (Purple Agent)

[![Test and Publish Agent](https://github.com/ranriver/hepex-analysisops-agents/actions/workflows/test-and-publish.yml/badge.svg)](https://github.com/ranriver/hepex-analysisops-agents/actions/workflows/test-and-publish.yml)

> **AgentBeats Purple Agent** for performing high-energy physics analysis tasks.

## Overview

This is the **Purple Agent** (participant) for the [HEPEx AnalysisOps Benchmark](https://github.com/ranriver/hepex-analysisops-benchmark). It uses the Google ADK runtime with an OpenAI-backed model configuration and specialized physics tools to analyze ATLAS Open Data.

## Features

| Capability | Description |
|------------|-------------|
| **ROOT File Analysis** | Inspect schema and content of ROOT files |
| **Kinematics Processing** | Load and process particle kinematics (pT, η, φ, mass) |
| **Mass Calculations** | Compute dilepton and system invariant masses |
| **Peak Fitting** | Perform Gaussian + Polynomial fits on mass distributions |
| **A2A Protocol** | Full Agent-to-Agent protocol compliance |

## Quick Start

### Docker Image

```bash
# Pull from GHCR
docker pull ghcr.io/ranriver/hepex-analysisops-agents:latest

# Or build locally
docker build -t hepex-purple-agent:local .

# Run (listens on port 9009)
docker run -p 9009:9009 \
  -e OPENAI_API_KEY="..." \
  -e HEPEX_AGENT_MODEL="openai/gpt-5" \
  ghcr.io/ranriver/hepex-analysisops-agents:latest
```

### Local Development

```bash
# Install dependencies
uv sync

# Set API key and optional model override
export OPENAI_API_KEY="..."
export HEPEX_AGENT_MODEL="openai/gpt-5"

# Run the agent
uv run src/server.py --host 0.0.0.0 --port 9009
```

## AgentBeats Integration

### Agent Card

- **Name**: `HEPEx Purple Agent`
- **Port**: 9009 (A2A standard)
- **Protocol**: A2A (Agent-to-Agent)

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key used by the default ADK LiteLLM model backend |
| `HEPEX_OPENAI_MODEL` | No | Fallback OpenAI model string for ADK LiteLLM when `HEPEX_AGENT_MODEL` is unset |
| `HEPEX_AGENT_MODEL` | No | Generic model override; if set, takes precedence over `HEPEX_OPENAI_MODEL` |
| `HEPEX_DATA_DIR` | No | Data storage directory (default: `/tmp/atlas_data`) |

### Data Directory Structure

When downloading ATLAS Open Data, files are stored in:

```
$HEPEX_DATA_DIR/<release>/<dataset>/<skim>/
```

Example:
```
/home/agent/output/2025e-13tev-beta/data/2muons/
```

## Project Structure

```
.
├── src/
│   ├── server.py          # A2A server entrypoint
│   ├── agent.py           # Agent logic
│   ├── executor.py        # A2A executor for the purple agent
│   └── tools/             # Physics analysis tools
│       ├── data_tools.py  # ATLAS data download
│       ├── root_tools.py  # ROOT file analysis
│       └── fit_tools.py   # Peak fitting
├── tests/                 # Unit and integration tests
├── Dockerfile             # Container configuration
└── pyproject.toml         # Dependencies
```

## Testing

```bash
# Run tests
uv run pytest -v

# Run against live agent
uv run pytest -v --agent-url http://localhost:9009
```

## License

See [LICENSE](LICENSE) for details.
