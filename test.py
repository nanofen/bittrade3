import json
import matplotlib.pyplot as plt
from datetime import datetime

# JSONデータの読み込み（ここでは、'data.json'というファイル名とします）
with open('data/test_agent.json', 'r') as file:
    data = json.load(file)

# UNIXタイムスタンプを日時に変換し、in_diffとout_diffのデータを抽出
timestamps = [datetime.utcfromtimestamp(item['timestamp']) for item in data.values()]
in_diffs = [item['in_diff'] for item in data.values()]
out_diffs = [item['out_diff'] for item in data.values()]

# 時系列データのプロット
plt.figure(figsize=(10, 6))
plt.plot(timestamps, in_diffs, label='in_diff', color='blue')
plt.plot(timestamps, out_diffs, label='out_diff', color='red')
plt.xlabel('Time')
plt.ylabel('Value')
plt.title('Time Series of in_diff and out_diff')
plt.legend()
plt.gcf().autofmt_xdate() # 日付の表示を良くする
plt.show()

axs[1].hist(out_diffs, bins=20, color='red', alpha=0.7, label='out_diff')
axs[1].set_title('out_diff Histogram')
axs[1].set_xlabel('out_diff value')
axs[1].set_ylabel('Frequency')
axs[1].legend()

plt.show()