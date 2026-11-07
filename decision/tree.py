from __future__ import annotations

import re
from typing import Any, Optional

from attempts.schemas import Attempt, Briefing


def _detect_subsystem(file_or_action: str) -> str:
    lower = file_or_action.lower()
    if "redis" in lower or "sentinel" in lower or "cache" in lower and "session" not in lower:
        return "Redis Client & Transport"
    if "auth" in lower or "jwt" in lower or "token" in lower or "session" in lower or "jwks" in lower:
        return "Authentication & Session Middleware"
    if "gc" in lower or "worker" in lower or "memory" in lower or "sweep" in lower:
        return "Worker Lifecycle & Memory Management"
    if "db" in lower or "postgres" in lower or "sql" in lower or "pool" in lower:
        return "Database & Transaction Pool"
    if "network" in lower or "envoy" in lower or "proxy" in lower or "ingress" in lower:
        return "Network & Ingress Routing"
    return "Application Core Services"


class HypothesisTreeBuilder:

    def build_tree(
        self,
        incident_id: str,
        attempts: list[Attempt],
        briefing: Briefing,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        title = meta.get("title", incident_id)
        severity = meta.get("severity", "SEV-2")
        service = meta.get("service", "core")

        root_node = {
            "id": f"root-{incident_id}",
            "type": "root",
            "label": f"{severity} · {title}",
            "subtitle": f"Active Service: {service} · Institutional Memory Tree",
            "status": "confirmed_fix" if any(a.outcome == "worked" for a in attempts) else "active",
            "stat_summary": f"{len(attempts)} attempts evaluated across shifts",
        }

        subsystem_map: dict[str, list[dict[str, Any]]] = {}

        for att in attempts:
            comp_str = " ".join(att.files_components) + " " + att.action + " " + att.hypothesis
            subsys = _detect_subsystem(comp_str)
            if subsys not in subsystem_map:
                subsystem_map[subsys] = []

            is_leading = (
                briefing.leading_suspect
                and (
                    att.id in briefing.leading_suspect
                    or any(c.lower() in briefing.leading_suspect.lower() for c in att.files_components)
                )
            )

            if att.outcome == "worked":
                node_status = "confirmed_fix"
            elif att.outcome == "failed":
                node_status = "ruled_out"
            elif is_leading:
                node_status = "leading_suspect"
            else:
                node_status = "under_investigation"

            hyp_node = {
                "id": att.id,
                "type": "hypothesis",
                "label": att.action or att.hypothesis,
                "hypothesis": att.hypothesis,
                "subsystem": subsys,
                "status": node_status,
                "who": att.who,
                "site": att.site,
                "timestamp_utc": att.timestamp_utc,
                "evidence": att.evidence_refs,
                "outcome_description": att.reason or att.conclusion or "Empirical trial outcome recorded.",
                "retry_of": att.retry_of,
                "conditions": att.conditions,
            }
            subsystem_map[subsys].append(hyp_node)

        # If briefing has a leading suspect not yet captured in worked attempts, add it as an unexplored node
        has_worked = any(a.outcome == "worked" for a in attempts)
        if briefing.leading_suspect and not has_worked:
            lead_subsys = _detect_subsystem(briefing.leading_suspect)
            lead_node = {
                "id": f"hyp-leading-{incident_id}",
                "type": "hypothesis",
                "label": briefing.leading_suspect,
                "hypothesis": f"Investigate {briefing.leading_suspect}",
                "subsystem": lead_subsys,
                "status": "leading_suspect",
                "who": "Hindsight Reflect",
                "site": "Global",
                "timestamp_utc": briefing.generated_at_utc,
                "evidence": ["hindsight-consolidated-belief"],
                "outcome_description": briefing.recommended_first_step or "Recommended primary path.",
                "retry_of": None,
                "conditions": "Prior dead ends ruled out upstream cause",
            }
            if lead_subsys not in subsystem_map:
                subsystem_map[lead_subsys] = []
            subsystem_map[lead_subsys].append(lead_node)

        nodes: list[dict[str, Any]] = [root_node]
        edges: list[dict[str, str]] = []

        for idx, (subsys_name, hyp_nodes) in enumerate(subsystem_map.items()):
            subsys_id = f"subsys-{incident_id}-{idx}"
            all_ruled_out = all(h["status"] == "ruled_out" for h in hyp_nodes)
            has_fix = any(h["status"] == "confirmed_fix" for h in hyp_nodes)
            has_lead = any(h["status"] == "leading_suspect" for h in hyp_nodes)

            if has_fix:
                subsys_status = "confirmed_fix"
            elif has_lead:
                subsys_status = "leading_suspect"
            elif all_ruled_out:
                subsys_status = "ruled_out"
            else:
                subsys_status = "active"

            nodes.append({
                "id": subsys_id,
                "parent_id": root_node["id"],
                "type": "subsystem",
                "label": subsys_name,
                "subtitle": f"{len(hyp_nodes)} trial(s) documented",
                "status": subsys_status,
            })
            edges.append({"from": root_node["id"], "to": subsys_id})

            for hyp in hyp_nodes:
                hyp["parent_id"] = subsys_id
                nodes.append(hyp)
                edges.append({"from": subsys_id, "to": hyp["id"]})

        return {
            "incident_id": incident_id,
            "title": title,
            "severity": severity,
            "nodes": nodes,
            "edges": edges,
            "counts": {
                "total_hypotheses": sum(len(h) for h in subsystem_map.values()),
                "ruled_out": sum(1 for n in nodes if n.get("status") == "ruled_out"),
                "confirmed_fix": sum(1 for n in nodes if n.get("status") == "confirmed_fix"),
                "leading_suspect": sum(1 for n in nodes if n.get("status") == "leading_suspect"),
            },
        }

