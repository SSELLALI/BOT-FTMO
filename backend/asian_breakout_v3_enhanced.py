"""
Asian Range Breakout v3 - Enhanced Strategy
=============================================
Améliorations:
1. Daily SMA 20 trend filter (LONG only above, SHORT only below)
2. Daily ATR filter (trade only if prev ATR > 20-day avg ATR)
3. Volatility-based stops (SL = 1x ATR M15, TP = 2x SL)
4. Breakout margin (+5 pips beyond Asian range)
5. No Monday trading

Multi-pair: GBPJPY, GBPUSD, USDJPY, EURUSD
NO optimization - fixed params for stability testing
"""

import csv
import json
import random
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from copy import deepcopy

INITIAL_BALANCE = 100_000
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS_PCT = 0.045
MAX_TOTAL_DD_PCT = 0.08

PARAMS = {
    'min_body_ratio': 0.60,
    'rsi_long_min': 55,
    'rsi_long_max': 70,
    'rsi_short_min': 30,
    'rsi_short_max': 45,
    'min_asian_range': 30,   # pips
    'max_asian_range': 90,   # pips
    'session_start': 7,
    'session_end': 11,
    'breakout_margin': 5,    # NEW: pips beyond Asian range
    'atr_m15_period': 14,    # NEW: M15 ATR period
    'daily_sma_period': 20,  # NEW: Daily SMA period
    'daily_atr_period': 20,  # NEW: Daily ATR period
    'spread_pips': 2.0,
    'min_sl_pips': 8,        # minimum SL floor
    'max_sl_pips': 40,       # maximum SL cap
}

PAIRS = {
    'GBPJPY': {'pip': 0.01,   'file': '/app/backend/historical_data/GBPJPY_M15_EXTENDED.csv'},
    'GBPUSD': {'pip': 0.0001, 'file': '/app/backend/historical_data/GBPUSD_M15_IC.csv'},
    'USDJPY': {'pip': 0.01,   'file': '/app/backend/historical_data/USDJPY_M15_TV.csv'},
    'EURUSD': {'pip': 0.0001, 'file': '/app/backend/historical_data/EURUSD_M15_TV.csv'},
}


def get_london_offset(dt_utc):
    year = dt_utc.year
    d = datetime(year, 3, 31, tzinfo=timezone.utc)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    bst_start = d.replace(hour=1)
    d = datetime(year, 10, 31, tzinfo=timezone.utc)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    bst_end = d.replace(hour=1)
    return 1 if bst_start <= dt_utc < bst_end else 0


def to_london(ts):
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt_utc + timedelta(hours=get_london_offset(dt_utc))


def load_m15(filepath):
    candles = []
    with open(filepath) as f:
        for row in csv.DictReader(f):
            rsi_str = row.get('RSI', '').strip()
            candles.append({
                'ts': int(row['time']),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'rsi': float(rsi_str) if rsi_str else None,
            })
    return candles


def compute_m15_atr(candles, period=14):
    """Compute ATR for each M15 candle (rolling)."""
    for i, c in enumerate(candles):
        tr = c['high'] - c['low']
        if i > 0:
            prev_close = candles[i - 1]['close']
            tr = max(tr, abs(c['high'] - prev_close), abs(c['low'] - prev_close))
        c['tr'] = tr

        if i < period - 1:
            c['atr'] = None
        elif i == period - 1:
            c['atr'] = sum(candles[j]['tr'] for j in range(period)) / period
        else:
            c['atr'] = (candles[i - 1]['atr'] * (period - 1) + tr) / period


def compute_daily_indicators(daily_ohlc, sma_period=20, atr_period=20):
    """Compute Daily SMA and ATR from daily OHLC list.
    Returns dict: date -> {sma20, atr20, daily_atr, close, trend}
    """
    dates = sorted(daily_ohlc.keys())
    indicators = {}

    # Compute True Range for each day
    for i, date in enumerate(dates):
        d = daily_ohlc[date]
        tr = d['high'] - d['low']
        if i > 0:
            prev_close = daily_ohlc[dates[i - 1]]['close']
            tr = max(tr, abs(d['high'] - prev_close), abs(d['low'] - prev_close))
        d['tr'] = tr

    for i, date in enumerate(dates):
        if i < max(sma_period, atr_period):
            indicators[date] = None
            continue

        # SMA 20 of daily close
        sma = sum(daily_ohlc[dates[j]]['close'] for j in range(i - sma_period + 1, i + 1)) / sma_period

        # ATR 20 of daily
        atr_avg = sum(daily_ohlc[dates[j]]['tr'] for j in range(i - atr_period + 1, i + 1)) / atr_period
        daily_atr = daily_ohlc[date]['tr']

        indicators[date] = {
            'sma20': sma,
            'atr20_avg': atr_avg,
            'daily_atr': daily_atr,
            'close': daily_ohlc[date]['close'],
            'trend': 'LONG' if daily_ohlc[date]['close'] > sma else 'SHORT',
        }

    return indicators


