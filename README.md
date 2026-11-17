# ₿ BTC Sentiment Agent

A Python agent that runs once a day. It scrapes Bitcoin forums, news, exchange order books, trades, derivatives and on-chain data, scores the overall picture, and publishes the result as a static dashboard website.

**It is free to run.** GitHub Actions does the daily scraping and GitHub Pages hosts the site, so you don't need a server.

> Research tool only — not financial advice. The dashboard describes current conditions; it doesn't predict prices.

---

## What it collects

| Area | Sources | Why it matters |
|---|---|---|
| **Forum & social sentiment** | Reddit (r/Bitcoin, r/BitcoinMarkets, r/CryptoCurrency, r/btc, r/CryptoMarkets — posts + daily-discussion and top-post comments), BitcoinTalk (Discussion, Speculation, Economics boards), StockTwits (users self-tag Bullish/Bearish) | What retail traders are saying, and whether the mood is shifting |
| **News tone** | CoinDesk, Cointelegraph, Decrypt, Bitcoin Magazine, The Block, CryptoSlate, Google News (RSS, last 36h) | How the news is framing Bitcoin |
| **Price & trend** | CoinGecko (Kraken/Coinbase fallback) | 50/200-day averages, RSI, MACD, volatility, distance from ATH, Mayer multiple |
| **Major buy/sell orders** | Order books from Coinbase, Kraken, Bitstamp, Gemini, OKX, Binance | Biggest bid/ask "walls" grouped across exchanges, single orders of 20 BTC or more, and depth imbalance within ±0.5/1/2/5% of price |
| **Aggressive flow & whales** | Binance 24h taker volume; recent trades on Coinbase/Kraken/Binance | Whether buyers or sellers are crossing the spread, plus prints of $500k or more |
| **Leverage** *(gap filled)* | Funding/OI from Hyperliquid, Deribit, OKX, Binance, Bybit; OKX/Binance long-short ratio; Deribit put/call OI | Crowded leverage often comes before sharp moves |
| **Institutional demand** *(gap filled)* | US spot-ETF daily net flows (Farside), IBIT volume | Since 2024, ETF flows have been one of the biggest drivers of BTC price |
| **Market mood** *(gap filled)* | Crypto Fear & Greed index | Read contrarian: extreme greed counts as a risk signal |
| **Retail attention** *(gap filled)* | Wikipedia "Bitcoin" pageviews | Rising attention shows new money arriving |
| **Network health** *(gap filled)* | mempool.space: fees, mempool, hashrate, difficulty | Measures on-chain demand and miner confidence |
| **Macro backdrop** *(gap filled)* | S&P 500, Nasdaq, DXY, gold, 10y yield, MSTR (Yahoo Finance) | BTC trades as a risk asset, so macro moves matter |

## How the score works

Each input becomes a sub-score from −1 to +1. The composite is their weighted average, scaled to **−100 … +100** and labeled from *Strong bearish lean* to *Strong bullish lean*.

- **Read with the market:** trend, momentum, ETF flows, order-book depth, taker flow, forum and news mood.
- **Read contrarian:** Fear & Greed, funding rates, long/short ratio and put/call. When the crowd is all-in, a flush becomes more likely.
- **Confidence** depends on how many inputs agree and how many sources worked that day. If fewer than 6 inputs come back, confidence is always shown as *Low*.
- Weights are set in `config.yaml`. If a source fails, it is skipped and the remaining weights are rebalanced.

**AI layer (optional, recommended):** if you set `ANTHROPIC_API_KEY`, Claude does two extra things.
1. It re-scores the ~150 highest-engagement posts and headlines. Claude handles sarcasm and slang that word-list scoring misses.
2. It writes the daily analyst brief at the top of the page, using only that day's collected data.

Without a key, the brief is a rules-based summary.

---

## Setup (about 10 minutes)

1. **Create a GitHub repo** and upload this folder. A private repo works, but GitHub Pages on a private repo requires a paid plan. A public repo is free.
2. **Turn on Pages:** go to repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Add secrets** under **Settings → Secrets and variables → Actions → New repository secret**:
   | Secret | Needed? | Where to get it |
   |---|---|---|
   | `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Strongly recommended. Reddit usually blocks anonymous requests from cloud servers | reddit.com/prefs/apps → "create another app" → type **script** |
   | `ANTHROPIC_API_KEY` | Optional. Adds the AI brief and better sentiment scoring | console.anthropic.com (roughly a few cents per day) |
   | `COINGECKO_API_KEY` | Optional. Raises rate limits | coingecko.com → free Demo API key |
4. **Run it once:** open **Actions → Daily BTC sentiment run → Run workflow**. After it finishes, your site is live at `https://<you>.github.io/<repo>/`.
5. After that, it runs automatically every day at 12:17 UTC. To change the time, edit the `cron` line in `.github/workflows/daily.yml`.

### Run locally

```bash
pip install -r requirements.txt
python -m agent.main --sample   # offline demo with fake data → open site_out/index.html
python -m agent.main            # real run (set the env vars above first)
python -m pytest -q             # parser tests, no network needed
```

---

## Things to know

- **US geo-blocks:** Binance futures and Bybit block US IP addresses, including GitHub's servers. The agent skips them and relies on Hyperliquid, Deribit, OKX, Coinbase, Kraken and the others. The "Data sources" table at the bottom of the site shows which sources worked each day.
- **Order-book walls are a snapshot.** Large orders can be pulled or spoofed, so read them as "where liquidity sat at run time."
- **Whale-trade lists** only cover the last few minutes to hours of public trade history at run time. The 24h taker-flow number is the more reliable figure.
- **Farside ETF data** comes from scraping an HTML table. It's the most fragile source and may fail some days.
- **Not included** (each needs a paid API or breaks the platform's rules): X/Twitter, Telegram, Discord, Glassnode/CryptoQuant on-chain analytics, CoinGlass liquidation heatmaps. Each collector is a separate file in `agent/collectors/`, so you can add one later if you get access.
- **Be polite:** the agent identifies itself, waits between requests to the same site, and runs once a day. Put your own contact address in `http.user_agent` in `config.yaml`.
- **History:** every run adds a row to `data/history.json`, which gets committed to the repo. The score-history charts get more useful over time. The full daily snapshot is also published at `/data/latest.json`.

## Project layout

```
agent/
  main.py              orchestrator (collect → score → brief → save → build site)
  collectors/          prices, orderbook, flow, derivatives, onchain, indicators, social, news
  analysis/            sentiment (VADER + crypto lexicon), technicals, signals, llm (Claude)
  site/                build.py + templates/index.html.j2  (Chart.js dashboard)
  sample_data.py       synthetic data for --sample
config.yaml            sources, thresholds, signal weights
.github/workflows/daily.yml
tests/
```
