# Bot de Trading FTMO - Portfolio de Stratégies

## Objectif Principal
Développer un portfolio de stratégies de trading automatisées pour la plateforme FTMO via cTrader, déployées en tant que cBots C# sur cTrader Cloud pour une exécution 24/7.

## Stratégies Déployées

### 1. USDJPY Price Action (Intraday)
- **Statut**: DEPLOYE sur cTrader Cloud
- **Performance validée**: +0.85%/semaine (walk-forward)
- **Fichier cBot**: `backend/usdjpy_pa_cbots/ValidatedUSDJPY_PA_cBot.cs`
- **Timeframe**: M30 entry, H1 structure
- **Type**: Support/Résistance + Price Action

### 2. GBPJPY Breakout-Pullback-Rejection (Intraday)
- **Statut**: DEPLOYE sur cTrader Cloud (27/02/2026)
- **Performance validée (Walk-Forward)**:
  - Train: +15.16% (23 trades, PF=3.45, DD=1.78%)
  - OOS: +7.74% (14 trades, PF=3.10)
  - Full: +0.25%/semaine
  - Monte Carlo (20 seeds): 100% profitable, mean +11.11%
  - Stress test (spread 4.0): toujours profitable (+10.94%)
- **Fichier cBot**: `backend/usdjpy_pa_cbots/GBPJPY_BreakoutPullback_cBot.cs`
- **Timeframe**: M30 entry, H1 structure
- **Paramètres optimaux**: swing=5, body=0.45, vol=0.3, RR=1.5, prox=1.0, timeout=25h
- **Limitations connues**: ~0.4 trades/semaine, clustering de trades

### Performance Portfolio Combinée
- USDJPY: +0.85%/semaine
- GBPJPY: +0.25%/semaine
- **Total estimé: ~1.1%/semaine**
- FTMO Compliant: Oui (DD combiné max ~4% < 8%)

## Architecture Technique

### Backend (Python/FastAPI)
```
/app/backend/
├── server.py                                    # FastAPI server
├── gbpjpy_breakout_backtester.py               # v2 optimisé (pre-scan H1)
├── run_gbpjpy_optimization.py                   # Walk-forward optimizer
├── realistic_backtester_v3_price_action.py     # USDJPY backtester
├── usdjpy_pa_strategy.py                        # Live signal logic USDJPY
├── live_trading_service.py                      # Server-side trading
├── tradingview_loader.py                        # Data loader
├── historical_data/                             # CSV data files
├── optimization_results/                        # JSON results
└── usdjpy_pa_cbots/
    ├── ValidatedUSDJPY_PA_cBot.cs              # cBot USDJPY
    └── GBPJPY_BreakoutPullback_cBot.cs         # cBot GBPJPY
```

### Améliorations v2 du Backtester GBPJPY
1. Multi-breakout tracking simultané
2. Pre-scan H1 breakouts (200x plus rapide pour optimization)
3. Binary search pour h1_index lookup
4. Scan rétroactif H1 (breakouts hors-session)
5. Niveaux clés multiples (3 swing + day high/low)
6. Patterns de rejet enrichis (close near extreme, impulse 50%)
7. Bug RSI corrigé (double filtre contradictoire)
8. Session étendue (London+Gap+NY)
9. Support precomputed breakouts pour grid search

## Données Historiques
- GBPJPY: H1 (2024-01 → 2026-02), M30 (2025-01 → 2026-02), M15, M5, D1
- USDJPY: données validées

## Règles FTMO
- Risque par trade: 1%
- Perte journalière max: 4.5%
- Drawdown total max: 8%
- Objectif profit: >2%/semaine (en cours)

## Tâches Complétées
- [x] Stratégie USDJPY PA validée et déployée (cBot + Cloud)
- [x] Stratégie GBPJPY Breakout-Pullback développée
- [x] Optimisation walk-forward GBPJPY (3072 combos, 9.3 min)
- [x] Monte Carlo + stress test GBPJPY
- [x] cBot C# GBPJPY créé et déployé sur cTrader Cloud
- [x] Guide utilisateur pas-à-pas fourni

## Backlog
- [ ] **P2**: Rapports email quotidiens/hebdomadaires (nerro_samy@live.fr)
- [ ] **P2**: 3ème stratégie haute fréquence (scalping M5 ou mean reversion)
- [ ] **P3**: Dashboard frontend amélioré
- [ ] **P4**: Nettoyage code (archiver v2, v4 backtesters)
- [ ] **P5**: Warning FIX API NumInGroup

## Projets Futurs (demandés par l'utilisateur)
- Outils d'investissement
- Suivi des dépenses
- Suivi sport/poids/calories
