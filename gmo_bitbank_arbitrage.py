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

        print(self.keys)

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


        self.logger = get_custom_logger(log_level)
        self.emergency_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        self.emergency_qty_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)


        # タスクの設定およびイベントループの開始
        loop = asyncio.get_event_loop()
        tasks = [
            self.gmo.ws_run(),
            self.bitbank.ws_run(),
            self.run()
        ]

        loop.run_until_complete(asyncio.wait(tasks))

    async def order_check(self):
        await self.order_list_bitbank()
        await self.order_list_gmo()

    async def order_cancel_all(self):
        for order in self.orders_bitbank:
            await self.bitbank.order_cancel(order_id=order["order_id"])
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
            self.bitbank.order_list(self.bitbank.SYMBOL)
            res = await self.bitbank.send()
            if res[0]["data"]["orders"] is not None:
                self.orders_bitbank = res[0]["data"]["orders"]
            else:
                self.orders_bitbank = []
        except Exception as e:
            print(traceback.format_exc().strip())

    async def position_check_bitbank(self):
        self.bitbank.position_list()
        dt = datetime.datetime.now(datetime.timezone.utc)
        utc_time = dt.replace(tzinfo=datetime.timezone.utc)
        ts_now = int(utc_time.timestamp())
        res = await self.bitbank.send()
        if res[0]["data"]["assets"] is not None:
            btc_amount = 0.0
            for x in res[0]["data"]["assets"]:
                if x["asset"] == 'btc':
                    btc_amount = float(x["onhand_amount"])
                    break
            if len(self.btc_amounts) == 0:
                self.btc_amounts["base"] = btc_amount
                self.btc_amounts[ts_now] = btc_amount
                self.positions_bitbank = {"symbol": self.bitbank.SYMBOL,
                                          "size": 0.0,
                                          "timestamp": ts_now}
            else:
                size = btc_amount - self.btc_amounts["base"]
                if size != self.positions_bitbank["size"]:
                    if size < float(self.bitbank_info["unit_amount"]):
                        size = 0
                    self.btc_amounts[ts_now] = btc_amount
                    self.positions_bitbank = {"symbol": self.bitbank.SYMBOL,
                                              "size": size,
                                              "timestamp": ts_now}

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
        
        loop_count = 0
        while True:
            loop_count += 1
            print(f"\n=== Loop {loop_count} ===")
            
            # Test mode: stop after 5 seconds
            if self.test_mode and (time.time() - self.test_start_time) > 5:
                print("Test mode: 5 seconds elapsed, stopping...")
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
            print(f"GMO orderbooks: {len(gmo_orderbooks)}")
            if len(gmo_orderbooks) < 1:
                print("GMO orderbook data not available")
                return True
            
            gmo_orderbook = gmo_orderbooks[0]
            gmo_bids = gmo_orderbook.get('bids', [])
            gmo_asks = gmo_orderbook.get('asks', [])
            
            if len(gmo_bids) < 1 or len(gmo_asks) < 1:
                self.logger.debug(f"**restart**. GMO insufficient orderbook data")
                return True
                
            gmo_best_bid = gmo_bids[0]  # 最高買い価格
            gmo_best_ask = gmo_asks[0]  # 最低売り価格
            #print(buy, sell)
            #print(self.bitbank.store.ticker.find())
            # 取引記録
            # print(self.bitbank.store.transactions.find())
            # 注文記録

            for order in self.orders_bitbank:
                await self.bitbank.order_cancel(order_id=order["order_id"])
            for order in self.orders_gmo:
                await self.gmo.order_cancel(order_id=order["orderId"])
            res = await self.bitbank.send()
            res = await self.gmo.send()

            bitbank_orderbooks = self.bitbank.store.depth.find()
            print(f"Bitbank orderbooks: {len(bitbank_orderbooks)}")
            bitbank_buy_order = [x for x in bitbank_orderbooks if x["side"] == "buy"]
            bitbank_sell_order = [x for x in bitbank_orderbooks if x["side"] == "sell"]
            print(f"Bitbank buy orders: {len(bitbank_buy_order)}, sell orders: {len(bitbank_sell_order)}")
            #print(bitbank_buy_order) # 0が一番上
            #print(bitbank_sell_order) # 0が一番下
            # アービトラージ機会の計算（同一通貨JPYなので為替変換不要）
            # パターン1: GMOで買い、Bitbank信用でショート
            # 条件: GMOの売値 < Bitbankの買値
            gmo_ask_price = float(gmo_best_ask['price']) if gmo_best_ask else 0
            bitbank_bid_price = float(bitbank_buy_order[0]["price"]) if bitbank_buy_order else 0
            
            # パターン2: GMOで売り、Bitbank信用でロング  
            gmo_bid_price = float(gmo_best_bid['price']) if gmo_best_bid else 0
            bitbank_ask_price = float(bitbank_sell_order[0]["price"]) if bitbank_sell_order else 0
            
            # 価格差計算
            arbitrage_opportunity_1 = bitbank_bid_price - gmo_ask_price  # GMO買い、Bitbank売り
            arbitrage_opportunity_2 = gmo_bid_price - bitbank_ask_price  # GMO売り、Bitbank買い
            # ポジション状態の確認
            bitbank_position_size = self.positions_bitbank.get("size", 0)
            gmo_long_size = self.positions_gmo.get("long_size", 0)
            gmo_short_size = self.positions_gmo.get("short_size", 0)
            total_gmo_pos = gmo_long_size + gmo_short_size
            
            # モード判定
            if bitbank_position_size == 0 and total_gmo_pos == 0:
                self.offensive_mode = True
            # 最後にpositionを持ってから10分以上になったら利確モードに入る
            elif self.positions_bitbank.get("timestamp", 0) + 60 * 10 < ts_now:
                self.offensive_mode = False
            # 新規アービトラージ実行（攻撃モード）
            if self.offensive_mode and bitbank_position_size < self.base_qty and total_gmo_pos <= bitbank_position_size:
                # アービトラージ機会1: GMO買い、Bitbank信用売り
                if arbitrage_opportunity_1 > 500:  # 500円以上の価格差
                    qty = min(float(bitbank_buy_order[0]["size"]), self.base_qty - bitbank_position_size)
                    
                    # GMOで買いポジション
                    await self.gmo.buy_in(gmo_ask_price, qty)
                    
                    # Bitbank信用取引でショート
                    await self.bitbank.margin_sell_in(bitbank_bid_price, qty)
                    
                    print(f"アービトラージ実行: GMO買い@{gmo_ask_price}, Bitbank売り@{bitbank_bid_price}, 差額:{arbitrage_opportunity_1}円, 数量:{qty}")
                    return False
                    
                # アービトラージ機会2: GMO売り、Bitbank信用買い  
                elif arbitrage_opportunity_2 > 500:  # 500円以上の価格差
                    qty = min(float(bitbank_sell_order[0]["size"]), self.base_qty - bitbank_position_size)
                    
                    # GMOで売りポジション
                    await self.gmo.sell_in(gmo_bid_price, qty)
                    
                    # Bitbank信用取引でロング
                    await self.bitbank.margin_buy_in(bitbank_ask_price, qty)
                    
                    print(f"アービトラージ実行: GMO売り@{gmo_bid_price}, Bitbank買い@{bitbank_ask_price}, 差額:{arbitrage_opportunity_2}円, 数量:{qty}")
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
                # 利確可能性をチェック
                profit_opportunity_1 = gmo_bid_price - bitbank_ask_price  # GMOロング、Bitbankショート決済
                profit_opportunity_2 = bitbank_bid_price - gmo_ask_price  # GMOショート、Bitbankロング決済
                
                if profit_opportunity_1 > 0 and gmo_long_size > 0:  # GMOロング + Bitbankショート決済
                    close_qty = min(gmo_long_size, abs(bitbank_position_size))
                    
                    # GMOロングポジション決済（売り）
                    gmo_long_positions = [pos for pos in self.gmo.store.positions.find({'symbol': self.gmo.SYMBOL}) if pos.get("side") == "BUY"]
                    if gmo_long_positions:
                        await self.gmo.sell_out(gmo_bid_price, close_qty, gmo_long_positions[0].get("positionId"))
                    
                    # Bitbankショートポジション決済（買い）
                    await self.bitbank.margin_buy_out(bitbank_ask_price, close_qty)
                    
                    print(f"利確決済: GMOロング決済@{gmo_bid_price}, Bitbankショート決済@{bitbank_ask_price}, 利益:{profit_opportunity_1}円, 数量:{close_qty}")
                    return False
                    
                elif profit_opportunity_2 > 0 and gmo_short_size > 0:  # GMOショート + Bitbankロング決済
                    close_qty = min(gmo_short_size, bitbank_position_size)
                    
                    # GMOショートポジション決済（買い）
                    gmo_short_positions = [pos for pos in self.gmo.store.positions.find({'symbol': self.gmo.SYMBOL}) if pos.get("side") == "SELL"]
                    if gmo_short_positions:
                        await self.gmo.buy_out(gmo_ask_price, close_qty, gmo_short_positions[0].get("positionId"))
                    
                    # Bitbankロングポジション決済（売り）
                    await self.bitbank.margin_sell_out(bitbank_bid_price, close_qty)
                    
                    print(f"利確決済: GMOショート決済@{gmo_ask_price}, Bitbankロング決済@{bitbank_bid_price}, 利益:{profit_opportunity_2}円, 数量:{close_qty}")
                    return False

            now_data = {"timestamp": ts_now,
                        "arbitrage_opportunity_1": arbitrage_opportunity_1,
                        "arbitrage_opportunity_2": arbitrage_opportunity_2,
                        "gmo_bid_price": gmo_bid_price,
                        "gmo_ask_price": gmo_ask_price,
                        "bitbank_bid_price": bitbank_bid_price,
                        "bitbank_ask_price": bitbank_ask_price,
                        "bitbank_position_size": bitbank_position_size,
                        "gmo_long_size": gmo_long_size,
                        "gmo_short_size": gmo_short_size,
                        "offensive_mode": self.offensive_mode,
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
