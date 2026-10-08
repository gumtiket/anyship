param(
    [ValidateSet('github')][string]$Mode = 'github',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$repoDirectory = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $repoDirectory 'service/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Python environment missing. Follow docs/LOCAL_DEVELOPMENT.md first.'
}
$runnerArguments = @((Join-Path $PSScriptRoot 'local_web.py'), '--mode', $Mode)
if ($CheckOnly) { $runnerArguments += '--check' }
& $pythonExecutable @runnerArguments
if ($LASTEXITCODE -ne 0) { throw 'Local service setup failed. See the message above.' }
