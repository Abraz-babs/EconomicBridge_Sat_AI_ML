#Requires -RunAsAdministrator
# EconomicBridge — reset Postgres 18 'postgres' user password to 'devpassword'.
#
# Safety: backs up pg_hba.conf with a timestamped suffix, switches the
# local + loopback (non-replication) auth lines to 'trust' temporarily,
# runs ALTER USER, then restores the original pg_hba.conf and restarts.
# The restore happens in a `finally` block so the original config is always
# put back, even if ALTER USER fails.
#
# How to run:
#   1. Right-click Windows PowerShell -> Run as Administrator
#   2. cd "c:\Users\HP\Downloads\economicbridge-ide-starter\economic-bridge-project\scripts"
#   3. powershell -ExecutionPolicy Bypass -File .\reset_postgres_password.ps1

$ErrorActionPreference = 'Stop'

$data   = 'C:\Program Files\PostgreSQL\18\data'
$hba    = Join-Path $data 'pg_hba.conf'
$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $data ("pg_hba.conf.bak-$stamp")
$psql   = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
$svc    = 'postgresql-x64-18'
$newPw  = 'devpassword'

if (-not (Test-Path $hba))  { throw "pg_hba.conf not found at $hba" }
if (-not (Test-Path $psql)) { throw "psql not found at $psql" }

Write-Host "[1/7] Backing up pg_hba.conf -> $backup"
Copy-Item $hba $backup -Force

try {
    Write-Host "[2/7] Switching local + loopback (non-replication) auth to trust"
    $lines = Get-Content $hba
    $patched = foreach ($line in $lines) {
        if ($line -match '^\s*(local|host)\s+all\s+all\s' -and $line -match 'scram-sha-256') {
            $line -replace 'scram-sha-256', 'trust'
        } else {
            $line
        }
    }
    Set-Content -Path $hba -Value $patched -Encoding ASCII

    Write-Host "[3/7] Restarting $svc to load trust auth"
    Restart-Service $svc -Force
    Start-Sleep -Seconds 2

    Write-Host "[4/7] ALTER USER postgres WITH PASSWORD '$newPw'"
    & $psql -U postgres -h 127.0.0.1 -p 5432 -d postgres -c "ALTER USER postgres WITH PASSWORD '$newPw';"
    if ($LASTEXITCODE -ne 0) { throw "ALTER USER failed (exit $LASTEXITCODE)" }
}
finally {
    Write-Host "[5/7] Restoring pg_hba.conf from $backup"
    Copy-Item $backup $hba -Force

    Write-Host "[6/7] Restarting $svc to load restored config"
    Restart-Service $svc -Force
    Start-Sleep -Seconds 2
}

Write-Host "[7/7] Verifying new password"
$env:PGPASSWORD = $newPw
& $psql -U postgres -h localhost -p 5432 -d postgres -c "SELECT 'reset OK' AS status, current_user, current_database();"
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "DONE. Postgres 18 'postgres' password is now '$newPw'." -ForegroundColor Green
    Write-Host "Backup of original pg_hba.conf left at: $backup"
} else {
    Write-Host ""
    Write-Host "VERIFY FAILED. Original pg_hba.conf has been restored from $backup." -ForegroundColor Red
    exit 1
}
