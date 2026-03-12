## Autonomous Incident Fix Agent (MVP)

This service exposes an API that accepts incident information (error descriptions, logs, stack traces, and repository metadata) and runs a staged agent pipeline to:

- understand the incident,
- analyze the codebase,
- retrieve relevant knowledge,
- propose a minimal fix,
- and prepare a human-readable resolution report.

This repository currently contains only the core Pydantic models and basic Python project metadata. Further phases (FastAPI API, orchestrator, indexing, sandboxing, etc.) can be implemented following the attached architecture plan.

### Development

- **Python version**: 3.10+
- **Install dependencies**:

```bash
pip install -e .
```

