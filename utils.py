from datetime import timedelta
import datetime
import pandas as pd
import talib
import os
import lightgbm as lgb
import numpy as np
#pd.set_option('display.max_rows', None)

def resample(df, sec, window=None):
    if window is not None:
        df = df[-window * sec * 2:]

    template = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
        "buy_vol": "sum",
        "buy_num": "sum",
        "sell_vol": "sum",
        "sell_num": "sum",
        "timestamp": "last"
    }
    resample_dict = {}

    for column in df.columns:
        if column in template:
            resample_dict[column] = template[column]

    df = df.resample('{}S'.format(sec)).agg(resample_dict)

    if window is not None:
        df = df[-window:]
    return df

def date_range(start, stop, step = timedelta(1)):
    current = start
    while current < stop:
        yield current
        current += step

def makeCandles(df, sec):
    # 参考: https://note.com/nagi7692/n/ne674d117d1b6?magazine_key=m0b2a506bf904
    df.drop(['tickDirection', 'trdMatchID', 'grossValue', 'homeNotional', 'foreignNotional'], axis=1, inplace=True)
    # 86400本の秒足ができるように0秒に約定を入れる
    # データはindexが始まりの時間を示しており、その後sec秒間におけるohlcを示す
    # つまり演算を行う際にはその次の行に入ったときに閲覧できる
    # 一方でtimestampはその時間帯の最後のデータの時間を示す
    df = df.sort_index()
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit="s", utc=True)
    df = df.rename(columns={'timestamp': 'exec_date'})
    df = df.set_index('exec_date')

    df['buy_size'] = df['size'].where(df['side'] == 'Buy', 0)
    df['buy_flag'] = df['side'] == 'Buy'
    df['sell_size'] = df['size'].where(df['side'] == 'Sell', 0)
    df['sell_flag'] = df['side'] == 'Sell'

    df_ohlcv = df.resample('{}S'.format(sec)).agg({"price": "ohlc", "size": "sum", "buy_size": "sum", "buy_flag": "sum",
                                                   "sell_size": "sum", "sell_flag": "sum", })

    df_ohlcv.columns = ['Open', 'High', 'Low', 'Close', 'Volume', 'buy_vol', 'buy_num', 'sell_vol', 'sell_num']

    # 条件を作成
    condition = (df_ohlcv['Volume'] == 0)
    # closeの値を一つ前の時間のcloseの値で更新
    df_ohlcv.loc[condition, 'Open'] = df_ohlcv['Close'].shift(1)[condition]
    df_ohlcv.loc[condition, 'Low'] = df_ohlcv['Close'].shift(1)[condition]
    df_ohlcv.loc[condition, 'High'] = df_ohlcv['Close'].shift(1)[condition]
    df_ohlcv.loc[condition, 'Close'] = df_ohlcv['Close'].shift(1)[condition]

    condition = (df_ohlcv['Open'] < df_ohlcv['Low'])
    df_ohlcv.loc[condition, 'Low'] = df_ohlcv.loc[condition, 'Open']
    condition = (df_ohlcv['Open'] > df_ohlcv['High'])
    df_ohlcv.loc[condition, 'High'] = df_ohlcv.loc[condition, 'Open']

    df_ohlcv['buy_num'] = df_ohlcv['buy_num'].astype(int)
    df_ohlcv['sell_num'] = df_ohlcv['sell_num'].astype(int)

    # 日付部分を取得
    date_part = df_ohlcv.index[0].date()
    # 欠損している期間を検出
    missing_periods = pd.date_range(start=f'{date_part} 00:00:00+00:00', end=f'{date_part} 23:59:59+00:00', freq='S').difference(df_ohlcv.index)
    # 欠損している期間にデフォルト値を適用
    default_data = {'buy_vol': 0.0, 'buy_num': 0.0, 'sell_vol': 0.0, 'sell_num': 0.0}
    for timestamp in missing_periods:
        df_ohlcv.loc[timestamp] = default_data

    df_ohlcv.sort_index(inplace=True)
    df_ohlcv["timestamp"] = df_ohlcv.index.view('int64') // 10**9

    while True:
        nan_count = df_ohlcv.isna().sum().sum()
        df_ohlcv.ffill(inplace=True)
        if nan_count == df_ohlcv.isna().sum().sum():
            break

    # fill後の対応
    condition = (df_ohlcv.index.second == 0)
    df_ohlcv.loc[condition, 'Open'] = df_ohlcv['Close'].shift(1)[condition]

    condition = (df_ohlcv['Open'] < df_ohlcv['Low'])
    df_ohlcv.loc[condition, 'Low'] = df_ohlcv.loc[condition, 'Open']
    condition = (df_ohlcv['Open'] > df_ohlcv['High'])
    df_ohlcv.loc[condition, 'High'] = df_ohlcv.loc[condition, 'Open']

    return df_ohlcv

