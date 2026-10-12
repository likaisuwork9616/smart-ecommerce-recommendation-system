param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot 'start_mysql.ps1')
$env:JUPYTER_CONFIG_DIR = Join-Path $projectRoot '.runtime/jupyter/config'
$env:JUPYTER_DATA_DIR = Join-Path $projectRoot '.runtime/jupyter/data'
$env:JUPYTER_RUNTIME_DIR = Join-Path $projectRoot '.runtime/jupyter/runtime'
$env:IPYTHONDIR = Join-Path $projectRoot '.runtime/ipython'
$env:MPLCONFIGDIR = Join-Path $projectRoot '.runtime/matplotlib'
$jupyterArgs = @('-m', 'jupyterlab', "--ServerApp.root_dir=$projectRoot/notebooks", '--ServerApp.ip=127.0.0.1', '--ServerApp.port=8888', '--ServerApp.port_retries=0')
if ($NoBrowser) { $jupyterArgs += '--no-browser' }
& (Join-Path $projectRoot '.venv/Scripts/python.exe') @jupyterArgs
exit $LASTEXITCODE
