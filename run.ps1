# RedHood Systems - PowerShell runner (with Trading System Analysis)
# Usage:
#   .\run.ps1                          # last 45 minutes (default), default symbols
#   .\run.ps1 -Hours 5                 # last 5 hours
#   .\run.ps1 -Hours 24                # last 24 hours (full day)
#   .\run.ps1 -Symbols "NU","AAPL"     # custom symbols
#   .\run.ps1 -SkipTrading             # skip trading analysis, run RedHood only
#   .\run.ps1 -SkipRedHood             # skip RedHood, run trading analysis only

param(
    [double]$Hours          = 0.75,             # default: 45 minutes  |  common: 5 (5h), 24 (full day)
    [string[]]$Symbols      = @("NU", "BTC-USD", "META", "AAPL", "AMZN", "NFLX", "GOOGL", "WMT"),  # default: NU + BTC + FAANG + WMT
    [double]$BaseTemp       = 25.0,
    [double]$MaxHeat        = 80.0,
    [double]$InitialEquity  = 100000.0,
    [switch]$SkipTrading,
    [switch]$SkipRedHood
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# ============================================================================
# TRADING SYSTEM
# ============================================================================

function Get-MarketData {
    param([string]$symbol)
    try {
        # 6 months of daily candles -> meaningful MA50/RSI/entropy samples
        # (default endpoint returns a thin intraday window that inflates entropy)
        $url = "https://query1.finance.yahoo.com/v8/finance/chart/$symbol`?range=6mo&interval=1d"
        $response = Invoke-RestMethod -Uri $url -ErrorAction Stop
        if ($response.chart.result -and $response.chart.result[0]) {
            return $response.chart.result[0]
        } else {
            Write-Error "No data returned for symbol: $symbol"
            return $null
        }
    }
    catch {
        Write-Error "Failed to fetch data for $symbol : $($_.Exception.Message)"
        return $null
    }
}

function Calculate-MovingAverages {
    param([array]$prices, [int]$shortPeriod = 20, [int]$longPeriod = 50)
    if ($prices.Count -lt $longPeriod) {
        return @{ ShortMA = $prices[-1]; LongMA = $prices[-1] }
    }
    $ma20 = ($prices | Select-Object -Last $shortPeriod | Measure-Object -Average).Average
    $ma50 = ($prices | Select-Object -Last $longPeriod  | Measure-Object -Average).Average
    return @{ ShortMA = $ma20; LongMA = $ma50 }
}

function Calculate-Momentum {
    param([array]$prices, [int]$period = 14)
    if ($prices.Count -le $period) { return 0 }
    $current = $prices[-1]
    $past    = $prices[-$period]
    if ($past -eq 0 -or $past -eq $null -or $current -eq $null) { return 0 }
    return (($current - $past) / $past) * 100
}

function Calculate-RSI {
    param([array]$prices, [int]$period = 14)
    if ($prices.Count -lt $period + 1) { return 50 }
    $gains = @(); $losses = @()
    for ($i = 1; $i -lt $prices.Count; $i++) {
        $change = $prices[$i] - $prices[$i-1]
        if ($change -gt 0) { $gains += $change; $losses += 0 }
        else                { $gains += 0; $losses += [Math]::Abs($change) }
    }
    $gains  = $gains  | Select-Object -Last $period
    $losses = $losses | Select-Object -Last $period
    $avgGain = ($gains  | Measure-Object -Average).Average
    $avgLoss = ($losses | Measure-Object -Average).Average
    if ($avgLoss -eq 0) { return 100 }
    if ($avgGain -eq 0) { return 0 }
    $rs = $avgGain / $avgLoss
    return 100 - (100 / (1 + $rs))
}

function Calculate-Temperature {
    param([array]$returns, [int]$window = 20)
    if ($returns.Count -lt $window) { return $BaseTemp }
    $volatility = $returns | Select-Object -Last $window
    $mean       = ($volatility | Measure-Object -Average).Average
    $sumSquares = ($volatility | ForEach-Object { [Math]::Pow($_ - $mean, 2) } | Measure-Object -Sum).Sum
    $std        = [Math]::Sqrt($sumSquares / ($window - 1))
    return $std * [Math]::Sqrt(252)
}

function Calculate-Entropy {
    param([array]$returns, [int]$bins = 0)
    if ($returns.Count -eq 0) { return 0 }
    $validReturns = $returns | Where-Object { $_ -ne $null }
    if ($validReturns.Count -eq 0) { return 0 }
    # Bin count scaled to sample size (square-root rule), clamped to [5,50].
    # Fixed 50 bins over a thin sample spreads mass thin and inflates entropy,
    # which previously forced a spurious OUT on short windows.
    if ($bins -le 0) {
        $bins = [Math]::Floor([Math]::Sqrt($validReturns.Count))
        $bins = [Math]::Min(50, [Math]::Max(5, $bins))
    }
    $hist = @{}
    $min  = ($validReturns | Measure-Object -Minimum).Minimum
    $max  = ($validReturns | Measure-Object -Maximum).Maximum
    if ($min -eq $max) { return 0 }
    $binWidth = ($max - $min) / $bins
    foreach ($r in $validReturns) {
        $bin = [Math]::Floor(($r - $min) / $binWidth)
        if ($hist.ContainsKey($bin)) { $hist[$bin]++ } else { $hist[$bin] = 1 }
    }
    $total   = $validReturns.Count
    $entropy = 0
    foreach ($count in $hist.Values) {
        $prob     = $count / $total
        $entropy -= $prob * [Math]::Log($prob + 1e-10)
    }
    # Normalise to [0,1] by max possible entropy (ln of bin count) so the
    # value is a sample-size-independent "disorder ratio": ~0 = ordered /
    # trending, ~1 = uniform / maximally disordered. Thresholds downstream
    # are calibrated against this 0-1 scale, not the raw nat value.
    $maxEntropy = [Math]::Log($bins)
    if ($maxEntropy -le 0) { return 0 }
    return $entropy / $maxEntropy
}

function Calculate-PositionSize {
    param(
        [double]$equity, [double]$temperature,
        [double]$entropy, [double]$heat, [double]$momentum
    )
    $tempRatio      = if ($temperature -eq 0) { 1 } else { $BaseTemp / $temperature }
    $entropyFactor  = [Math]::Exp(-$entropy / 2)
    $heatFactor     = 1 - ($heat / $MaxHeat)
    $momentumFactor = if ($momentum -gt 0) { 1 + ($momentum / 100) } else { 1 / (1 + [Math]::Abs($momentum) / 100) }
    $baseSize       = $equity * 0.01
    $calculated     = $baseSize * [Math]::Pow($tempRatio, 2) * $entropyFactor * $heatFactor * $momentumFactor
    return [Math]::Min([Math]::Max($calculated, 0), $equity * 0.02)
}

function Get-MarketRecommendation {
    param(
        [double]$temperature, [double]$entropy, [double]$baseTemp,
        [bool]$trendUp, [double]$momentum, [double]$rsi,
        [double]$price, [double]$ma20, [double]$ma50
    )

    # --- Entropy / volatility-regime signal -------------------------------
    # Disorder + vol gate. Says nothing about price level.
    # Entropy is a normalised 0-1 disorder ratio (see Calculate-Entropy):
    # >0.85 = highly disordered (avoid), <0.55 = orderly/trending (favourable).
    if ($temperature -gt ($baseTemp * 1.5) -or $entropy -gt 0.85) {
        $entropySignal = "OUT"
    } elseif ($temperature -lt ($baseTemp * 0.75) -and $entropy -lt 0.55) {
        $entropySignal = "IN"
    } else {
        $entropySignal = "NEUTRAL"
    }

    # --- Price / technical-entry signal -----------------------------------
    # Looks at trend structure, momentum, RSI and where price sits vs MAs.
    if ($rsi -gt 70 -or ($ma50 -gt 0 -and $price -lt $ma50)) {
        # Overbought (poor entry) or below long-term trend (broken structure)
        $priceSignal = "OUT"
    } elseif ($trendUp -and $momentum -gt 0 -and $rsi -ge 35 -and $rsi -le 70 `
              -and ($ma20 -le 0 -or $price -le ($ma20 * 1.03))) {
        # Uptrend, positive momentum, healthy RSI, not extended above MA20
        $priceSignal = "IN"
    } else {
        $priceSignal = "NEUTRAL"
    }

    # --- Combined view ----------------------------------------------------
    if ($entropySignal -eq "OUT" -or $priceSignal -eq "OUT") {
        $overall = "OUT"
    } elseif ($priceSignal -eq "IN" -and $entropySignal -ne "OUT") {
        $overall = "IN"
    } else {
        $overall = "NEUTRAL"
    }

    return @{
        Overall       = $overall
        EntropySignal = $entropySignal
        PriceSignal   = $priceSignal
    }
}

function Analyze-Symbol {
    param(
        [string]$symbol, [double]$baseTemp,
        [double]$maxHeat, [double]$initialEquity
    )
    Write-Host "`nAnalyzing $symbol..." -ForegroundColor Cyan
    $data = Get-MarketData -symbol $symbol
    if (-not $data) { Write-Warning "Skipping $symbol - failed to retrieve data"; return $null }
    $prices = $data.indicators.quote[0].close
    if (-not $prices -or $prices.Count -eq 0) { Write-Warning "Skipping $symbol - no price data"; return $null }
    $validPrices = @()
    foreach ($price in $prices) { if ($price -ne $null) { $validPrices += $price } }
    if ($validPrices.Count -eq 0) { Write-Warning "Skipping $symbol - no valid prices"; return $null }
    $previous = $null
    $returns  = $validPrices | ForEach-Object {
        if ($previous -ne $null) { $r = ($_ - $previous) / $previous; $previous = $_; return $r }
        $previous = $_; return 0
    }
    $mas           = Calculate-MovingAverages -prices $validPrices
    $momentum      = Calculate-Momentum      -prices $validPrices
    $rsi           = Calculate-RSI           -prices $validPrices
    $temperature   = Calculate-Temperature   -returns $returns
    $entropy       = Calculate-Entropy       -returns $returns
    $trendUp       = $mas.ShortMA -gt $mas.LongMA
    $positionSize  = Calculate-PositionSize  -equity $initialEquity -temperature $temperature -entropy $entropy -heat 0 -momentum $momentum
    $rec = Get-MarketRecommendation -temperature $temperature -entropy $entropy -baseTemp $baseTemp -trendUp $trendUp -momentum $momentum -rsi $rsi -price $validPrices[-1] -ma20 $mas.ShortMA -ma50 $mas.LongMA
    return @{
        Symbol       = $symbol
        Price        = $validPrices[-1]
        Temperature  = $temperature
        Entropy      = $entropy
        PositionSize = $positionSize
        TempStatus   = if ($temperature -gt ($baseTemp * 1.5)) {"HIGH"} elseif ($temperature -lt ($baseTemp * 0.75)) {"LOW"} else {"MEDIUM"}
        EntropyStatus = if ($entropy -gt 0.85) {"HIGH"} elseif ($entropy -lt 0.55) {"LOW"} else {"MEDIUM"}
        Trend        = if ($trendUp) {"UP"} else {"DOWN"}
        Momentum     = $momentum
        RSI          = $rsi
        Recommendation = $rec.Overall
        EntropySignal  = $rec.EntropySignal
        PriceSignal    = $rec.PriceSignal
        MA20         = $mas.ShortMA
        MA50         = $mas.LongMA
        DataPoints   = $validPrices.Count
        Timestamp    = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    }
}

# --- Run Trading System ---
if (-not $SkipTrading) {
    Write-Host "`n=== Trading System Analysis ===" -ForegroundColor Green
    Write-Host "Symbols: $($Symbols -join ', ')"   -ForegroundColor Yellow
    Write-Host "Base Temperature: $BaseTemp"        -ForegroundColor Yellow
    Write-Host "Initial Equity: $($InitialEquity.ToString('C'))" -ForegroundColor Yellow
    Write-Host ("=" * 50)                           -ForegroundColor Green

    $tradingResults = @()
    foreach ($symbol in $Symbols) {
        $result = Analyze-Symbol -symbol $symbol -baseTemp $BaseTemp -maxHeat $MaxHeat -initialEquity $InitialEquity
        if ($result) { $tradingResults += $result }
        Start-Sleep -Milliseconds 500
    }

    if ($tradingResults.Count -gt 0) {
        Write-Host "`n=== ANALYSIS RESULTS ===" -ForegroundColor Green
        $displayResults = $tradingResults | ForEach-Object {
            [PSCustomObject]@{
                Symbol       = $_.Symbol
                Price        = if ($_.Price -gt 1000) { $_.Price.ToString("C0") } else { $_.Price.ToString("C2") }
                Recommendation = $_.Recommendation
                EntropySig   = $_.EntropySignal
                PriceSig     = $_.PriceSignal
                Trend        = $_.Trend
                Momentum     = "{0:N2}%" -f $_.Momentum
                RSI          = "{0:N1}"  -f $_.RSI
                Temperature  = "{0:N1} ($($_.TempStatus))"    -f $_.Temperature
                Entropy      = "{0:N3} ($($_.EntropyStatus))"  -f $_.Entropy
                PositionSize = $_.PositionSize.ToString("C0")
                MA20         = if ($_.MA20 -gt 1000) { $_.MA20.ToString("C0") } else { $_.MA20.ToString("C2") }
                MA50         = if ($_.MA50 -gt 1000) { $_.MA50.ToString("C0") } else { $_.MA50.ToString("C2") }
            }
        }
        $displayResults | Format-Table -AutoSize

        Write-Host "`n=== RECOMMENDATION SUMMARY ===" -ForegroundColor Green
        foreach ($result in $tradingResults) {
            $color = if ($result.Recommendation -eq "IN") { "Green" } elseif ($result.Recommendation -eq "OUT") { "Red" } else { "Yellow" }
            Write-Host "$($result.Symbol): $($result.Recommendation)  (Entropy: $($result.EntropySignal) | Price: $($result.PriceSignal))" -ForegroundColor $color
        }

        $dataDir = Join-Path $ScriptDir "data"
        if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }

        $timestamp  = Get-Date -Format "yyyyMMdd_HHmmss"
        $jsonOutput = $tradingResults | ConvertTo-Json -Depth 3
        $jsonFile   = Join-Path $ScriptDir "data\TradingAnalysis_$timestamp.json"
        $jsonOutput | Out-File -FilePath $jsonFile
        Write-Host "`nFull results saved to: $jsonFile" -ForegroundColor Cyan

        # Write a fixed-path snapshot for the HTML report
        $latestTradingJson = Join-Path $ScriptDir "data\latest_trading.json"
        $jsonOutput | Out-File -FilePath $latestTradingJson -Encoding utf8
    } else {
        Write-Error "No valid analysis results obtained for any symbols."
    }
}

# ============================================================================
# REDHOOD SYSTEMS - Feed Aggregator
# ============================================================================

if (-not $SkipRedHood) {
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
        Write-Host "  ANTHROPIC_API_KEY=sk-ant-your-key-here"  -ForegroundColor Yellow
        exit 1
    }

    Write-Host "`nRunning RedHood Systems (last $Hours hours)..." -ForegroundColor Cyan
    $env:PYTHONIOENCODING = "utf-8"
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

    $latestTradingJson = Join-Path $ScriptDir "data\latest_trading.json"
    if (-not $SkipTrading -and (Test-Path $latestTradingJson)) {
        python "$ScriptDir\redhood_aggregator.py" --hours $Hours --trading-json $latestTradingJson
    } else {
        python "$ScriptDir\redhood_aggregator.py" --hours $Hours
    }
}
