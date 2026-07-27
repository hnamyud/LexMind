# =============================================================================
# dev.ps1 - Run the FastAPI API services and local mail worker.
# Usage: .\dev.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)] [int]$ProcessId,
        [Parameter(Mandatory = $true)] [string]$Name
    )

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        if (-not $process.HasExited) {
            Write-Host "⏹  [$Name] Dừng cây tiến trình PID=$ProcessId..." -ForegroundColor Yellow
            taskkill /PID $ProcessId /T /F | Out-Null
        }
    }
    catch {
        # The child process has already exited.
    }
}

function Start-ServiceWindow {
    param(
        [Parameter(Mandatory = $true)] [string]$Name,
        [Parameter(Mandatory = $true)] [string]$Title,
        [Parameter(Mandatory = $true)] [string]$Command,
        [Parameter(Mandatory = $true)] [string]$Color
    )

    Write-Host "▶  [$Name] Khởi động..." -ForegroundColor $Color
    $process = Start-Process powershell -PassThru -ArgumentList "-NoExit", "-Command", $Command
    return [PSCustomObject]@{ Name = $Name; Process = $process; Alive = $true }
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║        🚀  Chatbot-Law Dev Server            ║" -ForegroundColor Cyan
Write-Host "║  Core API    → http://localhost:8080         ║" -ForegroundColor Cyan
Write-Host "║  AI API      → http://localhost:8001         ║" -ForegroundColor Cyan
Write-Host "║  Mail worker → ARQ / Redis                    ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$aiPython = Join-Path $ROOT "ai-service\.venv\Scripts\python.exe"
if (-not (Test-Path $aiPython)) {
    Write-Host "⚠️  Không tìm thấy .venv trong ai-service!" -ForegroundColor Yellow
    Write-Host "   Chạy: cd ai-service && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

$corePython = Join-Path $ROOT "core-api\.venv\Scripts\python.exe"
if (-not (Test-Path $corePython)) {
    Write-Host "⚠️  Không tìm thấy .venv trong core-api!" -ForegroundColor Yellow
    Write-Host "   Chạy: cd core-api && uv sync --all-groups" -ForegroundColor Yellow
    exit 1
}

$services = @()
try {
    $services += Start-ServiceWindow -Name "AI" -Title "AI API :8001" -Color "Magenta" -Command `
        "Set-Location '$ROOT\ai-service'; `$host.UI.RawUI.WindowTitle = 'AI API :8001'; .\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload"
    $services += Start-ServiceWindow -Name "CORE" -Title "Core API :8080" -Color "Cyan" -Command `
        "Set-Location '$ROOT\core-api'; `$env:APP_ENV = 'development'; `$host.UI.RawUI.WindowTitle = 'Core API :8080'; .\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload"
    $services += Start-ServiceWindow -Name "MAIL" -Title "Core mail worker" -Color "Green" -Command `
        "Set-Location '$ROOT\core-api'; `$env:APP_ENV = 'development'; `$host.UI.RawUI.WindowTitle = 'Core mail worker'; .\.venv\Scripts\python -m arq app.workers.mail.WorkerSettings"

    Write-Host ""
    Write-Host "✅  Ba service đang khởi động trong cửa sổ riêng." -ForegroundColor Green
    Write-Host "   Nhấn Ctrl+C tại cửa sổ này để dừng toàn bộ service." -ForegroundColor Green
    Write-Host ("   " + (($services | ForEach-Object { "$($_.Name) PID: $($_.Process.Id)" }) -join " | ")) -ForegroundColor DarkGray
    Write-Host ""

    while ($true) {
        Start-Sleep -Seconds 1
        foreach ($service in $services) {
            try {
                $service.Alive = -not (Get-Process -Id $service.Process.Id -ErrorAction Stop).HasExited
            }
            catch {
                $service.Alive = $false
            }
        }

        if ($services.Where({ -not $_.Alive }).Count -gt 0) {
            Write-Host ""
            Write-Host "⚠️  Một service đã dừng. Đang tắt các service còn lại..." -ForegroundColor Yellow
            break
        }
    }
}
finally {
    foreach ($service in $services) {
        Stop-ProcessTree -ProcessId $service.Process.Id -Name $service.Name
    }
    Write-Host ""
    Write-Host "🛑  Đã dừng toàn bộ service dev." -ForegroundColor Green
    Write-Host ""
}
