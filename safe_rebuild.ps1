$exe = Join-Path (Split-Path -Path $MyInvocation.MyCommand.Path -Parent) 'dist\TajHomeoApp.exe'
# stop any running process named TajHomeoApp
Get-Process -Name TajHomeoApp -ErrorAction SilentlyContinue | ForEach-Object { Write-Output "Stopping process: $($_.Id)"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
if (Test-Path $exe) { Write-Output "Removing existing EXE: $exe"; Remove-Item $exe -Force -ErrorAction SilentlyContinue }
# run standard rebuild
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path (Split-Path -Path $MyInvocation.MyCommand.Path -Parent) 'rebuild_exe.ps1')
Write-Output 'safe_rebuild completed.'
