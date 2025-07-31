#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
REST APIを使用したGMO×Bitbank価格差チェック（複数通貨対応）
WebSocketを使わずに現在価格を取得
"""

import requests
import json
import time
import csv
import os
from datetime import datetime

# GMOコインとBitbankで共通対応している通貨ペア（名前をマッピング）
SUPPORTED_SYMBOLS = {
    'BTC_JPY': 'btc_jpy',
    'ETH_JPY': 'eth_jpy', 
    'XRP_JPY': 'xrp_jpy',
    'LTC_JPY': 'ltc_jpy',
    'LINK_JPY': 'link_jpy',
    'ADA_JPY': 'ada_jpy',
    'DOT_JPY': 'dot_jpy',
    'ATOM_JPY': 'atom_jpy',
    'SOL_JPY': 'sol_jpy',
    'DOGE_JPY': 'doge_jpy',
    'BCH_JPY': 'bcc_jpy'  # BitbankではBCHがbcc_jpyとして表記
}

def get_gmo_ticker(symbol="BTC_JPY"):
    """GMOCoinのティッカー情報を取得"""
    try:
        url = "https://api.coin.z.com/public/v1/ticker"
        params = {"symbol": symbol}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data["status"] == 0:
            ticker = data["data"][0]
            return {
                "bid": float(ticker["bid"]),  # 買値
                "ask": float(ticker["ask"]),  # 売値
                "timestamp": ticker["timestamp"],
                "symbol": symbol
            }
    except Exception as e:
        print(f"GMO価格取得エラー ({symbol}): {e}")
    return None

def get_gmo_all_tickers():
    """GMOCoinの全対応通貨のティッカー情報を取得"""
    tickers = {}
    for gmo_symbol in SUPPORTED_SYMBOLS.keys():
        ticker = get_gmo_ticker(gmo_symbol)
        if ticker:
            tickers[gmo_symbol] = ticker
        time.sleep(0.1)  # レート制限対策
    return tickers

def get_bitbank_ticker(symbol="btc_jpy"):
    """Bitbankのティッカー情報を取得"""
    try:
        url = f"https://public.bitbank.cc/{symbol}/ticker"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data["success"] == 1:
            ticker = data["data"]
            return {
                "bid": float(ticker["buy"]),   # 買値
                "ask": float(ticker["sell"]),  # 売値
                "timestamp": ticker["timestamp"],
                "symbol": symbol
            }
    except Exception as e:
        print(f"Bitbank価格取得エラー ({symbol}): {e}")
    return None

def get_bitbank_all_tickers():
    """Bitbankの全対応通貨のティッカー情報を取得"""
    tickers = {}
    for gmo_symbol, bitbank_symbol in SUPPORTED_SYMBOLS.items():
        ticker = get_bitbank_ticker(bitbank_symbol)
        if ticker:
            tickers[gmo_symbol] = ticker  # GMOのシンボル名で統一
        time.sleep(0.1)  # レート制限対策
    return tickers

def get_csv_filename():
    """日別CSVファイル名を生成"""
    today = datetime.now().strftime('%Y%m%d')
    data_dir = 'data'
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return os.path.join(data_dir, f'price_data_all_symbols_{today}.csv')

def save_to_csv(data):
    """データをCSVファイルに保存"""
    filename = get_csv_filename()
    file_exists = os.path.isfile(filename)
    
    with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'timestamp', 'datetime', 'symbol',
            'gmo_bid', 'gmo_ask', 'gmo_spread',
            'bitbank_bid', 'bitbank_ask', 'bitbank_spread',
            'arbitrage_1', 'arbitrage_2', 'max_arbitrage'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        # ヘッダーを書き込み（新規ファイルの場合）
        if not file_exists:
            writer.writeheader()
        
        # データを書き込み
        writer.writerow(data)

def analyze_single_symbol(symbol, gmo_data, bitbank_data):
    """単一シンボルのアービトラージ機会を分析"""
    print(f"\n=== {symbol} ===")
    print(f"GMO     - 買値: {gmo_data['bid']:,.1f}円, 売値: {gmo_data['ask']:,.1f}円")
    print(f"Bitbank - 買値: {bitbank_data['bid']:,.1f}円, 売値: {bitbank_data['ask']:,.1f}円")
    
    # 価格差計算
    arbitrage_1 = bitbank_data['bid'] - gmo_data['ask']  # GMO買→Bitbank売
    arbitrage_2 = gmo_data['bid'] - bitbank_data['ask']  # GMO売→Bitbank買
    
    # スプレッド計算
    gmo_spread = gmo_data['ask'] - gmo_data['bid']
    bitbank_spread = bitbank_data['ask'] - bitbank_data['bid']
    
    # 最大価格差
    max_arbitrage = max(arbitrage_1, arbitrage_2)
    
    # 約定機会判定の閾値（価格に応じて調整）
    if gmo_data['bid'] > 1000000:  # 100万円以上（BTC等）
        thresholds = [500, 200]
    elif gmo_data['bid'] > 100000:  # 10万円以上（ETH等）
        thresholds = [50, 20]
    elif gmo_data['bid'] > 1000:   # 1000円以上
        thresholds = [10, 5]
    else:                          # 1000円未満
        thresholds = [1, 0.5]
    
    # 結果表示
    status = ""
    if max_arbitrage > thresholds[0]:
        status = f"*** 約定機会! 最大{max_arbitrage:.1f}円"
    elif max_arbitrage > thresholds[1]:
        status = f"** 注目! 最大{max_arbitrage:.1f}円"
    elif max_arbitrage > 0:
        status = f"* 小差: 最大{max_arbitrage:.1f}円"
    else:
        status = f"- 逆差: 最大{max_arbitrage:.1f}円"
    
    print(f"価格差: {arbitrage_1:+.1f}円 / {arbitrage_2:+.1f}円 | {status}")
    
    return {
        'symbol': symbol,
        'gmo_bid': gmo_data['bid'],
        'gmo_ask': gmo_data['ask'],
        'gmo_spread': gmo_spread,
        'bitbank_bid': bitbank_data['bid'],
        'bitbank_ask': bitbank_data['ask'],
        'bitbank_spread': bitbank_spread,
        'arbitrage_1': arbitrage_1,
        'arbitrage_2': arbitrage_2,
        'max_arbitrage': max_arbitrage
    }

def analyze_arbitrage_opportunity():
    """全通貨ペアのアービトラージ機会を分析"""
    print("=== GMO×Bitbank 全通貨価格差チェック ===")
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 全通貨の価格データ取得
    print("\n[価格データ取得中...]")
    gmo_tickers = get_gmo_all_tickers()
    bitbank_tickers = get_bitbank_all_tickers()
    
    if not gmo_tickers or not bitbank_tickers:
        print("[エラー] 価格データの取得に失敗しました")
        return
    
    print(f"GMO: {len(gmo_tickers)}通貨, Bitbank: {len(bitbank_tickers)}通貨")
    
    # 各通貨ペアを分析
    results = []
    current_time = datetime.now()
    
    for symbol in SUPPORTED_SYMBOLS.keys():
        if symbol in gmo_tickers and symbol in bitbank_tickers:
            result = analyze_single_symbol(symbol, gmo_tickers[symbol], bitbank_tickers[symbol])
            
            # CSVデータ準備
            csv_data = {
                'timestamp': current_time.timestamp(),
                'datetime': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                **result
            }
            
            # CSVに保存
            save_to_csv(csv_data)
            results.append(result)
        else:
            print(f"\n=== {symbol} ===")
            print("データ取得失敗")
    
    # 総合結果表示
    if results:
        print(f"\n=== 総合結果 ===")
        # 最大価格差でソート
        sorted_results = sorted(results, key=lambda x: x['max_arbitrage'], reverse=True)
        
        print("最大価格差ランキング:")
        for i, result in enumerate(sorted_results[:5], 1):
            print(f"{i}. {result['symbol']}: {result['max_arbitrage']:+.1f}円")
        
        best_opportunity = sorted_results[0]['max_arbitrage']
        if best_opportunity > 200:
            print(f"\n[結論] 約定機会あり! 最大{best_opportunity:.1f}円の価格差")
        elif best_opportunity > 50:
            print(f"\n[結論] 要注目価格差! 最大{best_opportunity:.1f}円の価格差")
        else:
            print(f"\n[結論] 現在大きな約定機会なし")
        
        print(f"[データ保存] {get_csv_filename()}に保存しました")
    
    return results

def continuous_monitoring(duration=None, interval=5):
    """継続的な監視"""
    if duration:
        print(f"\n[監視開始] {duration}秒間、{interval}秒間隔で監視を開始...")
    else:
        print(f"\n[監視開始] 無制限に{interval}秒間隔で監視を開始...")
        print("停止するには Ctrl+C を押してください")
    
    start_time = time.time()
    check_count = 0
    best_opportunity = 0
    best_symbol = ""
    
    try:
        while True:
            if duration and time.time() - start_time >= duration:
                break
                
            check_count += 1
            print(f"\n--- チェック {check_count} ---")
            
            results = analyze_arbitrage_opportunity()
            if results:
                # 最大価格差を更新
                current_best = max(results, key=lambda x: x['max_arbitrage'])
                if current_best['max_arbitrage'] > best_opportunity:
                    best_opportunity = current_best['max_arbitrage']
                    best_symbol = current_best['symbol']
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n[停止] 監視を停止しました")
    
    elapsed_time = time.time() - start_time
    print(f"\n[監視結果サマリー]")
    print(f"実行時間: {elapsed_time/60:.1f}分")
    print(f"総チェック数: {check_count}回")
    print(f"最大価格差: {best_opportunity:.1f}円 ({best_symbol})")
    print(f"データファイル: {get_csv_filename()}")

if __name__ == '__main__':
    # まず1回チェック
    result = analyze_arbitrage_opportunity()
    
    # 継続監視するか確認
    print(f"\n[継続監視] 継続監視を行いますか？")
    print("1: はい (5分間監視)")
    print("2: はい (10分間監視)")
    print("3: はい (1時間監視)")
    print("4: はい (無制限監視)")
    print("5: いいえ")
    
    try:
        choice = input("選択 (1-5): ").strip()
        if choice == "1":
            continuous_monitoring(300, 5)  # 5分間
        elif choice == "2":
            continuous_monitoring(600, 5)  # 10分間
        elif choice == "3":
            continuous_monitoring(3600, 5)  # 1時間
        elif choice == "4":
            continuous_monitoring(None, 5)  # 無制限
        else:
            print("チェック完了")
    except KeyboardInterrupt:
        print("\n終了しました")