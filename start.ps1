# ETF Surge 启动脚本
#  无参数 / -Local  -> 本地开发:后端 uvicorn --reload + 前端 npm run dev
#  -Docker          -> docker compose up -d --build
#  -NoOpen          -> 不自动打开浏览器
param(
    [switch]$Local,
    [switch]$Docker,
    [switch]$NoOpen
)

# ─────────── 本地开发模式 ───────────
if ($Local -or -not $Docker) {
    Write-Host "=== ETF Surge 启动(本地) ===" -ForegroundColor Cyan

    Write-Host "[1] 启动后端 (:8000) ..." -ForegroundColor Yellow
    $r = wmic process call create "cmd /c $PSScriptRoot\run_backend.bat" 2>$null
    if ($r -match "ReturnValue = 0") { Write-Host "  后端 OK" -ForegroundColor Green }
    else { Write-Host "  后端启动失败!" -ForegroundColor Red; exit 1 }

    Start-Sleep 3

    Write-Host "[2] 启动前端 (:5173) ..." -ForegroundColor Yellow
    Start-Process cmd -ArgumentList "/c", "cd /d $PSScriptRoot\frontend && npm run dev"

    Start-Sleep 2

    Write-Host "`n=== 已就绪 ===" -ForegroundColor Cyan
    Write-Host "  前端: http://localhost:5173  (热更新)" -ForegroundColor Green
    Write-Host "  后端: http://localhost:8000" -ForegroundColor Green
    Write-Host "  文档: http://localhost:8000/docs" -ForegroundColor Green
    if (-not $NoOpen) { Start-Process http://localhost:5173 }
    return
}

# ─────────── Docker 部署 ───────────
if ($Docker) {
    Write-Host "=== ETF Surge 启动(Docker) ===" -ForegroundColor Cyan
    Push-Location $PSScriptRoot
    try {
        docker compose up -d --build
        Write-Host "`n=== 已就绪 ===" -ForegroundColor Cyan
        Write-Host "  前端: http://localhost" -ForegroundColor Green
    } finally { Pop-Location }
    if (-not $NoOpen) { Start-Process http://localhost }
}
