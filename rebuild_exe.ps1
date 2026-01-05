Param(
    [switch]$Watch
)

$projectRoot = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$spec = "TajHomeoApp.spec"
$distExe = Join-Path $projectRoot "dist\TajHomeoApp.exe"
$backup = Join-Path $projectRoot "dist\TajHomeoApp.exe.bak"

function Build {
    if (Test-Path $distExe) { Copy-Item $distExe $backup -Force; Write-Output "Backup created: $backup" }
    & $venvPython -m PyInstaller --clean --noconfirm $spec
    if (Test-Path $distExe) { Get-Item $distExe | Select-Object Name, Length, LastWriteTime | Format-List }
}

if (-not (Test-Path $venvPython)) {
    Write-Error "Could not find venv python at $venvPython. Ensure .venv exists and dependencies are installed." ; exit 1
}

Build

if ($Watch) {
    Write-Output "Watching for changes (*.py, *.kv, *.json, *.csv). Press Ctrl+C to stop."
    $state = @{}
    $getFiles = { Get-ChildItem -Path $projectRoot -Recurse -Include *.py,*.kv,*.json,*.csv -File -ErrorAction SilentlyContinue }
    foreach ($f in & $getFiles) { $state[$f.FullName] = $f.LastWriteTimeUtc.Ticks }
    while ($true) {
        Start-Sleep -Seconds 1
        $changed = $false
        foreach ($f in & $getFiles) {
            $t = $f.LastWriteTimeUtc.Ticks
            if (-not $state.ContainsKey($f.FullName) -or $state[$f.FullName] -ne $t) {
                $state[$f.FullName] = $t
                $changed = $true
            }
        }
        if ($changed) {
            Write-Output "Change detected. Rebuilding..."
            Build
        }
    }
}
