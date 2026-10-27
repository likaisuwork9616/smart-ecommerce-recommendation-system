param([string]$InitFile)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'mysql_paths.ps1')
$paths = Get-ProjectMySqlPaths -ProjectRoot $projectRoot
$configFile = $paths.Config
$server = $paths.Server
$admin = $paths.Admin
$credentials = $paths.Credentials
function Test-MySqlReady {
    try {
        & $admin "--defaults-extra-file=$credentials" '--connect-timeout=1' status 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}
$pidFile = $paths.Pid
if (Test-Path $pidFile) {
    $serverId = [int](Get-Content $pidFile -Raw).Trim()
    $running = Get-Process -Id $serverId -ErrorAction SilentlyContinue
    if ($running -and ($running.Path -eq $server -or $running.Path -eq $paths.OriginalServer)) {
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
    if ($process.HasExited) { throw "MySQL exited. See $($paths.Log)" }
    if (Test-MySqlReady) {
        Write-Output 'Project MySQL is running at 127.0.0.1:3307.'
        return
    }
}
throw "MySQL did not become ready. See $($paths.Log)"
