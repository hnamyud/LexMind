# =============================================================================
# dev.ps1 - Script chạy đồng thời NestJS (backend-core) và FastAPI (ai-service)
# Cách dùng: .\dev.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot

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

# --- Chạy NestJS trong cửa sổ mới ---
Write-Host "▶  [NEST]    Khởi động NestJS..." -ForegroundColor Blue
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$ROOT\backend-core'; `$host.UI.RawUI.WindowTitle = 'NestJS :8080'; npm run dev"

# --- Chạy FastAPI trong cửa sổ mới ---
Write-Host "▶  [FASTAPI] Khởi động FastAPI..." -ForegroundColor Magenta
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$ROOT\ai-service'; `$host.UI.RawUI.WindowTitle = 'FastAPI :8001'; .\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload"

Write-Host ""
Write-Host "✅  Cả 2 service đang khởi động trong cửa sổ riêng." -ForegroundColor Green
Write-Host "   Đóng các cửa sổ đó để dừng service."            -ForegroundColor Green
Write-Host ""
