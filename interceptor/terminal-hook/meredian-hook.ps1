<#
.SYNOPSIS
Meredian PowerShell Terminal Hook Interceptor.
Wraps selected commands (such as `redis-cli CONFIG SET timeout 800`) to query Meredian's
`POST /check` endpoint before execution.

.EXAMPLE
. .\interceptor\terminal-hook\meredian-hook.ps1
Invoke-MeredianCommand "redis-cli CONFIG SET timeout 800" -NonInteractive
#>

function Invoke-MeredianCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandText,
        [string]$ApiUrl = "http://127.0.0.1:8000",
        [string]$IncidentId = "payments-memleak",
        [string]$Actor = "Aarav",
        [string]$Site = "Bengaluru",
        [string]$Conditions = "",
        [switch]$NonInteractive
    )

    $bodyObj = @{
        incident_id     = $IncidentId
        actor           = $Actor
        site            = $Site
        source          = "terminal"
        diff_or_command = $CommandText
    }
    if ($Conditions) {
        $bodyObj["conditions"] = $Conditions
    }
    $jsonBody = $bodyObj | ConvertTo-Json -Depth 4

    try {
        $verdict = Invoke-RestMethod -Uri "$ApiUrl/check" -Method Post -ContentType "application/json" -Body $jsonBody -TimeoutSec 5
    }
    catch {
        Write-Warning "[Meredian Hook] API unreachable at $ApiUrl — proceeding without check."
        return $null
    }

    if ($verdict.policy_action -eq "interrupt" -or $verdict.policy_action -eq "soft_warning") {
        $evList = ($verdict.evidence -join ", ")
        Write-Host ""
        Write-Host "==========================================================================" -ForegroundColor Red
        if ($verdict.policy_action -eq "interrupt") {
            Write-Host "  MEREDIAN INTERCEPTOR — STOP: REPEAT DEAD END DETECTED" -ForegroundColor Red
        } else {
            Write-Host "  MEREDIAN INTERCEPTOR — HEADS UP: TRIED UNDER DIFFERENT CONDITIONS" -ForegroundColor Yellow
        }
        Write-Host "==========================================================================" -ForegroundColor Red
        Write-Host "  Command        : $CommandText"
        Write-Host "  Verdict        : $($verdict.verdict.ToUpper()) (Confidence: $([math]::Round($verdict.confidence * 100))%)"
        Write-Host "  Prior Shift    : $($verdict.who) ($($verdict.site)) at $($verdict.when)"
        Write-Host "  What was tried : $($verdict.what_was_tried)"
        Write-Host "  Evidence       : $evList"
        Write-Host "  Suggested Next : $($verdict.suggested_next)"
        Write-Host "==========================================================================" -ForegroundColor Red

        if ($NonInteractive) {
            return $verdict
        }

        $choice = Read-Host "Choose action: [A]bort command (default) | [O]verride ('this time is different')"
        if ($choice -match "^[Oo]") {
            $reason = Read-Host "Why is this time different? (e.g., new Redis 7.4 cluster / 2x load)"
            $overrideBody = @{
                incident_id      = $IncidentId
                interception_id  = $verdict.interception_id
                prior_attempt_id = $verdict.matched_attempt_id
                actor            = $Actor
                site             = $Site
                proposed_action  = $CommandText
                reason           = $reason
                new_conditions   = $reason
            } | ConvertTo-Json -Depth 4
            $ovr = Invoke-RestMethod -Uri "$ApiUrl/override" -Method Post -ContentType "application/json" -Body $overrideBody
            Write-Host "[Meredian] Override retained as linked attempt: $($ovr.retained_attempt.id)" -ForegroundColor Cyan
        } else {
            Write-Host "[Meredian] Command aborted — dead end avoided." -ForegroundColor Green
            return $verdict
        }
    }
    return $verdict
}

