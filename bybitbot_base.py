import asyncio
import traceback
import pandas as pd

import utils

class BybitBotBase():
    #User can ues MAX_DATA_CAPACITY to control memory usage.
    open_time_old = 0

    # ---------------------------------------- #
    # init
    # ---------------------------------------- #
    def __init__(self):
        self.orderbook_check = False
        self.execute_check = {}
        self.df = pd.DataFrame()
        self.trade = pd.DataFrame()
        self.df_ohlcv = pd.DataFrame(columns=["exec_date", "Open", "High", "Low", "Close", "Volume", "timestamp"]).set_index("exec_date")
        self.df_2h_ohlcv = pd.DataFrame(
            columns=["exec_date", "Open", "High", "Low", "Close", "Volume", "timestamp"]).set_index("exec_date")
        self.sum_profit = 0
        self.sum_fee = 0
        self.Debug = False

    # ---------------------------------------- #
    # bot main
    # ---------------------------------------- #

    async def resample(self):
        try:
            if 1 < len(self.df_ohlcv) < 60 * 36:
                while len(self.df_ohlcv) < 60 * 36:
                    first_line = self.df_ohlcv.index.view('int64')[0] // 10**9
                    self.bybit.kline(1, first_line - 200 * 60)
                    response = await self.bybit.send()

                    if response[0]["ret_code"] == 0:
                        data_d_list = []
                        for data in response[0]["result"]:
                            data_d = {"exec_date": int(data["start_at"]),
                                      "timestamp": int(data["start_at"]),
                                      "Open": float(data["open"]),
                                      "High": float(data["high"]),
                                      "Low": float(data["low"]),
                                      "Close": float(data["close"]),
                                      "Volume": float(data["volume"]),
                                     }
                            data_d_list.append(data_d)
                        data_d = pd.DataFrame(data_d_list)
                        data_d["exec_date"] = pd.to_datetime(data_d['exec_date'], unit="s")
                        data_d = data_d.set_index("exec_date")
                        self.df_ohlcv = pd.concat([data_d, self.df_ohlcv])

            if 1 < len(self.df_ohlcv):
                self.df_2h_ohlcv = utils.resample(self.df_ohlcv, 60 * 60 * 2, 12)
        except Exception as e:
            print(e)
            print(traceback.format_exc().strip())


    async def run(self):
        while(True):
            await self.resample()
            await self.main()
            await asyncio.sleep(30)


    async def main(self):
        pass
