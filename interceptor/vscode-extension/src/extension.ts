import * as vscode from "vscode";

interface VerdictResponse {
  verdict: "repeat" | "related" | "new";
  confidence: number;
  what_was_tried: string;
  outcome: string;
  who: string;
  site: string;
  when: string;
  evidence: string[];
  differences: string;
  suggested_next: string;
  policy_action: "interrupt" | "soft_warning" | "silent";
  matched_attempt_id?: string;
  interception_id?: string;
}

export function activate(context: vscode.ExtensionContext) {
  const outputChannel = vscode.window.createOutputChannel("Meredian Memory");

  const saveDisposable = vscode.workspace.onDidSaveTextDocument(async (doc) => {
    await evaluateDocument(doc, outputChannel);
  });

  const checkCmd = vscode.commands.registerCommand("meredian.checkCurrentFile", async () => {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      await evaluateDocument(editor.document, outputChannel);
    }
  });

  const briefingCmd = vscode.commands.registerCommand("meredian.showBriefing", async () => {
    const cfg = vscode.workspace.getConfiguration("meredian");
    const apiUrl = cfg.get<string>("apiUrl", "http://127.0.0.1:8000");
    const incidentId = cfg.get<string>("incidentId", "payments-memleak");
    try {
      const resp = await fetch(`${apiUrl}/briefing/${incidentId}`);
      const briefing = (await resp.json()) as any;
      outputChannel.clear();
      outputChannel.appendLine(`=== MEREDIAN SHIFT BRIEFING: ${incidentId} (Day ${briefing.day}) ===`);
      outputChannel.appendLine(briefing.headline);
      outputChannel.appendLine(`\nLeading Suspect: ${briefing.leading_suspect}`);
      outputChannel.appendLine(`Recommended First Step: ${briefing.recommended_first_step}`);
      outputChannel.show(true);
    } catch (err) {
      vscode.window.showErrorMessage(`Meredian API error: ${err}`);
    }
  });

  context.subscriptions.push(saveDisposable, checkCmd, briefingCmd);
}

async function evaluateDocument(
  doc: vscode.TextDocument,
  outputChannel: vscode.OutputChannel
): Promise<void> {
  const cfg = vscode.workspace.getConfiguration("meredian");
  const apiUrl = cfg.get<string>("apiUrl", "http://127.0.0.1:8000");
  const incidentId = cfg.get<string>("incidentId", "payments-memleak");
  const actor = cfg.get<string>("actor", "Aarav");
  const site = cfg.get<string>("site", "Bengaluru");

  const relPath = vscode.workspace.asRelativePath(doc.uri, false);
  const textSnippet = doc.getText().slice(0, 1200);

  try {
    const res = await fetch(`${apiUrl}/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        incident_id: incidentId,
        actor,
        site,
        source: "vscode",
        file_path: relPath,
        diff_or_command: textSnippet,
      }),
    });
    if (!res.ok) {
      return;
    }
    const verdict = (await res.json()) as VerdictResponse;
    if (verdict.policy_action === "silent") {
      return;
    }

    const prefix =
      verdict.policy_action === "interrupt"
        ? `STOP (${Math.round(verdict.confidence * 100)}% match): ${verdict.site} (${verdict.who}) already tried this`
        : `Heads up: Tried before under different conditions by ${verdict.who} (${verdict.site})`;

    const message = `${prefix} — ${verdict.what_was_tried}. Suggested next: ${verdict.suggested_next}`;

    const selection = await vscode.window.showWarningMessage(
      message,
      "View evidence",
      "Override",
      "Mark as different"
    );

    if (selection === "View evidence") {
      outputChannel.clear();
      outputChannel.appendLine("=== MEREDIAN EVIDENCE REPORT ===");
      outputChannel.appendLine(`File: ${relPath}`);
      outputChannel.appendLine(`Verdict: ${verdict.verdict.toUpperCase()} (${Math.round(verdict.confidence * 100)}%)`);
      outputChannel.appendLine(`Who / Site / When: ${verdict.who} (${verdict.site}) @ ${verdict.when}`);
      outputChannel.appendLine(`What was tried: ${verdict.what_was_tried}`);
      outputChannel.appendLine(`Evidence Refs: ${verdict.evidence.join(", ")}`);
      outputChannel.appendLine(`Differences: ${verdict.differences}`);
      outputChannel.appendLine(`Suggested Next Step: ${verdict.suggested_next}`);
      outputChannel.show(true);
    } else if (selection === "Override" || selection === "Mark as different") {
      const reason = await vscode.window.showInputBox({
        prompt: "Explain why this attempt is different (e.g. new load level, new Redis version, HPA enabled)",
        placeHolder: "Testing under Redis 7.4 cluster with Envoy multiplexing...",
      });
      if (reason) {
        await fetch(`${apiUrl}/override`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            incident_id: incidentId,
            interception_id: verdict.interception_id,
            prior_attempt_id: verdict.matched_attempt_id,
            actor,
            site,
            proposed_action: `Modified ${relPath}`,
            reason,
            new_conditions: reason,
            files_components: [relPath],
          }),
        });
        vscode.window.showInformationMessage(
          "Meredian: Override retained in Hindsight as a linked retry_of attempt."
        );
      }
    }
  } catch {
  }
}

export function deactivate() {}

