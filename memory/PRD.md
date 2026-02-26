# Bot de Trading FTMO - PRD

## Informations Generales
**Nom**: FTMO Trading Bot Dashboard  
**Version**: 2.2.0  
**Derniere MAJ**: 26 Fevrier 2026

---

## Objectif
Bot de trading automatise compatible FTMO pour le Forex avec:
- 2 strategies: Scalping (Multi-Signal Momentum M15) et Intraday (Trend + Breakout H1/M15)
- Gestion stricte des risques FTMO avec barrieres de securite inviolables
- Dashboard web en francais avec monitoring temps reel
- Backtesting avec donnees REELLES (Yahoo Finance) et simulees
- Integration FIX API live sur cTrader (deploye sur VPS Hetzner)

---

## Regles FTMO (Implementees et Validees)
| Regle | Valeur | Statut |
|-------|--------|--------|
| Max perte/trade | 1% (buffer 5%) | OK |
| R:R minimum | 1.3:1 (Scalp) / 2:1 (Intra) | OK |
| Max perte journaliere | 4.5% solde initial | OK - JAMAIS DEPASSEE |
| Max drawdown total | 8% solde initial | OK - JAMAIS DEPASSE |
| Arret consecutif Scalp | 3 pertes | OK |
| Arret consecutif Intra | 2 pertes | OK |
| Max positions simultanees | 1 | OK |
| Fermeture preventive | 3% daily / 6% total | OK |

---

## Fonctionnalites Implementees

### v2.2.0 (26/02/2026)
- [x] Donnees historiques reelles (Yahoo Finance via yfinance)
- [x] Backtesting sur EUR/USD reel (60 jours M15 + 2 ans H1)
- [x] Auto-download et cache des donnees CSV
- [x] Indicateur "data_source: real/simulated" dans les resultats
- [x] Fallback automatique vers donnees simulees si pas de donnees reelles

### v2.1.0 (25/02/2026)
- [x] Integration FIX API complete
- [x] Service de trading live
- [x] Deploiement VPS Hetzner (89.167.122.233)
- [x] Connexion FIX FTMO reussie
- [x] Onglet Trading Live dans le dashboard

### v2.0.0 (25/02/2026)
- [x] Reecriture strategies mode agressif
- [x] Barrieres FTMO strictes (calcul sur solde initial)
- [x] Hard cap PnL, fermeture preventive, 1 position max

### v1.0.0 (25/02/2026)
- [x] Dashboard complet en francais
- [x] Backtesting professionnel
- [x] API REST complete

---

## Resultats Backtest (Donnees Reelles - 60 jours EURUSD)

### Scalping
- Trades: 24 | WR: 33.3% | Return: -7.43% | PF: 0.36
- MaxDD: 7.43% | Max Daily: 3.46%
- FTMO: Toutes barrieres respectees

### Intraday
- Trades: 75 | WR: 32.0% | Return: -7.41% | PF: 0.82
- MaxDD: 7.41% | Max Daily: 1.95%
- FTMO: Toutes barrieres respectees

**CONCLUSION**: Les barrieres FTMO fonctionnent parfaitement. Les strategies ont besoin d'optimisation pour etre rentables sur le marche reel.

---

## Deploiement
- VPS: Hetzner CX22 (89.167.122.233)
- Backend: uvicorn sur port 8001
- Supervisor: ftmo-bot (auto-restart)
- GitHub: https://github.com/SSELLALI/BOT-FTMO (privé)

---

## Backlog
### P0 (Critique)
- [ ] Optimiser les strategies sur donnees reelles pour meilleur win rate
- [ ] Tester multi-paires (GBPUSD, USDJPY)

### P1 (Important)
- [ ] Trailing stop
- [ ] Notifications email/Telegram
- [ ] Dashboard frontend accessible sur VPS

### P2 (Nice to have)
- [ ] Optimisation automatique des parametres
- [ ] Machine Learning signaux
- [ ] Filtrage par sessions
