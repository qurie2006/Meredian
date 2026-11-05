# Meredian — Follow-the-Sun Engineering Memory

**Meredian** watches what each engineering shift tries, remembers what failed and why in **Hindsight**, and stops the next shift from repeating a dead end.

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

```powershell
# 1. Phase 1 Hindsight Smoke Test (retain -> recall -> reflect + async operation status)
.\tasks.ps1 smoke

# 2. Phase 4 Action Checker Evaluation (15 labelled repeat / related / new actions)
.\tasks.ps1 eval

# 3. Full 4-Stage Learning Curve Walkthrough (Day 1 Baseline -> Day 2 Interception -> Override -> Day 5 Root Cause)
.\tasks.ps1 demo

# 4. Run Full Pytest Suite
.\tasks.ps1 test
```

## Interceptors (VS Code, Terminal Hook & File Watcher)

- **PowerShell Terminal Hook (`interceptor/terminal-hook/meredian-hook.ps1`)**:
  ```powershell
  . .\interceptor\terminal-hook\meredian-hook.ps1
  Invoke-MeredianCommand "redis-cli CONFIG SET timeout 800"
  ```
- **Bash/Zsh Terminal Hook (`interceptor/terminal-hook/meredian-hook.sh`)**:
  ```bash
  source interceptor/terminal-hook/meredian-hook.sh
  meredian_exec "redis-cli CONFIG SET timeout 800"
  ```
- **Python File Watcher (`interceptor/watcher/file_watcher.py`)**:
  ```powershell
  python interceptor/watcher/file_watcher.py --watch-dir .
  ```
- **VS Code Extension (`interceptor/vscode-extension/`)**:
  Open `interceptor/vscode-extension` in VS Code and press `F5` (Run Extension) to intercept file saves with the *View evidence / Override / Mark as different* popup.
