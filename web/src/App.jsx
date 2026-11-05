import React, { useState, useEffect } from "react";

const API_BASE = window.MEREDIAN_API_BASE || "http://127.0.0.1:8000";

export default function App() {
  const [activeTab, setActiveTab] = useState("overview");
  const [incidentId, setIncidentId] = useState("payments-memleak");
  const [overview, setOverview] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [briefing, setBriefing] = useState(null);
  const [interceptions, setInterceptions] = useState(null);
  const [explorer, setExplorer] = useState(null);
  const [bandFeed, setBandFeed] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [compareAction, setCompareAction] = useState("REDIS_TIMEOUT: 200ms -> 800ms in config/redis.yml");
  const [compareFile, setCompareFile] = useState("config/redis.yml");
  const [compareConditions, setCompareConditions] = useState("");
  const [compareResult, setCompareResult] = useState(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [statusBanner, setStatusBanner] = useState("");

  async function refreshAll(inc = incidentId) {
    try {
      const [ovRes, tlRes, brRes, intRes, exRes, bdRes] = await Promise.all([
        fetch(`${API_BASE}/overview?incident_id=${inc}`).then((r) => r.json()),
        fetch(`${API_BASE}/timeline/${inc}`).then((r) => r.json()),
        fetch(`${API_BASE}/briefing/${inc}`).then((r) => r.json()),
        fetch(`${API_BASE}/interceptions?incident_id=${inc}`).then((r) => r.json()),
        fetch(`${API_BASE}/explorer/${inc}?q=${encodeURIComponent(searchQuery)}`).then((r) => r.json()),
        fetch(`${API_BASE}/band/messages?incident_id=${inc}`).then((r) => r.json()),
      ]);
      setOverview(ovRes);
      setTimeline(tlRes);
      setBriefing(brRes);
      setInterceptions(intRes);
      setExplorer(exRes);
      setBandFeed(bdRes.messages || []);
    } catch (err) {
      console.error("Failed to fetch Meredian state:", err);
    }
  }

  useEffect(() => {
    refreshAll(incidentId);
  }, [incidentId]);

  async function handleReplay(day) {
    setStatusBanner(`Replaying ${incidentId} up to Day ${day}...`);
    await fetch(`${API_BASE}/replay/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ incident_id: incidentId, up_to_day: day, reset_first: true }),
    });
    await refreshAll(incidentId);
    setStatusBanner(day === 0 ? "Reset to Day 1 Baseline (Empty Bank)" : `Loaded Day ${day} shift memory`);
  }

  async function handleToggleMemory() {
    if (!overview) return;
    const nextState = !overview.memory_enabled;
    await fetch(`${API_BASE}/memory/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ memory_enabled: nextState }),
    });
    await refreshAll(incidentId);
  }

  async function handleRunCheck(livePost = true) {
    const endpoint = livePost ? "/check" : "/check/compare";
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        incident_id: incidentId,
        actor: "Aarav",
        site: "Bengaluru",
        source: "web",
        file_path: compareFile || null,
        diff_or_command: compareAction,
        conditions: compareConditions || null,
      }),
    }).then((r) => r.json());

    if (livePost) {
      const cmp = await fetch(`${API_BASE}/check/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          incident_id: incidentId,
          actor: "Aarav",
          site: "Bengaluru",
          source: "web",
          file_path: compareFile || null,
          diff_or_command: compareAction,
          conditions: compareConditions || null,
        }),
      }).then((r) => r.json());
      cmp.with_memory.interception_id = res.interception_id;
      setCompareResult(cmp);
    } else {
      setCompareResult(res);
    }
    await refreshAll(incidentId);
  }

  async function handleOverride(interceptionId, priorAttemptId) {
    if (!overrideReason.trim()) return;
    await fetch(`${API_BASE}/override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        incident_id: incidentId,
        interception_id: interceptionId,
        prior_attempt_id: priorAttemptId,
        actor: "Aarav",
        site: "Bengaluru",
        proposed_action: compareAction,
        reason: overrideReason,
        new_conditions: overrideReason,
        files_components: compareFile ? [compareFile] : ["config/redis.yml"],
      }),
    });
    setOverrideReason("");
    setStatusBanner("Override retained in Hindsight as a linked retry_of attempt!");
    await refreshAll(incidentId);
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <header className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Meredian <span className="text-indigo-400 text-base font-normal">| Follow-the-Sun Engineering Memory</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Powered by Hindsight (retain · recall · reflect · observations) + Band Coordination
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleToggleMemory}
            className={`px-3 py-1.5 rounded text-xs font-semibold border ${
              overview?.memory_enabled
                ? "bg-emerald-900/50 border-emerald-500 text-emerald-300"
                : "bg-rose-900/50 border-rose-500 text-rose-300"
            }`}
          >
            Memory: {overview?.memory_enabled ? "ON" : "OFF"}
          </button>
        </div>
      </header>
      {statusBanner && (
        <div className="max-w-7xl mx-auto mb-4 px-4 py-2 rounded bg-indigo-950/70 border border-indigo-700 text-indigo-200 text-xs">
          {statusBanner}
        </div>
      )}
    </div>
  );
}

