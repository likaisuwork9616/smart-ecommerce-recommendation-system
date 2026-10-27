function Get-ProjectMySqlPaths {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $sourceConfig = Join-Path $ProjectRoot '.runtime/mysql/my.ini'
    if (!(Test-Path -LiteralPath $sourceConfig -PathType Leaf)) {
        throw 'MySQL is not configured. See docs/LOCAL_SETUP.md.'
    }
    $settings = @{}
    $inServerSection = $false
    foreach ($line in Get-Content -LiteralPath $sourceConfig) {
        $entry = $line.Trim()
        if ($entry -match '^\[([^\]]+)\]$') {
            $inServerSection = $Matches[1] -eq 'mysqld'
            continue
        }
        if ($inServerSection -and $entry -match '^([^#;=]+?)\s*=\s*(.*?)\s*$') {
            $key = $Matches[1].Trim().ToLowerInvariant()
            $value = $Matches[2]
            if ($value.Length -ge 2 -and
                (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                 ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $settings[$key] = $value
        }
    }
    foreach ($key in @('basedir', 'datadir')) {
        if (!$settings[$key] -or ![IO.Path]::IsPathRooted($settings[$key])) {
            throw "MySQL my.ini must contain an absolute $key path. See docs/LOCAL_SETUP.md."
        }
    }
    # Preserve the configured spelling: resolving a junction back to a Chinese
    # project path would make MySQL's Windows option-file handling fail again.
    $mysqlRoot = Split-Path $settings['datadir'] -Parent
    $server = Join-Path $settings['basedir'] 'bin/mysqld.exe'
    $originalTools = Join-Path $ProjectRoot ('.runtime/tools/' + (Split-Path $settings['basedir'] -Leaf))
    $paths = [PSCustomObject]@{
        Root = $mysqlRoot
        Config = Join-Path $mysqlRoot 'my.ini'
        Server = $server
        OriginalServer = Join-Path $originalTools 'bin/mysqld.exe'
        Admin = Join-Path $settings['basedir'] 'bin/mysqladmin.exe'
        Credentials = Join-Path $mysqlRoot 'admin.ini'
        Pid = if ($settings['pid-file']) { $settings['pid-file'] } else { Join-Path $mysqlRoot 'mysql.pid' }
        Log = if ($settings['log-error']) { $settings['log-error'] } else { Join-Path $mysqlRoot 'mysql-error.log' }
    }
    foreach ($path in @($paths.Config, $paths.Server, $paths.Admin, $paths.Credentials)) {
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) {
            throw 'MySQL paths are unavailable. Check my.ini and docs/LOCAL_SETUP.md.'
        }
    }
    return $paths
}
