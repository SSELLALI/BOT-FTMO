"""
USDJPY INTRADAY — Script Autonome
============================================
Copiez ce script complet dans une nouvelle fenêtre Emergent.

Stratégie actuelle (EMA pullback) qui a montré un signal intéressant :
- Train: +0.38%/sem → Test: +0.63%/sem (test > train = bon signe)
- PF Test: 1.16 | DD Test: 0.66%
- Robustesse: 25% (à améliorer)

Meilleurs paramètres trouvés :
  ema_period=15, min_rr=2.5, atr_multiplier=0.5, pullback_pct=0.003,
  min_sl_pips=8, max_sl_pips=20, risk_per_trade=0.005,
  session_start=7, session_end=21, max_daily_trades=6, max_consecutive_losses=3

Pour lancer: python3 usdjpy_intraday_standalone.py
Données nécessaires: historical_data/USDJPY_H1_TV.csv, historical_data/USDJPY_M30_TV.csv
Dépendances: realistic_backtester_v3.py, walkforward_optimizer_v2.py, 
             tradingview_loader.py, news_calendar.py
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from tradingview_loader import load_tradingview_csv
from walkforward_optimizer_v2 import walk_forward_optimize_mtf

def main():
    print("=" * 60)
    print("USDJPY INTRADAY — Optimisation Walk-Forward MTF")
    print("Stratégie: EMA Pullback + RSI")
    print("=" * 60)

    h1 = load_tradingview_csv("historical_data/USDJPY_H1_TV.csv")
    m30 = load_tradingview_csv("historical_data/USDJPY_M30_TV.csv")

    if not h1:
        print("ERREUR: Données H1 non trouvées")
        return

    print(f"H1: {len(h1)} bougies | M30: {len(m30)} bougies")

    result = walk_forward_optimize_mtf(
        h1_candles=h1,
        m30_candles=m30,
        strategy_type="INTRADAY",
        train_pct=0.70,
        min_trades_train=60,
        min_trades_total=200,
        top_n=15,
        initial_balance=100000,
        progress_key="USDJPY_intraday_standalone",
        symbol="USDJPY",
        base_spread=0.9,
    )

    print(f"\nStatus: {result.get('status')}")
    print(f"Viables train: {result.get('viable_on_train', 0)}")
    print(f"Rentables OOS: {result.get('profitable_oos', 0)}")
    print(f"Robustes: {result.get('robust_count', 0)}")

    if result.get("results"):
        for i, r in enumerate(result["results"][:5]):
            fp = r.get("full_period", {})
            print(f"\n  #{i+1}: weekly={fp.get('weekly_return_pct','?')}% "
                  f"PF={fp.get('profit_factor','?')} DD={fp.get('max_drawdown_pct','?')}% "
                  f"robust={r.get('robust')} ({r.get('robustness_rate',0)*100:.0f}%)")
            print(f"    Params: {json.dumps(r['params'])}")

    with open("usdjpy_intraday_results.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\nResultats sauvegardés: usdjpy_intraday_results.json")

if __name__ == "__main__":
    main()
