# US Market Update Dashboard

Bilingual US market update dashboard in Traditional Chinese (`zh.html`) and English (`en.html`).

The compiled official snapshot is the official Friday 27 November 2026 early close (13:00 ET), kept in `data/official-snapshot.json` and written into the tiles, one-day tables, and quote-refresh script. The pages can also show optional on-open delayed or live quotes.

The site is public. GitHub Pages deploys the `main` branch from `/`. There is no password gate.

This is not investment advice.

## Automatic updates

`.github/workflows/update-market-snapshot.yml` runs `scripts/market_update.py` on the free GitHub-hosted Ubuntu runner. It does not use a paid Actions plan, a paid market-data vendor, or a repository secret. Quotes come from the public CNBC quote service already used by the pages (`https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol`), with Yahoo Finance daily bars as a free check. If those two disagree by more than 0.5% on a cash close, that close is left unchanged and the run fails instead of picking one silently. Smaller differences are kept, with CNBC as the cash-close source, and written into the run log.

GitHub's scheduler is UTC and the US observes daylight saving time, so each New York time is listed at both the EST and EDT offsets:

| New York time | EDT cron (UTC) | EST cron (UTC) |
| --- | --- | --- |
| 08:00 | 12:00 | 13:00 |
| 16:15 | 20:15 | 21:15 |

The script allows 16:05–17:05 ET for the close and 07:50–08:45 ET for the morning. The offset that does not match that window exits successfully and writes nothing. Saturdays, Sundays, and NYSE full holidays are the same kind of no-op. The holiday and early-close lists for 2026–2028 are in `scripts/nyse_calendar.py`. Early-close days (the day after Thanksgiving, Christmas Eve, and 3 July when the NYSE lists it) are still trading days. The 16:15 ET job runs, and the snapshot is labeled with the actual 13:00 ET close rather than a full 16:00 session.

A second run of the same session does not create an empty commit. Overlapping runs share the `us-market-snapshot` concurrency group and wait instead of cancelling each other. The workflow is not triggered by `push`, so its own commit does not start another run.

### What each run writes

**16:15 ET, post-close.** Official cash closes for the S&P 500, Dow, Nasdaq Composite, Nasdaq-100, SOX, Russell 2000, and VIX; the 11 Select Sector SPDRs; and SPY, QQQ, RSP, QQEW, and SPYM. Day changes use the previous official cash close stored in the snapshot. Distances from highs use the ATH levels already in the snapshot. The VIX path keeps the last 14 equity sessions and does not insert a holiday. Brent, WTI, gold, and silver use the CNBC settlement when that settlement is dated the same session; a live futures last is not labeled as the official settle. DXY uses CNBC. USD/JPY and offshore USD/CNH use the Yahoo daily bar, and a CNBC difference is recorded rather than hidden. The US10Y market yield, when published by the quote service, is only a subline. It does not replace the Treasury cash yield already on the page.

**08:00 ET, morning.** Cross-assets can move to the latest print and are labeled as intraday when that print is not the stored official settlement or FX close. Equity, VIX, sector, and ETF official closes are not replaced with pre-market, futures, or overnight prices, and equity or VIX status lines are not rewritten from those prints. A cross-asset caption changes only when that cross-asset figure changes.

**Factual status lines, post-close only.** The same rules rewrite short status pills, hero captions, the equity-tile captions, the ATH-chart title, the one-day date chips, and a sector leader/laggard chip. A line is written only from the official snapshot: distance from the stored ATH (outside a correction, in a correction, a drawdown deeper than 20%, or a new closing high), the VIX band (below 20, out of the 25–35 mid-band, inside it, above it, or a close at or above 40) plus whether the stored 14-session path contains a close at or above 40, recapture of a 5 November 2026 close when that anchor is in the snapshot (S&P 7,353.73 and Nasdaq Composite 24,315.00), a stored up/down streak, and the leader and laggard among the 11 sector funds. If an anchor or streak is not stored, that clause is omitted and the run log says why. Year-to-date figures are not repeated in those pills.

**Left manual.** The headline call, probability bands, commentary paragraphs, GDP, PCE, CPI, PPI, NFP, official HY OAS, ChartRow breadth, SSGA holding weights, and official Treasury cash yields are not rewritten. The script does not invent unpublished official prints and does not use an LLM. `#auto-snapshot-note` says that the factual status lines follow the closes and that the call and commentary stay on the last human edition.

The on-open quote refresh in each page still runs. The cron only persists the compiled snapshot that refresh compares against.

### Run it manually

From the Actions tab, choose **Update market snapshot**, then **Run workflow**. The input is:

- `post-close` — write the official cash close if that session has already closed
- `morning` — refresh cross-assets only

Locally, from the repository root:

```bash
python3 -m unittest scripts/test_market_update.py
python3 scripts/market_update.py --job post-close --dry-run
python3 scripts/market_update.py --job morning --dry-run
python3 scripts/market_update.py --render-snapshot --dry-run
```

`--dry-run` prints the plan and does not write files. `--render-snapshot` rewrites the tiles from `data/official-snapshot.json` without fetching. A manual post-close before the cash close, and any run on a weekend or NYSE holiday, exits 0 without writing.
