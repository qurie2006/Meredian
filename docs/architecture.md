# Meredian Architecture & Runbook

## Five-Layer Architecture
1. **Sources (`collector/`, `data/`)**: Git commits/diffs (`GitAdapter`), terminal session logs (`TerminalAdapter`), and Band room messages (`BandAdapter`), plus deterministic synthetic world replay (`data/incidents.json`, `data/replay.py`).
2. **Coordination (`band_agent/`)**: Band room listener and poster (`BandAgentClient`) supporting both Mock mode (for offline/stage demos) and Live HTTP/SDK mode.
3. **Intelligence (`redactor/`, `llm/`, `attempts/`, `decision/`)**:
   - `Redactor`: Strips API keys (`gsk_`, `sk-`, `ghp_`, `AKIA`), JWT/Bearer tokens, URI passwords, emails, and internal corporate hostnames (`*.internal.northwind.corp`) before storage or LLM calls.
   - `GroqGateway`: Primary `openai/gpt-oss-120b` with fallback `qwen/qwen3-32b`, rate-limit backoff, single-retry JSON repair prompt, and deterministic template fallback.
   - `AttemptBuilder`: Clusters related events into structured `Attempt` records + plain-English narratives.
   - `ActionChecker` & `BriefingGenerator`: Normalizes actions, recalls within a token budget, judges `repeat | related | new`, enforces `interrupt | soft_warning | silent` policy, and generates shift-start briefings.
4. **Memory (`memory/`, `hindsight_client/`)**: Local Hindsight client & wrapper supporting `retain`, `recall`, `reflect`, bank mission/directives/disposition, and automatic observation consolidation.
5. **Experience (`web/`, `interceptor/`)**:
   - Web dashboard (`http://127.0.0.1:8000/`) with all 6 panels.
   - VS Code extension (`interceptor/vscode-extension/`).
   - PowerShell & Bash terminal hooks (`interceptor/terminal-hook/`).
   - Python file watcher (`interceptor/watcher/file_watcher.py`).

