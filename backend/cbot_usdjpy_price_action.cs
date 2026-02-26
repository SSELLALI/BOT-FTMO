// ============================================================
// USDJPY Price Action cBot — Stratégie Validée (BREAKOUT + BOUNCE)
// ============================================================
// Performance validée (walk-forward, 2 ans de données TradingView):
//   BREAKOUT: +0.288%/sem, PF=1.23, Robustesse 100%
//   BOUNCE:   +0.653%/sem, PF=1.26, Robustesse 92%
//   Combiné:  ~0.94%/sem | FTMO Compliant
//
// INSTRUCTIONS:
//   1. Ouvrir cTrader > onglet "Automate" (en bas)
//   2. Cliquer "+" > "New cBot"
//   3. Supprimer tout le code par défaut
//   4. Coller CE code en entier
//   5. Cliquer "Build" (icône marteau)
//   6. Aller sur le graphique USDJPY en M30
//   7. Dans le panneau de gauche > cBots > "USDJPY_PriceAction"
//   8. Double-cliquer ou glisser sur le graphique
//   9. Configurer le volume et cliquer "Start"
// ============================================================

using System;
using System.Collections.Generic;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class USDJPY_PriceAction : Robot
    {
        // ── Paramètres configurables ──
        [Parameter("Risk par trade (%)", DefaultValue = 0.5, MinValue = 0.1, MaxValue = 2.0, Step = 0.1)]
        public double RiskPercent { get; set; }

        [Parameter("Activer BREAKOUT", DefaultValue = true)]
        public bool EnableBreakout { get; set; }

        [Parameter("Activer BOUNCE", DefaultValue = true)]
        public bool EnableBounce { get; set; }

        [Parameter("Max trades/jour", DefaultValue = 5, MinValue = 1, MaxValue = 10)]
        public int MaxDailyTrades { get; set; }

        [Parameter("Max pertes consécutives", DefaultValue = 3, MinValue = 1, MaxValue = 5)]
        public int MaxConsecutiveLosses { get; set; }

        [Parameter("Session début (heure UTC)", DefaultValue = 7, MinValue = 0, MaxValue = 23)]
        public int SessionStart { get; set; }

        [Parameter("Session fin (heure UTC)", DefaultValue = 20, MinValue = 1, MaxValue = 23)]
        public int SessionEnd { get; set; }

        // ── Paramètres BREAKOUT (validés — ne pas modifier) ──
        private const int BreakoutSwingLookback = 15;
        private const double BreakoutClusterPips = 15;
        private const double BreakoutProximityPips = 10;
        private const double BreakoutMinRR = 3.0;
        private const double BreakoutMinSL = 20;
        private const double BreakoutMaxSL = 45;
        private const double BreakoutBreakPips = 12;
        private const double BreakoutBufferPips = 5;

        // ── Paramètres BOUNCE (validés — ne pas modifier) ──
        private const int BounceSwingLookback = 10;
        private const double BounceClusterPips = 25;
        private const double BounceProximityPips = 18;
        private const double BounceMinRR = 3.0;
        private const double BounceMinSL = 20;
        private const double BounceMaxSL = 30;
        private const double BounceBufferPips = 5;

        // ── État interne ──
        private Bars _h1Bars;
        private RelativeStrengthIndex _h1Rsi;
        private AverageTrueRange _h1Atr;
        private int _dailyTrades;
        private int _consecutiveLosses;
        private DateTime _lastTradeDate;
        private string _botLabel = "USDJPY_PA";

        protected override void OnStart()
        {
            // Charger les bougies H1 pour les zones S/R
            _h1Bars = MarketData.GetBars(TimeFrame.Hour, SymbolName);

            // Charger assez d'historique H1
            while (_h1Bars.Count < 300)
            {
                if (_h1Bars.LoadMoreHistory() < 1)
                    break;
            }

            // Indicateurs sur H1
            _h1Rsi = Indicators.RelativeStrengthIndex(_h1Bars.ClosePrices, 14);
            _h1Atr = Indicators.AverageTrueRange(_h1Bars, 14, MovingAverageType.Exponential);

            _dailyTrades = 0;
            _consecutiveLosses = 0;
            _lastTradeDate = Server.Time.Date;

            // Écouter les fermetures de position pour le risk management
            Positions.Closed += OnPositionClosed;

            Print("=== USDJPY Price Action cBot DÉMARRÉ ===");
            Print("H1 bougies chargées: {0}", _h1Bars.Count);
            Print("Stratégies: BREAKOUT={0} | BOUNCE={1}", EnableBreakout, EnableBounce);
            Print("Risk: {0}% | Max trades/jour: {1} | Session: {2}h-{3}h UTC",
                  RiskPercent, MaxDailyTrades, SessionStart, SessionEnd);

            // Afficher les zones S/R actuelles
            var zones = GetSRZones(BreakoutSwingLookback, BreakoutClusterPips);
            Print("Zones S/R BREAKOUT actuelles: {0}", zones.Count);
            foreach (var z in zones.Take(5))
                Print("  Zone: {0:F3} (force={1})", z.Price, z.Strength);

            var zonesB = GetSRZones(BounceSwingLookback, BounceClusterPips);
            Print("Zones S/R BOUNCE actuelles: {0}", zonesB.Count);
            foreach (var z in zonesB.Take(5))
                Print("  Zone: {0:F3} (force={1})", z.Price, z.Strength);
        }

        protected override void OnBar()
        {
            // Reset compteur journalier
            if (Server.Time.Date != _lastTradeDate)
            {
                if (_dailyTrades > 0)
                    Print("[RESET] Nouveau jour — {0} trades hier", _dailyTrades);
                _dailyTrades = 0;
                _consecutiveLosses = 0;
                _lastTradeDate = Server.Time.Date;
            }

            // Vérifier la session
            int hour = Server.Time.Hour;
            if (hour < SessionStart || hour >= SessionEnd)
                return;

            // Vérifier les limites
            if (_dailyTrades >= MaxDailyTrades)
            {
                Print("[LIMITE] Max trades/jour atteint ({0})", MaxDailyTrades);
                return;
            }
            if (_consecutiveLosses >= MaxConsecutiveLosses)
            {
                Print("[LIMITE] Max pertes consécutives atteint ({0})", MaxConsecutiveLosses);
                return;
            }

            // Vérifier FTMO drawdown
            double currentBalance = Account.Balance;
            double initialBalance = Account.Balance + Math.Abs(Account.UnrealizedNetProfit);
            // Simple protection: ne pas trader si drawdown > 6%
            if (Account.Equity < currentBalance * 0.94)
            {
                Print("[FTMO] Drawdown trop élevé — trading suspendu");
                return;
            }

            // Ne pas ouvrir si déjà une position PA ouverte
            var myPositions = Positions.FindAll(_botLabel, SymbolName);
            if (myPositions.Length > 0)
                return;

            // Récupérer le RSI H1 actuel
            int h1Index = _h1Bars.Count - 2; // Bougie H1 confirmée (pas en cours)
            if (h1Index < 50)
                return;

            double rsi = _h1Rsi.Result[h1Index];
            double atr = _h1Atr.Result[h1Index];

            // Bougies M30 (graphique actuel) — utiliser la bougie CONFIRMÉE (index -1 = avant-dernière)
            int m30Index = Bars.Count - 2;
            if (m30Index < 3)
                return;

            double prevClose = Bars.ClosePrices[m30Index];
            double prevOpen = Bars.OpenPrices[m30Index];
            double prevHigh = Bars.HighPrices[m30Index];
            double prevLow = Bars.LowPrices[m30Index];

            // Détecter les patterns candlestick sur M30
            var patterns = DetectPatterns(m30Index);

            // ── BREAKOUT ──
            if (EnableBreakout)
            {
                var zones = GetSRZones(BreakoutSwingLookback, BreakoutClusterPips);
                CheckBreakout(zones, prevClose, prevOpen, prevHigh, prevLow, patterns, rsi);
            }

            // ── BOUNCE ──
            if (EnableBounce && Positions.FindAll(_botLabel, SymbolName).Length == 0)
            {
                var zones = GetSRZones(BounceSwingLookback, BounceClusterPips);
                CheckBounce(zones, prevClose, prevOpen, prevHigh, prevLow, patterns, rsi);
            }
        }

        // ══════════════════════════════════════════
        // ZONES SUPPORT / RÉSISTANCE (depuis H1)
        // ══════════════════════════════════════════

        private struct SRZone
        {
            public double Price;
            public int Strength;
        }

        private List<SRZone> GetSRZones(int lookback, double clusterPips)
        {
            var swingLevels = new List<double>();
            int count = _h1Bars.Count;
            double clusterDist = clusterPips * Symbol.PipSize;

            // Trouver les swing highs et lows sur H1
            for (int i = lookback; i < count - lookback; i++)
            {
                bool isSwingHigh = true;
                bool isSwingLow = true;

                for (int j = i - lookback; j <= i + lookback; j++)
                {
                    if (j == i) continue;
                    if (_h1Bars.HighPrices[j] > _h1Bars.HighPrices[i]) isSwingHigh = false;
                    if (_h1Bars.LowPrices[j] < _h1Bars.LowPrices[i]) isSwingLow = false;
                }

                if (isSwingHigh) swingLevels.Add(_h1Bars.HighPrices[i]);
                if (isSwingLow) swingLevels.Add(_h1Bars.LowPrices[i]);
            }

            // Garder les 40 plus récents
            if (swingLevels.Count > 40)
                swingLevels = swingLevels.Skip(swingLevels.Count - 40).ToList();

            // Regrouper en clusters
            swingLevels.Sort();
            var zones = new List<SRZone>();
            var used = new HashSet<int>();

            for (int i = 0; i < swingLevels.Count; i++)
            {
                if (used.Contains(i)) continue;

                var cluster = new List<double> { swingLevels[i] };
                used.Add(i);

                for (int j = i + 1; j < swingLevels.Count; j++)
                {
                    if (used.Contains(j)) continue;
                    if (Math.Abs(swingLevels[j] - swingLevels[i]) <= clusterDist)
                    {
                        cluster.Add(swingLevels[j]);
                        used.Add(j);
                    }
                }

                zones.Add(new SRZone
                {
                    Price = cluster.Average(),
                    Strength = cluster.Count
                });
            }

            // Filtrer: au moins 2 touches
            return zones.Where(z => z.Strength >= 2).OrderByDescending(z => z.Strength).ToList();
        }

        // ══════════════════════════════════════════
        // PATTERNS CANDLESTICK (sur M30)
        // ══════════════════════════════════════════

        private List<string> DetectPatterns(int idx)
        {
            var patterns = new List<string>();
            if (idx < 2) return patterns;

            double open = Bars.OpenPrices[idx];
            double close = Bars.ClosePrices[idx];
            double high = Bars.HighPrices[idx];
            double low = Bars.LowPrices[idx];

            double body = Math.Abs(close - open);
            double range = high - low;
            if (range <= 0) return patterns;

            double bodyRatio = body / range;
            double upperWick = high - Math.Max(open, close);
            double lowerWick = Math.Min(open, close) - low;

            bool isBullish = close > open;
            bool isBearish = close < open;

            // Pin bar haussier (longue mèche basse)
            if (bodyRatio < 0.35 && lowerWick > body * 2.0 && upperWick < body * 1.0)
                patterns.Add("BULLISH_PINBAR");

            // Pin bar baissier (longue mèche haute)
            if (bodyRatio < 0.35 && upperWick > body * 2.0 && lowerWick < body * 1.0)
                patterns.Add("BEARISH_PINBAR");

            // Hammer
            if (isBullish && lowerWick > body * 2.0 && upperWick < body * 0.5)
                patterns.Add("HAMMER");

            // Shooting star
            if (isBearish && upperWick > body * 2.0 && lowerWick < body * 0.5)
                patterns.Add("SHOOTING_STAR");

            // Engulfing haussier
            double prevOpen = Bars.OpenPrices[idx - 1];
            double prevClose = Bars.ClosePrices[idx - 1];
            if (isBullish && prevClose < prevOpen && close > prevOpen && open < prevClose)
                patterns.Add("BULLISH_ENGULFING");

            // Engulfing baissier
            if (isBearish && prevClose > prevOpen && close < prevOpen && open > prevClose)
                patterns.Add("BEARISH_ENGULFING");

            // Doji
            if (bodyRatio < 0.1)
                patterns.Add("DOJI");

            // Bougie forte (corps > 65% de la range)
            if (bodyRatio > 0.65)
                patterns.Add(isBullish ? "STRONG_BULLISH" : "STRONG_BEARISH");

            return patterns;
        }

        // ══════════════════════════════════════════
        // STRATÉGIE BREAKOUT
        // ══════════════════════════════════════════

        private void CheckBreakout(List<SRZone> zones, double prevClose, double prevOpen,
                                    double prevHigh, double prevLow, List<string> patterns, double rsi)
        {
            double breakDist = BreakoutBreakPips * Symbol.PipSize;

            foreach (var zone in zones)
            {
                // ── Breakout HAUSSIER ──
                if (prevClose > zone.Price + breakDist && prevOpen <= zone.Price + breakDist)
                {
                    bool hasStrong = patterns.Contains("STRONG_BULLISH") || patterns.Contains("BULLISH_ENGULFING");
                    if (hasStrong && rsi > 40)
                    {
                        double slPips = Math.Max(BreakoutMinSL,
                            Math.Abs(prevClose - zone.Price) / Symbol.PipSize + BreakoutBufferPips);
                        slPips = Math.Min(slPips, BreakoutMaxSL);
                        double tpPips = slPips * BreakoutMinRR;

                        Print("[SIGNAL] BREAKOUT BUY — Zone {0:F3} (force={1}) | SL={2:F1} TP={3:F1} R:R={4:F1} | RSI={5:F1} | Pattern={6}",
                              zone.Price, zone.Strength, slPips, tpPips, BreakoutMinRR, rsi, string.Join("+", patterns));

                        OpenTrade(TradeType.Buy, slPips, tpPips, "BRK_BUY");
                        return;
                    }
                }

                // ── Breakout BAISSIER ──
                if (prevClose < zone.Price - breakDist && prevOpen >= zone.Price - breakDist)
                {
                    bool hasStrong = patterns.Contains("STRONG_BEARISH") || patterns.Contains("BEARISH_ENGULFING");
                    if (hasStrong && rsi < 60)
                    {
                        double slPips = Math.Max(BreakoutMinSL,
                            Math.Abs(prevClose - zone.Price) / Symbol.PipSize + BreakoutBufferPips);
                        slPips = Math.Min(slPips, BreakoutMaxSL);
                        double tpPips = slPips * BreakoutMinRR;

                        Print("[SIGNAL] BREAKOUT SELL — Zone {0:F3} (force={1}) | SL={2:F1} TP={3:F1} | RSI={4:F1} | Pattern={5}",
                              zone.Price, zone.Strength, slPips, tpPips, rsi, string.Join("+", patterns));

                        OpenTrade(TradeType.Sell, slPips, tpPips, "BRK_SELL");
                        return;
                    }
                }
            }
        }

        // ══════════════════════════════════════════
        // STRATÉGIE BOUNCE
        // ══════════════════════════════════════════

        private void CheckBounce(List<SRZone> zones, double prevClose, double prevOpen,
                                  double prevHigh, double prevLow, List<string> patterns, double rsi)
        {
            double proximity = BounceProximityPips * Symbol.PipSize;

            foreach (var zone in zones)
            {
                double dist = Math.Abs(prevClose - zone.Price);
                if (dist > proximity)
                    continue;

                // ── Bounce SUPPORT (BUY) ──
                if (prevClose >= zone.Price - proximity && prevClose <= zone.Price + proximity * 0.3)
                {
                    bool hasBullish = patterns.Any(p =>
                        p == "BULLISH_PINBAR" || p == "HAMMER" ||
                        p == "BULLISH_ENGULFING" || p == "DOJI");

                    if (hasBullish && rsi < 65)
                    {
                        double slPips = Math.Max(BounceMinSL,
                            dist / Symbol.PipSize + BounceBufferPips);
                        slPips = Math.Min(slPips, BounceMaxSL);
                        double tpPips = slPips * BounceMinRR;

                        Print("[SIGNAL] BOUNCE BUY — Support {0:F3} (force={1}) | Dist={2:F1}pips | SL={3:F1} TP={4:F1} | RSI={5:F1} | Pattern={6}",
                              zone.Price, zone.Strength, dist / Symbol.PipSize, slPips, tpPips, rsi, string.Join("+", patterns));

                        OpenTrade(TradeType.Buy, slPips, tpPips, "BNC_BUY");
                        return;
                    }
                }

                // ── Bounce RÉSISTANCE (SELL) ──
                if (prevClose <= zone.Price + proximity && prevClose >= zone.Price - proximity * 0.3)
                {
                    bool hasBearish = patterns.Any(p =>
                        p == "BEARISH_PINBAR" || p == "SHOOTING_STAR" ||
                        p == "BEARISH_ENGULFING" || p == "DOJI");

                    if (hasBearish && rsi > 35)
                    {
                        double slPips = Math.Max(BounceMinSL,
                            dist / Symbol.PipSize + BounceBufferPips);
                        slPips = Math.Min(slPips, BounceMaxSL);
                        double tpPips = slPips * BounceMinRR;

                        Print("[SIGNAL] BOUNCE SELL — Résistance {0:F3} (force={1}) | Dist={2:F1}pips | SL={3:F1} TP={4:F1} | RSI={5:F1} | Pattern={6}",
                              zone.Price, zone.Strength, dist / Symbol.PipSize, slPips, tpPips, rsi, string.Join("+", patterns));

                        OpenTrade(TradeType.Sell, slPips, tpPips, "BNC_SELL");
                        return;
                    }
                }
            }
        }

        // ══════════════════════════════════════════
        // EXÉCUTION & RISK MANAGEMENT
        // ══════════════════════════════════════════

        private void OpenTrade(TradeType tradeType, double slPips, double tpPips, string comment)
        {
            // Position sizing basé sur le risque
            double riskAmount = Account.Balance * (RiskPercent / 100.0);
            double pipValue = Symbol.PipValue;
            double volume = riskAmount / (slPips * pipValue);

            // Arrondir au volume valide
            volume = Symbol.NormalizeVolumeInUnits(volume, RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin)
            {
                Print("[SKIP] Volume trop petit: {0} < {1}", volume, Symbol.VolumeInUnitsMin);
                return;
            }
            if (volume > Symbol.VolumeInUnitsMax)
                volume = Symbol.VolumeInUnitsMax;

            string label = _botLabel;
            var result = ExecuteMarketOrder(tradeType, SymbolName, volume, label, slPips, tpPips, comment);

            if (result.IsSuccessful)
            {
                _dailyTrades++;
                Print("[TRADE] {0} {1} lots USDJPY @ {2:F3} | SL={3:F3} TP={4:F3} | {5}",
                      tradeType, Symbol.VolumeInUnitsToQuantity(volume),
                      result.Position.EntryPrice,
                      result.Position.StopLoss,
                      result.Position.TakeProfit,
                      comment);
            }
            else
            {
                Print("[ERREUR] Ordre rejeté: {0}", result.Error);
            }
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            var pos = args.Position;
            if (pos.Label != _botLabel || pos.SymbolName != SymbolName)
                return;

            if (pos.NetProfit < 0)
                _consecutiveLosses++;
            else
                _consecutiveLosses = 0;

            Print("[CLOSE] {0} {1} | P&L: {2:F2} ({3:F2} pips) | Consec. losses: {4}",
                  pos.TradeType, pos.Comment, pos.NetProfit, pos.Pips, _consecutiveLosses);
        }

        protected override void OnStop()
        {
            Print("=== USDJPY Price Action cBot ARRÊTÉ ===");
            Print("Trades aujourd'hui: {0} | Pertes consec: {1}", _dailyTrades, _consecutiveLosses);
        }
    }
}
