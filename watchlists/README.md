# Watchlists

This folder is the bridge between your **external watchlists** and the RedHood
pipeline. Drop your TradingView and Yahoo Finance exports here, run one command,
and the trading analysis (`run.ps1`) plus the Python pipeline will analyze *your*
symbols instead of the hardcoded default list.

```
watchlists/
├── tradingview.txt      <- replace with your TradingView export (.txt)
├── yahoo_finance.csv    <- replace with your Yahoo Finance export (.csv)
├── *.example.*          <- reference format samples (never loaded)
└── README.md            <- this file
```

The two files shipped here are **seeded with the old default symbols**
(NU + BTC + FAANG + WMT) so everything works immediately. Overwrite their
contents with your real exports.

## How the files are picked up

- Every `*.txt` in this folder is parsed as a **TradingView** export.
- Every `*.csv` in this folder is parsed as a **Yahoo Finance** export.
- Any file with `.example.` in its name is **ignored** (reference only).

You can have several of each (e.g. `tradingview_macro.txt`,
`tradingview_crypto.txt`) — they all merge into one deduped list.

## Exporting from TradingView

1. Open your watchlist (right-hand panel on the chart).
2. Click the **`⋮`** (three dots) at the top of the watchlist → **Export watchlist…**
3. Save the `.txt` file, then replace `tradingview.txt` here with it.

The export looks like comma-separated `EXCHANGE:SYMBOL` tokens with optional
`###Section` headers — see `tradingview.example.txt`.

## Exporting from Yahoo Finance

Yahoo Finance has no one-click watchlist export, so use either:

- **Portfolio export:** My Portfolio → your portfolio → **Export** → downloads a
  `.csv` whose first column is `Symbol`. Replace `yahoo_finance.csv` with it.
- **Manual:** make a `.csv` with a `Symbol` header and one ticker per line (a bare
  one-ticker-per-line list also works). See `yahoo_finance.example.csv`.

## Syncing

From the repo root:

```bash
# Parse exports, merge + dedupe, update the watchlist table in redhood.db
python watchlist.py --sync

# Preview the merge without touching the DB
python watchlist.py --dry-run

# Show the current watchlist
python watchlist.py --list
```

Then just run the pipeline as usual — `run.ps1` reads the synced symbols
automatically (pass `-Symbols "AAPL","MSFT"` to override for a single run):

```powershell
.\run.ps1
```

## Symbol normalization

Source formats are mapped onto the yfinance convention the pipeline uses:

| Source token        | Becomes    | Class  |
|---------------------|------------|--------|
| `NASDAQ:AAPL`       | `AAPL`     | equity |
| `NYSE:BRK.B`        | `BRK-B`    | equity |
| `TSX:RY`            | `RY.TO`    | equity |
| `BINANCE:BTCUSDT`   | `BTC-USD`  | crypto |
| `OANDA:EURUSD`      | `EURUSD=X` | fx     |
| `SP:SPX`            | `^GSPC`    | index  |

Symbols already in yfinance form (`AAPL`, `BTC-USD`, `^GSPC`, `EURUSD=X`) pass
through unchanged. Tokens that can't be recognized are reported by `--sync` /
`--dry-run` and skipped rather than silently dropped.

A symbol that disappears from every source on a later sync is **deactivated**
(`active = 0`), not deleted, so its history is preserved.

## Privacy note

These files list only tickers — no credentials. If you'd rather not commit your
personal watchlist, add `watchlists/tradingview.txt` and
`watchlists/yahoo_finance.csv` to `.gitignore` (the `.example.` files can stay).
