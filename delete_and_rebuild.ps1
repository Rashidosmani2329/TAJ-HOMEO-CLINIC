$projectRoot = 'C:\Users\RASHID\Music\Taj Homeo'
$dist = Join-Path $projectRoot 'dist'
$exe = Join-Path $dist 'TajHomeoApp.exe'
$backupDir = Join-Path $projectRoot 'backups'
$time = Get-Date -Format 'yyyyMMdd_HHmmss'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$distBackup = Join-Path $backupDir "dist_$time"
if (Test-Path $dist) { Copy-Item -Path $dist -Destination $distBackup -Recurse -Force -ErrorAction SilentlyContinue }
$storage = Join-Path $env:APPDATA 'TajHomeo'
if (Test-Path $storage) {
    $storageBackup = Join-Path $backupDir "storage_$time"
    Copy-Item -Path $storage -Destination $storageBackup -Recurse -Force -ErrorAction SilentlyContinue
}
# remove exe
if (Test-Path $exe) { Remove-Item $exe -Force -ErrorAction SilentlyContinue; Write-Output "Removed $exe" }
# remove storage data
if (Test-Path $storage) { Remove-Item $storage -Recurse -Force -ErrorAction SilentlyContinue; Write-Output "Removed $storage" }
# Rebuild EXE
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'rebuild_exe.ps1')
Write-Output 'delete_and_rebuild script finished.'
