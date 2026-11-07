from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

TRACKED_SUFFIXES = {".yml", ".yaml", ".py", ".json", ".toml", ".conf"}


def notify_desktop(title: str, message: str) -> None:
    print("\n" + "=" * 76)
    print(f"[ALERT] {title}")
    print("-" * 76)
    print(message)
    print("=" * 76 + "\n")
    if sys.platform == "win32":
        ps_script = (
            "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null; "
            "$n = New-Object System.Windows.Forms.NotifyIcon; "
            "$n.Icon = [System.Drawing.SystemIcons]::Warning; "
            "$n.Visible = $true; "
            f"$n.ShowBalloonTip(5000, '{title.replace(chr(39), '')}', '{message[:180].replace(chr(39), '')}', "
            "[System.Windows.Forms.ToolTipIcon]::Warning)"
        )
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def check_file_change(
    api_url: str,
    file_path: str,
    content_snippet: str,
    incident_id: str = "payments-memleak",
    actor: str = "Aarav",
    site: str = "Bengaluru",
) -> dict:
    payload = {
        "incident_id": incident_id,
        "actor": actor,
        "site": site,
        "source": "watcher",
        "file_path": file_path,
        "diff_or_command": content_snippet,
    }
    with httpx.Client(timeout=5.0) as client:
        resp = client.post(f"{api_url.rstrip('/')}/check", json=payload)
        resp.raise_for_status()
        verdict = resp.json()

    if verdict.get("policy_action") in ("interrupt", "soft_warning"):
        header = (
            "STOP: Repeat Dead End Detected"
            if verdict["policy_action"] == "interrupt"
            else "HEADS UP: Related Attempt Under Different Conditions"
        )
        evidence_str = ", ".join(verdict.get("evidence", []))
        msg = (
            f"File: {file_path}\n"
            f"Verdict: {verdict['verdict'].upper()} (confidence {verdict['confidence']:.0%})\n"
            f"Prior Attempt: {verdict.get('who')} ({verdict.get('site')}) at {verdict.get('when')}\n"
            f"What was tried: {verdict.get('what_was_tried')}\n"
            f"Evidence: {evidence_str}\n"
            f"Suggested Next Step: {verdict.get('suggested_next')}"
        )
        notify_desktop(header, msg)
    return verdict


def watch_directory(
    watch_dir: Path,
    api_url: str,
    incident_id: str,
    actor: str,
    site: str,
    poll_interval: float = 1.0,
) -> None:
    print(f"[Meredian Watcher] Watching `{watch_dir.resolve()}` -> {api_url} (incident={incident_id})")
    mtimes: dict[Path, float] = {}
    for p in watch_dir.rglob("*"):
        if p.is_file() and p.suffix in TRACKED_SUFFIXES:
            mtimes[p] = p.stat().st_mtime

    try:
        while True:
            time.sleep(poll_interval)
            for p in watch_dir.rglob("*"):
                if not p.is_file() or p.suffix not in TRACKED_SUFFIXES:
                    continue
                mtime = p.stat().st_mtime
                if p not in mtimes or mtime > mtimes[p]:
                    mtimes[p] = mtime
                    rel = p.relative_to(watch_dir).as_posix()
                    snippet = p.read_text(encoding="utf-8", errors="ignore")[:800]
                    check_file_change(
                        api_url=api_url,
                        file_path=rel,
                        content_snippet=snippet,
                        incident_id=incident_id,
                        actor=actor,
                        site=site,
                    )
    except KeyboardInterrupt:
        print("\n[Meredian Watcher] Stopped.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Meredian file watcher interceptor")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--incident", default="payments-memleak")
    parser.add_argument("--actor", default="Aarav")
    parser.add_argument("--site", default="Bengaluru")
    parser.add_argument("--watch-dir", default=".")
    parser.add_argument("--check-file", help="Run a one-shot check for a file path")
    parser.add_argument("--diff", default="REDIS_TIMEOUT: 200ms -> 800ms", help="Diff snippet for one-shot check")
    args = parser.parse_args(argv)

    if args.check_file:
        verdict = check_file_change(
            api_url=args.api_url,
            file_path=args.check_file,
            content_snippet=args.diff,
            incident_id=args.incident,
            actor=args.actor,
            site=args.site,
        )
        print(f"Verdict: {verdict['verdict']} | Policy: {verdict['policy_action']}")
        return 0

    watch_directory(
        watch_dir=Path(args.watch_dir),
        api_url=args.api_url,
        incident_id=args.incident,
        actor=args.actor,
        site=args.site,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

