# Bot de Trading FTMO - PRD (Product Requirements Document)

## Informations Generales

**Nom du Projet**: FTMO Trading Bot Dashboard
**Date de Creation**: 25 Fevrier 2026
**Version**: 2.0.0
**Derniere mise a jour**: 25 Fevrier 2026

---

## Objectif du Projet

Bot de trading automatise compatible FTMO pour le Forex, avec :
- Deux strategies : Scalping (Multi-Signal Momentum) et Intraday (Trend Continuation + Breakout)
- Gestion stricte des risques FTMO avec barrieres de securite
- Dashboard web de monitoring en temps reel (en francais)
- Systeme de backtesting professionnel integre

---

## Regles de Gestion des Risques (FTMO)
| Regle | Valeur | Statut |
|-------|--------|--------|
| Max perte par trade | 1% (avec buffer 5%) | Implemente |
| Risk/Reward minimum | 1.3:1 (Scalping) / 2:1 (Intraday) | Implemente |
| Max perte journaliere | 4.5% du solde initial | Implemente |
| Max drawdown total | 8% du solde initial | Implemente |
| Arret pertes consecutives (Scalping) | 3 pertes | Implemente |
| Arret pertes consecutives (Intraday) | 2 pertes | Implemente |
| Max positions simultanées | 1 | Implemente |
| Fermeture de securite preventive | 3% daily / 6% total | Implemente |

---

## Strategies Implementees

### Scalping - Multi-Signal Momentum (v2.0)
- **Timeframe**: M15
- **Sessions**: London etendu (07-17 UTC)
- **Indicateurs**: EMA9/21, RSI14, Bollinger Bands, Momentum
- **Signaux**: EMA bounce, Pattern (engulfing/rejection), Momentum candle, EMA21 breakout, BB reversal
- **R:R**: 1.3:1 minimum
- **Max trades/jour**: 10
- **Performance typique**: 500-660 trades / 6 mois, 51-56% WR, 190-313% return

### Intraday - Trend Continuation + Breakout (v2.0)
- **Analyse**: H1 | **Entree**: M15
- **Sessions**: London + NY (07-21 UTC)
- **Indicateurs**: EMA50/200 (H1), EMA9/21 + RSI + Momentum (M15)
- **Signaux**: H1 EMA50 pullback, Support/Resistance bounce, Breakout, M15 EMA cross
- **R:R**: 2:1 minimum
- **Max trades/jour**: 5
- **Performance typique**: 40-70 trades / 6 mois, 35-42% WR, 5-17% return

---

## Fonctionnalites Implementees

### Version 2.0.0 (25/02/2026)
- [x] Reecriture complete des strategies (mode agressif)
- [x] Barrieres de securite FTMO strictes (jamais depassees)
- [x] Max drawdown corrige de 10% a 8%
- [x] Calcul drawdown base sur solde INITIAL (regle FTMO)
- [x] Fermeture de securite preventive a 3% daily / 6% total
- [x] Hard cap PnL pour empecher tout depassement
- [x] Limite 1 position simultanee maximum
- [x] Buffer 5% sur position sizing

### Version 1.0.0 (25/02/2026)
- [x] Dashboard principal en francais
- [x] Widget de gestion des risques FTMO
- [x] Graphique d equite en temps reel
- [x] Donnees de marche en direct (simulees)
- [x] Indicateurs techniques (RSI, MACD, EMA, S/R)
- [x] Historique des trades
- [x] Modal de parametrage et connexion cTrader
- [x] Modal de backtesting avec resultats detailles
- [x] API REST complete

---

## Backlog Priorise

### P0 (Critique)
- [x] Reecriture strategies agressives avec barrieres FTMO - FAIT
- [ ] Obtenir mot de passe FIX API et tester connexion reelle

### P1 (Important)
- [ ] Ajouter des donnees historiques reelles (Dukascopy/HistData)
- [ ] Implementer un systeme de trailing stop
- [ ] Ajouter filtrage par sessions (London/NY)
- [ ] Notifications par email/Telegram

### P2 (Nice to have)
- [ ] Optimisation automatique des parametres
- [ ] Machine Learning pour ameliorer les signaux
- [ ] Multi-timeframe analysis avance
- [ ] Journaling des trades avec screenshots

---

## Architecture
```
/app/
├── backend/
│   ├── server.py                    # API FastAPI principale
│   ├── professional_strategies.py   # Strategies v2 + Risk Manager FTMO
│   ├── professional_backtester.py   # Moteur de backtesting multi-timeframe
│   ├── risk_manager.py              # Risk manager (dashboard)
│   ├── trading_strategies.py        # Strategies v1 (dashboard signals)
│   ├── market_simulator.py          # Simulation de marche
│   ├── real_market_data.py          # Donnees reelles
│   ├── models.py                    # Modeles Pydantic
│   ├── ctrader_fix_client.py        # Client FIX API
│   └── ctrader_open_api_client.py   # Client Open API
├── frontend/
│   └── src/
│       ├── App.js                   # Application React principale
│       └── App.css                  # Styles personnalises
└── memory/
    └── PRD.md                       # Ce document
```

---

## Credentials Requis

### cTrader FIX API (FTMO)
```
Host: live-uk-eqx-01.p.c-trader.com
Port: 5211 (SSL)
Account: 17061677
SenderCompID: live.ftmo.17061677
TargetCompID: cServer
Password: [A OBTENIR DE FTMO]
```

---

## Donnees Simulees (IMPORTANT)
Le systeme de backtesting utilise des donnees de marche GENEREES ALEATOIREMENT.
Les resultats sont representatifs du fonctionnement des barrieres de securite,
mais ne predisent PAS les performances reelles sur le marche.
Pour des resultats realistes, utiliser des donnees historiques CSV (P1).
