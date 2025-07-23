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


class Socket_PyBotters_Bybit():
    # 定数
    TIMEOUT = 3600  # タイムアウト
    EXTEND_TOKEN_TIME = 3000  # アクセストークン延長までの時間
    SYMBOL = 'BTCUSDT'  # シンボル[BTCUSDT]
    URLS = {'REST': 'https://api-testnet.bybit.com/',
            # 'REST': 'https://api.bybit.com',
            'WebSocket_Public': 'wss://stream-testnet.bybit.com/v5/public',
            'WebSocket_Private': 'wss://stream-testnet.bybit.com/v5/private',
            }
    '''
    URLS = {'REST': 'https://api.bybit.com',
            'WebSocket_Public': 'wss://stream.bybit.com/realtime_public',
            'WebSocket_Private': 'wss://stream.bybit.com/realtime_private',
           }  
    '''
    PUBLIC_CHANNELS = [SYMBOL + '@kline_1m',
                       # 'candle.1.' + SYMBOL,
                       ]
    # PUBLIC_CHANNELS = []

    PRIVATE_CHANNELS = ['position',
                        'execution',
                        'order',
                        'stop_order',
                        'wallet',
                        ]

    KEYS = {
        'bybit': ['BYBIT_API_KEY', 'BYBIT_API_SECRET'],
        'bybit_testnet': ['BYBIT_API_KEY', 'BYBIT_API_SECRET'],
    }
    store = pybotters.BybitDataStore()
    MAX_OHLCV_CAPACITY = 60 * 60 * 1
    df_ohlcv = pd.DataFrame(
        columns=["exec_date", "Open", "High", "Low", "Close", "Volume", "timestamp"]).set_index("exec_date")

    # 変数
    api_key = ''
    api_secret = ''

    session = None  # セッション保持
    requests = []  # リクエストパラメータ
    heartbeat = 0

    # ------------------------------------------------ #
    # init
    # ------------------------------------------------ #
    def __init__(self, keys, prod=False):
        # APIキー・SECRETをセット
        self.KEYS = keys
        if prod:
            self.URLS = {'REST': 'https://api.bybit.com/',
                         'WebSocket_Public': "wss://stream.bybit.com/v5/public/linear",
                         'WebSocket_Private': "wss://stream.bybit.com/v5/private",
                         }

    async def sell_in(self, buy_price, qty):
        self.order_create(side="Sell",
                          order_type="Limit",
                          qty=qty,
                          price=str(buy_price),
                          time_in_force="GTC",
                          close_on_trigger=False,
                          reduce_only=False,
                          )
        response = await self.send()
        print(response)
        return response

    async def sell_out(self, sell_price, exec_qty, timestamp=None):
        """
        売りの決済
        """
        self.order_create(side="Buy",
                          order_type="Limit",
                          qty=exec_qty,
                          price=str(sell_price),
                          time_in_force="GTC",
                          close_on_trigger=False,
                          order_link_id=str(timestamp) + "_sellout",
                          reduce_only=True,
                          )
        response = await self.send()
        print(response)

    async def buy_in(self, sell_price, qty):
        self.order_create(side="Buy",
                          order_type="Limit",
                          qty=qty,
                          price=str(sell_price),
                          time_in_force="GTC",
                          close_on_trigger=False,
                          reduce_only=False
                          )
        response = await self.send()
        print(response)

    async def buy_out(self, buy_price, exec_qty, timestamp=None):
        """
        買いの決済
        """
        self.order_create(side="Sell",
                          order_type="Limit",
                          qty=exec_qty,
                          price=str(buy_price),
                          time_in_force="GTC",
                          close_on_trigger=False,
                          order_link_id=str(timestamp) + "_buyout",
                          reduce_only=True,
                          )
        response = await self.send()
        print(response)

        # ------------------------------------------------ #

    # async request for rest api
    # ------------------------------------------------ #

    def set_request(self, method, access_modifiers, target_path, params, base_url=None):
        if base_url is None:
            base_url = self.URLS['REST']

        url = ''.join([base_url, target_path])
        if method == 'GET':
            headers = ''
            self.requests.append({'method': method,
                                  'access_modifiers': access_modifiers,
                                  'target_path': target_path, 'url': url,
                                  'params': params, 'headers': {}})

        if method == 'POST':
            headers = ''
            self.requests.append({'method': method,
                                  'access_modifiers': access_modifiers,
                                  'target_path': target_path, 'url': url,
                                  'params': params, 'headers': headers})

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

    async def fetch(self, req, retry_count=3, retry_delay=10):
        try:
            kwargs = {
                'timeout': aiohttp.ClientTimeout(total=10)}
            async with pybotters.Client(apis=self.KEYS, **kwargs) as client:
                if req["method"] == 'GET':
                    response = await client.get(req['url'], params=req['params'], headers=req['headers'])
                else:
                    response = await client.request(req["method"], req['url'], data=req['params'],
                                                    headers=req['headers'])

                if response.status == 200:
                    content = await response.read()
                    return json.loads(content.decode('utf-8'))
                else:
                    raise Exception(response)

        except Exception as e:
            traceback.print_exc()
            if retry_count > 0:
                wait = retry_delay * (2 ** (3 - retry_count))  # 指数的バックオフ
                print(f"リトライ待機時間: {wait}秒")
                await asyncio.sleep(wait)
                return await self.fetch(req, retry_count - 1)
            else:
                raise e

    async def send(self):
        promises = [self.fetch(req) for req in self.requests]
        self.requests.clear()
        return await asyncio.gather(*promises)

    # Long-Short Ratio
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # period	        true	    string	    Data recording period. 5min, 15min, 30min, 1h, 4h, 1d
    # limit	            false	    int	        Limit for data size per page, max size is 500. Default as showing 50 pieces of data per page
    # ================================================================
    def account_ratio(self, period, limit=''):
        target_path = ''.join(['/v2/public/account-ratio?symbol=', self.SYMBOL, '&period=', period])
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])
        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params, base_url='https://api.bybit.com')

    # ------------------------------------------------ #
    # REST API(Market Data Endpoints)
    # ------------------------------------------------ #
    # Orderbook
    # 確認済
    def orderbook(self):
        target_path = ''.join(['/v2/public/orderBook/L2/?symbol=', self.SYMBOL])
        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Query Kline
    # 確認済
    def kline(self, interval, from_timestamp, limit=''):
        # target_path = ''.join(['/v2/public/kline/list?symbol=', self.SYMBOL, '&interval=', str(interval), '&from=', str(from_timestamp)])
        target_path = ''.join(['v5/market/kline?category=linear&symbol=', self.SYMBOL, '&interval=', str(interval), ])
        if len(str(from_timestamp)) > 0:
            target_path = ''.join([target_path, '&start=', str(from_timestamp) + "000"])
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])
        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Latest Information for Symbol

    # Public Trading Records
    # 確認済
    def trading_records(self, category='linear', limit='1000'):
        target_path = ''.join(['/v5/market/recent-trade?symbol=', self.SYMBOL, '&category=', str(category)])
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])

        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Query Symbol
    # 確認済
    def symbols(self):
        target_path = '/v2/public/symbols'
        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Liquidated Orders
    # 確認済
    def liq_records(self, from_id='', limit='', start_time='', end_time=''):
        target_path = ''.join(['/v2/public/liq-records?symbol=', self.SYMBOL])

        if len(str(from_id)) > 0:
            target_path = ''.join([target_path, '&from=', str(from_id)])
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])
        if len(str(start_time)) > 0:
            target_path = ''.join([target_path, '&start_time=', str(start_time)])
        if len(str(end_time)) > 0:
            target_path = ''.join([target_path, '&end_time=', str(end_time)])

        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Get the Last Funding Rate
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # symbol	        true	    string	    Symbol
    # ================================================================
    def prev_funding_rate(self):
        target_path = ''.join(['/public/linear/funding/prev-funding-rate?', 'symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL
        }

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Query Mark Price Kline
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # interval	        true	    string  	Data refresh interval. Enum : 1 3 5 15 30 60 120 240 360 720 "D" "M" "W"
    # from_timestamp	true	    integer	    From timestamp in seconds
    # limit	            false	    integer	    Limit for data size, max size is 200. Default as showing 200 pieces of data
    # ================================================================
    def mark_price_kline(self, interval, from_timestamp, limit=''):
        target_path = ''.join(
            ['/public/linear/mark-price-kline?symbol=', self.SYMBOL, '&interval=', str(interval), '&from=',
             str(from_timestamp)])

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])

        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Query index price kline
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # interval	        true	    string  	Data refresh interval. Enum : 1 3 5 15 30 60 120 240 360 720 "D" "M" "W"
    # from_timestamp	true	    integer	    From timestamp in seconds
    # limit	            false	    integer	    Limit for data size, max size is 200. Default as showing 200 pieces of data
    # ================================================================
    def index_price_kline(self, interval, from_timestamp, limit=''):
        target_path = ''.join(
            ['/public/linear/index-price-kline?symbol=', self.SYMBOL, '&interval=', str(interval), '&from=',
             str(from_timestamp)])

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])

        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Query premium index kline
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # interval	        true	    string  	Data refresh interval. Enum : 1 3 5 15 30 60 120 240 360 720 "D" "M" "W"
    # from_timestamp	true	    integer	    From timestamp in seconds
    # limit	            false	    integer	    Limit for data size, max size is 200. Default as showing 200 pieces of data
    # ================================================================
    def premium_index_kline(self, interval, from_timestamp, limit=''):
        target_path = ''.join(
            ['/public/linear/premium-index-kline?symbol=', self.SYMBOL, '&interval=', str(interval), '&from=',
             str(from_timestamp)])

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])

        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Open Interest
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # period	        true	    string	    Data recording period. 5min, 15min, 30min, 1h, 4h, 1d
    # limit 	        false	    int	        Limit for data size per page, max size is 200. Default as showing 50 pieces of data per page
    # ================================================================
    def open_interest(self, period, limit=''):
        target_path = ''.join(['/v2/public/open-interest?symbol=', self.SYMBOL, '&period=', str(period)])

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])

        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Latest Big Deal
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # limit	            false	    int         Limit for data size per page, max size is 1000. Default as showing 500 pieces of data per page
    # ================================================================
    def big_deal(self, limit=''):
        target_path = ''.join(['/v2/public/big-deal?symbol=', self.SYMBOL])

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])

        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

    # Long-Short Ratio
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # period	        true	    string	    Data recording period. 5min, 15min, 30min, 1h, 4h, 1d
    # limit	            false	    int	        Limit for data size per page, max size is 500. Default as showing 50 pieces of data per page
    # ================================================================
    def account_ratio(self, period, limit=''):
        target_path = ''.join(['/v2/public/account-ratio?symbol=', self.SYMBOL, '&period=', period])
        test_flg = False
        if self.URLS['REST'] == 'https://api-testnet.bybit.com':
            self.URLS['REST'] = 'https://api.bybit.com'
            test_flg = True
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(limit)])

        params = {}
        self.set_request(method='GET', access_modifiers='public',
                         target_path=target_path, params=params)

        if test_flg:
            self.URLS['REST'] = 'https://api-testnet.bybit.com'

    # ------------------------------------------------ #
    # REST API(Account Data Endpoints)
    # ------------------------------------------------ #
    def order_hist(self, order_id='', order_link_id='', limit='', order_status=''):
        target_path = ''.join(['v5/order/history?category=linear', '&symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL,
        }

        if len(str(order_id)) > 0:
            target_path = ''.join([target_path, '&order_id=', order_id])
            params['orderId'] = order_id
        if len(str(order_link_id)) > 0:
            target_path = ''.join([target_path, '&order_link_id=', order_link_id])
            params['orderLinkId'] = order_link_id
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', limit])
            params['limit'] = limit
        if len(str(order_status)) > 0:
            target_path = ''.join([target_path, '&order_status=', order_status])
            params['orderStatus'] = order_status

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params={})

    # Place Active Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # side	            true	    string	    Side
    # symbol	        true	    string	    Symbol
    # order_type	    true	    string	    Active order type
    # qty	            true	    number	    Order quantity in BTC
    # price	            false	    number	    Order price. Required if you make limit price order
    # time_in_force	    true	    string	    Time in force
    # close_on_trigger	true	    bool	    What is a close on trigger order? For a closing order. It can only reduce your position, not increase it. If the account has insufficient available balance when the closing order is triggered, then other active orders of similar contracts will be cancelled or reduced. It can be used to ensure your stop loss reduces your position regardless of current available margin.
    # order_link_id	    false	    string	    Customised order ID, maximum length at 36 characters, and order ID under the same agency has to be unique.
    # take_profit	    false	    number	    Take profit price, only take effect upon opening the position
    # stop_loss	        false	    number	    Stop loss price, only take effect upon opening the position
    # tp_trigger_by	    false	    string	    Take profit trigger price type, default: LastPrice
    # sl_trigger_by	    false	    string	    Stop loss trigger price type, default: LastPrice
    # reduce_only	    true	    bool	    What is a reduce-only order? True means your position can only reduce in size if this order is triggered. When reduce_only is true, take profit/stop loss cannot be set
    # ================================================================
    def order_create(self, side, order_type, qty, price='', time_in_force='', close_on_trigger=False, order_link_id='',
                     take_profit='', stop_loss='', tp_trigger_by='', sl_trigger_by='', positionIdx=0,
                     reduce_only=False):
        target_path = 'v5/order/create'
        params = {
            'category': 'linear',
            'side': side,
            'symbol': self.SYMBOL,
            'orderType': order_type,
            'qty': str(qty),
            'timeInForce': time_in_force,
            'positionIdx': positionIdx,
        }

        if len(str(price)) > 0:
            params['price'] = str(float(price))
        if len(str(close_on_trigger)) > 0:
            params['closeOnTrigger'] = close_on_trigger
        if len(str(order_link_id)) > 0:
            params['orderLinkId'] = order_link_id
        if len(str(take_profit)) > 0:
            params['takeProfit'] = take_profit
        if len(str(stop_loss)) > 0:
            params['stopLoss'] = stop_loss
        if len(str(tp_trigger_by)) > 0:
            params['tpTriggerBy'] = tp_trigger_by
        if len(str(sl_trigger_by)) > 0:
            params['slTriggerBy'] = sl_trigger_by
        if len(str(reduce_only)) > 0:
            params['reduceOnly'] = reduce_only

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)
        print(self.requests)

    # Get Active Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # order_id	        false	    string	    Order ID
    # order_link_id	    false	    string	    Customised order ID, maximum length at 36 characters, and order ID under the same agency has to be unique.
    # order	            false	    string	    Sort orders by creation date. Defaults to desc
    # page	            false	    integer	    Page. By default, gets first page of data. Maximum of 50 pages
    # limit	            false	    integer	    Limit for data size per page, max size is 50. Default as showing 20 pieces of data per page
    # order_status	    false	    string	    Query your orders for all statuses if 'order_status' not provided. If you want to query orders with specific statuses, you can pass the order_status split by ','.
    # ================================================================
    def order_list(self, order_id='', order_link_id='', order='', page='', limit=''):
        target_path = ''.join(['v5/order/realtime?category=linear', '&symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL,
        }

        if len(str(order_id)) > 0:
            target_path = ''.join([target_path, '&order_id=', order_id])
            params['orderId'] = order_id
        if len(str(order_link_id)) > 0:
            target_path = ''.join([target_path, '&order_link_id=', order_link_id])
            params['orderLinkId'] = order_link_id
        if len(str(order)) > 0:
            target_path = ''.join([target_path, '&order=', order])
            params['order'] = order
        if len(str(page)) > 0:
            target_path = ''.join([target_path, '&page=', page])
            params['page'] = page
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', limit])
            params['limit'] = limit

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params={})

    # Cancel Active Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # order_id	        false	    string	    Order ID. Required if not passing order_link_id
    # order_link_id	    false	    string	    Agency customized order ID. Required if not passing order_id
    # ================================================================
    def order_cancel(self, order_id='', order_link_id=''):
        target_path = 'v5/order/cancel'

        params = {
            'symbol': self.SYMBOL,
            'category': 'linear',
        }

        if len(str(order_id)) > 0:
            params['orderId'] = order_id
        if len(str(order_link_id)) > 0:
            params['orderLinkId'] = order_link_id

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    # Cancel All Active Orders
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # symbol	        true	    string	    Symbol
    def order_cancelall(self):
        target_path = 'v5/order/cancel-all'

        params = {
            'symbol': self.SYMBOL,
            'category': 'linear',
        }

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    # Replace Active Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # order_id	        false	    string	    Order ID. Required if not passing order_link_id
    # order_link_id	    false	    string	    Agency customized order ID. Required if not passing order_id
    # p_r_qty	        false	    integer	    New order quantity. Do not pass this field if you don't want modify it
    # p_r_price	        false	    number	    New order price. Do not pass this field if you don't want modify it
    # take_profit	    false	    number	    New take_profit price, also known as stop_px. Do not pass this field if you don't want modify it
    # stop_loss	        false	    number	    New stop_loss price, also known as stop_px. Do not pass this field if you don't want modify it
    # tp_trigger_by	    false	    string	    Take profit trigger price type, default: LastPrice
    # sl_trigger_by	    false	    string	    Stop loss trigger price type, default: LastPrice
    # ================================================================
    def order_replace(self, order_id='', order_link_id='', p_r_qty='', p_r_price='', take_profit='', stop_loss='',
                      tp_trigger_by='', sl_trigger_by=''):
        target_path = '/private/linear/order/replace'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(order_id)) > 0:
            params['order_id'] = order_id

        if len(str(order_link_id)) > 0:
            params['order_link_id'] = order_link_id

        if len(str(p_r_qty)) > 0:
            params['p_r_qty'] = p_r_qty

        if len(str(p_r_price)) > 0:
            params['p_r_price'] = p_r_price

        if len(str(take_profit)) > 0:
            params['take_profit'] = take_profit

        if len(str(stop_loss)) > 0:
            params['stop_loss'] = stop_loss

        if len(str(tp_trigger_by)) > 0:
            params['tp_trigger_by'] = tp_trigger_by

        if len(str(sl_trigger_by)) > 0:
            params['sl_trigger_by'] = sl_trigger_by

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    '''
    # Query Active Order (real-time)
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # order_id	        false	    string	    Order ID. Required if not passing order_link_id
    # order_link_id	    false	    string	    Agency customized order ID. Required if not passing order_id
    # symbol	        true	    string	    Symbol
    # ================================================================
    def order(self, order_id='', order_link_id=''):
        target_path = ''.join(['/private/linear/order/search?', 'api_key=', self.api_key, 'symbol=', self.SYMBOL])

        params = {
                    'symbol': self.SYMBOL
        }

        if len(str(order_id)) > 0:
            target_path = ''.join([target_path, '&order_id=', order_id])
            params['order_id'] = order_id
        if len(str(order_link_id)) > 0:
            target_path = ''.join([target_path, '&order_link_id=', order_link_id])
            params['order_link_id'] = order_link_id

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)
    '''

    # Place Conditional Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # side	            true	    string	    Side
    # order_type	    true	    string	    Conditional order type
    # qty	            true	    number	    Order quantity in BTC
    # price	            false	    number	    Execution price for conditional order. Required if you make limit price order
    # base_price	    true	    number	    It will be used to compare with the value of stop_px, to decide whether your conditional order will be triggered by crossing trigger price from upper side or lower side. Mainly used to identify the expected direction of the current conditional order.
    # stop_px	        true	    number	    Trigger price
    # time_in_force	    true	    string	    Time in force
    # trigger_by	    false	    string	    Trigger price type. Default LastPrice
    # close_on_trigger	true	    bool	    What is a close on trigger order? For a closing order. It can only reduce your position, not increase it. If the account has insufficient available balance when the closing order is triggered, then other active orders of similar contracts will be cancelled or reduced. It can be used to ensure your stop loss reduces your position regardless of current available margin.
    # reduce_only	    true	    bool	    What is a reduce-only order? True means your position can only reduce in size if this order is triggered. When reduce_only is true, take profit/stop loss cannot be set
    # order_link_id	    false	    string	    Customised order ID, maximum length at 36 characters, and order ID under the same agency has to be unique.
    # take_profit	    false	    number	    Take profit price, only take effect upon opening the position
    # stop_loss	        false	    number	    Stop loss price, only take effect upon opening the position
    # tp_trigger_by	    false	    string	    Take profit trigger price type, default: LastPrice
    # sl_trigger_by	    false	    string	    Stop loss trigger price type, default: LastPrice
    # ================================================================
    def stop_order_create(self, side='', order_type='', qty='', price='', base_price='', stop_px='', time_in_force='',
                          trigger_by='', reduce_only=False, close_on_trigger='', order_link_id='', take_profit='',
                          stop_loss='', tp_trigger_by='', sl_trigger_by=''):
        target_path = '/private/linear/stop-order/create'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(side)) > 0:
            params['side'] = side

        if len(str(order_type)) > 0:
            params['order_type'] = order_type

        if len(str(qty)) > 0:
            params['qty'] = qty

        if len(str(price)) > 0:
            params['price'] = price

        if len(str(base_price)) > 0:
            params['base_price'] = base_price

        if len(str(stop_px)) > 0:
            params['stop_px'] = stop_px

        if len(str(time_in_force)) > 0:
            params['time_in_force'] = time_in_force

        if len(str(trigger_by)) > 0:
            params['trigger_by'] = trigger_by

        if len(str(close_on_trigger)) > 0:
            params['close_on_trigger'] = close_on_trigger

        if len(str(reduce_only)) > 0:
            params['reduce_only'] = reduce_only

        if len(str(order_link_id)) > 0:
            params['order_link_id'] = order_link_id

        if len(str(take_profit)) > 0:
            params['take_profit'] = take_profit

        if len(str(stop_loss)) > 0:
            params['stop_loss'] = stop_loss

        if len(str(tp_trigger_by)) > 0:
            params['tp_trigger_by'] = tp_trigger_by

        if len(str(sl_trigger_by)) > 0:
            params['sl_trigger_by'] = sl_trigger_by

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    # Get Conditional Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # stop_order_id	    false	    string	    Your conditional order ID. The unique order ID returned to you when the corresponding active order was created
    # order_link_id	    false	    string	    Customised order ID, maximum length at 36 characters, and order ID under the same agency has to be unique.
    # stop_order_status	false	    string	    Stop order status
    # order	            false	    string	    Sort orders by creation date. Defaults to desc
    # page	            false	    integer	    Page. By default, gets first page of data
    # limit	            false	    integer	    Limit for data size per page, max size is 50. Default as showing 20 pieces of data per page
    # ================================================================
    def stop_order_list(self, stop_order_id='', order_link_id='', stop_order_status='', order='', page='', limit=''):
        target_path = '/private/linear/stop-order/list'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(stop_order_id)) > 0:
            params['stop_order_id'] = stop_order_id

        if len(str(order_link_id)) > 0:
            params['order_link_id'] = order_link_id

        if len(str(stop_order_status)) > 0:
            params['stop_order_status'] = stop_order_status

        if len(str(order)) > 0:
            params['order'] = order

        if len(str(page)) > 0:
            params['page'] = page

        if len(str(limit)) > 0:
            params['limit'] = limit

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Cancel Conditional Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # stop_order_id	    false	    string	    Order ID. Required if not passing order_link_id
    # order_link_id	    false	    string	    Agency customized order ID. Required if not passing stop_order_id
    # ================================================================
    def stop_order_cancel(self, stop_order_id='', order_link_id=''):
        target_path = '/private/linear/stop-order/cancel'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(stop_order_id)) > 0:
            params['stop_order_id'] = stop_order_id

        if len(str(order_link_id)) > 0:
            params['order_link_id'] = order_link_id

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    # Cancel All Conditional Orders
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # ================================================================
    def stop_order_cancelall(self, stop_order_id='', order_link_id=''):
        target_path = '/private/linear/stop-order/cancel-all'

        params = {
            'symbol': self.SYMBOL
        }

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    # Replace Conditional Order
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # stop_order_id	    false	    string	Order ID. Required if not passing order_link_id
    # order_link_id	    false	    string	Agency customized order ID. Required if not passing stop_order_id
    # p_r_qty	        false	    integer	New order quantity. Do not pass this field if you don't want modify it
    # p_r_price	        false	    number	New order price. Do not pass this field if you don't want modify it
    # p_r_trigger_price	false	    number	New conditional order's trigger price or TP/SL order price, also known as stop_px. Do not pass this field if you don't want modify it
    # take_profit	    false	    number	New take_profit price, also known as stop_px. Do not pass this field if you don't want modify it
    # stop_loss	        false	    number	New stop_loss price, also known as stop_px. Do not pass this field if you don't want modify it
    # tp_trigger_by	    false	    string	Take profit trigger price type, default: LastPrice
    # sl_trigger_by	    false	    string	Stop loss trigger price type, default: LastPrice
    # ================================================================
    def stop_order_replace(self, stop_order_id='', order_link_id='', p_r_qty='', p_r_price='', p_r_trigger_price='',
                           take_profit='', stop_loss='', tp_trigger_by='', sl_trigger_by=''):
        target_path = '/private/linear/stop-order/replace'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(stop_order_id)) > 0:
            params['stop_order_id'] = stop_order_id

        if len(str(order_link_id)) > 0:
            params['order_link_id'] = order_link_id

        if len(str(p_r_qty)) > 0:
            params['p_r_qty'] = p_r_qty

        if len(str(p_r_price)) > 0:
            params['p_r_price'] = p_r_price

        if len(str(p_r_trigger_price)) > 0:
            params['p_r_trigger_price'] = p_r_trigger_price

        if len(str(take_profit)) > 0:
            params['take_profit'] = take_profit

        if len(str(stop_loss)) > 0:
            params['stop_loss'] = stop_loss

        if len(str(tp_trigger_by)) > 0:
            params['tp_trigger_by'] = tp_trigger_by

        if len(str(sl_trigger_by)) > 0:
            params['sl_trigger_by'] = sl_trigger_by

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    '''
    # Query Conditional Order (real-time)　未実装
    #
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # symbol	        true	    string	    Symbol
    # stop_order_id	    false	    string	    Order ID. Required if not passing order_link_id
    # order_link_id	    false	    string	    Agency customized order ID. Required if not passing order_id
    # ================================================================
    def stop_order(self, stop_order_id='', order_link_id=''):
        target_path = ''.join(['/v2/private/stop-order?', 'symbol=', self.SYMBOL])

        params = {
                    'symbol': self.SYMBOL
        }

        if len(str(stop_order_id)) > 0:
            target_path = ''.join([target_path, '&stop_order_id=', stop_order_id])
            params['stop_order_id'] = stop_order_id
        if len(str(order_link_id)) > 0:
            target_path = ''.join([target_path, '&order_link_id=', order_link_id])
            params['order_link_id'] = order_link_id

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)
    '''

    # My Position
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # ================================================================
    def position_list(self):
        target_path = ''.join(['v5/position/list?category=linear', '&symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL
        }

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Set Auto Add Margin
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # side	            true	    string	    Side
    # auto_add_margin	true	    bool	    Auto add margin button
    # ================================================================
    def set_auto_add_margin(self, side='', auto_add_margin=''):
        target_path = '/private/linear/position/set-auto-add-margin'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(side)) > 0:
            params['side'] = side

        if len(str(auto_add_margin)) > 0:
            params['auto_add_margin'] = auto_add_margin

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    # Cross/Isolated Margin Switch
    # 未実装
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # is_isolated	    true	    bool	    Cross/Isolated: true is Isolated; false is Cross
    # buy_leverage	    true	    number	    Must be greater than 0 and less than the risk limit leverage.
    # sell_leverage	    true	    number	    Must be greater than 0 and less than the risk limit leverage.
    # ================================================================

    # Full/Partial Position TP/SL Switch
    # 未実装
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # tp_sl_mode	    true	    string	    Stop loss and take profit mode
    # ================================================================

    # Add/Reduce Margin
    # 未実装
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # side	            true	    string	    Side
    # margin	        true	    number	    Add/Remove how much margin: Increase 10; decrease -10, supports 4 decimal places
    # ================================================================

    # Set Leverage
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # buy_leverage	    true	    number	    Must be greater than 0 and less than the risk limit leverage.
    # sell_leverage	    true	    number	    Must be greater than 0 and less than the risk limit leverage.
    # ================================================================
    def trading_stop(self, buy_leverage='', sell_leverage=''):
        target_path = '/private/linear/position/set-leverage'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(buy_leverage)) > 0:
            params['buy_leverage'] = buy_leverage

        if len(str(sell_leverage)) > 0:
            params['sell_leverage'] = sell_leverage

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

        # Set Trading-Stop

    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # side	            true	    string	    Position side
    # take_profit	    false	    number	    Cannot be less than 0, 0 means cancel TP
    # stop_loss	        false	    number	    Cannot be less than 0, 0 means cancel SL
    # trailing_stop	    false	    number	    Cannot be less than 0, 0 means cancel TS
    # tp_trigger_by	    false	    string	    Take profit trigger price type, default: LastPrice
    # sl_trigger_by	    false	    string	    Stop loss trigger price type, default: LastPrice
    # sl_size	        false	    number	    Stop loss quantity (when in partial mode)
    # tp_size	        false	    number	    Take profit quantity (when in partial mode)
    # ================================================================
    def trading_stop(self, side='', take_profit='', stop_loss='', trailing_stop='', tp_trigger_by='', sl_trigger_by='',
                     sl_size='', tp_size=''):
        target_path = '/private/linear/position/trading-stop'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(take_profit)) > 0:
            params['take_profit'] = take_profit
        if len(str(stop_loss)) > 0:
            params['stop_loss'] = stop_loss
        if len(str(trailing_stop)) > 0:
            params['trailing_stop'] = trailing_stop
        if len(str(tp_trigger_by)) > 0:
            params['tp_trigger_by'] = tp_trigger_by
        if len(str(sl_trigger_by)) > 0:
            params['sl_trigger_by'] = sl_trigger_by
        if len(str(sl_size)) > 0:
            params['sl_size'] = sl_size
        if len(str(tp_size)) > 0:
            params['tp_size'] = tp_size

        self.set_request(method='POST', access_modifiers='private',
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
    def execution_list(self, start_time='', end_time='', exec_type='', page='', limit=''):
        target_path = ''.join(['/private/linear/trade/execution/list?', 'symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(start_time)) > 0:
            target_path = ''.join([target_path, '&start_time=', start_time])
            params['start_time'] = start_time

        if len(str(end_time)) > 0:
            target_path = ''.join([target_path, '&end_time=', end_time])
            params['end_time'] = end_time

        if len(str(exec_type)) > 0:
            target_path = ''.join([target_path, '&exec_type=', exec_type])
            params['exec_type'] = exec_type

        if len(str(page)) > 0:
            target_path = ''.join([target_path, '&page=', page])
            params['page'] = page

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', limit])
            params['limit'] = limit

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Closed Profit and Loss
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # start_time	    false	    int	        Start timestamp point for result, in seconds
    # end_time	        false	    int	        End timestamp point for result, in seconds
    # exec_type	        false	    string	    Execution type (cannot be Funding)
    # page	            false	    integer	    Page. By default, gets first page of data. Maximum of 50 pages
    # limit	            false	    integer	    Limit for data size per page, max size is 50. Default as showing 20 pieces of data per page.
    # ================================================================
    def execution_list(self, start_time='', end_time='', exec_type='', page='', limit=''):
        target_path = ''.join(['/private/linear/trade/closed-pnl/list?', 'symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(start_time)) > 0:
            target_path = ''.join([target_path, '&start_time=', start_time])
            params['start_time'] = start_time

        if len(str(end_time)) > 0:
            target_path = ''.join([target_path, '&end_time=', end_time])
            params['end_time'] = end_time

        if len(str(exec_type)) > 0:
            target_path = ''.join([target_path, '&exec_type=', exec_type])
            params['exec_type'] = exec_type

        if len(str(page)) > 0:
            target_path = ''.join([target_path, '&page=', page])
            params['page'] = page

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', limit])
            params['limit'] = limit

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Get Risk Limit
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # ================================================================
    def risk_limit(self):
        target_path = '/public/linear/risk-limit?'

        params = {
            'symbol': self.SYMBOL
        }

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Set Risk Limit
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # side	            true	    string	    Side
    # risk_id	        true	    integer	    Risk ID
    # ================================================================
    def set_risk(self, side='', risk_id=''):
        target_path = '/private/linear/position/set-risk'

        params = {
            'symbol': self.SYMBOL
        }

        if len(str(side)) > 0:
            params['side'] = side

        if len(str(risk_id)) > 0:
            params['risk_id'] = risk_id

        self.set_request(method='POST', access_modifiers='private',
                         target_path=target_path, params=params)

    # Predicted Funding Rate and My Funding Fee
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # ================================================================
    def predicted_funding(self):
        target_path = ''.join(['/v2/private/funding/prev-funding?', 'symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL
        }

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # My Last Funding Fee
    # 未確認
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # ================================================================
    def prev_funding(self):
        target_path = ''.join(['/private/linear/funding/prev-funding?', 'symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL
        }

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # API Key Info
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # ================================================================
    def api_key_info(self):
        target_path = '/v2/private/account/api-key?'

        params = {}

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # LCP Info
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # symbol	        true	    string	    Symbol
    # ================================================================
    def lcp_info(self):
        target_path = ''.join(['/v2/private/account/lcp?', 'symbol=', self.SYMBOL])

        params = {
            'symbol': self.SYMBOL
        }

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # ------------------------------------------------ #
    # REST API(Wallet Data Endpoints)
    # ------------------------------------------------ #

    # Get Wallet Balance
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # coin	            false	    string	    currency alias. Returns all wallet balances if not passed
    # ================================================================
    def wallet_balance(self, coin=''):
        target_path = 'v5/account/wallet-balance?accountType=UNIFIED'

        params = {}

        if len(str(coin)) > 0:
            target_path = ''.join([target_path, '&coin=', coin])
            params['coin'] = coin

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Wallet Fund Records
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # start_date	    false	    string	    Start point for result
    # end_date	        false	    string	    End point for result
    # currency	        false	    string	    Currency type
    # coin	            false	    string	    currency alias
    # wallet_fund_type	false	    string	    Wallet fund type
    # page	            false	    integer	    Page. By default, gets first page of data
    # limit	            false	    integer	    Limit for data size per page, max size is 50. Default as showing 20 pieces of data per page
    # ================================================================
    def wallet_fund_records(self, start_date='', end_date='', currency='', coin='', wallet_fund_type='', page='',
                            limit=''):
        target_path = '/v2/private/wallet/fund/records?'

        params = {}

        if len(str(start_date)) > 0:
            target_path = ''.join([target_path, 'start_date=', start_date])
            params['start_date'] = start_date
        if len(str(end_date)) > 0:
            target_path = ''.join([target_path, 'end_date=', end_date])
            params['end_date'] = end_date
        if len(str(currency)) > 0:
            target_path = ''.join([target_path, 'currency=', currency])
            params['currency'] = currency
        if len(str(coin)) > 0:
            target_path = ''.join([target_path, 'coin=', coin])
            params['coin'] = coin
        if len(str(wallet_fund_type)) > 0:
            target_path = ''.join([target_path, 'wallet_fund_type=', wallet_fund_type])
            params['wallet_fund_type'] = wallet_fund_type
        if len(str(page)) > 0:
            target_path = ''.join([target_path, 'page=', page])
            params['page'] = page
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, 'limit=', limit])
            params['limit'] = limit

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Withdraw Records
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # start_date	    false	    string	    Start point for result
    # end_date	        false	    string	    End point for result
    # coin	            false	    string	    Currency type
    # status	        false	    string	    Withdraw Status Enum
    # page	            false	    integer	    Page. By default, gets first page of data
    # limit	            false	    integer	    Limit for data size per page, max size is 50. Default as showing 20 pieces of data per page
    # ================================================================
    def wallet_withdraw_list(self, start_date='', end_date='', coin='', status='', page='', limit=''):
        target_path = '/v2/private/wallet/withdraw/list?'

        params = {}

        if len(str(start_date)) > 0:
            target_path = ''.join([target_path, 'start_date=', start_date])
            params['start_date'] = start_date
        if len(str(end_date)) > 0:
            target_path = ''.join([target_path, 'end_date=', end_date])
            params['end_date'] = end_date
        if len(str(coin)) > 0:
            target_path = ''.join([target_path, 'coin=', coin])
            params['coin'] = coin
        if len(str(status)) > 0:
            target_path = ''.join([target_path, 'status=', status])
            params['status'] = status
        if len(str(page)) > 0:
            target_path = ''.join([target_path, 'page=', page])
            params['page'] = page
        if len(str(limit)) > 0:
            target_path = ''.join([target_path, 'limit=', limit])
            params['limit'] = limit

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    # Asset Exchange Records
    # 確認済
    # ================================================================
    # Request Parameters
    # parameter	        required	type	    comments
    # ================================================================
    # limit	            false	    integer 	Limit for data size per page, max size is 50. Default as showing 20 pieces of data per page
    # from	            false	    integer	    Start ID. By default, returns the latest IDs
    # direction	        false	    string	    Search direction. Prev: searches in ascending order from start ID, Next: searches in descending order from start ID. Defaults to Next
    # ================================================================
    def wallet_exchange_order_list(self, limit='', from_id='', direction=''):
        target_path = '/v2/private/exchange-order/list?'

        params = {}

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, 'limit=', limit])
            params['limit'] = limit
        if len(str(from_id)) > 0:
            target_path = ''.join([target_path, 'from_id=', from_id])
            params['from_id'] = from_id
        if len(str(direction)) > 0:
            target_path = ''.join([target_path, 'direction=', direction])
            params['direction'] = direction

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params=params)

    def instruments_info(self, category='linear', symbol='', baseCoin='', limit='', cursor=''):
        target_path = 'v5/market/instruments-info?'

        target_path = ''.join([target_path, 'category=', category])

        if len(str(limit)) > 0:
            target_path = ''.join([target_path, '&limit=', str(int(limit))])
        if len(str(symbol)) > 0:
            target_path = ''.join([target_path, '&symbol=', symbol])
        if len(str(baseCoin)) > 0:
            target_path = ''.join([target_path, '&baseCoin=', baseCoin])
        if len(str(cursor)) > 0:
            target_path = ''.join([target_path, '&cursor=', cursor])

        self.set_request(method='GET', access_modifiers='private',
                         target_path=target_path, params={})

    # ------------------------------------------------ #
    # WebSocket
    # ------------------------------------------------ #

    async def ws_run(self):
        try:
            async with pybotters.Client(apis=self.KEYS, base_url=self.URLS["REST"]) as client:
                await self.store.initialize(
                    client.get("v5/position/list", params={'symbol': self.SYMBOL, 'category': 'linear'}),
                    client.get("v5/order/realtime", params={'symbol': self.SYMBOL, 'category': 'linear'}),
                    client.get("v5/account/wallet-balance", params={'accountType': 'UNIFIED'}),
                )
                public = await client.ws_connect(
                    self.URLS['WebSocket_Public'],
                    send_json={
                        'op': 'subscribe',
                        'args': self.PUBLIC_CHANNELS,
                    },
                    hdlr_json=self.store.onmessage,
                )
                # Ctrl+C to break

                private = await client.ws_connect(
                    self.URLS['WebSocket_Private'],
                    send_json={
                        'op': 'subscribe',
                        'args': self.PRIVATE_CHANNELS,
                    },
                    hdlr_json=self.store.onmessage,
                )

                def stores(store):
                    xx = []
                    for x in self.PUBLIC_CHANNELS:
                        if x.startswith('kline.'):
                            xx.append(len(store.kline))
                        if x.startswith('orderbook.'):
                            xx.append(len(store.orderbook))
                    for x in self.PRIVATE_CHANNELS:
                        if x.startswith('position.'):
                            xx.append(len(store.position))
                        if x.startswith('order.'):
                            xx.append(len(store.order))
                    print(all(xx))
                    return xx

                # while not all(stores(self.store)):
                #    print("test")
                #    await self.store.wait()
                #    print(self.store.orderbook.find())
                for topic in self.PUBLIC_CHANNELS:
                    dsname, *_ = topic.split(".")
                    if dsname == "kline":
                        asyncio.create_task(self.realtime_klines(self.store[dsname].watch()))
                while True:
                    await self.store.wait()
                    # print(self.store.orderbook.find({'symbol': self.SYMBOL}))
                    # print(self.store.kline.find({'symbol': self.SYMBOL}))
                    # print(self.store.position.find({'symbol': self.SYMBOL}))

        except Exception as e:
            print(traceback.format_exc().strip())

    async def realtime_klines(self, ctx: pybotters.store.StoreStream):
        with ctx as klines:
            async for msg in klines:
                data = msg.data
                data_d = {"exec_date": int(str(data["start"])[:-3]),
                          "timestamp": int(str(data["start"])[:-3]),
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
                        # print(self.df_ohlcv)
                    else:
                        self.df_ohlcv = pd.concat([self.df_ohlcv, data_d])

                await asyncio.sleep(1)
            if len(self.df_ohlcv) > self.MAX_OHLCV_CAPACITY:
                self.df_ohlcv = self.df_ohlcv[1:]

    async def realtime_trades(self, ctx: pybotters.store.StoreStream):
        with ctx as trades:
            async for msg in trades:
                data = msg.data
                print("trades", data)


