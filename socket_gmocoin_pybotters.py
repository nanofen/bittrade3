# bybit_usdtperpetual.py

import aiohttp
import asyncio
from enum import Enum
import json
import traceback
import pybotters
import pandas as pd

class Socket_PyBotters_GMOCoin():

    # 定数
    TIMEOUT = 3600               # タイムアウト
    EXTEND_TOKEN_TIME = 3000     # アクセストークン延長までの時間
    SYMBOL = 'BTC_JPY'           # シンボル[BTCUSDT]
    URLS = {'REST_PRIVATE': 'https://api.coin.z.com/private',
            'REST_PUBRIC': 'https://api.coin.z.com/public',
            'WebSocket_Public': 'wss://api.coin.z.com/ws/public/v1',
            'WebSocket_Private': 'wss://api.coin.z.com/ws/private/v1/{}',
           }
    '''
    URLS = {'REST': 'https://api.bybit.com',
            'WebSocket_Public': 'wss://stream.bybit.com/realtime_public',
            'WebSocket_Private': 'wss://stream.bybit.com/realtime_private',
           }  
    '''
    PUBLIC_CHANNELS = ['ticker',
                       'orderbooks',
                       'trades',
                      ]
    #PUBLIC_CHANNELS = []
                      
    PRIVATE_CHANNELS = ['position',
                        'execution',
                        'order',
                        'stop_order',
                        'wallet',
                        ]

    KEYS = {
        'gmocoin': ['GMOCOIN_API_KEY', 'GMOCOIN_API_SECRET'],
    }
    store = pybotters.GMOCoinDataStore()
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
    async def get_info_gmocoin(self):
        self.info()
        response = await self.send()
        pairs = response[0]["data"]["pairs"]
        return next(item for item in pairs if item["name"] == self.SYMBOL)

    async def buy_in(self, sell_price, qty=None):
        self.order_create(side="BUY",
                          symbol=self.SYMBOL,
                          executionType="LIMIT",
                          qty=qty,
                          price=sell_price,
                          )
        response = await self.send()
        print(response)

    async def buy_out(self, buy_price, exec_qty, pos_id):
        """
        買いの決済
        """
        self.order_close(side="SELL",
                         symbol=self.SYMBOL,
                         executionType="LIMIT",
                         qty=exec_qty,
                         price=buy_price,
                         positionId=pos_id,
                         )
        response = await self.send()
        print(response)

    async def sell_in(self, buy_price, qty=None):
        self.order_create(side="SELL",
                          symbol=self.SYMBOL,
                          executionType="LIMIT",
                          qty=qty,
                          price=buy_price,
                          )
        response = await self.send()
        print(response)

    async def sell_out(self, sell_price, exec_qty, pos_id):
        """
        買いの決済
        """
        self.order_close(side="BUY",
                         symbol=self.SYMBOL,
                         executionType="LIMIT",
                         qty=exec_qty,
                         price=sell_price,
                         positionId=pos_id,
                         )
        response = await self.send()
        print(response)

    async def order_cancel(self, order_id):
        self._order_cancel(order_id=order_id)
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


    # Query Kline
    # 確認済
    def kline(self, symbol, interval, date):
        target_path = '/v1/klines'
        params = {
                    'interval': interval,
                    'symbol': symbol,
                    'date': date,
        }
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)
                         
    
    # Latest Information for Symbol
    # 確認済
    def ticker(self, pair):
        target_path = '/v1/ticker'
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path)

    def info(self):
        target_path = '/v1/symbols'

        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params={})

    
    # ------------------------------------------------ #
    # REST API(Account Data Endpoints)
    # ------------------------------------------------ #

    def order_create(self, side, symbol, executionType, qty, price='', timeInForce='', losscutPrice=''):
        target_path = '/v1/order'
        params = {
                    'side': side,
                    'symbol': symbol,
                    'executionType': executionType,
                    'size': qty,
        }

        if len(str(price)) > 0:
            params['price'] = float(price)
        if len(str(timeInForce)) > 0:
            params['post_only'] = timeInForce
        if len(str(losscutPrice)) > 0:
            params['losscutPrice'] = losscutPrice


        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)
        print(self.requests)

    def order_close(self, side, symbol, executionType, qty, positionId, price='', timeInForce='', losscutPrice=''):
        target_path = '/v1/closeOrder'
        params = {
                    'side': side,
                    'symbol': symbol,
                    'executionType': executionType,
                    'settlePosition': {'positionId': positionId, 'size': qty},
        }

        if len(str(price)) > 0:
            params['price'] = float(price)
        if len(str(timeInForce)) > 0:
            params['post_only'] = timeInForce
        if len(str(losscutPrice)) > 0:
            params['losscutPrice'] = losscutPrice


        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)
        print(self.requests)
    
    # Get Active Order
    def order_list(self, symbol, count=None, page=None):
        target_path = '/v1/activeOrders'
        
        params = {
                    'symbol': symbol
        }

        if count is not None:
            params['count'] = int(count)
        if page is not None:
            params['page'] = int(page)

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
    def _order_cancel(self, order_id=''):
        target_path = '/v1/cancelOrder'
        
        params = {
                    'orderId': order_id,
        }

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)


    def orders_cancel(self, order_ids):
        target_path = '/v1/cancelOrders'
        
        params = {
                    'orderIds': order_ids
        }

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    def order_bulk_cancel(self, symbols, side='', settle_type='', desc=''):
        target_path = '/v1/cancelBulkOrder'

        params = {
            'symbols': symbols
        }

        if len(str(side)) > 0:
            params['side'] = side
        if len(str(settle_type)) > 0:
            params['settleType'] = settle_type
        if len(str(desc)) > 0:
            params['desc'] = desc

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    def order_info(self, order_id):
        target_path = '/v1/orders'

        params = {
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
    def position_list(self, symbol):
        target_path = '/v1/openPositions'

        params = {
            'symbol': symbol
        }

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)



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
    def execution_list(self, symbol):
        target_path = '/v1/latestExecutions'

        params = {
                    'symbol': symbol
        }


        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)


    # ------------------------------------------------ #
    # WebSocket
    # ------------------------------------------------ #

    async def ws_run(self):
        try:
            async with pybotters.Client(apis=self.KEYS, base_url=self.URLS["REST_PRIVATE"]) as client:
                await self.store.initialize(
                    client.post("/v1/ws-auth", params={}),
                    client.get("/v1/activeOrders", params={'symbol': self.SYMBOL}),
                    client.get("/v1/openPositions", params={'symbol': self.SYMBOL}),
                    client.get("/v1/latestExecutions", params={'symbol': self.SYMBOL}),
                    client.get("/v1/positionSummary", params={}),)

                await client.ws_connect(
                    self.URLS['WebSocket_Public'],
                    send_json=[{
                            "command": "subscribe",
                            "channel": "trades",
                            "symbol": self.SYMBOL,
                        },
                        {
                            "command": "subscribe",
                            "channel": "orderbooks",
                            "symbol": self.SYMBOL,
                        },
                    ],
                    hdlr_json=self.store.onmessage
                )

                await client.ws_connect(
                    self.URLS['WebSocket_Private'].format(self.store.token),
                    send_json=[
                        {
                            "command": "subscribe",
                            "channel": "positionEvents",
                        },
                        {
                            "command": "subscribe",
                            "channel": "orderEvents",
                        },
                    ],
                    hdlr_json=self.store.onmessage,
                )



                while True:
                    #print("orderbook", self.store.orderbooks.find())
                    #print("trade", self.store.trades.find())
                    #print(self.store.orders.find())
                    await self.store.wait()

                    # store dict
                    # {'orderbook', 'trade', 'insurance', 'instrument', 'kline', 'liquidation', 'position_inverse', 'position_usdt', 'execution', 'order', 'stoporder', 'wallet', '_events', 'timestamp_e6'}

                #watch_kline = await asyncio.gather(
                #    self.realtime_klines(),
                #)
                #await watch_kline
        except Exception as e:
            print(e)