def run_backtest(candles, pip_size, params):
    p = params
    spread = p['spread_pips'] * pip_size

    # Annotate London time
    for c in candles:
        ldn = to_london(c['ts'])
        c['ldn_date'] = ldn.date()
        c['ldn_hour'] = ldn.hour
        c['ldn_str'] = ldn.strftime('%Y-%m-%d %H:%M')

    # Compute M15 ATR
    compute_m15_atr(candles, p['atr_m15_period'])

    # Group by London date
    daily_candles = defaultdict(list)
    for c in candles:
        daily_candles[c['ldn_date']].append(c)

    # Build daily OHLC from M15
    daily_ohlc = {}
    for date in sorted(daily_candles.keys()):
        dc = daily_candles[date]
        daily_ohlc[date] = {
            'open': dc[0]['open'],
            'high': max(c['high'] for c in dc),
            'low': min(c['low'] for c in dc),
            'close': dc[-1]['close'],
        }

    # Compute daily indicators
    daily_ind = compute_daily_indicators(daily_ohlc, p['daily_sma_period'], p['daily_atr_period'])

    balance = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    trades = []
    skipped = defaultdict(int)
    dates_sorted = sorted(daily_candles.keys())

    for idx, date in enumerate(dates_sorted):
        if date.weekday() >= 5:
            continue

        # FILTER 5: No Monday
        if date.weekday() == 0:
            skipped['monday'] += 1
            continue

        # FTMO total drawdown
        total_dd = (peak - balance) / peak if peak > 0 else 0
        if total_dd >= MAX_TOTAL_DD_PCT:
            skipped['ftmo_total'] += 1
            break

        day_candles = daily_candles[date]
        day_start = balance

        # FILTER 1: Daily trend (use PREVIOUS day's indicator)
        prev_date = dates_sorted[idx - 1] if idx > 0 else None
        if prev_date is None or daily_ind.get(prev_date) is None:
            skipped['no_daily_ind'] += 1
            continue
        prev_ind = daily_ind[prev_date]
        allowed_direction = prev_ind['trend']  # LONG or SHORT

        # FILTER 2: Daily ATR filter (prev day ATR > 20-day avg)
        if prev_ind['daily_atr'] <= prev_ind['atr20_avg']:
            skipped['atr_low'] += 1
            continue

        # Asian Range
        asian = [c for c in day_candles if c['ldn_hour'] < 7]
        if len(asian) < 4:
            skipped['no_asian'] += 1
            continue

        asian_high = max(c['high'] for c in asian)
        asian_low = min(c['low'] for c in asian)
        asian_range_pips = round((asian_high - asian_low) / pip_size, 1)

        if asian_range_pips < p['min_asian_range']:
            skipped['range_small'] += 1
            continue
        if asian_range_pips > p['max_asian_range']:
            skipped['range_large'] += 1
            continue

        # Session candles
        session = [c for c in day_candles
                   if p['session_start'] <= c['ldn_hour'] < p['session_end']]

        trade_taken = False
        for candle in session:
            if trade_taken:
                break
            if candle['rsi'] is None or candle['atr'] is None:
                continue

            body = abs(candle['close'] - candle['open'])
            total_range = candle['high'] - candle['low']
            if total_range == 0:
                continue
            if body / total_range < p['min_body_ratio']:
                continue

            rsi = candle['rsi']
            direction = None
            margin = p['breakout_margin'] * pip_size

            # LONG: close > Asian high + margin, bullish, RSI filter, trend filter
            if (candle['close'] > asian_high + margin
                    and candle['close'] > candle['open']
                    and p['rsi_long_min'] < rsi <= p['rsi_long_max']
                    and allowed_direction == 'LONG'):
                direction = 'LONG'

            # SHORT: close < Asian low - margin, bearish, RSI filter, trend filter
            elif (candle['close'] < asian_low - margin
                  and candle['close'] < candle['open']
                  and p['rsi_short_min'] <= rsi < p['rsi_short_max']
                  and allowed_direction == 'SHORT'):
                direction = 'SHORT'

            if direction is None:
                continue

            # FILTER 3: Volatility-based stops
            atr_pips = candle['atr'] / pip_size
            sl_pips = max(p['min_sl_pips'], min(p['max_sl_pips'], round(atr_pips)))
            tp_pips = sl_pips * 2  # RR 1:2

            if direction == 'LONG':
                entry = candle['close'] + spread / 2
                sl = entry - sl_pips * pip_size
                tp = entry + tp_pips * pip_size
            else:
                entry = candle['close'] - spread / 2
                sl = entry + sl_pips * pip_size
                tp = entry - tp_pips * pip_size

            # Simulate exit
            entry_idx = day_candles.index(candle)
            remaining = day_candles[entry_idx + 1:]

            exit_price = None
            exit_reason = None
            exit_time = None

            for nc in remaining:
                if nc['ldn_hour'] >= p['session_end']:
                    exit_price = nc['open']
                    exit_reason = 'TIME_EXIT'
                    exit_time = nc['ldn_str']
                    break
                if direction == 'LONG':
                    if nc['low'] <= sl:
                        exit_price, exit_reason = sl, 'SL'
                        exit_time = nc['ldn_str']
                        break
                    if nc['high'] >= tp:
                        exit_price, exit_reason = tp, 'TP'
                        exit_time = nc['ldn_str']
                        break
                else:
                    if nc['high'] >= sl:
                        exit_price, exit_reason = sl, 'SL'
                        exit_time = nc['ldn_str']
                        break
                    if nc['low'] <= tp:
                        exit_price, exit_reason = tp, 'TP'
                        exit_time = nc['ldn_str']
                        break

            if exit_price is None:
                if remaining:
                    exit_price = remaining[-1]['close']
                    exit_time = remaining[-1]['ldn_str']
                else:
                    exit_price = candle['close']
                    exit_time = candle['ldn_str']
                exit_reason = 'EOD'

            if direction == 'LONG':
                pips = (exit_price - entry) / pip_size
            else:
                pips = (entry - exit_price) / pip_size

            pnl_ratio = pips / sl_pips
            pnl = balance * RISK_PER_TRADE * pnl_ratio

            # FTMO daily loss
            daily_loss = day_start - balance
            if (daily_loss + max(0, -pnl)) / day_start > MAX_DAILY_LOSS_PCT:
                skipped['ftmo_daily'] += 1
                continue

            balance += pnl
            if balance > peak:
                peak = balance

            trade_taken = True
            trades.append({
                'date': str(date),
                'weekday': date.strftime('%A'),
                'direction': direction,
                'entry_price': round(entry, 5),
                'exit_price': round(exit_price, 5),
                'exit_reason': exit_reason,
                'sl_pips': sl_pips,
                'tp_pips': tp_pips,
                'pips': round(pips, 1),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_ratio * RISK_PER_TRADE * 100, 2),
                'balance': round(balance, 2),
                'rsi': round(rsi, 1),
                'atr_m15': round(atr_pips, 1),
                'asian_range': asian_range_pips,
                'trend': allowed_direction,
                'entry_time': candle['ldn_str'],
                'exit_time': exit_time,
            })

        if not trade_taken and not any(k in ('monday', 'no_daily_ind', 'atr_low', 'range_small', 'range_large', 'no_asian')
                                       for k in skipped if skipped[k] > 0):
            skipped['no_signal'] += 1

    return trades, balance, dict(skipped)


