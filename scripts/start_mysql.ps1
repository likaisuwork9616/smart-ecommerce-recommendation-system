param([string]$InitFile)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$mysqlRoot = Join-Path $projectRoot '.runtime/mysql'
$configFile = Join-Path $mysqlRoot 'my.ini'
$server = Join-Path $projectRoot '.runtime/tools/mysql-8.4.11-winx64/bin/mysqld.exe'
$admin = Join-Path $projectRoot '.runtime/tools/mysql-8.4.11-winx64/bin/mysqladmin.exe'
$credentials = Join-Path $mysqlRoot 'admin.ini'
if (!(Test-Path $configFile) -or !(Test-Path $server) -or !(Test-Path $credentials)) {
    throw 'MySQL is not configured. See docs/LOCAL_SETUP.md.'
}
$server = (Resolve-Path -LiteralPath $server).Path
function Test-MySqlReady {
    try {
        & $admin "--defaults-extra-file=$credentials" '--connect-timeout=1' status 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}
$pidFile = Join-Path $mysqlRoot 'mysql.pid'
if (Test-Path $pidFile) {
    $serverId = [int](Get-Content $pidFile -Raw).Trim()
    $running = Get-Process -Id $serverId -ErrorAction SilentlyContinue
    if ($running -and $running.Path -eq $server) {
        if (Test-MySqlReady) {
            Write-Output 'Project MySQL is already running at 127.0.0.1:3307.'
            return
        }
        throw 'The project MySQL process exists but is not ready. Check mysql-error.log.'
    }
}
$probe = [Net.Sockets.TcpClient]::new()
$occupied = $false
try { $probe.Connect('127.0.0.1', 3307); $occupied = $true } catch { } finally { $probe.Dispose() }
if ($occupied) { throw 'Port 3307 is occupied by another process; MySQL was not started.' }
$serverArgs = @("--defaults-file=`"$configFile`"")
if ($InitFile) { $serverArgs += "--init-file=`"$InitFile`"" }
$process = Start-Process -FilePath $server -ArgumentList $serverArgs -WindowStyle Hidden -PassThru
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 1
    $process.Refresh()
    if ($process.HasExited) { throw "MySQL exited. See $mysqlRoot/mysql-error.log" }
    if (Test-MySqlReady) {
        Write-Output 'Project MySQL is running at 127.0.0.1:3307.'
        return
    }
}
throw "MySQL did not become ready. See $mysqlRoot/mysql-error.log"
