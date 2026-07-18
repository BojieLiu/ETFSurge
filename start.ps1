# ETF Surge 启动脚本
#  无参数 / -Local  -> 本地开发:后端 uvicorn --reload + 前端 npm run dev
#  -Docker          -> docker compose up -d --build
#  -NoOpen          -> 不自动打开浏览器
#  -Silent          -> 静默启动:后端/前端窗口隐藏或最小化,启动器自身不保留窗口
param(
    [switch]$Local,
    [switch]$Docker,
    [switch]$NoOpen,
    [switch]$Silent
)

# 修复中文乱码：强制 PowerShell 以 UTF-8 读取/输出（配合 start.bat 的 chcp 65001）
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# ─────────── 本地开发模式 ───────────
if ($Local -or -not $Docker) {
    Write-Host "=== ETF Surge 启动(本地) ===" -ForegroundColor Cyan

    Write-Host "[1] 启动后端 (:8000) ..." -ForegroundColor Yellow
    if ($Silent) {
        # 静默:后台隐藏启动 uvicorn,不弹出可见窗口
        # 注意:不能用 RedirectStandardOutput/Error,否则父进程会等待子进程 stdout 关闭而挂起
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c","cd /d $PSScriptRoot\backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" -WindowStyle Hidden
        Write-Host "  后端已后台启动" -ForegroundColor Green
    } else {
        # 普通:新建可见窗口运行 run_backend.bat
        $r = wmic process call create "cmd /c $PSScriptRoot\run_backend.bat" 2>$null
        if ($r -match "ReturnValue = 0") { Write-Host "  后端 OK" -ForegroundColor Green }
        else { Write-Host "  后端启动失败!" -ForegroundColor Red; exit 1 }
    }

    Start-Sleep 3

    Write-Host "[2] 启动前端 (:5173) ..." -ForegroundColor Yellow
    if ($Silent) {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c","cd /d $PSScriptRoot\frontend && npm run dev" -WindowStyle Minimized
        Write-Host "  前端已后台启动" -ForegroundColor Green
    } else {
        Start-Process cmd -ArgumentList "/c", "cd /d $PSScriptRoot\frontend && npm run dev"
    }

    Start-Sleep 2

    Write-Host "`n=== 已就绪 ===" -ForegroundColor Cyan
    Write-Host "  前端: http://localhost:5173  (热更新)" -ForegroundColor Green
    Write-Host "  后端: http://localhost:8000" -ForegroundColor Green
    Write-Host "  文档: http://localhost:8000/docs" -ForegroundColor Green
    if (-not $NoOpen) { Start-Process http://localhost:5173 }
    if ($Silent) { return }
    return
}

# ─────────── Docker 部署 ───────────
if ($Docker) {
    Write-Host "=== ETF Surge 启动(Docker) ===" -ForegroundColor Cyan
    Push-Location $PSScriptRoot
    try {
        if ($Silent) { docker compose up -d --build } else { docker compose up -d --build }
        Write-Host "`n=== 已就绪 ===" -ForegroundColor Cyan
        Write-Host "  前端: http://localhost" -ForegroundColor Green
    } finally { Pop-Location }
    if (-not $NoOpen) { Start-Process http://localhost }
    if ($Silent) { return }
}