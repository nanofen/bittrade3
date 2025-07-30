#!/usr/bin/env python3
"""
実取引フロー考慮型アービトラージ分析
エントリー→エグジットの完全なサイクルをシミュレーション
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import glob
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Trade:
    """取引記録クラス"""
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_spread: float
    exit_spread: Optional[float]
    direction: str  # 'gmo_to_bitbank' or 'bitbank_to_gmo'
    pnl: Optional[float]
    duration_minutes: Optional[float]
    exit_reason: Optional[str]  # 'profit_target', 'stop_loss', 'timeout'

class ArbitrageSimulator:
    """アービトラージ取引シミュレーター"""
    
    def __init__(self, 
                 entry_threshold=200,     # エントリー閾値（円）
                 exit_threshold=50,       # 利益確定閾値（円）
                 stop_loss=-5000,         # 損切り閾値（実損失額、円）
                 max_hold_minutes=10,     # 最大保有時間（分）
                 trading_fee=0.001):      # 取引手数料（0.1%）
        
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.stop_loss = stop_loss
        self.max_hold_minutes = max_hold_minutes
        self.trading_fee = trading_fee
        
        self.trades: List[Trade] = []
        self.current_position: Optional[Trade] = None
        
    def load_data(self):
        """価格データの読み込み"""
        data_files = glob.glob('data/price_data_*.csv')
        data_files.sort()
        
        all_data = []
        for file in data_files:
            df = pd.read_csv(file)
            all_data.append(df)
        
        combined_df = pd.concat(all_data, ignore_index=True)
        combined_df['datetime'] = pd.to_datetime(combined_df['datetime'])
        combined_df = combined_df.sort_values('datetime').reset_index(drop=True)
        
        return combined_df
    
    def check_entry_conditions(self, row):
        """エントリー条件をチェック"""
        if self.current_position is not None:
            return None  # 既にポジション保有中
        
        # GMO買い→Bitbank売り（arbitrage_1が正の場合）
        if row['arbitrage_1'] > self.entry_threshold:
            return Trade(
                entry_time=row['datetime'],
                exit_time=None,
                entry_spread=row['arbitrage_1'],
                exit_spread=None,
                direction='gmo_to_bitbank',
                pnl=None,
                duration_minutes=None,
                exit_reason=None
            )
        
        # Bitbank買い→GMO売り（arbitrage_2が正の場合）
        if row['arbitrage_2'] > self.entry_threshold:
            return Trade(
                entry_time=row['datetime'],
                exit_time=None,
                entry_spread=row['arbitrage_2'],
                exit_spread=None,
                direction='bitbank_to_gmo',
                pnl=None,
                duration_minutes=None,
                exit_reason=None
            )
        
        return None
    
    def check_exit_conditions(self, row):
        """エグジット条件をチェック"""
        if self.current_position is None:
            return False
        
        # 時間経過チェック
        duration = (row['datetime'] - self.current_position.entry_time).total_seconds() / 60
        if duration >= self.max_hold_minutes:
            self._exit_position(row, 'timeout')
            return True
        
        # 【修正】決済方向（逆方向）のスプレッド取得
        if self.current_position.direction == 'gmo_to_bitbank':
            # GMO買い+Bitbank売りで参入 → GMO売り+Bitbank買いで決済（arbitrage_2）
            current_exit_spread = row['arbitrage_2']
        else:
            # Bitbank買い+GMO売りで参入 → Bitbank売り+GMO買いで決済（arbitrage_1）
            current_exit_spread = row['arbitrage_1']
        
        # 現在の予想損益を計算（手数料込み）
        gross_pnl = self.current_position.entry_spread + current_exit_spread
        trading_cost = (abs(self.current_position.entry_spread) + abs(current_exit_spread)) * self.trading_fee
        current_net_pnl = gross_pnl - trading_cost
        
        # 損切りチェック（実際の損失額で判定）
        if current_net_pnl <= self.stop_loss:
            self._exit_position(row, 'stop_loss')
            return True
        
        # 利益確定チェック（実際の利益額で判定）
        if current_net_pnl >= self.exit_threshold:
            self._exit_position(row, 'profit_target')
            return True
        
        return False
    
    def _exit_position(self, row, exit_reason):
        """ポジション決済"""
        # 【修正】決済時は逆方向のスプレッドが実際の利益
        if self.current_position.direction == 'gmo_to_bitbank':
            # GMO買い+Bitbank売りで参入 → GMO売り+Bitbank買いで決済
            exit_spread = row['arbitrage_2']
        else:
            # Bitbank買い+GMO売りで参入 → Bitbank売り+GMO買いで決済
            exit_spread = row['arbitrage_1']
        
        # 正しいP&L計算：エントリー時とエグジット時の両方の利益を合計
        gross_pnl = self.current_position.entry_spread + exit_spread
        trading_cost = (abs(self.current_position.entry_spread) + abs(exit_spread)) * self.trading_fee
        net_pnl = gross_pnl - trading_cost
        
        duration = (row['datetime'] - self.current_position.entry_time).total_seconds() / 60
        
        # 取引記録を完成
        self.current_position.exit_time = row['datetime']
        self.current_position.exit_spread = exit_spread
        self.current_position.pnl = net_pnl
        self.current_position.duration_minutes = duration
        self.current_position.exit_reason = exit_reason
        
        self.trades.append(self.current_position)
        self.current_position = None
    
    def simulate(self):
        """シミュレーション実行"""
        print("取引シミュレーションを開始...")
        df = self.load_data()
        
        for idx, row in df.iterrows():
            # エグジット条件チェック（優先）
            if self.current_position is not None:
                self.check_exit_conditions(row)
            
            # エントリー条件チェック
            if self.current_position is None:
                entry_trade = self.check_entry_conditions(row)
                if entry_trade is not None:
                    self.current_position = entry_trade
        
        # 最終ポジションの強制決済
        if self.current_position is not None:
            final_row = df.iloc[-1]
            self._exit_position(final_row, 'forced_exit')
        
        return self.trades
    
    def analyze_results(self):
        """取引結果の分析"""
        if not self.trades:
            print("取引が発生しませんでした。")
            return
        
        trades_df = pd.DataFrame([
            {
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'entry_spread': t.entry_spread,
                'exit_spread': t.exit_spread,
                'pnl': t.pnl,
                'duration_minutes': t.duration_minutes,
                'direction': t.direction,
                'exit_reason': t.exit_reason
            }
            for t in self.trades
        ])
        
        print(f"\n=== 取引シミュレーション結果 ===")
        print(f"総取引数: {len(self.trades)}回")
        print(f"分析期間: {trades_df['entry_time'].min()} ～ {trades_df['exit_time'].max()}")
        
        # P&L統計
        total_pnl = trades_df['pnl'].sum()
        win_trades = trades_df[trades_df['pnl'] > 0]
        loss_trades = trades_df[trades_df['pnl'] <= 0]
        
        print(f"\n=== 収益性分析 ===")
        print(f"総利益/損失: {total_pnl:.2f}円")
        print(f"平均P&L: {trades_df['pnl'].mean():.2f}円")
        print(f"勝率: {len(win_trades)/len(self.trades)*100:.1f}% ({len(win_trades)}/{len(self.trades)})")
        
        if len(win_trades) > 0:
            print(f"勝ちトレード平均: {win_trades['pnl'].mean():.2f}円")
            print(f"最大利益: {win_trades['pnl'].max():.2f}円")
        
        if len(loss_trades) > 0:
            print(f"負けトレード平均: {loss_trades['pnl'].mean():.2f}円")
            print(f"最大損失: {loss_trades['pnl'].min():.2f}円")
        
        # 保有時間分析
        print(f"\n=== 保有時間分析 ===")
        print(f"平均保有時間: {trades_df['duration_minutes'].mean():.1f}分")
        print(f"最長保有時間: {trades_df['duration_minutes'].max():.1f}分")
        print(f"最短保有時間: {trades_df['duration_minutes'].min():.1f}分")
        
        # 決済理由分析
        print(f"\n=== 決済理由分析 ===")
        exit_reasons = trades_df['exit_reason'].value_counts()
        for reason, count in exit_reasons.items():
            percentage = count / len(self.trades) * 100
            print(f"{reason}: {count}回 ({percentage:.1f}%)")
        
        # 方向別分析
        print(f"\n=== 方向別分析 ===")
        direction_stats = trades_df.groupby('direction')['pnl'].agg(['count', 'sum', 'mean'])
        print(direction_stats)
        
        return trades_df
    
    def visualize_results(self, trades_df):
        """結果の可視化"""
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # 1. P&L分布
        axes[0,0].hist(trades_df['pnl'], bins=30, alpha=0.7, edgecolor='black')
        axes[0,0].axvline(0, color='red', linestyle='--', label='Break-even')
        axes[0,0].set_title('P&L Distribution')
        axes[0,0].set_xlabel('P&L (JPY)')
        axes[0,0].set_ylabel('Frequency')
        axes[0,0].legend()
        
        # 2. 累積P&L
        cumulative_pnl = trades_df['pnl'].cumsum()
        axes[0,1].plot(range(len(cumulative_pnl)), cumulative_pnl)
        axes[0,1].set_title('Cumulative P&L')
        axes[0,1].set_xlabel('Trade Number')
        axes[0,1].set_ylabel('Cumulative P&L (JPY)')
        axes[0,1].grid(True)
        
        # 3. 保有時間分布
        axes[1,0].hist(trades_df['duration_minutes'], bins=20, alpha=0.7, edgecolor='black')
        axes[1,0].set_title('Holding Duration Distribution')
        axes[1,0].set_xlabel('Duration (Minutes)')
        axes[1,0].set_ylabel('Frequency')
        
        # 4. 決済理由
        exit_reasons = trades_df['exit_reason'].value_counts()
        axes[1,1].pie(exit_reasons.values, labels=exit_reasons.index, autopct='%1.1f%%')
        axes[1,1].set_title('Exit Reasons')
        
        plt.tight_layout()
        plt.savefig('realistic_arbitrage_analysis.png', dpi=300, bbox_inches='tight')
        plt.show()

def main():
    """メイン実行"""
    # 異なるパラメータでのシミュレーション
    scenarios = [
        # 平均回帰分析結果を反映：240分で98.2%成功率を活用
        # 現実的な損切り額（-3000〜-8000円）を設定
        
        # エントリー閾値の影響を詳細分析
        {'name': 'エントリー40k+240分', 'entry': 40000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 240},
        {'name': 'エントリー35k+240分', 'entry': 35000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 240},
        {'name': 'エントリー30k+240分', 'entry': 30000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 240},
        {'name': 'エントリー25k+240分', 'entry': 25000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 240},
        
        # 保有時間の比較（40k閾値で）
        {'name': '40k+60分', 'entry': 40000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 60},
        {'name': '40k+120分', 'entry': 40000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 120},
        {'name': '40k+240分', 'entry': 40000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 240},
        {'name': '40k+480分', 'entry': 40000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 480},
        
        # 損切り閾値の詳細検証（40k閾値、240分保有）
        {'name': 'SL-3k', 'entry': 40000, 'exit': 5000, 'stop_loss': -3000, 'max_hold': 240},
        {'name': 'SL-4k', 'entry': 40000, 'exit': 5000, 'stop_loss': -4000, 'max_hold': 240},
        {'name': 'SL-5k', 'entry': 40000, 'exit': 5000, 'stop_loss': -5000, 'max_hold': 240},
        {'name': 'SL-6k', 'entry': 40000, 'exit': 5000, 'stop_loss': -6000, 'max_hold': 240},
        {'name': 'SL-7k', 'entry': 40000, 'exit': 5000, 'stop_loss': -7000, 'max_hold': 240},
        {'name': 'SL-8k', 'entry': 40000, 'exit': 5000, 'stop_loss': -8000, 'max_hold': 240},
        {'name': 'SL-9k', 'entry': 40000, 'exit': 5000, 'stop_loss': -9000, 'max_hold': 240},
        {'name': 'SL-10k', 'entry': 40000, 'exit': 5000, 'stop_loss': -10000, 'max_hold': 240},
        {'name': 'SL-12k', 'entry': 40000, 'exit': 5000, 'stop_loss': -12000, 'max_hold': 240},
        {'name': 'SL-15k', 'entry': 40000, 'exit': 5000, 'stop_loss': -15000, 'max_hold': 240},
        
        # 利確閾値と損切り閾値の組み合わせ検証
        {'name': '利確3k+SL-10k', 'entry': 40000, 'exit': 3000, 'stop_loss': -10000, 'max_hold': 240},
        {'name': '利確7k+SL-10k', 'entry': 40000, 'exit': 7000, 'stop_loss': -10000, 'max_hold': 240},
        {'name': '利確10k+SL-10k', 'entry': 40000, 'exit': 10000, 'stop_loss': -10000, 'max_hold': 240},
    ]
    
    all_results = {}
    
    for scenario in scenarios:
        print(f"\n{'='*50}")
        print(f"シナリオ: {scenario['name']}")
        print(f"エントリー閾値: {scenario['entry']}円")
        print(f"利確閾値: {scenario['exit']}円") 
        print(f"損切り閾値: {scenario['stop_loss']}円")
        print(f"最大保有時間: {scenario['max_hold']}分")
        print(f"{'='*50}")
        
        simulator = ArbitrageSimulator(
            entry_threshold=scenario['entry'],
            exit_threshold=scenario['exit'],
            stop_loss=scenario['stop_loss'],
            max_hold_minutes=scenario['max_hold']
        )
        
        trades = simulator.simulate()
        trades_df = simulator.analyze_results()
        
        if trades_df is not None:
            all_results[scenario['name']] = {
                'trades_df': trades_df,
                'total_pnl': trades_df['pnl'].sum(),
                'win_rate': len(trades_df[trades_df['pnl'] > 0]) / len(trades_df) * 100,
                'total_trades': len(trades_df)
            }
    
    # シナリオ比較
    print(f"\n{'='*60}")
    print("シナリオ比較サマリー")
    print(f"{'='*60}")
    
    for name, result in all_results.items():
        print(f"{name:10} | 取引数: {result['total_trades']:3d} | "
              f"総P&L: {result['total_pnl']:8.0f}円 | "
              f"勝率: {result['win_rate']:5.1f}%")

if __name__ == "__main__":
    main()