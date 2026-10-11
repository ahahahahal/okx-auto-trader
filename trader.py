#!/usr/bin/env python3
"""
OKX Automated Trading Script
Trades SNDK/ETH/SOL with technical analysis and risk management.
"""

import json
import time
import logging
import os
import sys
import csv
from datetime import datetime, timedelta
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Tuple

import ccxt
import numpy as np
import pandas as pd
import ta
from colorama import init, Fore, Style
from tabulate import tabulate

# Initialize colorama for Windows
init(autoreset=True)

# ─── Configuration ────────────────────────────────────────────────────────────

def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from JSON file."""
    path = Path(__file__).parent / config_path
    if not path.exists():
        print(f"{Fore.RED}Config file not found: {path}")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

CONFIG = load_config()

# ─── Logging Setup ────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """Configure logging with file rotation."""
    log_cfg = CONFIG['logging']
    log_file = Path(__file__).parent / log_cfg['file']
    
    logger = logging.getLogger('OKXTrader')
    logger.setLevel(getattr(logging, log_cfg['level']))
    
    # File handler with rotation
    fh = RotatingFileHandler(
        log_file,
        maxBytes=log_cfg['max_log_size_mb'] * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    fh.setLevel(logging.DEBUG)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

logger = setup_logging()

# ─── Trade Logger ─────────────────────────────────────────────────────────────

class TradeLogger:
    """Logs trades to CSV file."""
    
    def __init__(self):
        self.filepath = Path(__file__).parent / CONFIG['logging']['trade_log']
        self._ensure_file()
    
    def _ensure_file(self):
        if not self.filepath.exists():
            with open(self.filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'symbol', 'side', 'price', 'amount',
                    'cost', 'stop_loss', 'take_profit', 'pnl', 'mode'
                ])
    
    def log_trade(self, trade: dict):
        with open(self.filepath, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                trade.get('timestamp', datetime.now().isoformat()),
                trade.get('symbol', ''),
                trade.get('side', ''),
                trade.get('price', 0),
                trade.get('amount', 0),
                trade.get('cost', 0),
                trade.get('stop_loss', 0),
                trade.get('take_profit', 0),
                trade.get('pnl', 0),
                trade.get('mode', 'live')
            ])

trade_logger = TradeLogger()

# ─── OKX Exchange Connection ──────────────────────────────────────────────────

class OKXConnection:
    """Manages connection to OKX exchange via ccxt."""
    
    def __init__(self, config: dict):
        self.config = config
        self.exchange = self._create_exchange()
        self.paper_mode = config['trading']['trade_mode'] == 'paper'
        self.paper_balance = 10000.0  # Starting paper balance in USDT
        self.paper_positions: Dict[str, dict] = {}
        self.last_fill_time: Dict[str, float] = {}
    
    def _create_exchange(self) -> ccxt.okx:
        """Create and configure OKX exchange instance."""
        okx_cfg = self.config['okx']
        proxy_cfg = self.config['proxy']
        
        exchange_params = {
            'apiKey': okx_cfg['api_key'],
            'secret': okx_cfg['secret'],
            'password': okx_cfg['password'],
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',
                'adjustForTimeDifference': True,
            }
        }
        
        # Configure proxy
        if proxy_cfg['enabled']:
            proxy_url = self._build_proxy_url(proxy_cfg)
            exchange_params['proxies'] = {
                'http': proxy_url,
                'https': proxy_url,
            }
            logger.info(f"Proxy configured: {proxy_cfg['protocol']}://{proxy_cfg['host']}:{proxy_cfg['port']}")
        
        exchange = ccxt.okx(exchange_params)
        
        if okx_cfg.get('sandbox', False):
            exchange.set_sandbox_mode(True)
            logger.info("Sandbox mode enabled")
        
        return exchange
    
    def _build_proxy_url(self, proxy_cfg: dict) -> str:
        """Build proxy URL from configuration."""
        protocol = proxy_cfg['protocol']
        host = proxy_cfg['host']
        port = proxy_cfg['port']
        
        if proxy_cfg.get('username') and proxy_cfg.get('password'):
            return f"{protocol}://{proxy_cfg['username']}:{proxy_cfg['password']}@{host}:{port}"
        return f"{protocol}://{host}:{port}"
    
    def test_connection(self) -> bool:
        """Test exchange connection."""
        try:
            self.exchange.load_markets()
            logger.info(f"{Fore.GREEN}✓ Connected to OKX successfully")
            logger.info(f"  Markets loaded: {len(self.exchange.markets)}")
            return True
        except Exception as e:
            logger.error(f"{Fore.RED}✗ Connection failed: {e}")
            return False
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> pd.DataFrame:
        """Fetch OHLCV data and return as DataFrame."""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            return pd.DataFrame()
    
    def fetch_ticker(self, symbol: str) -> dict:
        """Fetch current ticker data."""
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {symbol}: {e}")
            return {}
    
    def set_leverage(self, symbol: str, leverage: int):
        """Set leverage for a symbol."""
        try:
            self.exchange.set_leverage(leverage, symbol)
            logger.info(f"Leverage set to {leverage}x for {symbol}")
        except Exception as e:
            logger.warning(f"Could not set leverage for {symbol}: {e}")
    
    def check_cooldown(self, symbol: str) -> bool:
        """Check if cooldown period has passed after last fill."""
        cooldown = self.config['risk_management']['cooldown_after_fill_seconds']
        if symbol in self.last_fill_time:
            elapsed = time.time() - self.last_fill_time[symbol]
            if elapsed < cooldown:
                logger.debug(f"Cooldown active for {symbol}: {cooldown - elapsed:.1f}s remaining")
                return False
        return True
    
    def create_order(self, symbol: str, side: str, amount: float, 
                     price: Optional[float] = None, params: dict = None) -> dict:
        """Create an order (live or paper)."""
        if not self.check_cooldown(symbol):
            return {'status': 'rejected', 'reason': 'cooldown'}
        
        if self.paper_mode:
            return self._paper_order(symbol, side, amount, price)
        return self._live_order(symbol, side, amount, price, params or {})
    
    def _paper_order(self, symbol: str, side: str, amount: float, price: Optional[float]) -> dict:
        """Simulate order execution for paper trading."""
        ticker = self.fetch_ticker(symbol)
        if not ticker:
            return {'status': 'error', 'reason': 'no_ticker'}
        
        exec_price = ticker['last']
        cost = exec_price * amount
        
        if side == 'buy':
            if cost > self.paper_balance:
                return {'status': 'rejected', 'reason': 'insufficient_balance'}
            self.paper_balance -= cost
            self.paper_positions[symbol] = {
                'side': 'long',
                'amount': amount,
                'entry_price': exec_price,
                'timestamp': datetime.now().isoformat()
            }
        elif side == 'sell':
            if symbol in self.paper_positions:
                pos = self.paper_positions[symbol]
                pnl = (exec_price - pos['entry_price']) * amount
                if pos['side'] == 'short':
                    pnl = -pnl
                self.paper_balance += cost + pnl
                del self.paper_positions[symbol]
            else:
                self.paper_balance += cost
                self.paper_positions[symbol] = {
                    'side': 'short',
                    'amount': amount,
                    'entry_price': exec_price,
                    'timestamp': datetime.now().isoformat()
                }
        
        self.last_fill_time[symbol] = time.time()
        
        order = {
            'id': f'paper_{int(time.time()*1000)}',
            'symbol': symbol,
            'side': side,
            'amount': amount,
            'price': exec_price,
            'cost': cost,
            'status': 'filled',
            'mode': 'paper',
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"{Fore.CYAN}[PAPER] {side.upper()} {amount} {symbol} @ {exec_price}")
        return order
    
    def _live_order(self, symbol: str, side: str, amount: float, 
                    price: Optional[float], params: dict) -> dict:
        """Execute real order on OKX."""
        try:
            order_type = 'limit' if price else 'market'
            order = self.exchange.create_order(symbol, order_type, side, amount, price, params)
            self.last_fill_time[symbol] = time.time()
            
            logger.info(f"{Fore.GREEN}[LIVE] {side.upper()} {amount} {symbol} @ {order.get('price', 'market')}")
            return order
        except Exception as e:
            logger.error(f"Order failed for {symbol}: {e}")
            return {'status': 'error', 'reason': str(e)}
    
    def get_balance(self) -> float:
        """Get current balance."""
        if self.paper_mode:
            return self.paper_balance
        try:
            balance = self.exchange.fetch_balance()
            return float(balance.get('USDT', {}).get('free', 0))
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0
    
    def get_positions(self) -> dict:
        """Get current positions."""
        if self.paper_mode:
            return self.paper_positions
        try:
            positions = self.exchange.fetch_positions()
            return {p['symbol']: p for p in positions if float(p.get('contracts', 0)) > 0}
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return {}

# ─── Technical Analysis ───────────────────────────────────────────────────────

class TechnicalAnalyzer:
    """Calculates technical indicators and generates signals."""
    
    def __init__(self, config: dict):
        self.config = config['indicators']
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all technical indicators."""
        if df.empty or len(df) < 30:
            return df
        
        # RSI
        df['rsi'] = ta.momentum.rsi(df['close'], window=self.config['rsi_period'])
        
        # MACD
        macd = ta.trend.MACD(
            df['close'],
            window_fast=self.config['macd_fast'],
            window_slow=self.config['macd_slow'],
            window_sign=self.config['macd_signal']
        )
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_hist'] = macd.macd_diff()
        
        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            df['close'],
            window=self.config['bb_period'],
            window_dev=self.config['bb_std_dev']
        )
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_middle'] = bb.bollinger_mavg()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        
        # EMAs
        df['ema_fast'] = ta.trend.ema_indicator(df['close'], window=self.config['ema_fast'])
        df['ema_slow'] = ta.trend.ema_indicator(df['close'], window=self.config['ema_slow'])
        
        # ATR for volatility
        df['atr'] = ta.volatility.average_true_range(
            df['high'], df['low'], df['close'],
            window=self.config['atr_period']
        )
        
        # Volume MA
        df['volume_ma'] = df['volume'].rolling(window=self.config['volume_ma_period']).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # Stochastic RSI
        stoch_rsi = ta.momentum.stochrsi(df['close'], window=self.config['rsi_period'])
        df['stoch_rsi_k'] = ta.momentum.stochrsi_k(df['close'], window=self.config['rsi_period'])
        df['stoch_rsi_d'] = ta.momentum.stochrsi_d(df['close'], window=self.config['rsi_period'])
        
        return df
    
    def generate_signal(self, df: pd.DataFrame) -> Tuple[str, int, dict]:
        """
        Generate trading signal based on multiple indicators.
        Returns: (signal, score, details)
        signal: 'buy', 'sell', or 'hold'
        score: integer from -5 to +5 (positive = bullish)
        """
        if df.empty or len(df) < 30:
            return 'hold', 0, {'reason': 'insufficient_data'}
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 0
        reasons = []
        
        # ── RSI Signal ─────────────────────────────────────────────────────────
        rsi = latest['rsi']
        if rsi < self.config['rsi_oversold']:
            score += 2
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi > self.config['rsi_overbought']:
            score -= 2
            reasons.append(f"RSI overbought ({rsi:.1f})")
        elif rsi < 40:
            score += 1
            reasons.append(f"RSI low ({rsi:.1f})")
        elif rsi > 60:
            score -= 1
            reasons.append(f"RSI high ({rsi:.1f})")
        
        # ── MACD Signal ────────────────────────────────────────────────────────
        macd_hist = latest['macd_hist']
        prev_macd_hist = prev['macd_hist']
        
        if macd_hist > 0 and prev_macd_hist <= 0:
            score += 2
            reasons.append("MACD bullish crossover")
        elif macd_hist < 0 and prev_macd_hist >= 0:
            score -= 2
            reasons.append("MACD bearish crossover")
        elif macd_hist > 0:
            score += 1
            reasons.append("MACD positive")
        elif macd_hist < 0:
            score -= 1
            reasons.append("MACD negative")
        
        # ── Bollinger Bands Signal ──────────────────────────────────────────────
        close = latest['close']
        bb_upper = latest['bb_upper']
        bb_lower = latest['bb_lower']
        bb_middle = latest['bb_middle']
        
        if close <= bb_lower:
            score += 2
            reasons.append("Price at lower Bollinger Band")
        elif close >= bb_upper:
            score -= 2
            reasons.append("Price at upper Bollinger Band")
        elif close < bb_middle:
            price_position = (close - bb_lower) / (bb_middle - bb_lower) if bb_middle != bb_lower else 0.5
            if price_position < 0.3:
                score += 1
                reasons.append("Price near lower BB")
        elif close > bb_middle:
            price_position = (close - bb_middle) / (bb_upper - bb_middle) if bb_upper != bb_middle else 0.5
            if price_position > 0.7:
                score -= 1
                reasons.append("Price near upper BB")
        
        # ── EMA Crossover Signal ───────────────────────────────────────────────
        ema_fast = latest['ema_fast']
        ema_slow = latest['ema_slow']
        prev_ema_fast = prev['ema_fast']
        prev_ema_slow = prev['ema_slow']
        
        if ema_fast > ema_slow and prev_ema_fast <= prev_ema_slow:
            score += 2
            reasons.append("EMA bullish crossover")
        elif ema_fast < ema_slow and prev_ema_fast >= prev_ema_slow:
            score -= 2
            reasons.append("EMA bearish crossover")
        elif ema_fast > ema_slow:
            score += 1
            reasons.append("EMA bullish alignment")
        else:
            score -= 1
            reasons.append("EMA bearish alignment")
        
        # ── Volume Signal ──────────────────────────────────────────────────────
        vol_ratio = latest['volume_ratio']
        if vol_ratio > self.config['volume_spike_threshold']:
            # Volume spike amplifies existing signal
            if score > 0:
                score += 1
                reasons.append(f"Volume spike ({vol_ratio:.1f}x) - bullish")
            elif score < 0:
                score -= 1
                reasons.append(f"Volume spike ({vol_ratio:.1f}x) - bearish")
        
        # ── Stochastic RSI ─────────────────────────────────────────────────────
        stoch_k = latest['stoch_rsi_k']
        stoch_d = latest['stoch_rsi_d']
        
        if stoch_k < 0.2 and stoch_d < 0.2:
            score += 1
            reasons.append("StochRSI oversold")
        elif stoch_k > 0.8 and stoch_d > 0.8:
            score -= 1
            reasons.append("StochRSI overbought")
        
        # ── Determine Signal ───────────────────────────────────────────────────
        threshold = self.config['signal_threshold']
        
        if score >= threshold:
            signal = 'buy'
        elif score <= -threshold:
            signal = 'sell'
        else:
            signal = 'hold'
        
        details = {
            'score': score,
            'reasons': reasons,
            'rsi': rsi,
            'macd_hist': macd_hist,
            'bb_position': (close - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5,
            'volume_ratio': vol_ratio,
            'atr': latest['atr'],
            'close': close
        }
        
        return signal, score, details

# ─── Risk Manager ─────────────────────────────────────────────────────────────

class RiskManager:
    """Handles position sizing, stop-loss, and take-profit calculations."""
    
    def __init__(self, config: dict):
        self.config = config['risk_management']
        self.daily_pnl = 0.0
        self.daily_reset = datetime.now().date()
        self.trade_history: List[dict] = []
    
    def reset_daily_pnl(self):
        """Reset daily PnL if new day."""
        today = datetime.now().date()
        if today > self.daily_reset:
            self.daily_pnl = 0.0
            self.daily_reset = today
            logger.info("Daily PnL counter reset")
    
    def check_daily_limit(self, balance: float) -> bool:
        """Check if daily loss limit is reached."""
        self.reset_daily_pnl()
        max_loss = balance * (self.config['max_daily_loss_pct'] / 100)
        if self.daily_pnl <= -max_loss:
            logger.warning(f"{Fore.RED}Daily loss limit reached: {self.daily_pnl:.2f}")
            return False
        return True
    
    def calculate_position_size(self, balance: float, price: float, 
                                stop_loss_pct: float) -> float:
        """Calculate position size based on risk management rules."""
        if self.config['use_kelly_criterion']:
            return self._kelly_position_size(balance, price)
        return self._fixed_position_size(balance, price, stop_loss_pct)
    
    def _fixed_position_size(self, balance: float, price: float, stop_loss_pct: float) -> float:
        """Fixed percentage risk position sizing."""
        max_risk = balance * (self.config['max_position_size_pct'] / 100)
        risk_per_unit = price * (stop_loss_pct / 100)
        
        if risk_per_unit <= 0:
            return 0.0
        
        position_size = max_risk / risk_per_unit
        return round(position_size, 6)
    
    def _kelly_position_size(self, balance: float, price: float) -> float:
        """Kelly criterion position sizing."""
        if len(self.trade_history) < 20:
            return self._fixed_position_size(balance, price, self.config['stop_loss_pct'])
        
        # Calculate win rate and avg win/loss from history
        wins = [t for t in self.trade_history[-100:] if t.get('pnl', 0) > 0]
        losses = [t for t in self.trade_history[-100:] if t.get('pnl', 0) <= 0]
        
        if not wins or not losses:
            return self._fixed_position_size(balance, price, self.config['stop_loss_pct'])
        
        win_rate = len(wins) / len(self.trade_history[-100:])
        avg_win = np.mean([t['pnl'] for t in wins])
        avg_loss = abs(np.mean([t['pnl'] for t in losses]))
        
        if avg_loss == 0:
            return self._fixed_position_size(balance, price, self.config['stop_loss_pct'])
        
        # Kelly formula: f = (p * b - q) / b
        # where p = win rate, q = 1-p, b = avg_win/avg_loss
        b = avg_win / avg_loss
        kelly_fraction = (win_rate * b - (1 - win_rate)) / b
        
        # Apply fractional Kelly (more conservative)
        kelly_fraction *= self.config['kelly_fraction']
        kelly_fraction = max(0, min(kelly_fraction, 0.25))  # Cap at 25%
        
        position_value = balance * kelly_fraction
        position_size = position_value / price
        
        logger.debug(f"Kelly sizing: fraction={kelly_fraction:.4f}, size={position_size:.6f}")
        return round(position_size, 6)
    
    def calculate_stop_loss(self, entry_price: float, side: str, atr: float = None) -> float:
        """Calculate stop-loss price."""
        sl_pct = self.config['stop_loss_pct'] / 100
        
        if atr and atr > 0:
            # Use ATR-based stop loss (2x ATR)
            atr_stop = 2 * atr
            pct_stop = entry_price * sl_pct
            sl_distance = max(atr_stop, pct_stop)  # Use wider stop
        else:
            sl_distance = entry_price * sl_pct
        
        if side == 'buy':
            return round(entry_price - sl_distance, 2)
        return round(entry_price + sl_distance, 2)
    
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """Calculate take-profit price."""
        tp_pct = self.config['take_profit_pct'] / 100
        
        if side == 'buy':
            return round(entry_price * (1 + tp_pct), 2)
        return round(entry_price * (1 - tp_pct), 2)
    
    def should_close_position(self, entry_price: float, current_price: float, 
                               side: str, highest_price: float = None) -> Tuple[bool, str]:
        """Check if position should be closed (trailing stop)."""
        # Check stop loss
        sl = self.calculate_stop_loss(entry_price, side)
        if side == 'buy' and current_price <= sl:
            return True, 'stop_loss'
        if side == 'sell' and current_price >= sl:
            return True, 'stop_loss'
        
        # Check take profit
        tp = self.calculate_take_profit(entry_price, side)
        if side == 'buy' and current_price >= tp:
            return True, 'take_profit'
        if side == 'sell' and current_price <= tp:
            return True, 'take_profit'
        
        # Check trailing stop
        if highest_price and self.config['trailing_stop_pct'] > 0:
            trail_pct = self.config['trailing_stop_pct'] / 100
            if side == 'buy':
                trail_stop = highest_price * (1 - trail_pct)
                if current_price <= trail_stop and current_price > entry_price:
                    return True, 'trailing_stop'
            else:
                trail_stop = lowest_price * (1 + trail_pct) if 'lowest_price' in dir() else entry_price
                if current_price >= trail_stop and current_price < entry_price:
                    return True, 'trailing_stop'
        
        return False, ''
    
    def record_trade(self, trade: dict):
        """Record trade for Kelly criterion calculation."""
        self.trade_history.append(trade)
        if 'pnl' in trade:
            self.daily_pnl += trade['pnl']

# ─── Main Trader ──────────────────────────────────────────────────────────────

class OKXTrader:
    """Main trading engine."""
    
    def __init__(self, config: dict):
        self.config = config
        self.connection = OKXConnection(config)
        self.analyzer = TechnicalAnalyzer(config)
        self.risk_manager = RiskManager(config)
        self.running = False
        self.position_tracker: Dict[str, dict] = {}  # Track positions with metadata
    
    def initialize(self) -> bool:
        """Initialize the trader."""
        logger.info("=" * 60)
        logger.info("OKX Automated Trader Starting")
        logger.info("=" * 60)
        
        # Display configuration
        logger.info(f"Mode: {Fore.YELLOW if self.config['trading']['trade_mode'] == 'paper' else Fore.GREEN}"
                    f"{self.config['trading']['trade_mode'].upper()}{Style.RESET_ALL}")
        logger.info(f"Primary Symbol: {self.config['trading']['primary_symbol']}")
        logger.info(f"Leverage: {self.config['trading']['leverage']}x")
        logger.info(f"Stop Loss: {self.config['risk_management']['stop_loss_pct']}%")
        logger.info(f"Take Profit: {self.config['risk_management']['take_profit_pct']}%")
        logger.info(f"Max Position: {self.config['risk_management']['max_position_size_pct']}%")
        
        # Test connection
        if not self.connection.test_connection():
            logger.error("Failed to connect to OKX. Please check your API keys and proxy settings.")
            return False
        
        # Set leverage for each symbol
        for symbol in self.config['trading']['symbols']:
            self.connection.set_leverage(symbol, self.config['trading']['leverage'])
        
        logger.info(f"{Fore.GREEN}✓ Initialization complete")
        return True
    
    def analyze_symbol(self, symbol: str) -> Tuple[str, int, dict]:
        """Analyze a symbol and generate signal."""
        # Fetch OHLCV data
        df = self.connection.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        if df.empty:
            return 'hold', 0, {'reason': 'no_data'}
        
        # Calculate indicators
        df = self.analyzer.calculate_indicators(df)
        
        # Generate signal
        signal, score, details = self.analyzer.generate_signal(df)
        
        return signal, score, details
    
    def execute_signal(self, symbol: str, signal: str, score: int, details: dict):
        """Execute a trading signal."""
        if signal == 'hold':
            return
        
        # Check daily loss limit
        balance = self.connection.get_balance()
        if not self.risk_manager.check_daily_limit(balance):
            return
        
        # Check max open positions
        positions = self.connection.get_positions()
        max_positions = self.config['risk_management']['max_open_positions']
        
        current_price = details.get('close', 0)
        atr = details.get('atr', 0)
        
        if signal == 'buy':
            # Check if already in position
            if symbol in positions:
                logger.debug(f"Already in position for {symbol}, skipping buy")
                return
            
            if len(positions) >= max_positions:
                logger.warning(f"Max positions ({max_positions}) reached, skipping")
                return
            
            # Calculate position size
            amount = self.risk_manager.calculate_position_size(
                balance, current_price, self.config['risk_management']['stop_loss_pct']
            )
            
            if amount <= 0:
                return
            
            # Calculate stop loss and take profit
            stop_loss = self.risk_manager.calculate_stop_loss(current_price, 'buy', atr)
            take_profit = self.risk_manager.calculate_take_profit(current_price, 'buy')
            
            # Execute order
            order = self.connection.create_order(symbol, 'buy', amount)
            
            if order.get('status') in ['filled', 'ok']:
                self.position_tracker[symbol] = {
                    'entry_price': current_price,
                    'side': 'buy',
                    'amount': amount,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'highest_price': current_price,
                    'entry_time': datetime.now().isoformat()
                }
                
                # Log trade
                trade_data = {
                    'symbol': symbol,
                    'side': 'buy',
                    'price': current_price,
                    'amount': amount,
                    'cost': current_price * amount,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'mode': self.config['trading']['trade_mode']
                }
                trade_logger.log_trade(trade_data)
                self.risk_manager.record_trade(trade_data)
                
                logger.info(f"{Fore.GREEN}BUY SIGNAL EXECUTED{Style.RESET_ALL}")
                logger.info(f"  Symbol: {symbol}")
                logger.info(f"  Amount: {amount}")
                logger.info(f"  Price: {current_price}")
                logger.info(f"  Stop Loss: {stop_loss}")
                logger.info(f"  Take Profit: {take_profit}")
                logger.info(f"  Score: {score} | Reasons: {', '.join(details.get('reasons', []))}")
        
        elif signal == 'sell':
            # Check if in position to sell
            if symbol not in positions and symbol not in self.position_tracker:
                logger.debug(f"No position for {symbol}, skipping sell")
                return
            
            # Get position details
            pos = self.position_tracker.get(symbol, {})
            amount = pos.get('amount', 0)
            
            if amount <= 0:
                return
            
            # Execute order
            order = self.connection.create_order(symbol, 'sell', amount)
            
            if order.get('status') in ['filled', 'ok']:
                # Calculate PnL
                entry_price = pos.get('entry_price', current_price)
                pnl = (current_price - entry_price) * amount
                
                # Log trade
                trade_data = {
                    'symbol': symbol,
                    'side': 'sell',
                    'price': current_price,
                    'amount': amount,
                    'cost': current_price * amount,
                    'pnl': pnl,
                    'mode': self.config['trading']['trade_mode']
                }
                trade_logger.log_trade(trade_data)
                self.risk_manager.record_trade(trade_data)
                
                # Clean up position tracker
                if symbol in self.position_tracker:
                    del self.position_tracker[symbol]
                
                logger.info(f"{Fore.RED}SELL SIGNAL EXECUTED{Style.RESET_ALL}")
                logger.info(f"  Symbol: {symbol}")
                logger.info(f"  Amount: {amount}")
                logger.info(f"  Price: {current_price}")
                logger.info(f"  PnL: {Fore.GREEN if pnl > 0 else Fore.RED}{pnl:.2f} USDT")
    
    def monitor_positions(self):
        """Monitor open positions for stop-loss and take-profit."""
        for symbol, pos in list(self.position_tracker.items()):
            ticker = self.connection.fetch_ticker(symbol)
            if not ticker:
                continue
            
            current_price = ticker['last']
            
            # Update highest price for trailing stop
            if current_price > pos.get('highest_price', 0):
                pos['highest_price'] = current_price
            
            # Check if should close
            should_close, reason = self.risk_manager.should_close_position(
                pos['entry_price'], current_price, pos['side'], pos.get('highest_price')
            )
            
            if should_close:
                logger.info(f"Closing {symbol} due to {reason}")
                self.execute_signal(symbol, 'sell', 0, {'close': current_price, 'reasons': [reason]})
    
    def display_status(self):
        """Display current status."""
        balance = self.connection.get_balance()
        positions = self.connection.get_positions()
        
        status_table = [
            ['Balance', f"{balance:.2f} USDT"],
            ['Mode', self.config['trading']['trade_mode'].upper()],
            ['Open Positions', len(positions)],
            ['Daily PnL', f"{self.risk_manager.daily_pnl:.2f} USDT"],
        ]
        
        print("\n" + "=" * 50)
        print(tabulate(status_table, headers=['Metric', 'Value'], tablefmt='grid'))
        
        if positions:
            pos_table = []
            for symbol, pos in positions.items():
                if isinstance(pos, dict):
                    tracker = self.position_tracker.get(symbol, {})
                    ticker = self.connection.fetch_ticker(symbol)
                    current_price = ticker.get('last', 0) if ticker else 0
                    entry_price = tracker.get('entry_price', 0)
                    pnl = (current_price - entry_price) * tracker.get('amount', 0) if tracker else 0
                    
                    pos_table.append([
                        symbol,
                        tracker.get('side', 'N/A'),
                        tracker.get('amount', 0),
                        entry_price,
                        current_price,
                        f"{Fore.GREEN if pnl > 0 else Fore.RED}{pnl:.2f}",
                        tracker.get('stop_loss', 'N/A'),
                        tracker.get('take_profit', 'N/A')
                    ])
            
            if pos_table:
                print("\nOpen Positions:")
                print(tabulate(pos_table, 
                    headers=['Symbol', 'Side', 'Amount', 'Entry', 'Current', 'PnL', 'SL', 'TP'],
                    tablefmt='grid'))
    
    def run(self):
        """Main trading loop."""
        self.running = True
        interval = self.config['trading']['trade_interval_seconds']
        
        logger.info(f"Starting main loop (interval: {interval}s)")
        logger.info("Press Ctrl+C to stop")
        
        try:
            while self.running:
                try:
                    # Analyze each symbol
                    for symbol in self.config['trading']['symbols']:
                        signal, score, details = self.analyze_symbol(symbol)
                        
                        if signal != 'hold':
                            logger.info(f"Signal for {symbol}: {signal} (score: {score})")
                            self.execute_signal(symbol, signal, score, details)
                    
                    # Monitor existing positions
                    self.monitor_positions()
                    
                    # Display status every 5 iterations
                    if int(time.time()) % (interval * 5) < interval:
                        self.display_status()
                    
                    # Wait for next interval
                    time.sleep(interval)
                    
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    time.sleep(10)  # Wait before retrying
                    
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
            self.running = False
            self.display_status()
            logger.info("Trader stopped.")

# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='OKX Automated Trader')
    parser.add_argument('--config', default='config.json', help='Config file path')
    parser.add_argument('--paper', action='store_true', help='Force paper trading mode')
    parser.add_argument('--live', action='store_true', help='Force live trading mode')
    parser.add_argument('--symbols', nargs='+', help='Override symbols to trade')
    parser.add_argument('--interval', type=int, help='Override trade interval in seconds')
    
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.config)
    
    # Override settings from command line
    if args.paper:
        config['trading']['trade_mode'] = 'paper'
    elif args.live:
        config['trading']['trade_mode'] = 'live'
    
    if args.symbols:
        config['trading']['symbols'] = args.symbols
    
    if args.interval:
        config['trading']['trade_interval_seconds'] = args.interval
    
    # Create and run trader
    trader = OKXTrader(config)
    
    if trader.initialize():
        trader.run()
    else:
        logger.error("Initialization failed. Exiting.")
        sys.exit(1)

if __name__ == '__main__':
    main()