# 大きな値を1または-1に変換する関数
def replace_large_values(value):
    if value > 1e12:  # 値が1兆より大きい場合
        return 1
    elif value < -1e12:  # 値が-1兆より小さい場合
        return -1
    else:
        return value  # それ以外の場合は値をそのまま返す

def shift_window(df, column_name, window):
    a = df[column_name].copy()
    bs = []
    for x in range(1, window + 1):
        b = df[column_name].shift(x).copy()
        b = b.rename(f"{column_name}_{x}")
        bs.append(b)
    return pd.concat(bs, axis=1)

def shift_window_24(df, column_name, window):
    a = df[column_name].copy()
    bs = []
    for x in range(1 * 24, window * 24+ 1, 24):
        b = df[column_name].shift(x).copy()
        b = b.rename(f"{column_name}_{x}")
        b.replace({np.nan: 0, np.inf: 1, -np.inf: -1}, inplace=True)
        bs.append(b)
    return pd.concat(bs, axis=1)

def pct_change_window(df, column_name, window):
    a = df[column_name].copy()
    bs = []
    for x in range(1, window + 1):
        b = df[column_name].pct_change(x).copy()
        b = b.rename(f"{column_name}_change_{x}")
        b.replace({np.nan: 0, np.inf: 1, -np.inf: -1}, inplace=True)
        b = b.apply(replace_large_values)
        bs.append(b)
    return pd.concat(bs, axis=1)

def pct_change_window_24(df, column_name, window):
    a = df[column_name].copy()
    bs = []
    for x in range(1 * 24, window * 24+ 1, 24):
        b = df[column_name].pct_change(x).copy()
        b = b.rename(f"{column_name}_change_{x}")
        b.replace({np.nan: 0, np.inf: 1, -np.inf: -1}, inplace=True)
        b = b.apply(replace_large_values)
        bs.append(b)
    return pd.concat(bs, axis=1)

