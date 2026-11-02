$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'Kontur Local Website.lnk'
$powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$launcherPath = Join-Path $projectRoot 'start_kontur.ps1'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcherPath`" -OpenBrowser"
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'Starts the local Kontur website when you sign in to Windows'
$shortcut.Save()
Write-Output "Autostart configured: $shortcutPath"
