# Meredian — Follow the Sun Engineering Memory

**Meredian** watches what each engineering shift tries, remembers what failed and why in **Hindsight**, and stops the next shift from repeating a dead end.

## Key Architectural Capabilities

- **Mission Control & Panoramic Incident Console**: Real-time cross-shift telemetry, Follow-the-Sun shift relay (Seattle -> London -> Bengaluru), and unified panoramic workspace bringing the Hypothesis Tree, Timeline, Shift Briefing, Interception Engine, and Action Simulator into a single cohesive view.
- **Institutional Memory RAG Engine (`POST /rag/query`)**: Fast, multi-field retrieval grounded in raw terminal logs, commit deltas, and Hindsight belief banks. Integrates conversational Staff SRE synthesis with dynamic action chips and grounded citations.
- **Hypothesis Elimination DAG (`decision/tree.py`)**: Hierarchical Bayesian hypothesis resolution graph with real-time branch pruning, tracking invalidated dead ends, suspect components, and verified root causes.
- **Pre-Execution Interception Suite**: GitHub Actions PR checker, Bash/Zsh and PowerShell terminal hooks, local file watcher, and VS Code extension halting disproven operations before code reaches production.

---

## One-Click Start (Windows & macOS / Linux)

### On Windows (`start.bat`)
Double-click **`start.bat`** in File Explorer, or run from PowerShell / Command Prompt:
```bat
.\start.bat
```
What `start.bat` does automatically:
1. Creates `.env` from `.env.example` if not present.
2. Starts the Local Hindsight Server on `http://127.0.0.1:8888`.
3. Starts the Meredian FastAPI backend + Web Dashboard on `http://127.0.0.1:8000`.
4. Opens `http://127.0.0.1:8000` in your default browser.

### On macOS / Linux (`start.sh`)
```bash
chmod +x start.sh
./start.sh
```

---

## Running Verification, Eval & Stage Demo Scripts

### On macOS / Linux (`tasks.sh`)
```bash
./tasks.sh smoke   # 1. Hindsight local smoke test (recall < 1ms)
./tasks.sh eval    # 2. Action Checker 15-case evaluation (100% accuracy)
./tasks.sh demo    # 3. 4-Stage Follow-the-Sun Learning Curve demo
./tasks.sh test    # 4. Full Pytest suite
```

### On Windows (`tasks.ps1`)
```powershell
.\tasks.ps1 smoke  # 1. Hindsight local smoke test
.\tasks.ps1 eval   # 2. Action Checker 15-case evaluation
.\tasks.ps1 demo   # 3. 4-Stage Follow-the-Sun Learning Curve demo
.\tasks.ps1 test   # 4. Full Pytest suite
```

---

## Onboarding Your Own Product / Incident

You can connect your own application or incident to Meredian in seconds:
1. **1-Click Web Dashboard**: Click the **`+ Onboard`** button next to the active bank selector at `http://127.0.0.1:8000`.
2. **REST API**: Call `POST /incidents` with product name, severity, and initial symptoms.
3. **Full Runbook**: See [docs/onboarding_your_product.md](docs/onboarding_your_product.md).

---

## Interceptors (VS Code, GitHub PR, Terminal Hook & File Watcher)

- **GitHub PR / CI/CD Action (`.github/workflows/meredian-check.yml`)**:
  Automatically blocks pull requests repeating known dead ends and posts the prior shift evidence and recommended fix directly as a PR review comment.
  ```bash
  python scripts/github_pr_checker.py --file config/redis.yml --action "Raise REDIS_TIMEOUT 200ms -> 1000ms" --pr 42
  ```
- **Bash/Zsh Terminal Hook (`interceptor/terminal-hook/meredian-hook.sh`)**:
  ```bash
  source interceptor/terminal-hook/meredian-hook.sh
  meredian_exec "redis-cli CONFIG SET timeout 800"
  ```
- **PowerShell Terminal Hook (`interceptor/terminal-hook/meredian-hook.ps1`)**:
  ```powershell
  . .\interceptor\terminal-hook\meredian-hook.ps1
  Invoke-MeredianCommand "redis-cli CONFIG SET timeout 800"
  ```
- **Python File Watcher (`interceptor/watcher/file_watcher.py`)**:
  ```bash
  python interceptor/watcher/file_watcher.py --watch-dir .
  ```
- **VS Code Extension (`interceptor/vscode-extension/`)**:
  Open `interceptor/vscode-extension` in VS Code and press `F5` (Run Extension) to intercept file saves with the *View evidence / Override / Mark as different* popup.
