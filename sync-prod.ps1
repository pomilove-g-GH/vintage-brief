# =================================================================
# Vintage Daily Digest — 프로덕션 데이터 동기화 스크립트
# -----------------------------------------------------------------
# 사이트에서 "업데이트(영상 5개 추가)" 누른 후 이 스크립트를 실행하면
# 자동으로 Fly의 영상 데이터를 가져와 Claude로 요약 채워서 다시 올림.
#
# 1. SFTP get  — /data/data/*.json → 로컬 tmp
# 2. backfill-dates.py — pubDate 채움
# 3. resummarize-local.py — summary Claude 요약
# 4. SFTP put — 다시 Fly로 업로드
# 5. tmp 정리
# =================================================================

$ErrorActionPreference = "Continue"
$projectDir = "C:\Users\pomil\매일아침_빈티지"
Set-Location $projectDir

Write-Host ""
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  Vintage Daily Digest — 프로덕션 동기화" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------
# 1. API 키 확인
# ------------------------------------------------
$key = [System.Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
if (-not $key -or $key.Length -lt 80) {
    Write-Host "❌ ANTHROPIC_API_KEY 환경변수가 없거나 잘못됨." -ForegroundColor Red
    Write-Host "   설정 방법:" -ForegroundColor Yellow
    Write-Host '   [System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "User")'
    Read-Host "Enter 키 입력 후 종료"
    exit 1
}
$env:ANTHROPIC_API_KEY = $key
Write-Host "✓ API 키 확인됨 (길이: $($key.Length))" -ForegroundColor Green

# ------------------------------------------------
# 2. fly CLI PATH
# ------------------------------------------------
$env:Path += ";$env:USERPROFILE\.fly\bin"
$flyCheck = Get-Command fly -ErrorAction SilentlyContinue
if (-not $flyCheck) {
    Write-Host "❌ fly CLI를 찾을 수 없음." -ForegroundColor Red
    Read-Host "Enter 키 입력 후 종료"
    exit 1
}
Write-Host "✓ fly CLI 사용 가능" -ForegroundColor Green

# ------------------------------------------------
# 3. VM 깨우기
# ------------------------------------------------
Write-Host ""
Write-Host "[1/5] Fly VM 깨우는 중..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri "https://vintage-brief.fly.dev/api/me" -UseBasicParsing -TimeoutSec 15 | Out-Null
} catch {}
Start-Sleep -Seconds 3

# ------------------------------------------------
# 4. 임시 폴더 준비 + SFTP get
# ------------------------------------------------
Write-Host ""
Write-Host "[2/5] 프로덕션 JSON 다운로드..." -ForegroundColor Cyan

$tmpDir = Join-Path $projectDir "tmp_prod_data"
$tmpData = Join-Path $tmpDir "data"

# 기존 tmp 정리
if (Test-Path $tmpDir) {
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $tmpData | Out-Null

$files = @('vintage-startup.json','vintage-interview.json','vintage-wholesale.json','vintage-shops.json')
$allOk = $true
foreach ($f in $files) {
    $local = Join-Path $tmpData $f
    $out = fly ssh sftp get "/data/data/$f" $local 2>&1 | Out-String
    if (Test-Path $local) {
        Write-Host "  ✓ $f" -ForegroundColor Green
    } else {
        Write-Host "  ❌ $f 다운로드 실패" -ForegroundColor Red
        Write-Host $out -ForegroundColor DarkGray
        $allOk = $false
    }
}
if (-not $allOk) {
    Read-Host "Enter 키 입력 후 종료"
    exit 1
}

# ------------------------------------------------
# 5. backfill-dates.py (pubDate)
# ------------------------------------------------
Write-Host ""
Write-Host "[3/5] pubDate 백필..." -ForegroundColor Cyan
$env:DATA_ROOT = $tmpDir
$env:PYTHONIOENCODING = "utf-8"
python backfill-dates.py 2>&1 | ForEach-Object { Write-Host "  $_" }

# ------------------------------------------------
# 6. resummarize-local.py (summary) — --force 로 heuristic 덮어쓰기
# ------------------------------------------------
Write-Host ""
Write-Host "[4/5] Claude로 요약 생성 (--force)..." -ForegroundColor Cyan
python resummarize-local.py --force 2>&1 | ForEach-Object { Write-Host "  $_" }

# ------------------------------------------------
# 7. SFTP put (delete + upload)
# ------------------------------------------------
Write-Host ""
Write-Host "[5/5] 프로덕션에 업로드..." -ForegroundColor Cyan
$env:MSYS_NO_PATHCONV = "1"
Push-Location $tmpData
foreach ($f in $files) {
    fly ssh console -a vintage-brief -C "rm -f /data/data/$f" 2>&1 | Out-Null
    $out = fly ssh sftp put $f "/data/data/$f" -a vintage-brief 2>&1 | Out-String
    if ($out -match "uploaded") {
        Write-Host "  ✓ $f" -ForegroundColor Green
    } else {
        Write-Host "  ❌ $f 업로드 실패" -ForegroundColor Red
        Write-Host $out -ForegroundColor DarkGray
    }
}
Pop-Location

# ------------------------------------------------
# 8. 정리
# ------------------------------------------------
Start-Sleep -Seconds 2
Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "===============================================" -ForegroundColor Green
Write-Host "  ✅ 동기화 완료" -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green
Write-Host ""
Write-Host "이제 https://vintage-brief.fly.dev/ 에서 Ctrl+Shift+R 새로고침" -ForegroundColor Yellow
Write-Host ""
Read-Host "Enter 키 입력하면 창 닫힘"
