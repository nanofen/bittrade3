# -*- coding: utf-8 -*-
import asyncio
import json
import traceback
import sys
import numpy as np
import pandas as pd
import datetime
import os
import time
import pickle
import bybitbot_base
from socket_bitbank_pybotters import Socket_PyBotters_BitBank
from socket_gmocoin_pybotters import Socket_PyBotters_GMOCoin
from get_logger import get_custom_logger
import warnings
warnings.simplefilter('ignore')


class GMOBitbankArbitrageBot(bybitbot_base.BybitBotBase):
    # User can ues MAX_DATA_CAPACITY to control memory usage.
    open_time_old = 0

    # ---------------------------------------- #
    # init
    # ---------------------------------------- #
    def __init__(self, keys, prod, log_level="INFO"):
        super().__init__()
        self.keys = keys

        if self.Debug:
            self.logger.debug(f"API keys loaded: {list(self.keys.keys())}")

        self.gmo = Socket_PyBotters_GMOCoin(self.keys)
        self.gmo.SYMBOL = 'BTC_JPY'

        self.bitbank = Socket_PyBotters_BitBank(self.keys)
        self.bitbank.SYMBOL = 'btc_jpy'

        self.orderbook_check = False
        self.execute_check = {}
        self.df = pd.DataFrame()
        self.trade = pd.DataFrame()
        self.df_ohlcv = pd.DataFrame(
            columns=["exec_date", "Open", "High", "Low", "Close", "Volume", "timestamp"]).set_index("exec_date")
        self.df_1h_ohlcv = pd.DataFrame(
            columns=["exec_date", "Open", "High", "Low", "Close", "Volume", "timestamp"]).set_index("exec_date")
        self.MAX_OHLCV_CAPACITY = 60 * 60 * 1  # 1時間分
        self.MAX_DATA_CAPACITY = 10
        self.sum_profit = 0
        self.sum_fee = 0
        self.base_qty = 0.01
        self.test_mode = False
        self.test_start_time = time.time()
        self.bitbank_info = 0
        
        # 【分析結果ベース最適化パラメータ】
        # realistic_arbitrage_analysis結果: SL-10k(+573,049円, 83.9%勝率)が最適
        self.entry_threshold = 40000      # エントリー閾値（分析結果: 40k円で最適収益）
        self.exit_threshold = 10000       # 利益確定閾値（分析結果: 10k円で最高収益）
        self.stop_loss_threshold = -10000 # 損切り閾値（分析結果: -10k円で83.9%勝率）
        self.trading_fee = 0.001          # 手数料 0.1%
        self.max_hold_minutes = 240       # 最大保有時間（分析結果: 240分で98.2%成功率）
        self.prefer_gmo_to_bitbank = True # GMO→Bitbank方向を優先


        self.qty = self.base_qty
        self.Debug = False
        self.positions_bitbank = {}
        self.positions_gmo = {}
        self.orders_gmo = []
        self.slip_in = 0.0
        self.slip_out = 0.0
        self.info = {}
        self.orders_bitbank = []
        self.btc_amounts = {}
        self.offensive_mode = True
        self.position_entry_time = None  # ポジション建玉時刻を記録
        self.entry_arbitrage_1 = 0  # エントリー時のarbitrage_1を記録
        self.entry_arbitrage_2 = 0  # エントリー時のarbitrage_2を記録


        self.logger = get_custom_logger(log_level)
        self.emergency_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        self.emergency_qty_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)


        # 【修正】タスクの設定およびイベントループの改善
        self.start_bot()

    def start_bot(self):
        """ボットを開始する"""
        try:
            asyncio.run(self.run_all_tasks())
        except KeyboardInterrupt:
            print("ボット停止中...")
        except Exception as e:
            print(f"ボット実行エラー: {e}")
            import traceback
            traceback.print_exc()

    async def run_all_tasks(self):
        """すべてのタスクを実行する"""
        print("すべてのタスクを開始...")
        tasks = [
            asyncio.create_task(self.gmo.ws_run(), name="gmo_websocket"),
            asyncio.create_task(self.bitbank.ws_run(), name="bitbank_websocket"),
            asyncio.create_task(self.run(), name="main_logic")
        ]
        
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            print(f"タスク実行エラー: {e}")
            for task in tasks:
                if not task.done():
                    task.cancel()
            raise

    async def order_check(self):
        await self.order_list_bitbank()
        await self.order_list_gmo()

    async def order_cancel_all(self):
        # 【修正】Bitbankは信用取引用の注文キャンセルを使用
        for order in self.orders_bitbank:
            await self.bitbank.margin_order_cancel(order_id=order["order_id"])
        for order in self.orders_gmo:
            await self.gmo.order_cancel(order_id=order["orderId"])
        res = await self.bitbank.send()
        res = await self.gmo.send()

    async def order_list_gmo(self):
        try:
            self.gmo.order_list(self.gmo.SYMBOL)
            res = await self.gmo.send()
            if res[0]["data"] is not None:
                self.orders_gmo = res[0]["data"]
            else:
                self.orders_gmo = []
        except Exception as e:
            self.logger.error(traceback.format_exc().strip())

    async def order_list_bitbank(self):
        try:
            # 【修正】信用取引用の注文リスト取得
            self.bitbank.margin_order_list(self.bitbank.SYMBOL)
            res = await self.bitbank.send()
            # print(f"Bitbank order list response: {res}")
            # レスポンスが空リストの場合は正常（注文なし）
            if isinstance(res, list) and len(res) == 0:
                self.orders_bitbank = []
            elif res and len(res) > 0 and "data" in res[0]:
                if "orders" in res[0]["data"] and res[0]["data"]["orders"] is not None:
                    self.orders_bitbank = res[0]["data"]["orders"]
                else:
                    self.orders_bitbank = []
            else:
                self.orders_bitbank = []
        except Exception as e:
            print(f"Bitbank order list error: {e}")
            self.orders_bitbank = []

    async def position_check_bitbank(self):
        # 【修正】信用取引用のポジション確認に変更
        try:
            self.bitbank.margin_position_list()
            dt = datetime.datetime.now(datetime.timezone.utc)
            utc_time = dt.replace(tzinfo=datetime.timezone.utc)
            ts_now = int(utc_time.timestamp())
            res = await self.bitbank.send()
            
            # print(f"Bitbank position response: {res}")
            
            # 【修正】新しい信用取引ポジション情報の処理
            if res and len(res) > 0 and "data" in res[0]:
                positions_data = res[0]["data"]
                long_size = 0.0
                short_size = 0.0
                
                # 新しいレスポンス形式に対応
                if "positions" in positions_data and positions_data["positions"] is not None:
                    for pos in positions_data["positions"]:
                        if pos["pair"] == self.bitbank.SYMBOL:
                            if pos["position_side"] == "long":  # 修正: "side" -> "position_side"
                                long_size += float(pos["open_amount"])  # 修正: "amount" -> "open_amount"
                            elif pos["position_side"] == "short":  # 修正: "side" -> "position_side"
                                short_size += float(pos["open_amount"])  # 修正: "amount" -> "open_amount"
                
                # ネットポジション計算（long - short）
                net_size = long_size - short_size
                
                self.positions_bitbank = {"symbol": self.bitbank.SYMBOL,
                                          "size": net_size,
                                          "long_size": long_size,
                                          "short_size": short_size,
                                          "timestamp": ts_now}
            else:
                self.positions_bitbank = {"symbol": self.bitbank.SYMBOL,
                                          "size": 0.0,
                                          "long_size": 0.0,
                                          "short_size": 0.0,
                                          "timestamp": ts_now}
        except Exception as e:
            print(f"Bitbank position check error: {e}")
            print(traceback.format_exc().strip())
            # エラー時はデフォルト値を設定
            self.positions_bitbank = {"symbol": self.bitbank.SYMBOL,
                                      "size": 0.0,
                                      "long_size": 0.0,
                                      "short_size": 0.0,
                                      "timestamp": int(datetime.datetime.now(datetime.timezone.utc).timestamp())}

    def position_check_gmo(self):
        dt = datetime.datetime.now(datetime.timezone.utc)
        utc_time = dt.replace(tzinfo=datetime.timezone.utc)
        ts_now = int(utc_time.timestamp())
        
        # GMOのポジション情報を取得
        gmo_positions = self.gmo.store.positions.find({'symbol': self.gmo.SYMBOL})
        
        long_pos_size = 0
        short_pos_size = 0
        
        for pos in gmo_positions:
            if pos.get("side") == "BUY":
                long_pos_size += float(pos.get("size", 0))
            elif pos.get("side") == "SELL":
                short_pos_size += float(pos.get("size", 0))
        
        if len(self.positions_gmo) == 0:
            self.positions_gmo = {"symbol": self.gmo.SYMBOL,
                                  "long_size": 0.0,
                                  "short_size": 0.0,
                                  "timestamp": ts_now}
        
        if (long_pos_size != self.positions_gmo.get("long_size", 0) or 
            short_pos_size != self.positions_gmo.get("short_size", 0)):
            self.positions_gmo = {"symbol": self.gmo.SYMBOL,
                                  "long_size": long_pos_size,
                                  "short_size": short_pos_size,
                                  "timestamp": ts_now}

    def get_timestamp(self):
        dt = datetime.datetime.now(datetime.timezone.utc)
        utc_time = dt.replace(tzinfo=datetime.timezone.utc)
        ts_now = int(utc_time.timestamp())
        return ts_now
    # ---------------------------------------- #
    # bot main
    # ---------------------------------------- #

    async def run(self):
        checkout = False
        print("Starting bot run...")
        self.bitbank_info = await self.bitbank.get_info_bitbank()
        print(f"Bitbank info: {self.bitbank_info}")

        while True:
            # Test mode: stop after 10 minutes for opportunity analysis
            if self.test_mode and (time.time() - self.test_start_time) > 600:
                print("Test mode: 10 minutes elapsed, stopping...")
                break
            
            await self.order_check()
            await self.order_cancel_all()
            await self.position_check_bitbank()
            self.position_check_gmo()

            await self.main()
            await asyncio.sleep(1)


    async def main(self):
        try:
            ts_now = self.get_timestamp()

            # GMOの板情報を取得
            gmo_orderbooks = self.gmo.store.orderbooks.find({'symbol': self.gmo.SYMBOL})
            # print(f"GMO orderbooks: {len(gmo_orderbooks)}")
            
            if len(gmo_orderbooks) < 1:
                print("GMO orderbook data not available")
                return True
            
            # GMOのorderbookからbids/asks抽出（データ構造に依存）
            gmo_bids = [x for x in gmo_orderbooks if x.get('side') == 'bids']
            gmo_asks = [x for x in gmo_orderbooks if x.get('side') == 'asks']
            
            # print(f"GMO bids: {len(gmo_bids)}, asks: {len(gmo_asks)}")
            
            if len(gmo_bids) < 1 or len(gmo_asks) < 1:
                print(f"GMO insufficient bid/ask data")
                return True
                
            gmo_best_bid = gmo_bids[0]  # 最高買い価格
            gmo_best_ask = gmo_asks[0]  # 最低売り価格
            #print(buy, sell)
            #print(self.bitbank.store.ticker.find())
            # 取引記録
            # print(self.bitbank.store.transactions.find())
            # 注文記録

            # 【修正】Bitbankは信用取引用の注文キャンセルを使用
            for order in self.orders_bitbank:
                await self.bitbank.margin_order_cancel(order_id=order["order_id"])
            for order in self.orders_gmo:
                await self.gmo.order_cancel(order_id=order["orderId"])
            res = await self.bitbank.send()
            res = await self.gmo.send()

            bitbank_orderbooks = self.bitbank.store.depth.find()
            # print(f"Bitbank orderbooks: {len(bitbank_orderbooks)}")
            
            # Bitbankは "bids"/"asks" を使用（単体テストで確認済み）
            bitbank_buy_order = [x for x in bitbank_orderbooks if x["side"] == "bids"]
            bitbank_sell_order = [x for x in bitbank_orderbooks if x["side"] == "asks"]
            
            # 板情報の存在確認
            if not bitbank_buy_order or not bitbank_sell_order:
                self.logger.warning(f"Bitbank板情報不足 - buy orders: {len(bitbank_buy_order)}, sell orders: {len(bitbank_sell_order)}")
                return True
            # アービトラージ機会の計算（同一通貨JPYなので為替変換不要）
            # パターン1: GMOで買い、Bitbank信用でショート
            # 条件: GMOの売値 < Bitbankの買値
            gmo_ask_price = float(gmo_best_ask['price']) if gmo_best_ask else 0
            # Bitbank板情報の構造確認：[price, amount]配列かオブジェクトか
            if bitbank_buy_order:
                if isinstance(bitbank_buy_order[0], list):
                    # API仕様通りの[price, amount]配列形式
                    bitbank_bid_price = float(bitbank_buy_order[0][0])  # price
                else:
                    # pybottersが変換したオブジェクト形式
                    bitbank_bid_price = float(bitbank_buy_order[0]["price"])
            else:
                bitbank_bid_price = 0
            
            # パターン2: GMOで売り、Bitbank信用でロング  
            gmo_bid_price = float(gmo_best_bid['price']) if gmo_best_bid else 0
            if bitbank_sell_order:
                if isinstance(bitbank_sell_order[0], list):
                    # API仕様通りの[price, amount]配列形式
                    bitbank_ask_price = float(bitbank_sell_order[0][0])  # price
                else:
                    # pybottersが変換したオブジェクト形式
                    bitbank_ask_price = float(bitbank_sell_order[0]["price"])
            else:
                bitbank_ask_price = 0
            
            # 【修正】アービトラージ機会計算（realistic_arbitrage_analysis.pyと統一）
            arbitrage_1 = bitbank_bid_price - gmo_ask_price  # GMO買い→Bitbank売り（パターン1）
            arbitrage_2 = gmo_bid_price - bitbank_ask_price  # GMO売り→Bitbank買い（パターン2）
            
            # 価格差情報を常にログ出力（約定機会分析用）
            self.logger.debug(f"価格差分析 - arbitrage_1(GMO買い/BB売り): {arbitrage_1:.1f}円, arbitrage_2(GMO売り/BB買い): {arbitrage_2:.1f}円")
            self.logger.debug(f"価格詳細 - GMO買値:{gmo_ask_price}, GMO売値:{gmo_bid_price}, BB買値:{bitbank_bid_price}, BB売値:{bitbank_ask_price}")
            
            # 分析結果と統一した変数名
            gmo_to_bitbank_profit = arbitrage_1  # GMO買い→Bitbank売り
            bitbank_to_gmo_profit = arbitrage_2  # Bitbank買い→GMO売り
            
            # 方向性フィルター: GMO→Bitbank方向を優先（分析結果で高収益）
            primary_opportunity = gmo_to_bitbank_profit if self.prefer_gmo_to_bitbank else max(gmo_to_bitbank_profit, bitbank_to_gmo_profit)
            secondary_opportunity = bitbank_to_gmo_profit if self.prefer_gmo_to_bitbank else min(gmo_to_bitbank_profit, bitbank_to_gmo_profit)
            
            if primary_opportunity > self.entry_threshold:
                direction = "GMO→Bitbank" if self.prefer_gmo_to_bitbank else "最適方向"
                self.logger.warning(f"*** 約定機会検出 *** {direction}: {primary_opportunity:.1f}円の価格差（閾値{self.entry_threshold}円超過）")
            
            if secondary_opportunity > self.entry_threshold:
                direction = "Bitbank→GMO" if self.prefer_gmo_to_bitbank else "サブ方向"
                self.logger.info(f"サブ機会: {direction}が{self.entry_threshold}円閾値を超過 ({secondary_opportunity:.1f}円)")
            # ポジション状態の確認
            bitbank_position_size = self.positions_bitbank.get("size", 0)
            gmo_long_size = self.positions_gmo.get("long_size", 0)
            gmo_short_size = self.positions_gmo.get("short_size", 0)
            total_gmo_pos = gmo_long_size + gmo_short_size
            
            # 【修正】モード判定（分析結果ベース: 240分保有）
            if bitbank_position_size == 0 and total_gmo_pos == 0:
                self.offensive_mode = True
                self.position_entry_time = None
                self.entry_arbitrage_1 = 0
                self.entry_arbitrage_2 = 0
            # 分析結果ベース: 240分経過または実P&Lベースの判定
            elif self.positions_bitbank.get("timestamp", 0) + 60 * self.max_hold_minutes < ts_now:
                self.offensive_mode = False
            # 分析ベースの最適化された新規アービトラージ実行
            if self.offensive_mode and bitbank_position_size < self.base_qty and total_gmo_pos <= bitbank_position_size:
                # 優先機会: GMO買い→Bitbank信用売り（分析結果で高収益）
                if True and gmo_to_bitbank_profit > self.entry_threshold:  # 実取引有効化
                    # 板情報から数量を取得
                    if isinstance(bitbank_buy_order[0], list):
                        # API仕様通りの[price, amount]配列形式
                        bitbank_available_size = float(bitbank_buy_order[0][1])  # amount
                    else:
                        # pybottersが変換したオブジェクト形式（amountキーを使用）
                        bitbank_available_size = float(bitbank_buy_order[0]["amount"]) 
                    qty = min(bitbank_available_size, self.base_qty - bitbank_position_size)
                    
                    # GMOで買いポジション
                    await self.gmo.buy_in(gmo_ask_price, qty)
                    
                    # Bitbank信用取引でショート
                    await self.bitbank.margin_sell_in(bitbank_bid_price, qty)
                    
                    # ポジション建玉時刻とエントリー価格差を記録
                    self.position_entry_time = ts_now
                    self.entry_arbitrage_1 = arbitrage_1
                    
                    print(f"アービトラージ実行: GMO買い@{gmo_ask_price}, Bitbank売り@{bitbank_bid_price}, 差額:{arbitrage_1}円, 数量:{qty}")
                    return False
                    
                # サブ機会: Bitbank買い→GMO信用売り（低収益だが機会あり）
                elif True and bitbank_to_gmo_profit > self.entry_threshold and gmo_to_bitbank_profit <= self.entry_threshold:  # メイン機会がない場合のみ
                    # 板情報から数量を取得
                    if isinstance(bitbank_sell_order[0], list):
                        # API仕様通りの[price, amount]配列形式
                        bitbank_available_size = float(bitbank_sell_order[0][1])  # amount
                    else:
                        # pybottersが変換したオブジェクト形式
                        bitbank_available_size = float(bitbank_sell_order[0]["amount"])
                    qty = min(bitbank_available_size, self.base_qty - bitbank_position_size)
                    
                    # GMOで売りポジション
                    await self.gmo.sell_in(gmo_bid_price, qty)
                    
                    # Bitbank信用取引でロング
                    await self.bitbank.margin_buy_in(bitbank_ask_price, qty)
                    
                    # ポジション建玉時刻とエントリー価格差を記録
                    self.position_entry_time = ts_now
                    self.entry_arbitrage_2 = arbitrage_2
                    
                    print(f"アービトラージ実行: GMO売り@{gmo_bid_price}, Bitbank買い@{bitbank_ask_price}, 差額:{arbitrage_2}円, 数量:{qty}")
                    return False
            # ポジション調整（GMOとBitbankのポジション不均衡解消）
            if self.offensive_mode and bitbank_position_size == self.base_qty and total_gmo_pos < bitbank_position_size:
                diff_size = bitbank_position_size - total_gmo_pos
                # GMOのポジションを調整
                if gmo_long_size > gmo_short_size:
                    await self.gmo.sell_in(gmo_bid_price, diff_size)
                else:
                    await self.gmo.buy_in(gmo_ask_price, diff_size)
                return False
                
            # 利確モード（ポジション決済） 
            if not self.offensive_mode and (total_gmo_pos > 0 or bitbank_position_size != 0):
                # 【修正】正しいnet_profit計算：実際のエントリー時の利益＋決済時の利益
                # パターン1: GMOロング + Bitbankショート → GMO売り + Bitbank買い戻し
                entry_profit_1 = self.entry_arbitrage_1  # 実際のエントリー時の利益
                exit_profit_1 = gmo_bid_price - bitbank_ask_price  # 決済時の利益
                gross_profit_1 = entry_profit_1 + exit_profit_1
                trading_fee_1 = (abs(entry_profit_1) + abs(exit_profit_1)) * self.trading_fee
                net_profit_1 = gross_profit_1 - trading_fee_1
                
                # パターン2: GMOショート + Bitbankロング → GMO買い戻し + Bitbank売り
                entry_profit_2 = self.entry_arbitrage_2  # 実際のエントリー時の利益
                exit_profit_2 = bitbank_bid_price - gmo_ask_price  # 決済時の利益
                gross_profit_2 = entry_profit_2 + exit_profit_2
                trading_fee_2 = (abs(entry_profit_2) + abs(exit_profit_2)) * self.trading_fee
                net_profit_2 = gross_profit_2 - trading_fee_2
                
                # 分析ベース最適化エグジット条件
                if (net_profit_1 > self.exit_threshold or net_profit_1 < self.stop_loss_threshold) and gmo_long_size > 0:  # GMOロング + Bitbankショート決済
                    close_qty = min(gmo_long_size, abs(bitbank_position_size))
                    
                    # GMOロングポジション決済（売り）
                    gmo_long_positions = [pos for pos in self.gmo.store.positions.find({'symbol': self.gmo.SYMBOL}) if pos.get("side") == "BUY"]
                    if gmo_long_positions:
                        await self.gmo.sell_out(gmo_bid_price, close_qty, gmo_long_positions[0].get("positionId"))
                    
                    # Bitbankショートポジション決済（買い）
                    await self.bitbank.margin_buy_out(bitbank_ask_price, close_qty)
                    
                    exit_reason = "利確" if net_profit_1 > self.exit_threshold else "損切り"
                    print(f"{exit_reason}決済: GMOロング決済@{gmo_bid_price}, Bitbankショート決済@{bitbank_ask_price}, 純利益:{net_profit_1:.2f}円, 数量:{close_qty}")
                    return False
                    
                elif (net_profit_2 > self.exit_threshold or net_profit_2 < self.stop_loss_threshold) and gmo_short_size > 0:  # GMOショート + Bitbankロング決済
                    close_qty = min(gmo_short_size, bitbank_position_size)
                    
                    # GMOショートポジション決済（買い）
                    gmo_short_positions = [pos for pos in self.gmo.store.positions.find({'symbol': self.gmo.SYMBOL}) if pos.get("side") == "SELL"]
                    if gmo_short_positions:
                        await self.gmo.buy_out(gmo_ask_price, close_qty, gmo_short_positions[0].get("positionId"))
                    
                    # Bitbankロングポジション決済（売り）
                    await self.bitbank.margin_sell_out(bitbank_bid_price, close_qty)
                    
                    exit_reason = "利確" if net_profit_2 > self.exit_threshold else "損切り"
                    print(f"{exit_reason}決済: GMOショート決済@{gmo_ask_price}, Bitbankロング決済@{bitbank_bid_price}, 純利益:{net_profit_2:.2f}円, 数量:{close_qty}")
                    return False

            # 【修正】データ保存フォーマット（分析スクリプトと統一）
            now_data = {"timestamp": ts_now,
                        "datetime": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        "arbitrage_1": arbitrage_1,
                        "arbitrage_2": arbitrage_2,
                        "gmo_bid": gmo_bid_price,
                        "gmo_ask": gmo_ask_price,
                        "bitbank_bid": bitbank_bid_price,
                        "bitbank_ask": bitbank_ask_price,
                        "bitbank_position_size": bitbank_position_size,
                        "gmo_long_size": gmo_long_size,
                        "gmo_short_size": gmo_short_size,
                        "offensive_mode": self.offensive_mode,
                        "max_arbitrage": max(arbitrage_1, arbitrage_2),
                        }
            old_data = {}

            today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
            if os.path.exists(f"./data/{today}.json"):
                with open(f"./data/{today}.json", "r") as f:
                    old_data = json.load(f)
                old_data[now_data["timestamp"]] = now_data
            with open(f"./data/{today}.json", "w") as f:
                json.dump(old_data, f, indent=2)




            return False


        except Exception as e:
            self.logger.exception(e)
            #print(traceback.format_exc().strip())


# --------------------------------------- #
# main
# --------------------------------------- #
if __name__ == '__main__':
    import argparse
    import auth

    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    #pd.set_option('display.max_colwidth', -1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action='store_true')
    args = parser.parse_args()

    keys = {}
    # GMOコインとBitbankのAPIキーを設定
    gmo_key, gmo_secret = auth.GMOCoinKeys().keys()
    bitbank_key, bitbank_secret = auth.BitbankKeys().keys()
    keys = {'gmocoin': [gmo_key, gmo_secret],
            'bitbank': [bitbank_key, bitbank_secret],}
    GMOBitbankArbitrageBot(keys=keys, prod=args.prod, log_level="INFO")
