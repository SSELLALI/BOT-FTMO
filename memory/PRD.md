# Bot de Trading FTMO - PRD

## Informations Generales
**Nom**: FTMO Trading Bot Dashboard  
**Version**: 2.1.0  
**Derniere MAJ**: 25 Fevrier 2026

---

## Objectif
Bot de trading automatise compatible FTMO pour le Forex avec:
- 2 strategies: Scalping (Multi-Signal Momentum M15) et Intraday (Trend + Breakout H1/M15)
- Gestion stricte des risques FTMO avec barrieres de securite inviolables
- Dashboard web en francais avec monitoring temps reel
- Systeme de backtesting professionnel
- Integration FIX API pour trading live sur cTrader

---

## Regles FTMO (Implementees)
| Regle | Valeur | Statut |
|-------|--------|--------|
| Max perte/trade | 1% (buffer 5%) | OK |
| R:R minimum | 1.3:1 (Scalp) / 2:1 (Intra) | OK |
| Max perte journaliere | 4.5% solde initial | OK |
| Max drawdown total | 8% solde initial | OK |
| Arret consecutif Scalp | 3 pertes | OK |
| Arret consecutif Intra | 2 pertes | OK |
| Max positions simultanees | 1 | OK |
| Fermeture preventive | 3% daily / 6% total | OK |
| Hard cap PnL | Empeche tout depassement | OK |

---

## Fonctionnalites Implementees

### v2.1.0 (25/02/2026)
- [x] Integration FIX API complete (credentials en .env)
- [x] Service de trading live (live_trading_service.py)
- [x] Endpoints API: /api/live/connect, start, stop, status
- [x] Onglet "Trading Live" dans le dashboard
- [x] Panneau de controle avec statut connexion
- [x] Affichage positions et risque temps reel
- [x] Barrieres FTMO affichees dans l'UI

### v2.0.0 (25/02/2026)
- [x] Reecriture complete strategies (mode agressif)
- [x] Drawdown base sur solde INITIAL (regle FTMO)
- [x] Fermeture preventive 3%/6%
- [x] Hard cap PnL journalier
- [x] 1 position max simultanee
- [x] Buffer 5% position sizing

### v1.0.0 (25/02/2026)
- [x] Dashboard complet en francais
- [x] Gestion risques FTMO
- [x] Graphique equite
- [x] Marche simule
- [x] Indicateurs techniques
- [x] Historique trades
- [x] Backtesting professionnel

---

## Architecture
```
backend/
  server.py                    # API FastAPI
  professional_strategies.py   # Strategies v2 + Risk Manager FTMO
  professional_backtester.py   # Backtesting multi-timeframe
  live_trading_service.py      # Service trading live FIX
  ctrader_fix_client.py        # Client FIX protocol
  risk_manager.py              # Risk manager dashboard
  .env                         # FIX credentials + MongoDB
frontend/src/
  App.js                       # Dashboard React (tabs: Dashboard, Trades, Signaux, Trading Live)
```

---

## Credentials FIX (dans backend/.env)
- Host: live-uk-eqx-01.p.c-trader.com:5211
- Compte: 17061677
- SenderCompID: live.ftmo.17061677
- Password: configure

---

## Backlog
### P1 (Important)
- [ ] Donnees historiques reelles (CSV) pour backtests realistes
- [ ] Trailing stop pour securiser profits
- [ ] Test connexion FIX sur serveur dedie (pas preview)

### P2 (Nice to have)
- [ ] Optimisation auto des parametres
- [ ] Notifications email/Telegram
- [ ] Filtrage par sessions (London/NY)
- [ ] Machine Learning signaux

---

## Note Importante
Les donnees de marche du backtesting sont SIMULEES (aleatoires).
Les resultats valident le fonctionnement des barrieres FTMO
mais ne predisent PAS les performances reelles.
La connexion FIX ne fonctionne pas dans l'environnement preview
(bloquee par le reseau). Elle fonctionnera sur un serveur dedie.
