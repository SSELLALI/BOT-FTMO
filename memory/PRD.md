# Bot de Trading FTMO - PRD (Product Requirements Document)

## 📋 Informations Générales

**Nom du Projet**: FTMO Trading Bot Dashboard
**Date de Création**: 25 Février 2026
**Version**: 1.0.0

---

## 🎯 Objectif du Projet

Créer un bot de trading automatisé compatible avec les règles FTMO pour le Forex, avec :
- Deux stratégies : Scalping et Intraday
- Gestion stricte des risques FTMO
- Dashboard web de monitoring en temps réel
- Système de backtesting intégré

---

## 👥 Personas Utilisateurs

### Trader FTMO
- **Profil**: Trader forex cherchant à passer/maintenir un challenge FTMO
- **Besoins**: Automatisation du trading, respect des limites de risque, suivi en temps réel
- **Contraintes**: Max 4.5% perte/jour, max 10% drawdown total, min 1:1 RR

---

## 📌 Exigences Principales (Statiques)

### Règles de Gestion des Risques
| Règle | Valeur | Statut |
|-------|--------|--------|
| Max perte par trade | 1% | ✅ Implémenté |
| Risk/Reward minimum | 1:1 | ✅ Implémenté |
| Max perte journalière | 4.5% | ✅ Implémenté |
| Max drawdown total | 10% | ✅ Implémenté |

### Stratégies de Trading
| Stratégie | Indicateurs | Timeframe |
|-----------|-------------|-----------|
| Scalping | RSI + EMA (8/21) | M15-H1 |
| Intraday | Support/Résistance + MACD | H1-H4 |

### Paires de Devises
- Focus principal : **EUR/USD**
- Autres majors disponibles : GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD, NZD/USD

---

## ✅ Fonctionnalités Implémentées

### Version 1.0.0 (25/02/2026)

#### Backend (FastAPI + MongoDB)
- [x] API REST complète pour le dashboard
- [x] Gestion des risques FTMO
- [x] Moteur de stratégies (Scalping + Intraday)
- [x] Simulateur de marché avec données réalistes
- [x] Client FIX API pour cTrader (prêt à connecter)
- [x] Client Open API pour cTrader
- [x] **Système de backtesting complet**

#### Frontend (React + Tailwind)
- [x] Dashboard principal en français
- [x] Widget de gestion des risques FTMO (Risk Meter)
- [x] Graphique d'équité en temps réel
- [x] Données de marché en direct
- [x] Indicateurs techniques (RSI, MACD, EMA, S/R)
- [x] Signaux de trading actifs
- [x] Historique des trades
- [x] Modal de paramétrage
- [x] Modal de connexion cTrader
- [x] **Modal de backtesting avec résultats détaillés**

#### Base de Données (MongoDB)
- [x] Collection `trades` : Historique des trades
- [x] Collection `account` : État du compte
- [x] Collection `settings` : Configuration du bot
- [x] Collection `alerts` : Notifications
- [x] Collection `backtests` : Résultats de backtesting

---

## 🔄 Mode Actuel

### Paper Trading (Simulation)
- ✅ Utilise des données de marché réelles via APIs gratuites
- ✅ Simule les trades sans risque réel
- ✅ Prêt pour connexion au compte réel

### Pour activer le Trading Réel
1. Obtenir le mot de passe FIX API de FTMO (contacter support@ftmo.com)
2. Cliquer sur "Connexion" dans le dashboard
3. Entrer le mot de passe FIX
4. Le bot commencera à trader en réel

---

## 📊 Résultats de Backtesting (6 mois)

| Métrique | Valeur |
|----------|--------|
| Rendement | -5.84% |
| Win Rate | 21.6% |
| Profit Factor | 0.55 |
| Max Drawdown | 5.84% |
| Conformité FTMO Daily | ✅ OK |
| Conformité FTMO Total | ✅ OK |

**Note**: Les stratégies actuelles respectent les limites FTMO mais nécessitent une optimisation pour devenir rentables.

---

## 📋 Backlog Priorisé

### P0 (Critique)
- [ ] Obtenir mot de passe FIX API et tester connexion réelle
- [ ] Optimiser les stratégies pour améliorer le win rate

### P1 (Important)
- [ ] Ajouter des données historiques réelles (Dukascopy/HistData)
- [ ] Implémenter un système de trailing stop
- [ ] Ajouter filtrage par sessions (London/NY)
- [ ] Notifications par email/Telegram

### P2 (Nice to have)
- [ ] Optimisation automatique des paramètres
- [ ] Machine Learning pour améliorer les signaux
- [ ] Multi-timeframe analysis
- [ ] Journaling des trades avec screenshots

---

## 🔐 Credentials Requis

### cTrader FIX API (FTMO)
```
Host: live-uk-eqx-01.p.c-trader.com
Port: 5211 (SSL)
Account: 17061677
SenderCompID: live.ftmo.17061677
TargetCompID: cServer
Password: [À OBTENIR DE FTMO]
```

---

## 📁 Architecture des Fichiers

```
/app/
├── backend/
│   ├── server.py           # API FastAPI principale
│   ├── models.py           # Modèles Pydantic
│   ├── risk_manager.py     # Gestion des risques FTMO
│   ├── trading_strategies.py # Stratégies Scalping/Intraday
│   ├── backtesting.py      # Moteur de backtesting
│   ├── market_simulator.py # Simulation de marché
│   ├── real_market_data.py # Données réelles
│   ├── ctrader_fix_client.py # Client FIX API
│   └── ctrader_open_api_client.py # Client Open API
├── frontend/
│   └── src/
│       ├── App.js          # Application React principale
│       └── App.css         # Styles personnalisés
└── memory/
    └── PRD.md              # Ce document
```

---

## 📅 Prochaines Étapes

1. **Connexion Réelle** : Attendre le mot de passe FIX de FTMO
2. **Optimisation** : Améliorer les signaux avec des filtres supplémentaires
3. **Test en Démo** : Valider sur compte démo avant réel
4. **Monitoring** : Surveiller les performances en direct

---

*Document mis à jour le 25/02/2026*
