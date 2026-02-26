// ============================================================================
// GBPJPY Breakout-Pullback-Rejection cBot v2
// Validated via Walk-Forward Optimization
// Train: +15.16% (PF=3.45) | OOS: +7.74% (PF=3.10)
// Parameters: SL=5, body=0.45, vol=0.3, RR=1.5, prox=1.0, timeout=25h
// ============================================================================

using System;
using System.Collections.Generic;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None, TimeZone = TimeZones.UTC)]
    public class GBPJPY_BreakoutPullback_cBot : Robot
    {
        // ── Strategy Parameters (from optimization) ──
        [Parameter("Risk Per Trade (%)", DefaultValue = 1.0, MinValue = 0.1, MaxValue = 3.0)]
        public double RiskPercent { get; set; }

        [Parameter("Min R:R", DefaultValue = 1.5, MinValue = 1.0, MaxValue = 4.0)]
        public double MinRR { get; set; }

        [Parameter("Swing Lookback (H1 candles)", DefaultValue = 5, MinValue = 3, MaxValue = 15)]
        public int SwingLookback { get; set; }

        [Parameter("Breakout Body Ratio", DefaultValue = 0.45, MinValue = 0.2, MaxValue = 0.8)]
        public double BreakoutBodyRatio { get; set; }

        [Parameter("Breakout Size Multiplier", DefaultValue = 0.3, MinValue = 0.1, MaxValue = 1.5)]
        public double BreakoutSizeMult { get; set; }

        [Parameter("Max Pullback Depth", DefaultValue = 1.2, MinValue = 0.5, MaxValue = 3.0)]
        public double MaxPullbackDepth { get; set; }

        [Parameter("Proximity Factor", DefaultValue = 1.0, MinValue = 0.3, MaxValue = 2.0)]
        public double ProximityFactor { get; set; }

        [Parameter("Stale Timeout (H1 candles)", DefaultValue = 25, MinValue = 10, MaxValue = 60)]
        public int StaleTimeout { get; set; }

        [Parameter("SL Buffer (pips)", DefaultValue = 5, MinValue = 1, MaxValue = 20)]
        public double SlBufferPips { get; set; }

        [Parameter("Min SL (pips)", DefaultValue = 5, MinValue = 1, MaxValue = 30)]
        public double MinSlPips { get; set; }

        [Parameter("Max SL (pips)", DefaultValue = 100, MinValue = 30, MaxValue = 200)]
        public double MaxSlPips { get; set; }

        [Parameter("BE Trigger R:R", DefaultValue = 1.0, MinValue = 0, MaxValue = 3.0)]
        public double BeTriggerRR { get; set; }

        [Parameter("Max Daily Trades", DefaultValue = 4, MinValue = 1, MaxValue = 10)]
        public int MaxDailyTrades { get; set; }

        [Parameter("Max Consec. Losses", DefaultValue = 4, MinValue = 2, MaxValue = 8)]
        public int MaxConsecLosses { get; set; }

        [Parameter("RSI Long Min", DefaultValue = 35)]
        public int RsiLongMin { get; set; }

        [Parameter("RSI Long Max", DefaultValue = 78)]
        public int RsiLongMax { get; set; }

        [Parameter("RSI Short Min", DefaultValue = 22)]
        public int RsiShortMin { get; set; }

        [Parameter("RSI Short Max", DefaultValue = 65)]
        public int RsiShortMax { get; set; }

        [Parameter("FTMO Max Daily Loss (%)", DefaultValue = 4.5)]
        public double FtmoMaxDailyLoss { get; set; }

        [Parameter("FTMO Max Total DD (%)", DefaultValue = 8.0)]
        public double FtmoMaxTotalDD { get; set; }

        // ── Internal State ──
        private MarketSeries h1Series;
        private RelativeStrengthIndex rsi;
        private const string BotLabel = "GBPJPY_BP_v2";

        private List<BreakoutSetup> activeBreakouts = new List<BreakoutSetup>();
        private HashSet<string> detectedKeys = new HashSet<string>();
        private int dailyTradeCount;
        private DateTime lastTradeDate;
        private int consecutiveLosses;
        private double peakBalance;
        private double dayStartBalance;

        protected override void OnStart()
        {
            h1Series = MarketData.GetSeries(TimeFrame.Hour);
            rsi = Indicators.RelativeStrengthIndex(Bars.ClosePrices, 14);
            peakBalance = Account.Balance;
            dayStartBalance = Account.Balance;
            lastTradeDate = Server.Time.Date;
            dailyTradeCount = 0;
            consecutiveLosses = 0;

            Positions.Closed += OnPositionClosed;

            Print("=== GBPJPY Breakout-Pullback cBot v2 Started ===");
            Print("Risk: {0}% | RR: {1} | SL Buffer: {2} pips", RiskPercent, MinRR, SlBufferPips);
            Print("Swing: {0} | Body: {1} | Vol: {2}", SwingLookback, BreakoutBodyRatio, BreakoutSizeMult);
        }

        protected override void OnBar()
        {
            var now = Server.Time;

            // ── Reset daily counters ──
            if (now.Date != lastTradeDate)
            {
                lastTradeDate = now.Date;
                dailyTradeCount = 0;
                dayStartBalance = Account.Balance;
            }

            // ── FTMO Safety Checks ──
            double dailyLossPct = (dayStartBalance - Account.Balance) / dayStartBalance * 100;
            if (dailyLossPct > FtmoMaxDailyLoss * 0.9)
            {
                Print("FTMO daily loss limit approaching: {0:F2}%", dailyLossPct);
                return;
            }

            peakBalance = Math.Max(peakBalance, Account.Balance);
            double totalDD = (peakBalance - Account.Balance) / peakBalance * 100;
            if (totalDD > FtmoMaxTotalDD * 0.9)
            {
                Print("FTMO total DD limit approaching: {0:F2}%", totalDD);
                return;
            }

            // ── Manage Breakeven for open positions ──
            ManageBreakeven();

            // ── Skip if already in a position ──
            var myPositions = Positions.FindAll(BotLabel, SymbolName);
            if (myPositions.Length > 0)
                return;

            // ── Session Filter (Rule 2): London 07-11:30, Gap 11:30-13:30, NY 13:30-16:30 UTC ──
            int minutes = now.Hour * 60 + now.Minute;
            bool inLondon = minutes >= 420 && minutes <= 690;
            bool inGap = minutes > 690 && minutes < 810;
            bool inNY = minutes >= 810 && minutes <= 990;
            if (!(inLondon || inGap || inNY))
                return;
            if (now.DayOfWeek == DayOfWeek.Saturday || now.DayOfWeek == DayOfWeek.Sunday)
                return;

            // ── Prune stale breakouts ──
            int currentH1Index = h1Series.Close.Count - 1;
            activeBreakouts.RemoveAll(b => (currentH1Index - b.H1Index) > StaleTimeout || b.Traded);

            // ── H1 Structure Analysis (Rules 3, 4) ──
            var swings = DetectSwings(currentH1Index);
            string bias = DetermineBias(swings);
            if (bias == null)
                return;

            // ── Key Levels (multiple) ──
            var resistances = new List<double>();
            var supports = new List<double>();
            for (int i = swings.Count - 1; i >= 0; i--)
            {
                var sw = swings[i];
                if ((sw.Type == "HH" || sw.Type == "LH") && resistances.Count < 3)
                {
                    if (!resistances.Any(r => Math.Abs(r - sw.Price) < 0.10))
                        resistances.Add(sw.Price);
                }
                if ((sw.Type == "HL" || sw.Type == "LL") && supports.Count < 3)
                {
                    if (!supports.Any(s => Math.Abs(s - sw.Price) < 0.10))
                        supports.Add(sw.Price);
                }
            }

            // Add previous day high/low
            AddDayLevels(currentH1Index, resistances, supports);

            // ── Breakout Detection (Rule 4, 5) — scan recent H1 candles ──
            int scanBack = Math.Min(12, currentH1Index);
            for (int si = currentH1Index; si > currentH1Index - scanBack && si > 1; si--)
            {
                double h1Close = h1Series.Close[si];
                double h1PrevClose = h1Series.Close[si - 1];
                double h1High = h1Series.High[si];
                double h1Low = h1Series.Low[si];
                double h1Open = h1Series.Open[si];
                double candleRange = h1High - h1Low;
                double candleBody = Math.Abs(h1Close - h1Open);
                double bodyRatio = candleRange > 0 ? candleBody / candleRange : 0;

                // Average range of last 10 H1 candles
                double avgRange = 0;
                int count = 0;
                for (int k = Math.Max(1, si - 10); k < si; k++)
                {
                    avgRange += h1Series.High[k] - h1Series.Low[k];
                    count++;
                }
                avgRange = count > 0 ? avgRange / count : candleRange;

                // Volatility + body filter (Rule 5)
                if (candleRange <= avgRange * BreakoutSizeMult || bodyRatio < BreakoutBodyRatio)
                    continue;

                if (bias == "BULLISH")
                {
                    foreach (var keyR in resistances)
                    {
                        string bk = string.Format("B_{0:F2}_{1}", keyR, si);
                        if (!detectedKeys.Contains(bk) && h1Close > keyR && h1PrevClose <= keyR)
                        {
                            activeBreakouts.Add(new BreakoutSetup
                            {
                                H1Index = si,
                                Level = keyR,
                                Direction = TradeType.Buy,
                                CandleRange = candleRange,
                                PullbackLow = Bars.LowPrices.Last(0),
                                PullbackHigh = Bars.HighPrices.Last(0),
                                Swings = new List<SwingPoint>(swings),
                                Traded = false
                            });
                            detectedKeys.Add(bk);
                        }
                    }
                }

                if (bias == "BEARISH")
                {
                    foreach (var keyS in supports)
                    {
                        string bk = string.Format("S_{0:F2}_{1}", keyS, si);
                        if (!detectedKeys.Contains(bk) && h1Close < keyS && h1PrevClose >= keyS)
                        {
                            activeBreakouts.Add(new BreakoutSetup
                            {
                                H1Index = si,
                                Level = keyS,
                                Direction = TradeType.Sell,
                                CandleRange = candleRange,
                                PullbackLow = Bars.LowPrices.Last(0),
                                PullbackHigh = Bars.HighPrices.Last(0),
                                Swings = new List<SwingPoint>(swings),
                                Traded = false
                            });
                            detectedKeys.Add(bk);
                        }
                    }
                }
            }

            if (activeBreakouts.Count == 0)
                return;

            // ── Daily/Consecutive limits ──
            if (dailyTradeCount >= MaxDailyTrades)
                return;
            if (consecutiveLosses >= MaxConsecLosses)
                return;

            // ── Check all active breakouts for entry ──
            double currentClose = Bars.ClosePrices.Last(0);
            double currentHigh = Bars.HighPrices.Last(0);
            double currentLow = Bars.LowPrices.Last(0);
            double currentOpen = Bars.OpenPrices.Last(0);
            double rsiValue = rsi.Result.Last(0);
            double rsiPrev = rsi.Result.Last(1);

            foreach (var bo in activeBreakouts)
            {
                if (bo.Traded)
                    continue;

                // Update pullback extremes
                bo.PullbackLow = Math.Min(bo.PullbackLow, currentLow);
                bo.PullbackHigh = Math.Max(bo.PullbackHigh, currentHigh);

                // ── Pullback Conditions (Rule 6) ──
                if (bo.Direction == TradeType.Buy)
                {
                    if (currentClose > bo.Level + bo.CandleRange)
                        continue; // Not pulled back yet

                    // Structure check: price must not break last HL
                    var lastHL = bo.Swings.LastOrDefault(s => s.Type == "HL");
                    if (lastHL != null && currentLow < lastHL.Price)
                    {
                        bo.Traded = true; // Cancel
                        continue;
                    }

                    double depth = bo.CandleRange > 0 ? (bo.PullbackHigh - currentLow) / bo.CandleRange : 999;
                    if (depth > MaxPullbackDepth)
                        continue;

                    if (Math.Abs(currentClose - bo.Level) > bo.CandleRange * ProximityFactor)
                        continue;
                }
                else // SELL
                {
                    if (currentClose < bo.Level - bo.CandleRange)
                        continue;

                    var lastLH = bo.Swings.LastOrDefault(s => s.Type == "LH");
                    if (lastLH != null && currentHigh > lastLH.Price)
                    {
                        bo.Traded = true;
                        continue;
                    }

                    double depth = bo.CandleRange > 0 ? (currentHigh - bo.PullbackLow) / bo.CandleRange : 999;
                    if (depth > MaxPullbackDepth)
                        continue;

                    if (Math.Abs(currentClose - bo.Level) > bo.CandleRange * ProximityFactor)
                        continue;
                }

                // ── Rejection Candle (Rule 7) ──
                if (!HasRejectionPattern(bo.Direction, currentOpen, currentClose, currentHigh, currentLow))
                    continue;

                // ── RSI Confirmation (Rule 8) ──
                if (bo.Direction == TradeType.Buy)
                {
                    if (rsiValue < RsiLongMin || rsiValue > RsiLongMax || rsiValue <= rsiPrev)
                        continue;
                }
                else
                {
                    if (rsiValue < RsiShortMin || rsiValue > RsiShortMax || rsiValue >= rsiPrev)
                        continue;
                }

                // ── Spread Check (Rule 13) ──
                double spreadPips = Symbol.Spread / Symbol.PipSize;
                if (spreadPips > 5.0)
                {
                    Print("Spread too wide: {0:F1} pips", spreadPips);
                    continue;
                }

                // ── Calculate SL/TP (Rules 10, 11) ──
                double entryPrice, sl, tp, slPips;

                if (bo.Direction == TradeType.Buy)
                {
                    entryPrice = Symbol.Ask;
                    sl = bo.PullbackLow - SlBufferPips * Symbol.PipSize;
                    slPips = (entryPrice - sl) / Symbol.PipSize;

                    if (slPips < MinSlPips || slPips > MaxSlPips)
                        continue;

                    // Structural TP: look for next swing high
                    double structuralTP = FindStructuralTP(bo.Swings, entryPrice, TradeType.Buy);
                    if (structuralTP > 0 && (structuralTP - entryPrice) / Symbol.PipSize / slPips >= MinRR)
                        tp = structuralTP;
                    else
                        tp = entryPrice + slPips * MinRR * Symbol.PipSize;
                }
                else
                {
                    entryPrice = Symbol.Bid;
                    sl = bo.PullbackHigh + SlBufferPips * Symbol.PipSize;
                    slPips = (sl - entryPrice) / Symbol.PipSize;

                    if (slPips < MinSlPips || slPips > MaxSlPips)
                        continue;

                    double structuralTP = FindStructuralTP(bo.Swings, entryPrice, TradeType.Sell);
                    if (structuralTP > 0 && (entryPrice - structuralTP) / Symbol.PipSize / slPips >= MinRR)
                        tp = structuralTP;
                    else
                        tp = entryPrice - slPips * MinRR * Symbol.PipSize;
                }

                // ── Position Sizing (Rule 9: 1% risk) ──
                double riskAmount = Account.Balance * (RiskPercent / 100.0);
                double pipValue = Symbol.PipValue;
                double volume = riskAmount / (slPips * pipValue);
                volume = Symbol.NormalizeVolumeInUnits(volume, RoundingMode.Down);
                volume = Math.Max(volume, Symbol.VolumeInUnitsMin);
                volume = Math.Min(volume, Symbol.VolumeInUnitsMax);

                // ── Execute Trade ──
                var result = ExecuteMarketOrder(
                    bo.Direction, SymbolName, volume,
                    BotLabel, slPips, null);

                if (result.IsSuccessful)
                {
                    var pos = result.Position;
                    if (bo.Direction == TradeType.Buy)
                        ModifyPosition(pos, sl, tp);
                    else
                        ModifyPosition(pos, sl, tp);

                    bo.Traded = true;
                    dailyTradeCount++;

                    Print("TRADE: {0} | Entry: {1:F3} | SL: {2:F3} ({3:F1} pips) | TP: {4:F3} | Vol: {5}",
                        bo.Direction, entryPrice, sl, slPips, tp, volume);
                }
                else
                {
                    Print("Order FAILED: {0}", result.Error);
                }

                break; // One trade per bar
            }
        }

        // ── Breakeven Management (Rule 12) ──
        private void ManageBreakeven()
        {
            foreach (var pos in Positions.FindAll(BotLabel, SymbolName))
            {
                if (BeTriggerRR <= 0)
                    continue;

                double entryPrice = pos.EntryPrice;
                double currentSL = pos.StopLoss ?? 0;
                double slDistance = Math.Abs(entryPrice - currentSL);
                double beTarget = slDistance * BeTriggerRR;

                if (pos.TradeType == TradeType.Buy)
                {
                    if (currentSL < entryPrice && Symbol.Bid >= entryPrice + beTarget)
                    {
                        double newSL = entryPrice + Symbol.Spread / 2;
                        ModifyPosition(pos, newSL, pos.TakeProfit);
                        Print("BE moved for BUY: new SL = {0:F3}", newSL);
                    }
                }
                else
                {
                    if (currentSL > entryPrice && Symbol.Ask <= entryPrice - beTarget)
                    {
                        double newSL = entryPrice - Symbol.Spread / 2;
                        ModifyPosition(pos, newSL, pos.TakeProfit);
                        Print("BE moved for SELL: new SL = {0:F3}", newSL);
                    }
                }
            }
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            var pos = args.Position;
            if (pos.Label != BotLabel || pos.SymbolName != SymbolName)
                return;

            if (pos.NetProfit < 0)
                consecutiveLosses++;
            else
                consecutiveLosses = 0;

            Print("CLOSED: {0} | PnL: {1:F2} | Consec Losses: {2}",
                pos.TradeType, pos.NetProfit, consecutiveLosses);
        }

        // ── Swing Detection (Rule 3) ──
        private List<SwingPoint> DetectSwings(int upToIndex)
        {
            var rawHighs = new List<(int idx, double price)>();
            var rawLows = new List<(int idx, double price)>();
            int start = Math.Max(SwingLookback, upToIndex - 200);

            for (int i = start; i <= upToIndex - SwingLookback; i++)
            {
                bool isSwingHigh = true;
                bool isSwingLow = true;
                double high_i = h1Series.High[i];
                double low_i = h1Series.Low[i];

                for (int j = Math.Max(0, i - SwingLookback); j <= Math.Min(h1Series.Close.Count - 1, i + SwingLookback); j++)
                {
                    if (j == i) continue;
                    if (h1Series.High[j] > high_i) isSwingHigh = false;
                    if (h1Series.Low[j] < low_i) isSwingLow = false;
                    if (!isSwingHigh && !isSwingLow) break;
                }

                if (isSwingHigh)
                    rawHighs.Add((i, high_i));
                if (isSwingLow)
                    rawLows.Add((i, low_i));
            }

            // Keep last 10
            if (rawHighs.Count > 10) rawHighs = rawHighs.Skip(rawHighs.Count - 10).ToList();
            if (rawLows.Count > 10) rawLows = rawLows.Skip(rawLows.Count - 10).ToList();

            var swings = new List<SwingPoint>();

            for (int j = 1; j < rawHighs.Count; j++)
            {
                string type = rawHighs[j].price > rawHighs[j - 1].price ? "HH" : "LH";
                swings.Add(new SwingPoint { Price = rawHighs[j].price, Index = rawHighs[j].idx, Type = type });
            }

            for (int j = 1; j < rawLows.Count; j++)
            {
                string type = rawLows[j].price > rawLows[j - 1].price ? "HL" : "LL";
                swings.Add(new SwingPoint { Price = rawLows[j].price, Index = rawLows[j].idx, Type = type });
            }

            swings.Sort((a, b) => a.Index.CompareTo(b.Index));
            return swings;
        }

        // ── Bias Detection (Rule 3) ──
        private string DetermineBias(List<SwingPoint> swings)
        {
            if (swings.Count < 4)
                return null;

            var recent = swings.Skip(swings.Count - 4).ToList();
            var types = recent.Select(s => s.Type).ToList();

            if (types.Contains("HH") && types.Contains("HL"))
                return "BULLISH";
            if (types.Contains("LL") && types.Contains("LH"))
                return "BEARISH";
            return null;
        }

        // ── Rejection Pattern Detection (Rule 7) ──
        private bool HasRejectionPattern(TradeType direction, double open, double close, double high, double low)
        {
            double body = Math.Abs(close - open);
            double range = high - low;
            if (range <= 0) return false;
            double bodyRatio = body / range;
            double upperWick = high - Math.Max(open, close);
            double lowerWick = Math.Min(open, close) - low;
            bool isBull = close > open;
            bool isBear = close < open;

            if (direction == TradeType.Buy)
            {
                if (!isBull) return false;

                // Bullish pinbar
                if (bodyRatio < 0.35 && lowerWick > body * 2.0 && upperWick < body * 1.0)
                    return true;
                // Hammer
                if (lowerWick > body * 2.0 && upperWick < body * 0.5)
                    return true;
                // Strong bullish impulse
                if (bodyRatio > 0.50)
                    return true;
                // Close near high
                if ((close - low) / range > 0.70)
                    return true;
            }
            else
            {
                if (!isBear) return false;

                // Bearish pinbar
                if (bodyRatio < 0.35 && upperWick > body * 2.0 && lowerWick < body * 1.0)
                    return true;
                // Shooting star
                if (upperWick > body * 2.0 && lowerWick < body * 0.5)
                    return true;
                // Strong bearish impulse
                if (bodyRatio > 0.50)
                    return true;
                // Close near low
                if ((high - close) / range > 0.70)
                    return true;
            }

            return false;
        }

        // ── Structural TP (Rule 11) ──
        private double FindStructuralTP(List<SwingPoint> swings, double entry, TradeType direction)
        {
            if (direction == TradeType.Buy)
            {
                foreach (var s in swings)
                {
                    if ((s.Type == "HH" || s.Type == "LH") && s.Price > entry + 10 * Symbol.PipSize)
                        return s.Price;
                }
            }
            else
            {
                for (int i = swings.Count - 1; i >= 0; i--)
                {
                    var s = swings[i];
                    if ((s.Type == "HL" || s.Type == "LL") && s.Price < entry - 10 * Symbol.PipSize)
                        return s.Price;
                }
            }
            return 0;
        }

        // ── Previous Day High/Low ──
        private void AddDayLevels(int currentH1Index, List<double> resistances, List<double> supports)
        {
            DateTime currentDate = h1Series.OpenTime[currentH1Index].Date;
            double dayHigh = double.MinValue;
            double dayLow = double.MaxValue;
            bool foundPrevDay = false;

            for (int i = currentH1Index - 1; i >= Math.Max(0, currentH1Index - 100); i--)
            {
                DateTime d = h1Series.OpenTime[i].Date;
                if (d == currentDate)
                    continue;

                if (!foundPrevDay)
                    foundPrevDay = true;

                if (foundPrevDay && d != h1Series.OpenTime[Math.Min(i + 1, currentH1Index)].Date
                    && d != currentDate)
                {
                    // We've gone past the previous day
                    break;
                }

                dayHigh = Math.Max(dayHigh, h1Series.High[i]);
                dayLow = Math.Min(dayLow, h1Series.Low[i]);
            }

            if (dayHigh > double.MinValue && !resistances.Any(r => Math.Abs(r - dayHigh) < 0.10))
                resistances.Add(dayHigh);
            if (dayLow < double.MaxValue && !supports.Any(s => Math.Abs(s - dayLow) < 0.10))
                supports.Add(dayLow);
        }

        protected override void OnStop()
        {
            Print("=== GBPJPY Breakout-Pullback cBot Stopped ===");
            Print("Active breakouts tracked: {0}", activeBreakouts.Count);
        }

        // ── Data Classes ──
        private class BreakoutSetup
        {
            public int H1Index;
            public double Level;
            public TradeType Direction;
            public double CandleRange;
            public double PullbackLow;
            public double PullbackHigh;
            public List<SwingPoint> Swings;
            public bool Traded;
        }

        private class SwingPoint
        {
            public double Price;
            public int Index;
            public string Type; // HH, HL, LH, LL
        }
    }
}
