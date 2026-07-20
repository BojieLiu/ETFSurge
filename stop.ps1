# ETF Surge 停止服务脚本
$ErrorActionPreference = "SilentlyContinue"

function Stop-ByPort {
    param([int]$Port, [string]$Label)
    $pids = @()
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) { $pids += $c.OwningProcess }
    } catch {}
    $pids = $pids | Sort-Object -Unique
    if ($pids.Count -eq 0) {
        Write-Host "  $Label (: $Port) 未运行" -ForegroundColor DarkGray
        return
    }
    foreach ($p in $pids) {
        taskkill /F /T /PID $p 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Host "  已停止 $Label (PID=$p 及子进程)" -ForegroundColor Green }
        else { Write-Host "  未能停止 $Label (PID=$p)" -ForegroundColor DarkYellow }
    }
}

Write-Host "=== 停止 ETF Surge 服务 ===" -ForegroundColor Cyan

Stop-ByPort 8000 "后端"
Stop-ByPort 5173 "前端"

# 兜底：清理本机残留的 uvicorn / vite 进程（wmic 按命令行匹配）
$uv = wmic process where "name='python.exe' and commandline like '%uvicorn%'" get processid 2>$null
if ($uv) {
    $uv | ForEach-Object {
        if ($_ -match '(\d+)') {
            taskkill /F /PID $matches[1] 2>$null
            if ($LASTEXITCODE -eq 0) { Write-Host "  已停止残留 uvicorn (PID=$($matches[1]))" -ForegroundColor Green }
        }
    }
}
$vi = wmic process where "name='node.exe' and commandline like '%vite%'" get processid 2>$null
if ($vi) {
    $vi | ForEach-Object {
        if ($_ -match '(\d+)') {
            taskkill /F /PID $matches[1] 2>$null
            if ($LASTEXITCODE -eq 0) { Write-Host "  已停止残留 vite (PID=$($matches[1]))" -ForegroundColor Green }
        }
    }
}

Write-Host "`n=== 停止完成 ===" -ForegroundColor Cyan
