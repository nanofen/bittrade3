#!/usr/bin/env python3
"""
平均回帰分析：高い乖離後の統計的収束を分析
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import glob
from scipy import stats

def analyze_mean_reversion():
    """平均回帰の分析"""
    
    # データ読み込み
    data_files = glob.glob('data/price_data_*.csv')
    data_files.sort()
    
    all_data = []
    for file in data_files:
        df = pd.read_csv(file)
        all_data.append(df)
    
    combined_df = pd.concat(all_data, ignore_index=True)
    combined_df['datetime'] = pd.to_datetime(combined_df['datetime'])
    
    print("=== 平均回帰分析：統計的収束の検証 ===\n")
    
    # 基本統計
    arb1_mean = combined_df['arbitrage_1'].mean()
    arb2_mean = combined_df['arbitrage_2'].mean()
    arb1_std = combined_df['arbitrage_1'].std()
    arb2_std = combined_df['arbitrage_2'].std()
    
    print("基本統計情報:")
    print(f"Arbitrage_1: 平均={arb1_mean:.1f}円, 標準偏差={arb1_std:.1f}円")
    print(f"Arbitrage_2: 平均={arb2_mean:.1f}円, 標準偏差={arb2_std:.1f}円")
    print()
    
    # 正規分布の検定
    print("正規分布検定 (Shapiro-Wilk test):")
    
    # サンプルサイズが大きいので一部をサンプリング
    sample_size = min(5000, len(combined_df))
    sample_df = combined_df.sample(sample_size)
    
    stat1, p1 = stats.shapiro(sample_df['arbitrage_1'])
    stat2, p2 = stats.shapiro(sample_df['arbitrage_2'])
    
    print(f"Arbitrage_1: 統計量={stat1:.4f}, p値={p1:.6f}")
    print(f"Arbitrage_2: 統計量={stat2:.4f}, p値={p2:.6f}")
    print(f"正規分布性: {'Yes' if p1 > 0.05 else 'No'} (Arb1), {'Yes' if p2 > 0.05 else 'No'} (Arb2)")
    print()
    
    # 極値イベントの分析
    print("極値イベント分析:")
    threshold_40k = 40000
    extreme_events = combined_df[combined_df['arbitrage_1'] > threshold_40k]
    
    print(f"Arbitrage_1 > {threshold_40k}円の発生:")
    print(f"  発生回数: {len(extreme_events)}回")
    print(f"  発生確率: {len(extreme_events)/len(combined_df)*100:.2f}%")
    print(f"  平均値: {extreme_events['arbitrage_1'].mean():.1f}円")
    print()
    
    # 平均回帰分析：極値後の動向
    print("平均回帰分析:")
    print("-" * 50)
    
    if len(extreme_events) > 0:
        # 極値発生時のインデックス
        extreme_indices = extreme_events.index.tolist()
        
        reversion_analysis = []
        # 分単位で時間窓を定義
        future_windows_minutes = [1, 2, 5, 10, 20, 30, 60, 120, 240, 480, 720]
        
        for window_minutes in future_windows_minutes:
            profitable_cases = 0
            total_cases = 0
            profit_amounts = []
            
            for idx in extreme_indices:
                entry_time = combined_df.loc[idx, 'datetime']
                entry_arb1 = combined_df.loc[idx, 'arbitrage_1']
                
                # 指定時間後までのデータを取得
                future_time_limit = entry_time + pd.Timedelta(minutes=window_minutes)
                future_mask = (combined_df['datetime'] > entry_time) & (combined_df['datetime'] <= future_time_limit)
                future_data = combined_df[future_mask]
                
                if len(future_data) > 0:
                    # 未来の時点でのarbitrage_2を確認
                    future_arb2_values = future_data['arbitrage_2']
                    
                    if len(future_arb2_values) > 0:
                        # 現実的な決済閾値を設定（例：5000円以上の機会があれば決済）
                        exit_threshold = 5000
                        viable_exits = future_arb2_values[future_arb2_values >= exit_threshold]
                        
                        if len(viable_exits) > 0:
                            # 最初に閾値を超えた時点で決済（現実的なシナリオ）
                            exit_arb2 = viable_exits.iloc[0]
                        else:
                            # 閾値を超えない場合は最後の値で強制決済
                            exit_arb2 = future_arb2_values.iloc[-1]
                        
                        # 正しいアービトラージ利益計算
                        gross_profit = entry_arb1 + exit_arb2
                        
                        # 手数料を考慮した純利益
                        trading_cost = (abs(entry_arb1) + abs(exit_arb2)) * 0.001
                        net_profit = gross_profit - trading_cost
                        
                        total_cases += 1
                        profit_amounts.append(net_profit)
                        
                        if net_profit > 0:
                            profitable_cases += 1
            
            if total_cases > 0:
                success_rate = profitable_cases / total_cases * 100
                avg_profit = np.mean(profit_amounts)
                median_profit = np.median(profit_amounts)
                
                reversion_analysis.append({
                    'window_minutes': window_minutes,
                    'total_cases': total_cases,
                    'profitable_cases': profitable_cases,
                    'success_rate': success_rate,
                    'avg_profit': avg_profit,
                    'median_profit': median_profit
                })
        
        # 結果表示
        print("時間別平均回帰成功率:")
        print(f"{'時間':>8} {'ケース数':>8} {'成功数':>8} {'成功率':>8} {'平均利益':>12} {'中央値':>12}")
        print("-" * 70)
        
        for result in reversion_analysis:
            print(f"{result['window_minutes']:>6.1f}分 "
                  f"{result['total_cases']:>8d} "
                  f"{result['profitable_cases']:>8d} "
                  f"{result['success_rate']:>7.1f}% "
                  f"{result['avg_profit']:>11.0f}円 "
                  f"{result['median_profit']:>11.0f}円")
        
        print()
        
        # 統計的分析
        print("統計的考察:")
        print("-" * 30)
        
        # 理論的期待値
        theoretical_reversion = arb2_mean - arb1_mean
        print(f"理論的平均回帰利益: {theoretical_reversion:.1f}円")
        
        # 実際の結果との比較
        if reversion_analysis:
            best_result = max(reversion_analysis, key=lambda x: x['success_rate'])
            print(f"最良の成功率: {best_result['success_rate']:.1f}% ({best_result['window_minutes']:.1f}分後)")
            print(f"最良時の平均利益: {best_result['avg_profit']:.1f}円")
        
        # 分布特性
        print(f"\n分布特性:")
        print(f"Arbitrage_1の分布範囲: {combined_df['arbitrage_1'].min():.0f}円 ～ {combined_df['arbitrage_1'].max():.0f}円")
        print(f"Arbitrage_2の分布範囲: {combined_df['arbitrage_2'].min():.0f}円 ～ {combined_df['arbitrage_2'].max():.0f}円")
        
        # 相関分析（時間的な）
        print(f"\n時系列相関:")
        lag_correlation = combined_df['arbitrage_1'].corr(combined_df['arbitrage_2'].shift(1))
        print(f"Arb1とArb2(1期後)の相関: {lag_correlation:.3f}")
        
        # 平均回帰の統計的検証
        print(f"\n平均回帰の統計的証拠:")
        
        # 極値からの回復時間分析
        recovery_times = []
        for idx in extreme_indices[:100]:  # 最初の100ケースを分析
            entry_time = combined_df.loc[idx, 'datetime']
            
            # 20分以内のデータを取得
            future_time_limit = entry_time + pd.Timedelta(minutes=20)
            future_mask = (combined_df['datetime'] > entry_time) & (combined_df['datetime'] <= future_time_limit)
            future_data = combined_df[future_mask]
            
            # 利確可能レベル到達を確認
            profitable_data = future_data[future_data['arbitrage_2'] > 5000]
            if len(profitable_data) > 0:
                first_profitable_time = profitable_data['datetime'].iloc[0]
                recovery_time = (first_profitable_time - entry_time).total_seconds() / 60  # 分単位
                recovery_times.append(recovery_time)
        
        if recovery_times:
            print(f"利確レベル到達時間: 平均{np.mean(recovery_times):.1f}分, 中央値{np.median(recovery_times):.1f}分")
            print(f"最短{np.min(recovery_times):.1f}分, 最長{np.max(recovery_times):.1f}分")
        else:
            print("利確レベルへの到達例なし")
    
    else:
        print(f"Arbitrage_1 > {threshold_40k}円の事象が存在しません")

if __name__ == "__main__":
    analyze_mean_reversion()