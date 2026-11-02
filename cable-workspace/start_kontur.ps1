param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$url = 'http://127.0.0.1:8765/'
$logPath = Join-Path $projectRoot 'start_kl.log'

function Test-KonturServer {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect('127.0.0.1', 8765, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(2000)) { return $false }
        $client.EndConnect($connect)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if (-not (Test-KonturServer)) {
    Write-Output 'Checking Python and required packages...'
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        $pythonPath = (& $pythonLauncher.Source -3 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -First 1)
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand) {
            $pythonPath = $pythonCommand.Source
        }
    }

    if (-not $pythonPath -or -not (Test-Path $pythonPath)) {
        Add-Content -Path $logPath -Value "$(Get-Date -Format s) Python 3 was not found."
        throw 'Python 3 was not found. Install Python and retry.'
    }

    & $pythonPath -c 'import pdfplumber, openpyxl' *> $null
    if ($LASTEXITCODE -ne 0) {
        Add-Content -Path $logPath -Value "$(Get-Date -Format s) Installing PDF calculation packages."
        & $pythonPath -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements-kl.txt') *>> $logPath
        if ($LASTEXITCODE -ne 0) {
            throw "Could not install required packages. See $logPath"
        }
    }

    Add-Content -Path $logPath -Value "$(Get-Date -Format s) Starting local Kontur server."
    Write-Output 'Starting the local server in the background...'
    Start-Process -FilePath $pythonPath -ArgumentList 'server.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot 'server.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'server.stderr.log')

    $ready = $false
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-KonturServer) {
            $ready = $true
            break
        }
        if (($attempt + 1) % 5 -eq 0) { Write-Output "Still waiting for the server ($($attempt + 1)s)..." }
    }
    if (-not $ready) {
        Add-Content -Path $logPath -Value "$(Get-Date -Format s) Server did not respond at $url."
        throw "The local website did not start. Check server.stderr.log and server.stdout.log in $projectRoot"
    }
} else {
    Write-Output 'The local server is already running.'
}

if ($OpenBrowser) {
    Write-Output "Kontur is available at $url"
    Start-Process $url
}
