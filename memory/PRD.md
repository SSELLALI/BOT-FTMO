# Bot de Trading FTMO - PRD

## Problème Original
Bot de trading compatible FTMO et cTrader pour paires forex majeures.
- Stratégies : Scalping et Intraday
- Gestion des risques stricte : 1% max risque/trade, 4.5% perte journalière max, 8% drawdown max

## Architecture
- Frontend: React + TailwindCSS + Recharts
- Backend: FastAPI + Motor (MongoDB async)
- Trading: FIX API pour cTrader, backtester avec données réelles (yfinance)
- Déploiement: VPS Hetzner (supervisord) + code sur GitHub

## Stratégie Scalping - Paramètres Optimisés
- **EMA rapide**: 10 périodes
- **EMA lente**: 30 périodes
- **Ratio Risque/Récompense**: 2.5
- **Multiplicateur ATR**: 1.0
- **RSI max achat**: 60
- **RSI min vente**: 40
- **SL min/max**: 5-20 pips
- **Sessions**: 07h-17h UTC

## Résultats Backtest (données réelles EUR/USD, 60 jours)
- **Return total**: +18.33%
- **Return/semaine**: +2.18% ✅ (objectif: 2%/semaine)
- **Trades**: 102 (12.1/semaine)
- **Win rate**: 34.3%
- **Profit Factor**: 1.27
- **Max Drawdown**: 6.13% (< 8% FTMO)
- **Max Daily Loss**: 3.38% (< 4.5% FTMO)
- **FTMO Compliant**: Oui

## Ce qui a été fait
- [x] Dashboard frontend avec stats trading
- [x] Panel Trading Live (connect/disconnect, start/stop)
- [x] Connexion FIX API cTrader fonctionnelle
- [x] Backtester avec données réelles (yfinance)
- [x] Optimiseur de paramètres
- [x] Stratégie scalping rentable (+2.18%/semaine)
- [x] Déploiement complet sur VPS Hetzner
- [x] Bot en mode live trading

## Tâches à venir
- [ ] P1: Améliorer stratégie Intraday (actuellement ~breakeven)
- [ ] P1: Corriger warning FIX API (NumInGroup)
- [ ] P2: Historique des trades live dans le dashboard
- [ ] P2: UI pour ajuster paramètres de stratégie
- [ ] P3: Support multi-paires (GBPUSD, USDJPY)
- [ ] P3: Trailing stop
- [ ] P3: Notifications email/Telegram
- [ ] P4: Machine Learning signaux
- [ ] P4: Filtrage par sessions optimisé
- [ ] Refactoring: découper trading_service.py en modules
