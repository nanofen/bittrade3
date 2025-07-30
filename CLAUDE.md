# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 言語設定

このプロジェクトでは**日本語**でのやり取りを行います。コードのコメント、説明、質問への回答はすべて日本語で行ってください。

## 開発フロー

**重要**: すべての実装作業は以下の手順で行ってください：

1. 新しいブランチを作成する
2. コードの実装・修正を行う
3. 変更をコミットする
4. プルリクエスト（PR）を作成する

直接mainブランチには変更を加えないこと。

## Running the Application

**Main Entry Point:**
```bash
python3 main.py [--prod]
```
- Default: runs in testnet mode using test API keys
- `--prod`: runs in production mode with real API keys

**Test Script:**
```bash
python3 test.py
```

## Code Architecture

This is a cryptocurrency arbitrage trading bot that monitors price differences between exchanges (Bybit and Bitbank) and executes arbitrage trades.

### Core Components

- **main.py**: Primary entry point containing `ArbitrageBot` class that orchestrates the entire trading strategy
- **bybitbot_base.py**: Base class `BybitBotBase` providing common bot functionality including OHLCV data management and resampling
- **Socket Integration**: WebSocket connections to exchanges:
  - `socket_bybit_pybotters.py`: Bybit exchange WebSocket interface using pybotters library
  - `socket_bitbank_pybotters.py`: Bitbank exchange WebSocket interface
  - `socket_gmocoin_pybotters.py`: GMO Coin exchange interface
- **auth.py**: API key management for multiple exchanges with testnet/production environment support
- **utils.py**: Technical analysis utilities using TA-Lib with feature engineering functions
- **get_logger.py**: Centralized logging configuration

### Key Dependencies

- **pybotters**: WebSocket connections and data store management for crypto exchanges
- **yfinance**: USD/JPY exchange rate data fetching
- **pandas/numpy**: Data manipulation and analysis
- **talib**: Technical analysis indicators
- **lightgbm**: Machine learning model loading (referenced in utils)
- **asyncio**: Asynchronous execution for concurrent exchange monitoring

### Data Flow

1. WebSocket connections established to both Bybit and Bitbank
2. Real-time orderbook and price data collected via pybotters DataStore
3. USD/JPY rates fetched from Yahoo Finance for currency conversion
4. Price differences calculated between exchanges
5. Arbitrage opportunities identified based on configurable thresholds
6. Orders executed on both exchanges simultaneously
7. Position tracking and profit/loss monitoring
8. Data logged to JSON files in `/data/` directory

### Bot Modes

- **Offensive Mode**: Actively seeks new arbitrage opportunities when positions are balanced
- **Defensive Mode**: Focuses on closing existing positions when timeout conditions are met (10+ minutes)

### Configuration

API keys are managed through `auth.py` with separate configurations for:
- Bybit (testnet/production with environment-specific keys)
- Bitbank (production keys)
- GMO Coin (production keys)

Trading parameters are hardcoded in `main.py`:
- Base quantity: 0.1 BTC
- Price difference threshold: 200 USD for entry
- Position timeout: 10 minutes for defensive mode

### 取引メソッドの命名規則

**重要**: 取引所のメソッド命名は直感的でない場合があります：

**Bitbank (socket_bitbank_pybotters.py):**
- `buy_in(price, qty)`: 買い注文を出す（side="buy"）
- `buy_out(price, qty)`: 買いポジションを決済する（side="sell"）

**Bybit (socket_bybit_pybotters.py):**
- `buy_in(price, qty)`: 買い注文を出す（side="Buy", reduce_only=False）
- `buy_out(price, qty)`: 買いポジションを決済する（side="Sell", reduce_only=True）
- `sell_in(price, qty)`: 売り注文を出す（side="Sell", reduce_only=False）
- `sell_out(price, qty)`: 売りポジションを決済する（side="Buy", reduce_only=True）

**アービトラージでの使用パターン:**
1. Bitbankで買い(`buy_in`) → Bybitで売り(`sell_in`)でポジション構築
2. Bitbankで売却(`buy_out`) → Bybitで買戻し(`sell_out`)でポジション決済

メソッド名は「in/out」がポジションの建玉/決済を表し、「buy/sell」は最初の建玉方向を表す。