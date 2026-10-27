$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'mysql_paths.ps1')
$paths = Get-ProjectMySqlPaths -ProjectRoot $projectRoot
$admin = $paths.Admin
$credentials = $paths.Credentials
$pidFile = $paths.Pid
$serverProcess = $null
if (Test-Path $pidFile) {
    $serverId = [int](Get-Content $pidFile -Raw).Trim()
    $serverProcess = Get-Process -Id $serverId -ErrorAction SilentlyContinue
    if ($serverProcess -and $serverProcess.Path -ne $paths.Server -and
        $serverProcess.Path -ne $paths.OriginalServer) {
        throw 'The PID file refers to another process; MySQL was not stopped.'
    }
}
& $admin "--defaults-extra-file=$credentials" shutdown
if ($LASTEXITCODE -ne 0) { throw 'MySQL shutdown failed.' }
if ($serverProcess -and !$serverProcess.WaitForExit(30000)) {
    throw "MySQL shutdown is still in progress; see $($paths.Log)."
}
Write-Output 'Project MySQL stopped.'
