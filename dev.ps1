# =============================================================================
# dev.ps1 - Script chạy đồng thời NestJS (backend-core) và FastAPI (ai-service)
# Cách dùng: .\dev.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        if (-not $process.HasExited) {
            Write-Host "⏹  [$Name] Dừng cây tiến trình PID=$ProcessId..." -ForegroundColor Yellow
            taskkill /PID $ProcessId /T /F | Out-Null
        }
    }
    catch {
        # Tiến trình đã thoát trước đó, không cần xử lý thêm.
    }
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║        🚀  Chatbot-Law Dev Server            ║" -ForegroundColor Cyan
Write-Host "║  NestJS  → http://localhost:8080             ║" -ForegroundColor Cyan
Write-Host "║  FastAPI → http://localhost:8001             ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# --- Kiểm tra .venv của FastAPI ---
$venvPython = Join-Path $ROOT "ai-service\.venv\Scripts\python.exe"
if (-Not (Test-Path $venvPython)) {
    Write-Host "⚠️  Không tìm thấy .venv trong ai-service!" -ForegroundColor Yellow
    Write-Host "   Chạy: cd ai-service && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

$nestProcess = $null
$fastApiProcess = $null

try {
    # --- Chạy NestJS trong cửa sổ mới ---
    Write-Host "▶  [NEST]    Khởi động NestJS..." -ForegroundColor Blue
    $nestProcess = Start-Process powershell -PassThru -ArgumentList "-NoExit", "-Command", `
        "cd '$ROOT\backend-core'; `$host.UI.RawUI.WindowTitle = 'NestJS :8080'; npm run dev"

    # --- Chạy FastAPI trong cửa sổ mới ---
    Write-Host "▶  [FASTAPI] Khởi động FastAPI..." -ForegroundColor Magenta
    $fastApiProcess = Start-Process powershell -PassThru -ArgumentList "-NoExit", "-Command", `
        "cd '$ROOT\ai-service'; `$host.UI.RawUI.WindowTitle = 'FastAPI :8001'; .\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload"

    Write-Host ""
    Write-Host "✅  Cả 2 service đang khởi động trong cửa sổ riêng." -ForegroundColor Green
    Write-Host "   Nhấn Ctrl+C tại cửa sổ này để dừng cả hai service." -ForegroundColor Green
    Write-Host "   NEST PID: $($nestProcess.Id) | FASTAPI PID: $($fastApiProcess.Id)" -ForegroundColor DarkGray
    Write-Host ""

    while ($true) {
        Start-Sleep -Seconds 1

        $nestAlive = $false
        $fastApiAlive = $false

        try {
            $nestAlive = -not (Get-Process -Id $nestProcess.Id -ErrorAction Stop).HasExited
        }
        catch {
            $nestAlive = $false
        }

        try {
            $fastApiAlive = -not (Get-Process -Id $fastApiProcess.Id -ErrorAction Stop).HasExited
        }
        catch {
            $fastApiAlive = $false
        }

        if (-not $nestAlive -or -not $fastApiAlive) {
            Write-Host "" 
            Write-Host "⚠️  Một service đã dừng. Đang tắt service còn lại..." -ForegroundColor Yellow
            break
        }
    }
}
finally {
    if ($fastApiProcess) {
        Stop-ProcessTree -ProcessId $fastApiProcess.Id -Name "FASTAPI"
    }
    if ($nestProcess) {
        Stop-ProcessTree -ProcessId $nestProcess.Id -Name "NEST"
    }

    Write-Host ""
    Write-Host "🛑  Đã dừng toàn bộ service dev." -ForegroundColor Green
    Write-Host ""
}
