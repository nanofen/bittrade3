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

# GMOコインとBitbankで共通対応している通貨ペア
SUPPORTED_SYMBOLS = [
    'BTC_JPY', 'ETH_JPY', 'XRP_JPY', 'LTC_JPY', 
    'LINK_JPY', 'ADA_JPY', 'DOT_JPY', 'ATOM_JPY', 
    'SOL_JPY', 'DOGE_JPY'
]

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
    for symbol in SUPPORTED_SYMBOLS:
        ticker = get_gmo_ticker(symbol)
        if ticker:
            tickers[symbol] = ticker
        time.sleep(0.1)  # レート制限対策
    return tickers

def get_bitbank_ticker():
    """Bitbankのティッカー情報を取得"""
    try:
        url = "https://public.bitbank.cc/btc_jpy/ticker"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data["success"] == 1:
            ticker = data["data"]
            return {
                "bid": float(ticker["buy"]),   # 買値
                "ask": float(ticker["sell"]),  # 売値
                "timestamp": ticker["timestamp"]
            }
    except Exception as e:
        print(f"Bitbank価格取得エラー: {e}")
    return None

def get_csv_filename():
    """日別CSVファイル名を生成"""
    today = datetime.now().strftime('%Y%m%d')
    data_dir = 'data'
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return os.path.join(data_dir, f'price_data_{today}.csv')

def save_to_csv(data):
    """データをCSVファイルに保存"""
    filename = get_csv_filename()
    file_exists = os.path.isfile(filename)
    
    with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'timestamp', 'datetime',
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

def analyze_arbitrage_opportunity():
    """アービトラージ機会を分析"""
    print("=== GMO×Bitbank価格差チェック ===")
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 価格データ取得
    gmo_data = get_gmo_ticker()
    bitbank_data = get_bitbank_ticker()
    
    if not gmo_data or not bitbank_data:
        print("[エラー] 価格データの取得に失敗しました")
        return
    
    print(f"\n[現在価格]")
    print(f"GMO     - 買値: {gmo_data['bid']:,.0f}円, 売値: {gmo_data['ask']:,.0f}円")
    print(f"Bitbank - 買値: {bitbank_data['bid']:,.0f}円, 売値: {bitbank_data['ask']:,.0f}円")
    
    # 価格差計算
    # パターン1: GMOで買い、Bitbankで売り
    arbitrage_1 = bitbank_data['bid'] - gmo_data['ask']
    
    # パターン2: GMOで売り、Bitbankで買い  
    arbitrage_2 = gmo_data['bid'] - bitbank_data['ask']
    
    print(f"\n[価格差分析]")
    print(f"パターン1 (GMO買→Bitbank売): {arbitrage_1:+.1f}円")
    print(f"パターン2 (GMO売→Bitbank買): {arbitrage_2:+.1f}円")
    
    # 約定機会判定
    opportunities = []
    
    if arbitrage_1 > 500:
        opportunities.append(f"*** 約定機会! パターン1: {arbitrage_1:.1f}円の利益機会")
    elif arbitrage_1 > 200:
        opportunities.append(f"** 注目! パターン1: {arbitrage_1:.1f}円の価格差")
    elif arbitrage_1 > 0:
        opportunities.append(f"* パターン1: {arbitrage_1:.1f}円の小さな価格差")
    else:
        opportunities.append(f"- パターン1: {arbitrage_1:.1f}円の逆価格差")
    
    if arbitrage_2 > 500:
        opportunities.append(f"*** 約定機会! パターン2: {arbitrage_2:.1f}円の利益機会")
    elif arbitrage_2 > 200:
        opportunities.append(f"** 注目! パターン2: {arbitrage_2:.1f}円の価格差")
    elif arbitrage_2 > 0:
        opportunities.append(f"* パターン2: {arbitrage_2:.1f}円の小さな価格差")
    else:
        opportunities.append(f"- パターン2: {arbitrage_2:.1f}円の逆価格差")
    
    print(f"\n[約定機会評価]")
    for opportunity in opportunities:
        print(f"  {opportunity}")
    
    # スプレッド情報
    gmo_spread = gmo_data['ask'] - gmo_data['bid']
    bitbank_spread = bitbank_data['ask'] - bitbank_data['bid']
    
    print(f"\n[スプレッド情報]")
    print(f"GMO: {gmo_spread:.1f}円")
    print(f"Bitbank: {bitbank_spread:.1f}円")
    
    # 総合評価
    max_arbitrage = max(arbitrage_1, arbitrage_2)
    if max_arbitrage > 500:
        print(f"\n[結論] 約定機会あり! 最大{max_arbitrage:.1f}円の利益機会")
    elif max_arbitrage > 200:
        print(f"\n[結論] 要注目価格差! 最大{max_arbitrage:.1f}円の価格差")
    elif max_arbitrage > 0:
        print(f"\n[結論] 小さな価格差あり。最大{max_arbitrage:.1f}円")
    else:
        print(f"\n[結論] 現在約定機会なし")
    
    # CSVデータ準備
    current_time = datetime.now()
    csv_data = {
        'timestamp': current_time.timestamp(),
        'datetime': current_time.strftime('%Y-%m-%d %H:%M:%S'),
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
    
    # CSVに保存
    save_to_csv(csv_data)
    print(f"[データ保存] {get_csv_filename()}に保存しました")
    
    return {
        'gmo': gmo_data,
        'bitbank': bitbank_data,
        'arbitrage_1': arbitrage_1,
        'arbitrage_2': arbitrage_2,
        'max_arbitrage': max_arbitrage
    }

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
    
    try:
        while True:
            if duration and time.time() - start_time >= duration:
                break
                
            check_count += 1
            print(f"\n--- チェック {check_count} ---")
            
            result = analyze_arbitrage_opportunity()
            if result and result['max_arbitrage'] > best_opportunity:
                best_opportunity = result['max_arbitrage']
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n[停止] 監視を停止しました")
    
    elapsed_time = time.time() - start_time
    print(f"\n[監視結果サマリー]")
    print(f"実行時間: {elapsed_time/60:.1f}分")
    print(f"総チェック数: {check_count}回")
    print(f"最大価格差: {best_opportunity:.1f}円")
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