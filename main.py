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
import yfinance as yf
import bybitbot_base
from socket_bitbank_pybotters import Socket_PyBotters_BitBank
from socket_bybit_pybotters import Socket_PyBotters_Bybit
from get_logger import get_custom_logger
import warnings
warnings.simplefilter('ignore')


class ArbitrageBot(bybitbot_base.BybitBotBase):
    # User can ues MAX_DATA_CAPACITY to control memory usage.
    open_time_old = 0

    # ---------------------------------------- #
    # init
    # ---------------------------------------- #
    def __init__(self, keys, prod, log_level="INFO"):
        super().__init__()
        self.keys = keys

        print(self.keys)

        self.bybit = Socket_PyBotters_Bybit(self.keys, prod=prod)
        self.bybit.SYMBOL = 'BTCUSDT'
        self.bybit.PUBLIC_CHANNELS = ['kline.1.' + self.bybit.SYMBOL,
                                      'orderbook.50.' + self.bybit.SYMBOL,
                                      # 'orderBook_200.100ms.' + self.bybit.SYMBOL,
                                      # 'instrument_info.100ms.' + self.bybit.SYMBOL,
                                      #'candle.1.' + self.bybit.SYMBOL,
                                      ]
        self.bybit.PRIVATE_CHANNELS = ["position",
                                       "execution",
                                       "order",
                                       "wallet",
                                       "greeks",]

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
        self.base_qty = 0.1
        self.bitbank_info = 0


        self.qty = self.base_qty
        self.Debug = False
        self.positions_bitbank = {}
        self.positions_bybit = {"sell_size": 0.0, "buy_size": 0.0}
        self.orders_bybit = []
        self.slip_in = 0.0
        self.slip_out = 0.0
        self.info = {}
        self.usdjpy ={}
        self.orders_bitbank = []
        self.btc_amounts = {}
        self.offensive_mode = True


        self.logger = get_custom_logger(log_level)
        self.emergency_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        self.emergency_qty_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)


        # タスクの設定およびイベントループの開始
        loop = asyncio.get_event_loop()
        tasks = [
            self.bybit.ws_run(),
            self.bitbank.ws_run(),
            #self.bybit.private_ws_run(),
            self.run()
        ]

        loop.run_until_complete(asyncio.wait(tasks))

    async def get_usdjpy(self):
        try:
            yfdata = yf.download(tickers="JPY=X", period="1d", interval="1m", progress=False)
            self.usdjpy["Adj Close"] = yfdata["Adj Close"][-1]
            self.usdjpy["Close"] = yfdata["Close"][-1]
        except Exception as e:
            print(traceback.format_exc().strip())

    async def order_check(self):
        await self.order_list_bitbank()
        await self.order_list_bybit()

    async def order_cancel_all(self):
        for order in self.orders_bitbank:
            await self.bitbank.order_cancel(order_id=order["order_id"])
        for order in self.orders_bybit:
            self.bybit.order_cancel(order_id=order["orderId"])
        res = await self.bitbank.send()
        res = await self.bybit.send()

    async def order_list_bybit(self):
        try:
            self.bybit.order_list()
            res = await self.bybit.send()
            if res[0]["result"]["list"] is not None:
                self.orders_bybit = res[0]["result"]["list"]
            else:
                self.orders_bybit = []
        except Exception as e:
            print(traceback.format_exc().strip())

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

    def position_check_bybit(self):
        dt = datetime.datetime.now(datetime.timezone.utc)
        utc_time = dt.replace(tzinfo=datetime.timezone.utc)
        ts_now = int(utc_time.timestamp())
        
        # 売りポジション（ショート）を取得
        sell_pos = self.bybit.store.position.find({'symbol': self.bybit.SYMBOL, 'side': 'Sell'})
        sell_pos_size = sum([float(x["size"]) for x in sell_pos])
        
        # 買いポジション（ロング）を取得
        buy_pos = self.bybit.store.position.find({'symbol': self.bybit.SYMBOL, 'side': 'Buy'})
        buy_pos_size = sum([float(x["size"]) for x in buy_pos])
        
        if len(self.positions_bybit) == 0:
            self.positions_bybit = {"symbol": self.bybit.SYMBOL,
                                    "sell_size": 0.0,
                                    "buy_size": 0.0,
                                    "timestamp": ts_now}
        
        # 売りまたは買いポジションに変更があった場合に更新
        if (sell_pos_size != self.positions_bybit.get("sell_size", 0) or 
            buy_pos_size != self.positions_bybit.get("buy_size", 0)):
            self.positions_bybit = {"symbol": self.bybit.SYMBOL,
                                    "sell_size": sell_pos_size,
                                    "buy_size": buy_pos_size,
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
        self.bitbank_info = await self.bitbank.get_info_bitbank()
        while True:
            await self.order_check()
            await self.order_cancel_all()
            await self.position_check_bitbank()
            self.position_check_bybit()

            await self.get_usdjpy()
            await self.main()
            await asyncio.sleep(1)


    async def main(self):
        try:
            if self.usdjpy.get("Close") is None:
                return True
            #self.logger.info("start main...")
            #data = self.df_ohlcv.iloc[-1]
            ts_now = self.get_timestamp()

            buy_order = self.bybit.store.orderbook.find({'symbol': self.bybit.SYMBOL, 'side': 'bids'})
            sell_order = self.bybit.store.orderbook.find({'symbol': self.bybit.SYMBOL, 'side': 'asks'})
            if len(buy_order) < 1 or len(sell_order) < 1:
                self.logger.debug(f"**restart**. not enough order data {len(buy_order)} {len(sell_order)}")
                return True
            buy = buy_order[0]
            sell = sell_order[0]
            #print(buy, sell)
            #print(self.bitbank.store.ticker.find())
            # 取引記録
            # print(self.bitbank.store.transactions.find())
            # 注文記録

            for order in self.orders_bitbank:
                await self.bitbank.order_cancel(order_id=order["order_id"])
            for order in self.orders_bybit:
                self.bybit.order_cancel(order_id=order["orderId"])
            res = await self.bitbank.send()
            res = await self.bybit.send()

            bitbank_orderbooks = self.bitbank.store.depth.find()
            bitbank_buy_order = [x for x in bitbank_orderbooks if x["side"] == "buy"]
            bitbank_sell_order = [x for x in bitbank_orderbooks if x["side"] == "sell"]
            #print(bitbank_buy_order) # 0が一番上
            #print(bitbank_sell_order) # 0が一番下
            # in
            # マイナスの場合 bybitのbuy値段よりbitbankのsell値段は高いことになる(inできない)
            # プラスの場合 bybitのbuy値段よりbitbankのsell値段は低い(inできる)
            #("in", float(buy["price"]) - float(bitbank_sell_order[0]["price"]) / self.usdjpy["Close"],
            #      bitbank_sell_order[0]["size"], float(bitbank_sell_order[0]["price"]) / self.usdjpy["Close"],
            #      buy["size"], buy["price"], )
            # out
            # マイナスの場合 bybitのsell値段よりbitbankのbuy値段は低い(inの時の利益 - 損失)
            # ゼロの時  bybitのsell値段とbitbankのbuy値段は均衡(inの時の利益)
            # プラスの場合 bybitのsell値段よりbitbankのbuy値段は高い(inの時の利益 + 差額利益)
            #print("out", float(bitbank_buy_order[0]["price"]) / self.usdjpy["Close"] - float(sell["price"]),
            #      bitbank_buy_order[0]["size"], float(bitbank_buy_order[0]["price"]) / self.usdjpy["Close"],
            #      sell["size"], sell["price"], )
            # bybit bitbank
            # in
            #  ×    〇    〇   ×
            # 110 / 105   100 / 95
            # 105 - 100 = 5$ ?
            # sell pos    buy pos
            #  〇    ×    ×  〇

            # 115 / 110   115 / 110
            # bybit 105 - 115 = -10
            # bitbank 110 - 100 = 10
            # 0$
            # (105 - 100) + (110 - 115) = 0

            # 130 / 125   120 / 115
            # bybit 105 - 130 = -25
            # bitbank 115 - 100 = 15
            # -10$
            # (105 - 100) + (115 - 130) = -10

            # 115 / 110   120 / 115
            # bybit 105 - 115 = -10
            # bitbank 115 - 100 = 15
            # 5$
            # (105 - 100) + (115 - 115) = 5

            # 売り63259.10 買い62747.62 = ~500$
            # 買い63160.00 売り63029.99 = ~-150$
            # = 350$

            # orderが残っている場合はキャンセル
            # return True
            # bitbankが安いのか / bybitが高いのか？は判定できてない
            # Bybitの総ポジション（売り+買い）を計算
            total_bybit_pos = self.positions_bybit.get("sell_size", 0) + self.positions_bybit.get("buy_size", 0)
            if self.positions_bitbank["size"] == 0 and total_bybit_pos == 0:
                self.offensive_mode = True
            # 最後にpositionを持ってから10分以上になったら利確モードに入る
            if self.positions_bitbank["timestamp"] + 60 * 10 < ts_now:
                self.offensive_mode = False
            # 条件1 初期 まだ買えるがposが安定
            if self.offensive_mode and self.positions_bitbank["size"] < self.base_qty and (self.positions_bybit.get("sell_size", 0) == self.positions_bitbank["size"]):



                if float(buy["price"]) - float(bitbank_sell_order[0]["price"]) / self.usdjpy["Close"] > 200:
                    qty = float(bitbank_sell_order[0]["size"])
                    if qty > self.base_qty - float(self.positions_bitbank["size"]):
                        qty = self.base_qty - float(self.positions_bitbank["size"])
                    await self.bitbank.buy_in(float(bitbank_sell_order[0]["price"]), qty)
                    get_pos_flg = False
                    ts_now = self.get_timestamp()
                    while True:
                        await self.position_check_bitbank()
                        buy_pos_size = self.positions_bitbank["size"]
                        if buy_pos_size == 0:
                            pass
                        if buy_pos_size < qty:
                            get_pos_flg = True
                            self.positions_bitbank["price_jpy_bitbank"] = float(bitbank_sell_order[0]["price"])
                            self.positions_bitbank["price_bitbank"] = float(bitbank_sell_order[0]["price"]) / self.usdjpy["Close"]
                        elif buy_pos_size == qty:
                            get_pos_flg = True
                            self.positions_bitbank["price_jpy_bitbank"] = float(bitbank_sell_order[0]["price"])
                            self.positions_bitbank["price_bitbank"] = float(bitbank_sell_order[0]["price"]) / self.usdjpy["Close"]
                            break
                        if self.get_timestamp() - ts_now > 1:
                            break
                        await asyncio.sleep(0.1)
                    if not get_pos_flg:
                        return False
                    print("in", float(buy["price"]) - float(bitbank_sell_order[0]["price"]) / self.usdjpy["Close"],
                          bitbank_sell_order[0]["size"], float(bitbank_sell_order[0]["price"]) / self.usdjpy["Close"],
                          buy["size"], buy["price"], )

                    #"""
                    pos_size = buy_pos_size
                    await self.bybit.sell_in(float(buy["price"]), pos_size)
                    ts_now = self.get_timestamp()
                    while True:
                        self.position_check_bybit()
                        sell_pos_size = self.positions_bybit.get("sell_size", 0)
                        if sell_pos_size == 0:
                            pass
                        if sell_pos_size < pos_size:
                            self.positions_bybit["price_bybit"] = float(buy["price"])
                        elif sell_pos_size == pos_size:
                            self.positions_bybit["price_bybit"] = float(buy["price"])
                            break
                        if self.get_timestamp() - ts_now > 1:
                            break
                        await asyncio.sleep(0.1)
                    return False
                    #"""
            # 条件2 bitbankはいっぱいだがposが不安定
            if self.offensive_mode and self.positions_bitbank["size"] == self.base_qty and (self.positions_bybit.get("sell_size", 0) < self.positions_bitbank["size"]):
                pos_size = self.positions_bitbank["size"] - self.positions_bybit.get("sell_size", 0)
                await self.bybit.sell_in(float(buy["price"]), pos_size)
                ts_now = self.get_timestamp()
                while True:
                    self.position_check_bybit()
                    sell_pos_size = self.positions_bybit.get("sell_size", 0)
                    if sell_pos_size == 0:
                        pass
                    if sell_pos_size < pos_size:
                        self.positions_bybit["price_bybit"] = float(buy["price"])
                    elif sell_pos_size == pos_size:
                        self.positions_bybit["price_bybit"] = float(buy["price"])
                        break
                    if self.get_timestamp() - ts_now > 1:
                        break
                    await asyncio.sleep(0.1)
                return False
            # 条件2 bitbank bybitともにいっぱい
            if not self.offensive_mode and (total_bybit_pos > 0 or self.positions_bitbank["size"] > 0):
                # 売る
                if float(bitbank_buy_order[0]["price"]) / self.usdjpy["Close"] - float(sell["price"]) > 0:
                    await self.bitbank.buy_out(float(bitbank_sell_order[0]["price"]), self.positions_bitbank["size"])
                    base_pos_size = self.positions_bitbank["size"]
                    sell_pos_flg = False
                    while True:
                        await self.position_check_bitbank()
                        pos_size = self.positions_bitbank["size"]
                        if pos_size == base_pos_size:
                            pass
                        if pos_size == 0:
                            sell_pos_flg = True
                            break
                        elif pos_size < base_pos_size:
                            sell_pos_flg = True
                            break
                        if self.get_timestamp() - ts_now > 1:
                            break
                        await asyncio.sleep(0.1)
                    if not sell_pos_flg:
                        return False
                    print("out", float(bitbank_buy_order[0]["price"]) / self.usdjpy["Close"] - float(sell["price"]),
                          bitbank_buy_order[0]["size"], float(bitbank_buy_order[0]["price"]) / self.usdjpy["Close"],
                          sell["size"], sell["price"], )

                    # 売りポジションがある場合は売りポジションを決済
                    if self.positions_bybit.get("sell_size", 0) > 0:
                        await self.bybit.sell_out(float(sell["price"]), self.positions_bybit["sell_size"] - pos_size)
                    
                    # 買いポジションがある場合は買いポジションを決済
                    if self.positions_bybit.get("buy_size", 0) > 0:
                        await self.bybit.buy_out(float(sell["price"]), self.positions_bybit["buy_size"])

            now_data = {"timestamp": ts_now,
                        "in_diff": float(buy["price"]) - float(bitbank_sell_order[0]["price"]) / self.usdjpy["Close"],
                        "out_diff": float(bitbank_buy_order[0]["price"]) / self.usdjpy["Close"] - float(sell["price"]),
                        "bybit_buy_price": float(buy["price"]),
                        "bybit_buy_size": float(buy["size"]),
                        "bybit_sell_price": float(sell["price"]),
                        "bybit_sell_size": float(sell["size"]),
                        "bitbank_buy_price": float(bitbank_buy_order[0]["price"]),
                        "bitbank_buy_size": float(bitbank_buy_order[0]["size"]),
                        "bitbank_sell_price": float(bitbank_sell_order[0]["price"]),
                        "bitbank_sell_size": float(bitbank_sell_order[0]["size"]),
                        "usdypy": self.usdjpy["Close"],
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
    if args.prod:
        bybit_key, bybit_secret = auth.BybitKeys().keys(prod=args.prod, env_name="lgbm")
        bitbank_key, bitbank_secret = auth.BitbankKeys().keys()
        keys = {'bybit': [bybit_key, bybit_secret],
                'bitbank': [bitbank_key, bitbank_secret],}
    else:
        bybit_key, bybit_secret = auth.BybitKeys().keys(False, env_name="lgbm")
        bitbank_key, bitbank_secret = auth.BitbankKeys().keys()
        keys = {'bybit_testnet': [bybit_key, bybit_secret],
                'bitbank': [bitbank_key, bitbank_secret],}
    ArbitrageBot(keys=keys, prod=args.prod, log_level="INFO")
