param(
    [Parameter(Position = 0)]
    [ValidateSet("dev", "test", "smoke", "eval", "demo", "hindsight-server")]
    [string]$Task = "demo"
)

$env:PYTHONPATH = "."

switch ($Task) {
    "smoke" {
        python scripts/hindsight_smoke.py
    }
    "eval" {
        python scripts/eval_checker.py
    }
    "test" {
        python -m pytest -v
    }
    "demo" {
        python scripts/demo_walkthrough.py
    }
    "hindsight-server" {
        python scripts/hindsight_local_server.py
    }
    "dev" {
        python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
    }
}

