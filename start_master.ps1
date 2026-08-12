# ============================================
# 主控端一键启动脚本
# 自动启动: cloudflared 隧道 → relay 中继 → master 主控
# ============================================

$ErrorActionPreference = "Stop"
$ProjectRoot = "E:\Codex Projects\企业微信群发系统"
$Python = "C:\Users\Administrator\AppData\Local\Python\bin\python.exe"
$Cloudflared = "$ProjectRoot\tools\cloudflared.exe"

Set-Location $ProjectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  企业微信群发系统 - 主控端启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 端口规划: relay→3000, master→8080, cloudflared 隧道→3000
$RELAY_PORT = 3000
$MASTER_PORT = 8080

# 1. 清理旧进程
Write-Host "`n[1/5] 清理旧进程..." -ForegroundColor Yellow
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "" } | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# 2. 启动 relay 中继（端口 3000）
Write-Host "[2/5] 启动 WebSocket 中继 (端口 $RELAY_PORT)..." -ForegroundColor Yellow
$env:PORT = "$RELAY_PORT"
Start-Process -FilePath $Python -ArgumentList "relay.py" -NoNewWindow `
  -RedirectStandardOutput "$ProjectRoot\logs\relay.log" `
  -RedirectStandardError "$ProjectRoot\logs\relay_error.log"
Start-Sleep -Seconds 2

# 验证 relay 是否启动成功
$relayRunning = netstat -ano 2>$null | Select-String ":$RELAY_PORT" | Select-String "LISTENING"
if (-not $relayRunning) {
    Write-Host "  × 中继启动失败，端口 $RELAY_PORT 未被监听" -ForegroundColor Red
    exit 1
}
Write-Host "  √ 中继已启动 (端口 $RELAY_PORT 监听中)" -ForegroundColor Green

# 3. 启动 cloudflared 隧道 (暴露 localhost:3000)
Write-Host "[3/5] 启动 Cloudflare 隧道..." -ForegroundColor Yellow
# cloudflared 把隧道 URL 输出到 stderr
$tunnelErrorLog = "$ProjectRoot\logs\tunnel_stderr.log"
Remove-Item $tunnelErrorLog -ErrorAction SilentlyContinue
$tunnelStdoutLog = "$ProjectRoot\logs\tunnel_stdout.log"

Start-Process -FilePath $Cloudflared `
  -ArgumentList "tunnel", "--url", "http://localhost:$RELAY_PORT", "--no-autoupdate" `
  -NoNewWindow `
  -RedirectStandardOutput $tunnelStdoutLog `
  -RedirectStandardError $tunnelErrorLog

# 等待隧道建立并捕获 URL
Write-Host "  等待隧道建立..." -ForegroundColor Gray
$tunnelUrl = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path $tunnelErrorLog) {
        $content = Get-Content $tunnelErrorLog -Raw -ErrorAction SilentlyContinue
        if ($content -match 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com') {
            $tunnelUrl = $matches[0]
            break
        }
    }
}

if (-not $tunnelUrl) {
    Write-Host "  × 隧道建立失败，检查日志: $tunnelErrorLog" -ForegroundColor Red
    exit 1
}
Write-Host "  √ 隧道已建立: $tunnelUrl" -ForegroundColor Green

# 4. 更新 config.yaml 中的中继地址
Write-Host "[4/5] 更新配置..." -ForegroundColor Yellow
$wsUrl = $tunnelUrl -replace '^https://', 'wss://'
$configPath = "$ProjectRoot\config.yaml"
$configContent = Get-Content $configPath -Raw
$configContent = $configContent -replace 'url:\s*"[^"]*"', "url: `"$wsUrl`""
$configContent = $configContent -replace 'master_port:\s*\d+', "master_port: $MASTER_PORT"
Set-Content -Path $configPath -Value $configContent

# 保存隧道 URL 供执行端参考
$wsUrl | Out-File -FilePath "$ProjectRoot\data\relay_url.txt" -Encoding UTF8
Write-Host "  √ 中继地址已更新: $wsUrl" -ForegroundColor Green

# 5. 启动主控
Write-Host "[5/5] 启动主控服务..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  ┌─────────────────────────────────────────────┐" -ForegroundColor White
Write-Host "  │  中继地址: $wsUrl" -ForegroundColor White
Write-Host "  │  主控面板: http://localhost:$MASTER_PORT" -ForegroundColor White
Write-Host "  │" -ForegroundColor White
Write-Host "  │  执行端连接命令:" -ForegroundColor Gray
Write-Host "  │  .\start_worker.ps1 -RelayUrl '$wsUrl'" -ForegroundColor Gray
Write-Host "  └─────────────────────────────────────────────┘" -ForegroundColor White
Write-Host ""

# 启动主控（前台运行，Ctrl+C 停止）
& $Python main.py --mode master

Write-Host "`n主控已停止。" -ForegroundColor Yellow
