# bybit_usdtperpetual.py

import aiohttp
import asyncio
import async_timeout
import json
from aiohttp import WSMsgType
import traceback
import time
from datetime import datetime
import hmac
import hashlib
from requests import Request
import pybotters
import pandas as pd

class Socket_PyBotters_BitBank():

    # 定数
    TIMEOUT = 3600               # タイムアウト
    EXTEND_TOKEN_TIME = 3000     # アクセストークン延長までの時間
    SYMBOL = 'btc_jpy'           # シンボル[BTCUSDT]
    URLS = {'REST_PRIVATE': 'https://api.bitbank.cc/v1',
            'REST_PUBRIC': 'https://public.bitbank.cc',
            #'REST': 'https://api.bybit.com',
            'WebSocket_Public': 'wss://stream.bitbank.cc/socket.io/?EIO=3&transport=websocket',
           }
    '''
    URLS = {'REST': 'https://api.bybit.com',
            'WebSocket_Public': 'wss://stream.bybit.com/realtime_public',
            'WebSocket_Private': 'wss://stream.bybit.com/realtime_private',
           }  
    '''
    PUBLIC_CHANNELS = [SYMBOL + '@kline_1m',
                       #'candle.1.' + SYMBOL,
                      ]
    #PUBLIC_CHANNELS = []
                      
    PRIVATE_CHANNELS = ['position',
                        'execution',
                        'order',
                        'stop_order',
                        'wallet',
                        ]

    KEYS = {
        'bitbank': ['BITBANK_API_KEY', 'BITBANK_API_SECRET'],
    }
    store = pybotters.bitbankDataStore()
    MAX_OHLCV_CAPACITY = 60 * 60 * 48
    df_ohlcv = pd.DataFrame(
        columns=["exec_date", "Open", "High", "Low", "Close", "Volume", "timestamp"]).set_index("exec_date")

    # 変数
    api_key = ''
    api_secret = ''

    session = None          # セッション保持
    requests = []           # リクエストパラメータ
    heartbeat = 0

    # ------------------------------------------------ #
    # init
    # ------------------------------------------------ #
    def __init__(self, keys):
        # APIキー・SECRETをセット
        self.KEYS = keys

    # ------------------------------------------------ #
    # async request for rest api
    # ------------------------------------------------ #
    async def get_info_bitbank(self):
        self.info()
        response = await self.send()
        pairs = response[0]["data"]["pairs"]
        return next(item for item in pairs if item["name"] == self.SYMBOL)

    async def buy_in(self, sell_price, qty=None):
        self.order_create(side="buy",
                          pair=self.SYMBOL,
                          order_type="limit",
                          qty=qty,
                          price=sell_price,
                          )
        response = await self.send()
        print(response)

    async def buy_out(self, buy_price, exec_qty):
        """
        買いの決済
        """
        self.order_create(side="sell",
                          pair=self.SYMBOL,
                          order_type="limit",
                          qty=exec_qty,
                          price=buy_price,
                          )
        response = await self.send()
        print(response)

    async def order_cancel(self, order_id):
        self._order_cancel(order_id=order_id, pair=self.SYMBOL)
        response = await self.send()
        print(response)

    def set_request(self, method, access_modifiers, target_path, params, base_url=None):
        if base_url is None:
            if access_modifiers == 'private':
                base_url = self.URLS['REST_PRIVATE']
            else:
                base_url = self.URLS['REST_PUBLIC']
            
        url = ''.join([base_url, target_path])
        if method == 'GET':
            headers = ''
            self.requests.append({'method': method,
                                  'access_modifiers': access_modifiers,
                                  'target_path': target_path, 'url': url,
                                  'params': params, 'headers':{}})

        if method == 'POST':
            headers = ''
            self.requests.append({'method': method,
                                  'access_modifiers': access_modifiers,
                                  'target_path': target_path, 'url': url,
                                  'params': params, 'headers':headers})


        if method == 'PUT':
            post_data = json.dumps(params)
            self.requests.append({'url': url,
                                  'method': method,
                                  'params': post_data,
                                  })

        if method == 'DELETE':
            self.requests.append({'url': url,
                                  'method': method,
                                  'params': params,
                                  })


    async def fetch(self, req):
        status = 0
        content = []
        async with pybotters.Client(apis=self.KEYS) as client:
            if req["method"] == 'GET':
                r = await client.get(req['url'], params=req['params'], headers=req['headers'])
            else:
                r = await client.request(req["method"], req['url'], data=req['params'], headers=req['headers'])
            if r.status == 200:
                content = await r.read()

            if len(content) == 0:
                result = []
            else:
                try:
                    result = json.loads(content.decode('utf-8'))
                except Exception as e:
                    traceback.print_exc()

                return result

    async def send(self):
        promises = [self.fetch(req) for req in self.requests]
        self.requests.clear()
        return await asyncio.gather(*promises)

    # ------------------------------------------------ #
    # REST API(Market Data Endpoints)
    # ------------------------------------------------ #
    # transactions
    # 確認済
    def transactions(self, yyyymmdd=None):
        target_path = '/' + self.SYMBOL + '/transactions'
        if yyyymmdd:
            target_path += '/' + yyyymmdd
        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Query Kline
    # 確認済
    def kline(self, pair, interval, yyyymmdd):
        target_path = '/' + pair + '/candlestick/' + interval + '/' + yyyymmdd
        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)
                         
    
    # Latest Information for Symbol
    # 確認済
    def ticker(self, pair):
        target_path = '/' + pair + '/ticker'
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path)

    def depth(self):
        target_path = '/' + self.SYMBOL + '/depth'
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path)

    
    # ------------------------------------------------ #
    # REST API(Account Data Endpoints)
    # ------------------------------------------------ #

    def order_create(self, side, pair, order_type, qty, price='', post_only='', trigger_price=''):
        target_path = '/user/spot/order'
        params = {
                    'side': side,
                    'pair': pair,
                    'type': order_type,
                    'amount': qty,
        }

        if len(str(price)) > 0:
            params['price'] = float(price)
        if len(str(post_only)) > 0:
            params['post_only'] = post_only
        if len(str(trigger_price)) > 0:
            params['trigger_price'] = trigger_price

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)
        print(self.requests)
    
    # Get Active Order
    def order_list(self, pair, count=None, from_id=None, end_id=None, since=None, end=None):
        target_path = '/user/spot/active_orders'
        
        params = {
                    'pair': pair
        }

        if count is not None:
            params['count'] = int(count)
        if from_id is not None:
            params['from_id'] = int(from_id)
        if end_id is not None:
            params['end_id'] = int(end_id)
        if since is not None:
            params['since'] = int(since)
        if end is not None:
            params['end'] = int(end)

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)



    # Cancel Active Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # order_id	        true	    string	    Order ID. Required if not passing order_link_id
    # ================================================================
    def _order_cancel(self, pair, order_id=''):
        target_path = '/user/spot/cancel_order'
        
        params = {
                    'pair': pair,
                    'order_id': order_id,
        }

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)


    def orders_cancel(self, pair, order_ids):
        target_path = '/user/spot/cancel_orders'
        
        params = {
                    'pair': pair,
                    'order_ids': order_ids
        }

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    def order_info(self, pair, order_id):
        target_path = '/user/spot/order'

        params = {
            'pair':pair,
            'order_id': order_id
        }

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)


    # My Position
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # ================================================================
    def position_list(self):
        target_path = '/user/assets'

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params={})



    # User Trade Records
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # start_time	    false	    integer	    Start timestamp point for result, in milliseconds. Timestamp must be within seven days of the current date. For earlier records, please contact customer support
    # end_time	        false	    integer	    End timestamp point for result, in milliseconds. Timestamp must be within seven days of the current date. For earlier records, please contact customer support
    # exec_type	        false	    string	    Execution type
    # page	            false	    integer	    Page. By default, gets first page of data
    # limit	            false	    integer	    Limit for data size per page, max size is 200. Default as showing 50 pieces of data per page.
    # ================================================================
    def execution_list(self, pair, count=None, order_id=None, since=None, end=None, order=''):
        target_path = '/user/spot/trade_history'

        params = {
                    'pair': pair
        }
        
        if count is not None:
            params['count'] = int(count)
        if order_id is not None:
            params['order_id'] = int(order_id)
        if since is not None:
            params['since'] = int(since)
        if end is not None:
            params['end'] = int(end)
        if len(str(order)) > 0:
            params['order'] = str(order)

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    def info(self):
        target_path = '/spot/pairs'
        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params={})


    # ------------------------------------------------ #
    # WebSocket
    # ------------------------------------------------ #

    async def ws_run(self):
        async with pybotters.Client(apis=self.KEYS) as client:

            public = await client.ws_connect(
                self.URLS['WebSocket_Public'],
                send_str=[
                    f'42["join-room","ticker_{self.SYMBOL}"]',
                    f'42["join-room","transactions_{self.SYMBOL}"]',
                    f'42["join-room","depth_whole_{self.SYMBOL}"]',
                ],
                hdlr_str=self.store.onmessage,
            )

            #def stores(store):
            #    xx = []
            #    for x in self.PUBLIC_CHANNELS:
            #        if x.startswith('candle.'):
            #            xx.append(len(store.kline))
            #        if x.startswith('trade.'):
            #            xx.append(len(store.trade))
            #        if x.startswith('orderBookL2_25.') or x.startswith('orderBook_200.'):
            #            xx.append(len(store.orderbook))
            #        if x.startswith('instrument_info.'):
            #            xx.append(len(store.instrument))
            #    return xx
            #while not all(stores(self.store)):
            while True:
                await self.store.wait()
                # store dict
                # {'orderbook', 'trade', 'insurance', 'instrument', 'kline', 'liquidation', 'position_inverse', 'position_usdt', 'execution', 'order', 'stoporder', 'wallet', '_events', 'timestamp_e6'}

            #watch_kline = await asyncio.gather(
            #    self.realtime_klines(),
            #)
            #await watch_kline

    async def realtime_klines(self):
        with self.store.kline.watch() as klines:
            async for msg in klines:
                data = msg.data
                data_d = {"exec_date": int(data["start"]),
                          "timestamp": int(data["start"]),
                          "Open": float(data["open"]),
                          "High": float(data["high"]),
                          "Low": float(data["low"]),
                          "Close": float(data["close"]),
                          "Volume": float(data["volume"]),
                         }
                data_d = pd.DataFrame(data_d, index=[0])
                data_d["exec_date"] = pd.to_datetime(data_d['exec_date'], unit="s")
                data_d = data_d.set_index("exec_date")
                data_d["timestamp"] = data_d["timestamp"].astype(int)
                if len(self.df_ohlcv) == 0:
                    self.df_ohlcv = pd.concat([self.df_ohlcv, data_d])
                else:
                    last_timestamp = self.df_ohlcv.index[-1]
                    if last_timestamp == data_d.index[0]:
                        self.df_ohlcv.update(data_d)
                    else:
                        self.df_ohlcv = pd.concat([self.df_ohlcv, data_d])

                await asyncio.sleep(1)
            if len(self.df_ohlcv) > self.MAX_OHLCV_CAPACITY:
                self.df_ohlcv = self.df_ohlcv[1:]