def calc_features(df, window_size=12):
    open = df['Open']
    high = df['High']
    low = df['Low']
    close = df['Close']
    volume = df['Volume']

    orig_columns = df.columns
    df["return"] = close.pct_change()
    df = pd.concat([df, shift_window(df, "return", window_size), pct_change_window(df, "Close", window_size)], axis=1)
    base_columns = df.columns
    hilo = (df['High'] + df['Low']) / 2
    df['BBANDS_upperband'], df['BBANDS_middleband'], df['BBANDS_lowerband'] = talib.BBANDS(close, timeperiod=7,
                                                                                           nbdevup=2, nbdevdn=2,
                                                                                           matype=0)
    df['BBANDS_upperband'] = (df['BBANDS_upperband'] - hilo) / df['BBANDS_upperband']
    df['BBANDS_middleband'] = (df['BBANDS_middleband'] - hilo) / df['BBANDS_middleband']
    df['BBANDS_lowerband'] = (df['BBANDS_lowerband'] - hilo) / df['BBANDS_lowerband']
    df['DEMA'] = (talib.DEMA(close, timeperiod=30) - hilo) / talib.DEMA(close, timeperiod=30)
    df['EMA16'] = (talib.EMA(close, timeperiod=16) - hilo) / talib.EMA(close, timeperiod=16)
    df['EMA30'] = (talib.EMA(close, timeperiod=30) - hilo) / talib.EMA(close, timeperiod=30)
    df['EMA50'] = (talib.EMA(close, timeperiod=50) - hilo) / talib.EMA(close, timeperiod=50)
    df['EMA100'] = (talib.EMA(close, timeperiod=100) - hilo) / talib.EMA(close, timeperiod=100)
    #df['EMA200'] = (talib.EMA(close, timeperiod=200) - hilo) / talib.EMA(close, timeperiod=200)
    df['HT_TRENDLINE'] = (talib.HT_TRENDLINE(close) - hilo) / talib.HT_TRENDLINE(close)
    df['KAMA'] = (talib.KAMA(close, timeperiod=30) - hilo) / talib.KAMA(close, timeperiod=30)
    df['MA17'] = (talib.MA(close, timeperiod=17, matype=0) - hilo) / talib.MA(close, timeperiod=17, matype=0)
    df['MA30'] = (talib.MA(close, timeperiod=30, matype=0) - hilo) / talib.MA(close, timeperiod=30, matype=0)
    df['MA50'] = (talib.MA(close, timeperiod=50, matype=0) - hilo) / talib.MA(close, timeperiod=50, matype=0)
    df['MA100'] = (talib.MA(close, timeperiod=100, matype=0) - hilo) / talib.MA(close, timeperiod=100, matype=0)
    #df['MA200'] = (talib.MA(close, timeperiod=200, matype=0) - hilo  ) / talib.MA(close, timeperiod=200, matype=0)
    df['MIDPOINT'] = (talib.MIDPOINT(close, timeperiod=14) - hilo) / talib.MIDPOINT(close, timeperiod=14)
    df['SMA5'] = (talib.SMA(close, timeperiod=5) - hilo) / talib.SMA(close, timeperiod=5)
    df['SMA17'] = (talib.SMA(close, timeperiod=17) - hilo) / talib.SMA(close, timeperiod=17)
    df['SMA25'] = (talib.SMA(close, timeperiod=25) - hilo) / talib.SMA(close, timeperiod=25)
    df['SMA50'] = (talib.SMA(close, timeperiod=50) - hilo) / talib.SMA(close, timeperiod=50)
    #df['SMA100'] = (talib.SMA(close, timeperiod=100) - hilo) / talib.SMA(close, timeperiod=100)
    #df['SMA200'] = (talib.SMA(close, timeperiod=200) - hilo) / talib.SMA(close, timeperiod=200)
    df['T3'] = (talib.T3(close, timeperiod=5, vfactor=0) - hilo) / talib.T3(close, timeperiod=5, vfactor=0)
    df['TEMA'] = (talib.TEMA(close, timeperiod=30) - hilo) / talib.TEMA(close, timeperiod=30)
    #df['TRIMA'] = (talib.TRIMA(close, timeperiod=30) - hilo) / talib.TRIMA(close, timeperiod=30)
    df['WMA5'] = (talib.WMA(close, timeperiod=5) - hilo) / talib.WMA(close, timeperiod=5)
    df['WMA17'] = (talib.WMA(close, timeperiod=17) - hilo) / talib.WMA(close, timeperiod=17)
    df['WMA25'] = (talib.WMA(close, timeperiod=25) - hilo) / talib.WMA(close, timeperiod=25)
    df['WMA50'] = (talib.WMA(close, timeperiod=50) - hilo) / talib.WMA(close, timeperiod=50)
    df['WMA100'] = (talib.WMA(close, timeperiod=100) - hilo) / talib.WMA(close, timeperiod=100)
    #df['WMA200'] = (talib.WMA(close, timeperiod=200) - hilo) / talib.WMA(close, timeperiod=200)

    df['ADX'] = talib.ADX(high, low, close, timeperiod=14) / 100
    df['ADXR'] = talib.ADXR(high, low, close, timeperiod=14) / 100
    #df['APO'] = talib.APO(close, fastperiod=12, slowperiod=26, matype=0)
    df['AROON_aroondown'], df['AROON_aroonup'] = talib.AROON(high, low, timeperiod=14)
    df['AROON_aroondown'] /= 100,
    df['AROON_aroonup'] /= 100,
    #df = pd.concat([df, shift_window(df, "AROON_aroondown", 12), shift_window(df, "AROON_aroonup", 12)], axis=1)
    df['AROONOSC'] = talib.AROONOSC(high, low, timeperiod=14) / 100
    df['BOP'] = talib.BOP(open, high, low, close)
    df['CCI'] = talib.CCI(high, low, close, timeperiod=14) / 100
    df['DX'] = talib.DX(high, low, close, timeperiod=14) / 100
    #df['MACD_macd'], df['MACD_macdsignal'], df['MACD_macdhist'] = talib.MACD(close, fastperiod=12, slowperiod=26,
    #                                                                        signalperiod=9)
    _, _, df['MACD_macdhist'] = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df['MACD_macdhist'] /= 1000
    # skip MACDEXT MACDFIX たぶん同じなので
    df['MFI'] = talib.MFI(high, low, close, volume, timeperiod=14) / 100
    df['MINUS_DI'] = talib.MINUS_DI(high, low, close, timeperiod=14) / 100
    #df['MINUS_DM'] = talib.MINUS_DM(high, low, timeperiod=14)
    df['MOM'] = talib.MOM(close, timeperiod=10)
    df['PLUS_DI'] = talib.PLUS_DI(high, low, close, timeperiod=14) / 100
    #df['PLUS_DM'] = talib.PLUS_DM(high, low, timeperiod=14)
    df['RSI'] = talib.RSI(close, timeperiod=14) / 100
    df['STOCH_slowk'], df['STOCH_slowd'] = talib.STOCH(high, low, close, fastk_period=5, slowk_period=3, slowk_matype=0,
                                                       slowd_period=3, slowd_matype=0)

    df['STOCH_slowk'] /= 100
    df['STOCH_slowd'] /= 100
    df['STOCHF_fastk'], df['STOCHF_fastd'] = talib.STOCHF(high, low, close, fastk_period=5, fastd_period=3,
                                                          fastd_matype=0)
    df['STOCHF_fastk'] /= 100
    df['STOCHF_fastd'] /= 100
    df['STOCHRSI_fastk'], df['STOCHRSI_fastd'] = talib.STOCHRSI(close, timeperiod=14, fastk_period=5, fastd_period=3,
                                                                fastd_matype=0)
    df['STOCHRSI_fastk'] /= 100
    df['STOCHRSI_fastd'] /= 100
    df['TRIX'] = talib.TRIX(close, timeperiod=30)
    df['ULTOSC'] = talib.ULTOSC(high, low, close, timeperiod1=7, timeperiod2=14, timeperiod3=28) / 100
    df['WILLR'] = talib.WILLR(high, low, close, timeperiod=14) / 100

    #df['AD'] = talib.AD(high, low, close, volume)
    df['ADOSC'] = talib.ADOSC(high, low, close, volume, fastperiod=3, slowperiod=10)
    df = pd.concat([df, pct_change_window(df, 'ADOSC', 1)], axis=1)
    df["ADOSC_change_1"].clip(-10, 10, inplace=True)
    df.rename(columns={'ADOSC_change_1': 'ADOSC_c'}, inplace=True)
    del df['ADOSC']
    #df['OBV'] = talib.OBV(close, volume)

    df['ATR'] = talib.ATR(high, low, close, timeperiod=14)
    df['ATR_R7'] = talib.ATR(high, low, close, timeperiod=7)
    df['ATR_R48'] = talib.ATR(high, low, close, timeperiod=48)
    #df['NATR'] = talib.NATR(high, low, close, timeperiod=14)
    df['TRANGE'] = talib.TRANGE(high, low, close) / ((high + low + close) / 3)

    df['HT_DCPERIOD'] = talib.HT_DCPERIOD(close)
    #df = pd.concat([df, pct_change_window(df, 'HT_DCPERIOD', 1)], axis=1)
    #df["HT_DCPERIOD_change_1"].clip(-10, 10)
    del df['HT_DCPERIOD']
    df['HT_DCPHASE'] = talib.HT_DCPHASE(close)
    #df = pd.concat([df, pct_change_window(df, 'HT_DCPHASE', 1)], axis=1)
    #df["HT_DCPHASE_change_1"].clip(-10, 10, inplace=True)
    del df['HT_DCPHASE']
    #df['HT_PHASOR_inphase'], df['HT_PHASOR_quadrature'] = talib.HT_PHASOR(close)

    df['HT_SINE_sine'], df['HT_SINE_leadsine'] = talib.HT_SINE(close)
    df['HT_TRENDMODE'] = talib.HT_TRENDMODE(close)

    df['BETA5'] = talib.BETA(high, low, timeperiod=5)
    df['BETA10'] = talib.BETA(high, low, timeperiod=10)
    df['BETA15'] = talib.BETA(high, low, timeperiod=15)
    df['BETA20'] = talib.BETA(high, low, timeperiod=20)
    #df['CORREL'] = talib.CORREL(high, low, timeperiod=30)
    df['LINEARREG'] = talib.LINEARREG(close, timeperiod=14) - close / talib.LINEARREG(close, timeperiod=14)
    df['LINEARREG_ANGLE'] = talib.LINEARREG_ANGLE(close, timeperiod=14) / 90
    df['LINEARREG_INTERCEPT'] = talib.LINEARREG_INTERCEPT(close, timeperiod=14) - close / talib.LINEARREG_INTERCEPT(close, timeperiod=14)
    #df['LINEARREG_SLOPE'] = talib.LINEARREG_SLOPE(close, timeperiod=14)
    df['STDDEV'] = talib.STDDEV(close, timeperiod=5, nbdev=1)

    df["RETURN_EWMS"] = df["return"].ewm(span = 100).std()

    #plt.figure()
    #df["return"].plot()
    #df['RETURN_EWMS'].plot()
    datas = [df.copy()]
    for x in sorted(set(df.columns) - set(base_columns)):
        datas.append(shift_window(df, x, window_size)),
        datas.append(shift_window_24(df, x, window_size)),
        datas.append(pct_change_window(df, x, window_size))
        datas.append(pct_change_window_24(df, x, window_size))
    df = pd.concat(datas, axis=1)
    df = df.loc[:, ~df.columns.duplicated()]

    #print(df.columns)
    df = df.round(5)

    return df


