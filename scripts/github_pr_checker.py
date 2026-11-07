#!/usr/bin/env python3
"""
Meredian GitHub PR & CI/CD Action Checker
Prevents engineering shifts from merging PRs that repeat ruled-out dead ends.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

API_DEFAULT = os.getenv("MEREDIAN_API_URL", "http://127.0.0.1:8000")


def generate_markdown_summary(verdict: dict[str, Any], file_path: str, action: str, pr_num: str) -> str:
    policy = verdict.get("policy_action", "silent")
    v_type = verdict.get("verdict", "new")
    conf = int(verdict.get("confidence", 0) * 100)
    latency = verdict.get("latency_ms", 35)

    if policy == "interrupt":
        badge = "**[BLOCKED] REPEAT DEAD END DETECTED**"
        color = "#ff2a36"
    elif policy == "soft_warning":
        badge = "**[CAUTION] SIMILAR PRIOR ATTEMPT**"
        color = "#ffb020"
    else:
        badge = "**[PASSED] NOVEL HYPOTHESIS**"
        color = "#00e676"

    lines = [
        f"## Meredian Institutional Memory Check #{pr_num}",
        f"{badge} · Conf: `{conf}%` · Latency: `{latency}ms`",
        "",
        f"**Proposed Change in PR:** `{action}`",
        f"**Target File:** `{file_path}`",
        "",
    ]

    if policy in ("interrupt", "soft_warning"):
        lines.extend([
            "### Prior Shift Evidence:",
            f"- **Prior Tested Action:** {verdict.get('what_was_tried')}",
            f"- **Tested By:** {verdict.get('who', 'Engineering Shift')} ({verdict.get('site', 'Global')}) at {verdict.get('when', 'earlier shift')}",
            f"- **Telemetry Citations:** `{(', '.join(verdict.get('evidence') or [])) or 'commit/log records'}`",
            f"- **Empirical Outcome:** {verdict.get('outcome', 'Failed to resolve outage.')}",
            "",
            "### Recommended Trajectory from Hindsight:",
            f"> {verdict.get('suggested_next', 'Investigate alternative subsystem suspects.')}",
            "",
            "---",
            "*To override this block if you are testing under distinct runtime conditions, add the PR label `meredian:override` with your rationale.*",
        ])
    else:
        lines.extend([
            "No prior matching dead ends found in active Hindsight memory bank.",
            "Outcome of this change will be automatically indexed into Hindsight upon merge.",
        ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Meredian GitHub PR Interceptor")
    parser.add_argument("--api-url", default=API_DEFAULT, help="Meredian API base URL")
    parser.add_argument("--incident", default="payments-memleak", help="Active incident ID")
    parser.add_argument("--file", default="config/redis.yml", help="Changed file path")
    parser.add_argument("--action", required=True, help="Code diff or parameter change")
    parser.add_argument("--pr", default="101", help="PR number")
    parser.add_argument("--actor", default="github-actions[bot]", help="Author name")
    parser.add_argument("--output-md", default=None, help="File to write markdown comment to")

    args = parser.parse_args()

    payload = {
        "incident_id": args.incident,
        "actor": args.actor,
        "site": "CI/CD",
        "source": "terminal",
        "file_path": args.file,
        "diff_or_command": args.action,
        "memory_enabled": True,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{args.api_url}/check", json=payload)
            if resp.status_code != 200:
                print(f"[Meredian CI] Error calling API: {resp.text}", file=sys.stderr)
                return 0
            verdict = resp.json()
    except Exception as exc:
        print(f"[Meredian CI] Could not connect to Meredian API at {args.api_url}: {exc}", file=sys.stderr)
        return 0

    md = generate_markdown_summary(verdict, args.file, args.action, args.pr)

    if args.output_md:
        Path(args.output_md).write_text(md, encoding="utf-8")

    github_step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if github_step_summary:
        try:
            with open(github_step_summary, "a", encoding="utf-8") as f:
                f.write(md + "\n\n")
        except Exception:
            pass

    policy = verdict.get("policy_action")
    print(f"\n=======================================================")
    print(f" MEREDIAN CI MEMORY CHECK: {verdict.get('verdict', '').upper()} ({policy})")
    print(f"=======================================================")
    print(f"Action: {args.action}")
    print(f"Latency: {verdict.get('latency_ms', 0)}ms")

    if policy == "interrupt":
        print(f"\n[FAIL] PR BLOCKED! Prior shift already tried this dead end.")
        print(f"Evidence: {verdict.get('what_was_tried')}")
        print(f"Outcome: {verdict.get('outcome')}")
        print(f"Recommended Next: {verdict.get('suggested_next')}\n")
        return 1
    elif policy == "soft_warning":
        print(f"\n[WARN] PR flagged with conditional nuance. Review evidence.\n")
        return 0
    else:
        print(f"\n[PASS] No repeat dead ends detected. Clear to merge.\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())

