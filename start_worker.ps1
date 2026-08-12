# ============================================
# 执行端一键启动脚本
# 用法: .\start_worker.ps1 -RelayUrl "wss://xxx.trycloudflare.com"
# ============================================

param(
    [Parameter(Mandatory=$false)]
    [string]$RelayUrl = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = "E:\Codex Projects\企业微信群发系统"
$Python = "C:\Users\Administrator\AppData\Local\Python\bin\python.exe"

Set-Location $ProjectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  企业微信群发系统 - 执行端启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 如果没有传入中继地址，尝试从文件读取
if (-not $RelayUrl) {
    $urlFile = "$ProjectRoot\data\relay_url.txt"
    if (Test-Path $urlFile) {
        $RelayUrl = Get-Content $urlFile -Raw
        $RelayUrl = $RelayUrl.Trim()
        Write-Host "从配置文件读取中继地址: $RelayUrl" -ForegroundColor Gray
    }
}

if (-not $RelayUrl) {
    Write-Host "`n请提供中继地址:" -ForegroundColor Yellow
    Write-Host "  .\start_worker.ps1 -RelayUrl 'wss://xxx.trycloudflare.com'" -ForegroundColor Gray
    exit 1
}

Write-Host "`n中继地址: $RelayUrl" -ForegroundColor White
Write-Host "启动执行端..." -ForegroundColor Yellow

& $Python main.py --mode worker --relay $RelayUrl
