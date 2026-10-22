# OKX Automated Trader

> **中文导读**：这是一个跑在 OKX 上的**多指标自动交易脚本**，支持 SNDK（代币化股票）、ETH、SOL 永续合约。
> 核心是多指标打分系统（RSI / MACD / 布林带 / EMA / 随机 RSI / 量能），
> 综合打分 ≥3 做多、≤-3 做空，中间不动。带仓位管理、止损止盈、移动止损、防插针冷却。
> **默认模拟盘（paper）**，用 `--live` 才切实盘。国内访问需配 SOCKS5/HTTP 代理。
>
> 快速上手：`pip install -r requirements.txt` → 在 `config.json` 填 API 密钥 → `python trader.py`。
> 详见下方完整英文文档。

Automated trading script for OKX exchange with technical analysis and risk management. Supports SNDK (tokenized stock), ETH, and SOL futures contracts.

## Features

- **Technical Analysis**: RSI, MACD, Bollinger Bands, EMA crossovers, Stochastic RSI, Volume analysis
- **Risk Management**: Position sizing (fixed % or Kelly criterion), stop-loss, take-profit, trailing stops
- **Anti-Spike Protection**: 5-second cooldown after order fills
- **Paper Trading**: Test strategies without risking real money
- **Proxy Support**: SOCKS5/HTTP proxy for mainland China users
- **Comprehensive Logging**: Trade logs in CSV, application logs with rotation

## Prerequisites

- Python 3.9+
- OKX account with API keys
- VPN/Proxy (if accessing from mainland China)

## Installation

1. **Clone or download** this folder to your local machine

2. **Install dependencies**:
   ```bash
   cd okx-auto-trader
   pip install -r requirements.txt
   ```

3. **Configure API keys** in `config.json`:
   ```json
   {
     "okx": {
       "api_key": "YOUR_API_KEY",
       "secret": "YOUR_SECRET",
       "password": "YOUR_PASSPHRASE"
     }
   }
   ```

4. **Configure proxy** (if needed):
   ```json
   {
     "proxy": {
       "enabled": true,
       "protocol": "socks5",
       "host": "127.0.0.1",
       "port": 1080
     }
   }
   ```

## Configuration

### Trading Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `symbols` | Trading pairs | SNDK, ETH, SOL |
| `primary_symbol` | Main trading pair | SNDK/USDT:USDT |
| `leverage` | Leverage multiplier | 50 |
| `trade_mode` | `paper` or `live` | paper |
| `trade_interval_seconds` | Analysis interval | 60 |

### Risk Management

| Parameter | Description | Default |
|-----------|-------------|---------|
| `max_position_size_pct` | Max position as % of balance | 5% |
| `stop_loss_pct` | Stop-loss percentage | 2% |
| `take_profit_pct` | Take-profit percentage | 4% |
| `trailing_stop_pct` | Trailing stop percentage | 1.5% |
| `max_open_positions` | Maximum concurrent positions | 3 |
| `max_daily_loss_pct` | Daily loss limit | 10% |
| `cooldown_after_fill_seconds` | Anti-spike cooldown | 5 |
| `use_kelly_criterion` | Use Kelly for sizing | false |
| `kelly_fraction` | Kelly fraction (0-1) | 0.25 |

### Technical Indicators

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rsi_period` | RSI period | 14 |
| `rsi_overbought` | RSI overbought level | 70 |
| `rsi_oversold` | RSI oversold level | 30 |
| `macd_fast/slow/signal` | MACD parameters | 12/26/9 |
| `bb_period` | Bollinger Bands period | 20 |
| `bb_std_dev` | Bollinger Bands std dev | 2.0 |
| `signal_threshold` | Minimum score to trade | 3 |

## Usage

### Basic Usage

```bash
# Paper trading (default)
python trader.py

# Live trading
python trader.py --live

# Force paper mode
python trader.py --paper
```

### Advanced Options

```bash
# Custom config file
python trader.py --config my_config.json