def model_load(path):
    bst = None
    if os.path.exists(path):
        bst = lgb.Booster(model_file=path)
    else:
        raise Exception(f"model {path} is not exists")
    return bst


def drops(df, columns=[]):
    drop = ["buy_vol", "buy_num", "sell_vol", "sell_num"]
    if len(columns) != 0:
        drop.extend(columns)
    for x in drop:
        if x in df.columns:
            df.drop(x, axis=1, inplace=True)
    return df


def fix_timestamp(df):
    df["timestamp"] = df.index.view('int64') // 10 ** 9 + 3600 - 1
    return df

def hour_rounder(dt):
    # Rounds to nearest hour by adding a timedelta hour
    return (dt.replace(second=0, microsecond=0, minute=0, hour=dt.hour)
               +timedelta(hours=1))

def quarter_rounder(dt):
    minute = dt.minute
    remainder = minute % 15
    dt += datetime.timedelta(minutes=15 - remainder)
    dt = dt.replace(second=0, microsecond=0)
    return dt

def get_next_time():
    checkout = False
    now = datetime.datetime.now()
    set_time = 15
    # 45分から59分の間の場合
    if 60 - set_time <= now.minute < 59:
        next_minute = 59
        checkout = True
    else:
        next_minute = (now.minute // set_time + 1) * set_time
    next_hour = now.hour

    # 次の5分で割り切れる時刻が1時間を超えた場合
    if next_minute >= 60:
        next_minute = 0
        next_hour += 1

        # 次の時間が24時間を超えた場合
        if next_hour >= 24:
            next_hour = 0
            now += datetime.timedelta(days=1)  # 翌日に移動

    next_time = now.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)
    interval = (next_time - now).seconds
    return next_time, interval, checkout

def round_up_hour(dt):
    if dt.minute > 0 or dt.second > 0 or dt.microsecond > 0:
        dt += datetime.timedelta(hours=1)
    return dt.replace(minute=0, second=0, microsecond=0)