def calc_stats(trades, label=""):
    if not trades:
        return None
    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)
    total_pips = sum(t['pips'] for t in trades)
    gp = sum(t['pnl'] for t in wins) if wins else 0
    gl = abs(sum(t['pnl'] for t in losses)) if losses else 0.001

    peak = INITIAL_BALANCE
    max_dd = 0
    running = INITIAL_BALANCE
    for t in trades:
        running += t['pnl']
        if running > peak:
            peak = running
        dd = (peak - running) / peak * 100
        max_dd = max(max_dd, dd)

    first_d = datetime.strptime(trades[0]['date'], '%Y-%m-%d')
    last_d = datetime.strptime(trades[-1]['date'], '%Y-%m-%d')
    weeks = max((last_d - first_d).days / 7, 1)

    reasons = defaultdict(int)
    for t in trades:
        reasons[t['exit_reason']] += 1

    monthly = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'pips': 0.0, 'wins': 0})
    for t in trades:
        m = t['date'][:7]
        monthly[m]['trades'] += 1
        monthly[m]['pnl'] += t['pnl']
        monthly[m]['pips'] += t['pips']
        if t['pnl'] > 0:
            monthly[m]['wins'] += 1

    max_cw = max_cl = cw = cl = 0
    for t in trades:
        if t['pnl'] > 0:
            cw += 1; cl = 0
        elif t['pnl'] < 0:
            cl += 1; cw = 0
        else:
            cw = cl = 0
        max_cw = max(max_cw, cw)
        max_cl = max(max_cl, cl)

    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']

    # Average SL/TP used
    avg_sl = round(sum(t['sl_pips'] for t in trades) / n, 1) if n else 0
    avg_tp = round(sum(t['tp_pips'] for t in trades) / n, 1) if n else 0

    return {
        'total_trades': n,
        'wins': len(wins), 'losses': len(losses),
        'win_rate': round(len(wins) / n * 100, 1),
        'profit_factor': round(gp / gl, 2),
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl / INITIAL_BALANCE * 100, 2),
        'total_pips': round(total_pips, 1),
        'avg_pips': round(total_pips / n, 1),
        'max_dd_pct': round(max_dd, 2),
        'weekly_return': round((total_pnl / INITIAL_BALANCE * 100) / weeks, 2),
        'weeks': round(weeks, 1),
        'max_consec_wins': max_cw, 'max_consec_losses': max_cl,
        'exit_reasons': dict(reasons),
        'longs': len(longs), 'shorts': len(shorts),
        'long_wr': round(len([t for t in longs if t['pnl'] > 0]) / max(len(longs), 1) * 100, 1),
        'short_wr': round(len([t for t in shorts if t['pnl'] > 0]) / max(len(shorts), 1) * 100, 1),
        'avg_sl_pips': avg_sl, 'avg_tp_pips': avg_tp,
        'monthly': {m: {k: round(v, 2) if isinstance(v, float) else v
                        for k, v in d.items()} for m, d in sorted(monthly.items())},
        'final_balance': round(INITIAL_BALANCE + total_pnl, 2),
    }