# Trade specific symbols
python trader.py --symbols "SNDK/USDT:USDT" "ETH/USDT:USDT"

# Custom interval (in seconds)
python trader.py --interval 30
```

### Command Line Arguments

| Argument | Description |
|----------|-------------|
| `--config` | Path to config file (default: config.json) |
| `--paper` | Force paper trading mode |
| `--live` | Force live trading mode |
| `--symbols` | Override symbols to trade |
| `--interval` | Override trade interval |

## Signal Generation

The script uses a multi-indicator scoring system:

- **Score >= 3**: BUY signal
- **Score <= -3**: SELL signal
- **Score between -3 and 3**: HOLD (no action)

### Scoring Logic

| Indicator | Bullish | Bearish |
|-----------|---------|---------|
| RSI < 30 | +2 | - |
| RSI > 70 | - | -2 |
| MACD crossover up | +2 | - |
| MACD crossover down | - | -2 |
| Price at lower BB | +2 | - |
| Price at upper BB | - | -2 |
| EMA crossover up | +2 | - |
| EMA crossover down | - | -2 |
| Volume spike | +1/-1 amplifies | +1/-1 amplifies |
| StochRSI oversold | +1 | - |
| StochRSI overbought | - | -1 |

## Output Files

### trades.csv

All trades are logged to `trades.csv` with the following columns:
- timestamp, symbol, side, price, amount, cost, stop_loss, take_profit, pnl, mode

### trader.log

Application log with rotation (max 50MB per file, 5 backups).

## Safety Features

1. **Paper Trading Default**: Starts in paper mode by default
2. **Daily Loss Limit**: Stops trading if daily loss exceeds threshold
3. **Position Limits**: Maximum number of open positions
4. **Cooldown Period**: 5-second delay between orders
5. **Connection Testing**: Verifies API connection before trading
6. **Graceful Shutdown**: Ctrl+C stops cleanly and shows final status

## Getting OKX API Keys

1. Log in to [OKX](https://www.okx.com)
2. Go to **Account** → **API**
3. Click **Create API Key**
4. Set permissions: **Trade** (read-only is not enough)
5. Enable **IP Whitelist** for security
6. Copy API Key, Secret, and Passphrase

## Proxy Setup (Mainland China)

### Using Shadowsocks

1. Install a SOCKS5 proxy client (e.g., Shadowsocks, v2rayN)
2. Configure local SOCKS5 proxy (default: 127.0.0.1:1080)
3. Update `config.json`:
   ```json
   {
     "proxy": {
       "enabled": true,
       "protocol": "socks5",
       "host": "127.0.0.1",
       "port": 1080
     }
   }
   ```

### Using HTTP Proxy

```json
{
  "proxy": {
    "enabled": true,
    "protocol": "http",
    "host": "127.0.0.1",
    "port": 7890
  }
}
```

## Troubleshooting

### Connection Issues

```
Error: Connection failed
```

**Solution**:
- Check API keys are correct
- Verify proxy is running and accessible
- Try testing with `curl` through proxy
- Check OKX API status page

### Rate Limit Errors

```
Error: Rate limit exceeded
```

**Solution**:
- Increase `trade_interval_seconds`
- Reduce number of symbols
- Check `enableRateLimit` is true in config

### Order Rejected

```
Error: Order rejected
```

**Solution**:
- Check sufficient balance
- Verify leverage is set correctly
- Check minimum order size for symbol
- Ensure position mode matches (long/short vs net)

## Disclaimer

⚠️ **WARNING**: This script is for educational purposes only.

- Trading cryptocurrencies involves significant risk
- Past performance does not guarantee future results
- Never trade with money you cannot afford to lose
- Always test thoroughly in paper mode first
- The authors are not responsible for any financial losses

## License

MIT License - Use at your own risk.

## Support

For issues or questions:
1. Check the logs (`trader.log`)
2. Verify configuration (`config.json`)
3. Test connection with paper mode first
4. Review OKX API documentation: https://www.okx.com/docs-v5/
