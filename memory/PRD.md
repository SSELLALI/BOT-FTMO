# Bot de Trading FTMO - PRD

## Problème Original
Trading bot pour FTMO/cTrader pour paires forex majeures, implémentant des stratégies Price Action avec gestion de risque stricte (1% risque/trade, 4.5% perte journalière, 8% perte totale) et objectif >2% profit hebdomadaire.

## Architecture
```
/app/backend/
├── server.py                           # FastAPI principal
├── live_trading_service.py             # Service de trading live (FIX API)
├── usdjpy_pa_strategy.py              # Stratégie PA validée (BREAKOUT + BOUNCE)
├── usdjpy_validated_strategy.json     # Paramètres verrouillés
├── price_action_backtester.py         # Backtester Price Action (H1/M30)
├── swing_backtester.py                # Backtester Swing (D1/H4/H2)
├── walkforward_optimizer_pa.py        # Optimiseur walk-forward PA
├── walkforward_optimizer_swing.py     # Optimiseur walk-forward Swing
├── run_swing_optimization.py          # Runner swing optimization
├── ctrader_fix_client.py              # Client FIX API
├── historical_data/                   # Données TradingView (M5 à D1)
└── optimization_results/              # Résultats JSON
```

## Stratégies Implémentées

### USDJPY Intraday Price Action (VALIDÉE ✅ DÉPLOYÉE)
- **BREAKOUT**: +0.288%/sem, PF=1.23, robustesse 100% (12/12)
- **BOUNCE**: +0.653%/sem, PF=1.26, robustesse 92% (11/12)
- **Combiné réaliste**: ~0.78-0.94%/semaine
- **FTMO compliant**: ✅ dans tous les scénarios
- **4/4 trimestres profitables** pour les deux stratégies
- **Déployé**: dans live_trading_service.py avec endpoints API

### Swing Trading (TESTÉ — NON VIABLE)
- GBPJPY: Échec total (overfitting massif, 0 profitable OOS)
- AUDCAD: Marginal (0 robuste)
- USDJPY Swing: 2 robustes mais rendement quasi-nul (+0.016%/sem)

## Tâches Complétées
- [x] Pivot vers Price Action (S/R + Candlestick)
- [x] Stratégie USDJPY validée et verrouillée (+0.94%/sem réaliste)
- [x] Audit de robustesse complet (perturbation + sous-périodes)
- [x] Intégration dans live_trading_service.py
- [x] Endpoints API: GET /api/live/pa-strategy, PUT /api/live/strategies
- [x] Initialisation automatique données H1/M30 au démarrage
- [x] Optimisation Swing sur 3 paires (résultats: non viable)
- [x] Testing agent: 14/14 tests passent

## Backlog
- [ ] **P1**: Rapports email quotidiens/hebdomadaires (nerro_samy@live.fr)
- [ ] **P2**: Stratégies alternatives pour GBPJPY/AUDCAD (mean reversion, momentum)
- [ ] **P3**: Dashboard frontend avec résultats stratégies
- [ ] **P4**: Nettoyage code (archiver v2, consolider)
- [ ] **P5**: Corriger warning FIX API NumInGroup
