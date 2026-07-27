# ETF Surge Diagnostics - Run everything in one session
param([switch]$NoFrontend)

Write-Host "=== ETF Surge Diagnostics ===" -ForegroundColor Cyan

# Step 1: Kill any existing Python processes on port 8000
Write-Host "[1] Cleaning up..." -ForegroundColor Yellow
Get-Process -Name "python*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# Step 2: Start backend with profiling
Write-Host "[2] Starting backend with PROFILE_WARMUP=1..." -ForegroundColor Yellow
$env:PROFILE_WARMUP = "1"
$proc = Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" -WorkingDirectory "E:\ETF_Surge\backend" -PassThru
Start-Sleep -Seconds 2

# Start frontend if needed
if (-not $NoFrontend) {
    Write-Host "[2b] Starting frontend..." -ForegroundColor Yellow
    Start-Process -NoNewWindow -FilePath "cmd.exe" -ArgumentList "/c", "cd /d E:\ETF_Surge\frontend && npm run dev"
    Start-Sleep -Seconds 3
}

# Step 3: Wait for backend to be ready
Write-Host "[3] Waiting for backend to be ready..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 3 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $ready = $true
            Write-Host "  Backend ready after $($i) seconds!" -ForegroundColor Green
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    Write-Host "[FAIL] Backend not ready after 120s" -ForegroundColor Red
    return
}

# Step 4: Trigger portfolio design
Write-Host "[4] Triggering portfolio design (balanced, 500k)..." -ForegroundColor Yellow
$body = @{risk_profile="balanced"; capital=500000; market="A"} | ConvertTo-Json -Compress
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/portfolio/design-async" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 180
    $result = $resp.Content | ConvertFrom-Json
    $taskId = $result.task_id
    Write-Host "  Design task $taskId created" -ForegroundColor Green
} catch {
    Write-Host "  Design trigger failed: $_" -ForegroundColor Red
    $taskId = $null
}

# Step 5: Trigger strategy check
Write-Host "[5] Triggering strategy check..." -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/portfolio/strategy-check-async" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 180
    $result = $resp.Content | ConvertFrom-Json
    $taskId2 = $result.task_id
    Write-Host "  Strategy check task $taskId2 created" -ForegroundColor Green
} catch {
    Write-Host "  Strategy check trigger failed: $_" -ForegroundColor Red
    $taskId2 = $null
}

# Step 6: Poll design task
if ($taskId) {
    Write-Host "[6] Polling design task $taskId..." -ForegroundColor Yellow
    for ($i = 0; $i -lt 120; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/portfolio/tasks/$taskId" -TimeoutSec 5
            $task = $resp.Content | ConvertFrom-Json
            $status = $task.status
            $progress = $task.progress
            $stage = $task.stage
            Write-Host "  Task $taskId: $status [$progress%] $stage"
            if ($status -eq "completed" -or $status -eq "failed") { break }
        } catch {
            Write-Host "  Poll error: $_"
        }
        Start-Sleep -Seconds 5
    }
}

# Step 7: Poll strategy check task
if ($taskId2) {
    Write-Host "[7] Polling strategy check task $taskId2..." -ForegroundColor Yellow
    for ($i = 0; $i -lt 120; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/portfolio/tasks/$taskId2" -TimeoutSec 5
            $task = $resp.Content | ConvertFrom-Json
            $status = $task.status
            $progress = $task.progress
            $stage = $task.stage
            Write-Host "  Task $taskId2: $status [$progress%] $stage"
            if ($status -eq "completed" -or $status -eq "failed") { break }
        } catch {
            Write-Host "  Poll error: $_"
        }
        Start-Sleep -Seconds 5
    }
}

# Step 8: Get design details
Write-Host "[8] Getting design details..." -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/portfolio/designs" -TimeoutSec 10
    $designs = $resp.Content | ConvertFrom-Json
    if ($designs.Count -gt 0) {
        $latestId = $designs[0].id
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/portfolio/designs/$latestId" -TimeoutSec 30
        $resp.Content | Out-File -FilePath "E:\ETF_Surge\backend\data\latest_design.json" -Encoding utf8
        Write-Host "  Design saved to data/latest_design.json" -ForegroundColor Green
    }
} catch {
    Write-Host "  Could not get design details: $_" -ForegroundColor Red
}

# Step 9: Strategy check result details
Write-Host "[9] Getting strategy check details..." -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/portfolio/strategy-checks" -TimeoutSec 10
    $checks = $resp.Content | ConvertFrom-Json
    if ($checks.Count -gt 0) {
        $latestCheckId = $checks[0].id
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/portfolio/strategy-checks/$latestCheckId" -TimeoutSec 30
        $resp.Content | Out-File -FilePath "E:\ETF_Surge\backend\data\latest_strategy_check.json" -Encoding utf8
        Write-Host "  Strategy check saved to data/latest_strategy_check.json" -ForegroundColor Green
    }
} catch {
    Write-Host "  Could not get strategy check details: $_" -ForegroundColor Red
}

# Step 10: Run perf_diag
Write-Host "[10] Running perf_diag..." -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/admin/sources/health" -TimeoutSec 10
    Write-Host "  Source health check OK"
} catch {}

Write-Host "=== Diagnostics Complete ===" -ForegroundColor Cyan
Write-Host "Results saved to: E:\ETF_Surge\backend\data\" -ForegroundColor Green
