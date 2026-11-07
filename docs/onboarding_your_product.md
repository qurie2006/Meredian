# Onboarding Your Product to Meredian

This guide explains how to connect your own application, service, or active incident to **Meredian** so that your engineering shifts (or AI coding agents) never repeat failed fix attempts.

---

## 1. Quick Onboarding: 3 Options

### Option A: 1-Click via Web Dashboard (Recommended for Demos)
1. Open the Meredian Dashboard: `http://127.0.0.1:8000`.
2. In the left sidebar, click **`+ Onboard Product`** next to the *Active Incident Bank* selector.
3. Fill in the modal:
   - **Product / System Name**: e.g. `Checkout Gateway`, `Video Transcoder Worker`, `Auth0 Broker`
   - **Incident Bank ID**: e.g. `checkout-spike-deadlock` (lowercase, alphanumeric with hyphens)
   - **Service Name**: e.g. `checkout-service`
   - **Severity Level**: `SEV-1`, `SEV-2`, or `SEV-3`
   - **Initial Outage Symptom**: e.g. `Postgres transaction pool timeout at 800 RPS; 504 Gateway Timeouts`
4. Click **Initialize Memory Bank**.
   * Meredian immediately provisions an isolated Hindsight memory bank, configures the institutional memory directives and skepticism disposition, indexes the symptom, and activates it as your current bank.

---

### Option B: Via REST API
You can register an incident programmatically from your monitoring or alert manager (PagerDuty, Datadog, OpsGenie):

```bash
curl -X POST http://127.0.0.1:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "id": "transcoder-oom-spike",
    "title": "FFmpeg Transcoder Pod OOM Crashloop",
    "service": "transcoder-worker",
    "severity": "SEV-1",
    "initial_symptom": "Kubelet Exit Code 137 during 4K HEVC renders over 50MB payload"
  }'
```

---

### Option C: Declarative YAML (`agent_config.yaml`)
For local repository workflows, configure `agent_config.yaml`:
```yaml
incident:
  id: "my-service-incident"
  title: "SEV-1 Database Connection Saturation"
  service: "order-management"
  severity: "SEV-1"
memory:
  backend: "hindsight"
  hindsight_url: "http://127.0.0.1:8888"
  token_budget: 400
policy:
  repeat_confidence_threshold: 0.75
  related_confidence_threshold: 0.45
```

---

## 2. Ingesting Real-Time Shift Events

Meredian automatically translates raw telemetry into structured hypotheses. You can stream events from 3 sources:

### A. Git Commits / Diffs
Whenever an engineer or agent commits a test change:
```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "checkout-spike-deadlock",
    "events": [
      {
        "id": "git-evt-101",
        "source": "git",
        "actor": "Sarah",
        "site": "Seattle",
        "type": "commit",
        "payload": {
          "commit_hash": "a1b2c3d",
          "message": "test: raise postgres statement_timeout to 60s",
          "files": ["config/database.yml"],
          "diff": "- statement_timeout: 5000\n+ statement_timeout: 60000"
        }
      }
    ]
  }'
```

### B. Terminal Shell Sessions
Use the built-in terminal hooks:
- **Bash / Zsh**:
  ```bash
  source interceptor/terminal-hook/meredian-hook.sh
  meredian_exec "pg_ctl restart"
  ```
- **PowerShell**:
  ```powershell
  . .\interceptor\terminal-hook\meredian-hook.ps1
  Invoke-MeredianCommand "kubectl scale deployment checkout --replicas=10"
  ```

---

## 3. Protecting Your Team with Pre-Execution Interceptors

### In VS Code
1. Open `interceptor/vscode-extension` in VS Code.
2. Update the active incident ID in settings to your bank ID (e.g. `checkout-spike-deadlock`).
3. Press `F5` to launch. Any file save (`Ctrl+S` / `Cmd+S`) will query Meredian in `<50ms` and display a modal before the engineer wastes hours testing a known dead end.

### In GitHub Pull Requests (CI/CD)
Add `.github/workflows/meredian-check.yml` to your repo. Any PR opened with a change that duplicates a dead end will receive an automated block and an explanation citing prior shift evidence.

### In Band.ai / Slack / Band Desktop
Meredian's ACP server (`scripts/acp_server.py`) connects natively to Band Desktop, posting real-time interrupts and handoff briefings straight into the incident room.

---

## 4. How Hindsight Isolates Products

Every product and incident receives its own **isolated Hindsight Bank**:
- `checkout-spike-deadlock` facts and observations stay completely separate from `transcoder-oom-spike`.
- Once an incident reaches Day 5 (root cause verified), verified fixes graduate into the cross-incident pattern bank: **`meredian-team-patterns`**.
- This enables your company to build a permanent, searchable institutional brain across all past outages.

