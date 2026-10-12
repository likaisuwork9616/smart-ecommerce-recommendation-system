$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$app = Join-Path $projectRoot '.runtime/tools/dbeaver/dbeaver.exe'
if (!(Test-Path $app)) { throw 'DBeaver is not installed. See docs/LOCAL_SETUP.md.' }
& (Join-Path $PSScriptRoot 'start_mysql.ps1')
$workspace = Join-Path $projectRoot '.runtime/dbeaver-workspace'
$env:DBEAVER_DATA = Join-Path $projectRoot '.runtime'
Start-Process -FilePath $app -ArgumentList @('-data', "`"$workspace`"")
