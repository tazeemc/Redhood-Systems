# RedHood Insights - PowerShell runner
# Usage:
#   .\run.ps1              # last 5 minutes (default)
#   .\run.ps1 -Hours 1     # last 1 hour
#   .\run.ps1 -Hours 24    # last 24 hours

param(
    [double]$Hours = 0.0833   # default: 5 minutes
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Load .env if present and not already set in environment
$EnvFile = Join-Path $ScriptDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $key   = $matches[1].Trim()
            $value = $matches[2].Trim()
            if (-not [System.Environment]::GetEnvironmentVariable($key)) {
                [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
}

if (-not $env:ANTHROPIC_API_KEY) {
    Write-Host "ERROR: ANTHROPIC_API_KEY is not set." -ForegroundColor Red
    Write-Host "  Create a .env file in $ScriptDir with:" -ForegroundColor Yellow
    Write-Host "  ANTHROPIC_API_KEY=sk-ant-your-key-here" -ForegroundColor Yellow
    exit 1
}

Write-Host "Running RedHood Insights (last $Hours hours)..." -ForegroundColor Cyan
python "$ScriptDir\redhood_aggregator.py" --hours $Hours
