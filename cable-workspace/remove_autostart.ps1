$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'Kontur Local Website.lnk'
if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath
    Write-Output 'Kontur autostart removed.'
} else {
    Write-Output 'Kontur autostart is already disabled.'
}
