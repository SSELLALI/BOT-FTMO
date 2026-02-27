// ============================================================
// ASIAN RANGE BREAKOUT cBot - CONFIG E (ATR Stops)
// ============================================================
// Paires: GBPJPY et USDJPY (M15)
// Session: 07h-11h Londres
// Risque: 0.5% par trade
// SL = 1x ATR(14), TP = 2x SL
// ============================================================

using System;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None, AddIndicators = true)]
    public class AsianBreakout_ATR : Robot
    {
        // ── PARAMETRES (ne pas modifier sauf si vous savez ce que vous faites) ──

        [Parameter("Risque par trade (%)", DefaultValue = 0.5, MinValue = 0.1, MaxValue = 2.0, Step = 0.1)]
        public double RiskPercent { get; set; }

        [Parameter("RSI Periode", DefaultValue = 14)]
        public int RsiPeriod { get; set; }

        [Parameter("ATR Periode", DefaultValue = 14)]
        public int AtrPeriod { get; set; }

        [Parameter("Body minimum (%)", DefaultValue = 60, MinValue = 40, MaxValue = 80)]
        public int MinBodyPercent { get; set; }

        [Parameter("RSI Long Min", DefaultValue = 55)]
        public double RsiLongMin { get; set; }

        [Parameter("RSI Long Max", DefaultValue = 70)]
        public double RsiLongMax { get; set; }

        [Parameter("RSI Short Min", DefaultValue = 30)]
        public double RsiShortMin { get; set; }

        [Parameter("RSI Short Max", DefaultValue = 45)]
        public double RsiShortMax { get; set; }

        [Parameter("Asian Range Min (pips)", DefaultValue = 30)]
        public double AsianRangeMinPips { get; set; }

        [Parameter("Asian Range Max (pips)", DefaultValue = 90)]
        public double AsianRangeMaxPips { get; set; }

        [Parameter("SL Min (pips)", DefaultValue = 8)]
        public double SlMinPips { get; set; }

        [Parameter("SL Max (pips)", DefaultValue = 40)]
        public double SlMaxPips { get; set; }

        [Parameter("Session Debut (heure Londres)", DefaultValue = 7)]
        public int SessionStart { get; set; }

        [Parameter("Session Fin (heure Londres)", DefaultValue = 11)]
        public int SessionEnd { get; set; }

        // ── VARIABLES INTERNES ──

        private RelativeStrengthIndex _rsi;
        private AverageTrueRange _atr;
        private TimeZoneInfo _londonTz;
        private string _label;

        private double _asianHigh;
        private double _asianLow;
        private bool _asianRangeReady;
        private bool _tradeTakenToday;
        private DateTime _lastTradeDate;

        protected override void OnStart()
        {
            // Indicateurs
            _rsi = Indicators.RelativeStrengthIndex(Bars.ClosePrices, RsiPeriod);
            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Exponential);

            // Fuseau horaire Londres (gere automatiquement BST/GMT)
            _londonTz = TimeZoneInfo.FindSystemTimeZoneById("GMT Standard Time");

            // Label unique pour identifier les trades de ce bot
            _label = "AsianBK_" + SymbolName;

            _asianRangeReady = false;
            _tradeTakenToday = false;
            _lastTradeDate = DateTime.MinValue;

            Print("=== Asian Breakout ATR demarré sur {0} ===", SymbolName);
            Print("Risque: {0}% | SL: ATR({1}) | TP: 2x SL", RiskPercent, AtrPeriod);
            Print("Session: {0}h-{1}h Londres | Asian Range: {2}-{3} pips",
                  SessionStart, SessionEnd, AsianRangeMinPips, AsianRangeMaxPips);
        }

        protected override void OnBar()
        {
            // Convertir l'heure du serveur en heure de Londres
            DateTime londonTime = TimeZoneInfo.ConvertTimeFromUtc(Server.TimeInUtc, _londonTz);
            int londonHour = londonTime.Hour;
            DateTime londonDate = londonTime.Date;

            // ── RESET JOURNALIER ──
            if (londonDate != _lastTradeDate)
            {
                _tradeTakenToday = false;
                _asianRangeReady = false;
                _asianHigh = double.MinValue;
                _asianLow = double.MaxValue;
            }
            _lastTradeDate = londonDate;

            // ── PHASE 1: CALCULER LE RANGE ASIATIQUE (00h-06h59 Londres) ──
            if (londonHour >= 0 && londonHour < 7)
            {
                // Mettre a jour le range avec la bougie qui vient de fermer
                int lastIndex = Bars.Count - 2; // bougie precedente (fermee)
                if (lastIndex >= 0)
                {
                    double high = Bars.HighPrices[lastIndex];
                    double low = Bars.LowPrices[lastIndex];

                    if (high > _asianHigh) _asianHigh = high;
                    if (low < _asianLow) _asianLow = low;
                }
                return;
            }

            // ── PHASE 2: VALIDER LE RANGE A 07h ──
            if (londonHour == SessionStart && !_asianRangeReady)
            {
                // Inclure la derniere bougie avant 07h
                int lastIndex = Bars.Count - 2;
                if (lastIndex >= 0)
                {
                    double high = Bars.HighPrices[lastIndex];
                    double low = Bars.LowPrices[lastIndex];
                    if (high > _asianHigh) _asianHigh = high;
                    if (low < _asianLow) _asianLow = low;
                }

                double rangePips = (_asianHigh - _asianLow) / Symbol.PipSize;

                if (_asianHigh == double.MinValue || _asianLow == double.MaxValue)
                {
                    Print("{0} Pas de donnees asiatiques", londonTime);
                    return;
                }

                if (rangePips < AsianRangeMinPips)
                {
                    Print("{0} Range asiatique trop petit: {1:F1} pips < {2}",
                          londonTime, rangePips, AsianRangeMinPips);
                    return;
                }

                if (rangePips > AsianRangeMaxPips)
                {
                    Print("{0} Range asiatique trop grand: {1:F1} pips > {2}",
                          londonTime, rangePips, AsianRangeMaxPips);
                    return;
                }

                _asianRangeReady = true;
                Print("{0} Range asiatique OK: H={1:F3} L={2:F3} ({3:F1} pips)",
                      londonTime, _asianHigh, _asianLow, rangePips);
            }

            // ── PHASE 3: FERMETURE FORCEE A 11h ──
            if (londonHour >= SessionEnd)
            {
                CloseAllPositions();
                return;
            }

            // ── PHASE 4: CHERCHER UN SIGNAL (07h-10h59) ──
            if (!_asianRangeReady || _tradeTakenToday)
                return;

            if (londonHour < SessionStart || londonHour >= SessionEnd)
                return;

            // Analyser la bougie qui vient de fermer
            int idx = Bars.Count - 2;
            if (idx < 0) return;

            double open = Bars.OpenPrices[idx];
            double high_c = Bars.HighPrices[idx];
            double low_c = Bars.LowPrices[idx];
            double close = Bars.ClosePrices[idx];
            double rsiValue = _rsi.Result[idx];
            double atrValue = _atr.Result[idx];

            // Verifier que les indicateurs sont prets
            if (double.IsNaN(rsiValue) || double.IsNaN(atrValue) || atrValue <= 0)
                return;

            // Verifier le body ratio
            double body = Math.Abs(close - open);
            double totalRange = high_c - low_c;
            if (totalRange <= 0) return;

            double bodyRatio = (body / totalRange) * 100;
            if (bodyRatio < MinBodyPercent) return;

            // Determiner la direction
            TradeType? direction = null;

            // LONG: close au-dessus du range asiatique, bougie haussiere, RSI OK
            if (close > _asianHigh && close > open)
            {
                if (rsiValue > RsiLongMin && rsiValue <= RsiLongMax)
                    direction = TradeType.Buy;
            }
            // SHORT: close en-dessous du range asiatique, bougie baissiere, RSI OK
            else if (close < _asianLow && close < open)
            {
                if (rsiValue >= RsiShortMin && rsiValue < RsiShortMax)
                    direction = TradeType.Sell;
            }

            if (direction == null) return;

            // ── PHASE 5: CALCULER SL/TP ET PASSER L'ORDRE ──
            double atrPips = atrValue / Symbol.PipSize;

            // Clamp le SL entre min et max
            double slPips = Math.Max(SlMinPips, Math.Min(SlMaxPips, Math.Round(atrPips)));
            double tpPips = slPips * 2; // RR 1:2

            // Calculer la taille de position (0.5% de risque)
            double riskAmount = Account.Balance * (RiskPercent / 100.0);
            double slInPrice = slPips * Symbol.PipSize;
            double pipValue = Symbol.PipValue;

            // Volume = risque / (SL en pips * valeur du pip par lot)
            double volumeInUnits = riskAmount / (slPips * pipValue);
            volumeInUnits = Symbol.NormalizeVolumeInUnits(volumeInUnits, RoundingMode.Down);

            if (volumeInUnits < Symbol.VolumeInUnitsMin)
            {
                Print("Volume trop petit: {0} < min {1}", volumeInUnits, Symbol.VolumeInUnitsMin);
                return;
            }

            // Passer l'ordre
            string dirStr = direction == TradeType.Buy ? "LONG" : "SHORT";
            Print("{0} >>> SIGNAL {1} | Close={2:F3} | RSI={3:F1} | ATR={4:F1}p | SL={5}p TP={6}p | Vol={7}",
                  londonTime, dirStr, close, rsiValue, atrPips, slPips, tpPips, volumeInUnits);

            var result = ExecuteMarketOrder(
                direction.Value,
                SymbolName,
                volumeInUnits,
                _label,
                slPips,
                tpPips,
                "Asian BK " + dirStr
            );

            if (result.IsSuccessful)
            {
                _tradeTakenToday = true;
                Print(">>> Trade ouvert: {0} {1} @ {2:F3} | SL={3}p TP={4}p",
                      dirStr, SymbolName, result.Position.EntryPrice, slPips, tpPips);
            }
            else
            {
                Print(">>> ERREUR: {0}", result.Error);
            }
        }

        private void CloseAllPositions()
        {
            var positions = Positions.FindAll(_label, SymbolName);
            foreach (var pos in positions)
            {
                var result = ClosePosition(pos);
                if (result.IsSuccessful)
                {
                    Print(">>> Position fermee (fin session): {0} P&L={1:F2}",
                          pos.TradeType, pos.NetProfit);
                }
            }
        }

        protected override void OnStop()
        {
            // Fermer toutes les positions du bot a l'arret
            CloseAllPositions();
            Print("=== Asian Breakout ATR arrete ===");
        }
    }
}