def monte_carlo(trades, n_sims=1000):
    pnl_list = [t['pnl'] for t in trades]
    results = []
    for seed in range(n_sims):
        random.seed(seed)
        shuffled = pnl_list[:]
        random.shuffle(shuffled)
        balance = INITIAL_BALANCE
        peak = INITIAL_BALANCE
        max_dd = 0
        for pnl in shuffled:
            # Scale PnL to current balance proportionally
            ratio = pnl / INITIAL_BALANCE
            balance += balance * ratio
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak
            max_dd = max(max_dd, dd)
        results.append({
            'pnl_pct': round((balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 2),
            'max_dd': round(max_dd * 100, 2),
        })
    results.sort(key=lambda x: x['pnl_pct'])
    profitable = sum(1 for r in results if r['pnl_pct'] > 0)
    ftmo_safe = sum(1 for r in results if r['max_dd'] < 8)
    return {
        'sims': n_sims,
        'profitable_pct': round(profitable / n_sims * 100, 1),
        'ftmo_safe_pct': round(ftmo_safe / n_sims * 100, 1),
        'median_pnl': results[n_sims // 2]['pnl_pct'],
        'p5_pnl': results[int(n_sims * 0.05)]['pnl_pct'],
        'p95_pnl': results[int(n_sims * 0.95)]['pnl_pct'],
        'median_dd': sorted(results, key=lambda x: x['max_dd'])[n_sims // 2]['max_dd'],
        'p95_dd': sorted(results, key=lambda x: x['max_dd'])[int(n_sims * 0.95)]['max_dd'],
    }


def walk_forward(trades, n_folds=3):
    if not trades or len(trades) < n_folds * 3:
        return []
    chunk = len(trades) // n_folds
    folds = []
    for i in range(n_folds):
        start = i * chunk
        end = start + chunk if i < n_folds - 1 else len(trades)
        ft = trades[start:end]
        if ft:
            s = calc_stats(ft)
            folds.append({
                'fold': i + 1,
                'period': f"{ft[0]['date']} -> {ft[-1]['date']}",
                'trades': s['total_trades'],
                'pnl_pct': s['total_pnl_pct'],
                'win_rate': s['win_rate'],
                'pf': s['profit_factor'],
                'max_dd': s['max_dd_pct'],
                'weekly': s['weekly_return'],
            })
    return folds


def stress_test(candles, pip_size, base_params, spreads):
    results = []
    for sp in spreads:
        p = {**base_params, 'spread_pips': sp}
        t, _, _ = run_backtest(deepcopy(candles), pip_size, p)
        if t:
            s = calc_stats(t)
            results.append({'spread': sp, 'trades': s['total_trades'],
                            'pnl_pct': s['total_pnl_pct'], 'wr': s['win_rate'],
                            'pf': s['profit_factor'], 'dd': s['max_dd_pct'],
                            'weekly': s['weekly_return']})
        else:
            results.append({'spread': sp, 'trades': 0, 'pnl_pct': 0})
    return results


def print_pair_report(pair, stats, skipped, mc, stress, wf):
    W = 70
    print(f"\n{'=' * W}")
    print(f"  {pair} - ASIAN RANGE BREAKOUT v3 (ENHANCED)")
    print(f"{'=' * W}")

    if stats is None:
        print("  AUCUN TRADE")
        print(f"  Filtres: {skipped}")
        return

    print(f"\n  RESULTATS:")
    print(f"  {'Trades:':<22} {stats['total_trades']}")
    print(f"  {'Wins/Losses:':<22} {stats['wins']}/{stats['losses']} (WR: {stats['win_rate']}%)")
    print(f"  {'Profit Factor:':<22} {stats['profit_factor']}")
    print(f"  {'P&L Total:':<22} {stats['total_pnl']:+,.2f} ({stats['total_pnl_pct']:+.2f}%)")
    print(f"  {'Pips:':<22} {stats['total_pips']:+.1f} (avg {stats['avg_pips']:+.1f})")
    print(f"  {'Max Drawdown:':<22} {stats['max_dd_pct']:.2f}%")
    print(f"  {'Semaines:':<22} {stats['weeks']}")
    print(f"  {'RENDEMENT/SEMAINE:':<22} {stats['weekly_return']:+.2f}%")
    print(f"  {'Avg SL/TP:':<22} {stats['avg_sl_pips']}/{stats['avg_tp_pips']} pips")
    print(f"  {'Balance:':<22} {stats['final_balance']:,.2f}")

    print(f"\n  Direction: L={stats['longs']}(WR={stats['long_wr']}%) S={stats['shorts']}(WR={stats['short_wr']}%)")
    for r, c in stats['exit_reasons'].items():
        print(f"    {r:10s}: {c:3d} ({c / stats['total_trades'] * 100:.0f}%)")
    print(f"  Consecutifs: wins={stats['max_consec_wins']}, losses={stats['max_consec_losses']}")

    print(f"\n  MENSUEL:")
    for month, d in stats['monthly'].items():
        wr = round(d['wins'] / max(d['trades'], 1) * 100, 0)
        print(f"    {month}: {d['trades']:2d} tr | {d['pnl']:+8,.2f} | {d['pips']:+6.1f}p | WR={wr:.0f}%")

    if mc:
        print(f"\n  MONTE CARLO ({mc['sims']} sims):")
        print(f"    Profitable: {mc['profitable_pct']}% | FTMO safe: {mc['ftmo_safe_pct']}%")
        print(f"    P&L: {mc['p5_pnl']:+.2f}% [P5] | {mc['median_pnl']:+.2f}% [med] | {mc['p95_pnl']:+.2f}% [P95]")
        print(f"    DD:  {mc['median_dd']:.2f}% [med] | {mc['p95_dd']:.2f}% [P95]")

    if stress:
        print(f"\n  STRESS TEST:")
        for s in stress:
            if s['trades'] > 0:
                print(f"    Spread {s['spread']:.0f}p: {s['trades']}tr, {s['pnl_pct']:+.2f}%, "
                      f"WR={s['wr']}%, PF={s['pf']}, DD={s['dd']:.2f}%")

    if wf:
        print(f"\n  WALK-FORWARD:")
        for f in wf:
            print(f"    F{f['fold']}: {f['period']} | {f['trades']}tr {f['pnl_pct']:+.2f}% "
                  f"WR={f['win_rate']}% PF={f['pf']} DD={f['max_dd']:.2f}%")

    print(f"\n  JOURS FILTRES:")
    for reason, count in sorted(skipped.items(), key=lambda x: -x[1]):
        if count > 0:
            print(f"    {reason}: {count}")


if __name__ == '__main__':
    all_results = {}
    all_trades = []

    for pair, cfg in PAIRS.items():
        print(f"\n{'#' * 70}")
        print(f"# {pair}")
        print(f"{'#' * 70}")

        candles = load_m15(cfg['file'])
        first = to_london(candles[0]['ts'])
        last = to_london(candles[-1]['ts'])
        print(f"  {len(candles)} bougies | {first.date()} -> {last.date()}")

        trades, final_bal, skipped = run_backtest(deepcopy(candles), cfg['pip'], PARAMS)

        if trades:
            stats = calc_stats(trades)
            mc = monte_carlo(trades, 1000)
            st = stress_test(candles, cfg['pip'], PARAMS, [0, 1, 2, 3, 4])
            wf = walk_forward(trades, 3)
            print_pair_report(pair, stats, skipped, mc, st, wf)
            for t in trades:
                t['pair'] = pair
            all_trades.extend(trades)
            all_results[pair] = {'stats': stats, 'mc': mc, 'stress': st, 'wf': wf,
                                 'skipped': skipped, 'trades': trades}
        else:
            print_pair_report(pair, None, skipped, None, None, None)
            all_results[pair] = {'stats': None, 'skipped': skipped, 'trades': []}

    # PORTFOLIO SUMMARY
    if all_trades:
        all_trades.sort(key=lambda t: t['date'])
        port_stats = calc_stats(all_trades)
        port_mc = monte_carlo(all_trades, 1000)

        W = 70
        print(f"\n\n{'*' * W}")
        print(f"  PORTFOLIO RESUME - TOUTES PAIRES")
        print(f"{'*' * W}")
        print(f"  Trades total:       {port_stats['total_trades']}")
        print(f"  Win Rate:           {port_stats['win_rate']}%")
        print(f"  Profit Factor:      {port_stats['profit_factor']}")
        print(f"  P&L Total:          {port_stats['total_pnl']:+,.2f} ({port_stats['total_pnl_pct']:+.2f}%)")
        print(f"  Max Drawdown:       {port_stats['max_dd_pct']:.2f}%")
        print(f"  RENDEMENT/SEMAINE:  {port_stats['weekly_return']:+.2f}%")
        print(f"  Monte Carlo:        {port_mc['profitable_pct']}% profitable | {port_mc['ftmo_safe_pct']}% FTMO safe")

        print(f"\n  Par paire:")
        for pair in PAIRS:
            s = all_results[pair].get('stats')
            if s:
                print(f"    {pair:8s}: {s['total_trades']:3d} trades | {s['total_pnl_pct']:+6.2f}% | "
                      f"WR={s['win_rate']}% | PF={s['profit_factor']} | DD={s['max_dd_pct']:.2f}% | "
                      f"weekly={s['weekly_return']:+.2f}%")
            else:
                print(f"    {pair:8s}: AUCUN TRADE")

        # Statistical robustness check
        print(f"\n  VERDICT STABILITE:")
        profitable_pairs = sum(1 for p in PAIRS if all_results[p].get('stats') and
                               all_results[p]['stats']['total_pnl'] > 0)
        total_tested = sum(1 for p in PAIRS if all_results[p].get('stats'))
        print(f"    Paires profitables: {profitable_pairs}/{total_tested}")
        print(f"    Trades total: {port_stats['total_trades']} {'(>80: SIGNIFICATIF)' if port_stats['total_trades'] >= 80 else '(<80: FAIBLE)'}")
        print(f"    Stabilite WF: {sum(1 for p in PAIRS for f in all_results[p].get('wf', []) if f['pnl_pct'] > 0)} folds positifs "
              f"/ {sum(len(all_results[p].get('wf', [])) for p in PAIRS)} total")
        print(f"{'*' * W}")

    # Save
    outfile = '/app/backend/optimization_results/asian_breakout_v3_enhanced.json'
    save = {'params': PARAMS}
    for pair in PAIRS:
        r = all_results[pair]
        save[pair] = {k: v for k, v in r.items() if k != 'trades'}
        save[pair]['trade_count'] = len(r.get('trades', []))
    if all_trades:
        save['portfolio'] = {'stats': port_stats, 'mc': port_mc}
    save['all_trades'] = all_trades

    with open(outfile, 'w') as f:
        json.dump(save, f, indent=2)
    print(f"\nResultats: {outfile}")
