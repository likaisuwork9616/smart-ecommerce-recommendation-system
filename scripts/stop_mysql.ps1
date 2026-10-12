$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$admin = Join-Path $projectRoot '.runtime/tools/mysql-8.4.11-winx64/bin/mysqladmin.exe'
$credentials = Join-Path $projectRoot '.runtime/mysql/admin.ini'
$pidFile = Join-Path $projectRoot '.runtime/mysql/mysql.pid'
$serverProcess = $null
if (Test-Path $pidFile) {
    $serverId = [int](Get-Content $pidFile -Raw).Trim()
    $serverProcess = Get-Process -Id $serverId -ErrorAction SilentlyContinue
}
& $admin "--defaults-extra-file=$credentials" shutdown
if ($LASTEXITCODE -ne 0) { throw 'MySQL shutdown failed.' }
if ($serverProcess -and !$serverProcess.WaitForExit(30000)) {
    throw 'MySQL shutdown is still in progress; see .runtime/mysql/mysql-error.log.'
}
Write-Output 'Project MySQL stopped.'
