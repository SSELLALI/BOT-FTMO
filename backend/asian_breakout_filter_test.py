"""
Asian Range Breakout - Test Systematique de Filtres
=====================================================
Teste chaque filtre INDIVIDUELLEMENT, puis combinaisons 2-3.
Objectif: maximiser trades ET résultats.
"""

import csv
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from copy import deepcopy
from itertools import combinations

INITIAL_BALANCE = 100_000
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS_PCT = 0.045
MAX_TOTAL_DD_PCT = 0.08
PIP_MAP = {'GBPJPY': 0.01, 'GBPUSD': 0.0001, 'USDJPY': 0.01, 'EURUSD': 0.0001}

FILES = {
    'GBPJPY': '/app/backend/historical_data/GBPJPY_M15_EXTENDED.csv',
    'GBPUSD': '/app/backend/historical_data/GBPUSD_M15_IC.csv',
    'USDJPY': '/app/backend/historical_data/USDJPY_M15_TV.csv',
    'EURUSD': '/app/backend/historical_data/EURUSD_M15_TV.csv',
}

BASE_PARAMS = {
    'sl_pips': 20, 'tp_pips': 40,
    'min_body_ratio': 0.60,
    'rsi_long_min': 55, 'rsi_long_max': 70,
    'rsi_short_min': 30, 'rsi_short_max': 45,
    'min_asian_range': 30, 'max_asian_range': 90,
    'session_start': 7, 'session_end': 11,
    'spread_pips': 2.0,
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


def load_and_prepare(filepath):
    candles = []
    with open(filepath) as f:
        for row in csv.DictReader(f):
            rsi_str = row.get('RSI', '').strip()
            c = {
                'ts': int(row['time']),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'rsi': float(rsi_str) if rsi_str else None,
            }
            ldn = to_london(c['ts'])
            c['ldn_date'] = ldn.date()
            c['ldn_hour'] = ldn.hour
            c['ldn_str'] = ldn.strftime('%Y-%m-%d %H:%M')
            candles.append(c)

    # Compute M15 ATR
    for i, c in enumerate(candles):
        tr = c['high'] - c['low']
        if i > 0:
            pc = candles[i-1]['close']
            tr = max(tr, abs(c['high'] - pc), abs(c['low'] - pc))
        c['tr'] = tr
        if i < 13:
            c['atr14'] = None
        elif i == 13:
            c['atr14'] = sum(candles[j]['tr'] for j in range(14)) / 14
        else:
            c['atr14'] = (candles[i-1]['atr14'] * 13 + tr) / 14

    # Group by London date
    daily_candles = defaultdict(list)
    for c in candles:
        daily_candles[c['ldn_date']].append(c)

    # Build daily OHLC (excluding weekends with < 10 candles)
    daily_ohlc = {}
    for date in sorted(daily_candles.keys()):
        dc = daily_candles[date]
        if len(dc) < 10:  # Skip partial days (Sunday evening)
            continue
        daily_ohlc[date] = {
            'open': dc[0]['open'],
            'high': max(c['high'] for c in dc),
            'low': min(c['low'] for c in dc),
            'close': dc[-1]['close'],
        }

    # Compute daily True Range + SMA20 + ATR20
    dates = sorted(daily_ohlc.keys())
    daily_ind = {}
    for i, date in enumerate(dates):
        d = daily_ohlc[date]
        tr = d['high'] - d['low']
        if i > 0:
            prev_c = daily_ohlc[dates[i-1]]['close']
            tr = max(tr, abs(d['high'] - prev_c), abs(d['low'] - prev_c))
        d['tr'] = tr

        if i < 19:
            daily_ind[date] = None
            continue

        sma20 = sum(daily_ohlc[dates[j]]['close'] for j in range(i-19, i+1)) / 20
        atr20 = sum(daily_ohlc[dates[j]]['tr'] for j in range(i-19, i+1)) / 20

        daily_ind[date] = {
            'sma20': sma20,
            'atr20': atr20,
            'daily_tr': tr,
            'close': d['close'],
        }

    return candles, daily_candles, daily_ind


def run_filtered_backtest(daily_candles, daily_ind, pip_size, params,
                          use_no_monday=False,
                          use_trend_filter=False,
                          use_atr_daily_filter=False,
                          use_breakout_margin=False,
                          use_atr_stops=False,
                          margin_pips=5,
                          min_sl=8, max_sl=40):
    """Run backtest with optional filters. Returns trades list and stats."""
    p = params
    spread = p['spread_pips'] * pip_size
    balance = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    trades = []
    skipped = defaultdict(int)

    dates_sorted = sorted(daily_candles.keys())

    for idx, date in enumerate(dates_sorted):
        if date.weekday() >= 5:
            continue

        # Filter A: No Monday
        if use_no_monday and date.weekday() == 0:
            skipped['monday'] += 1
            continue

        # FTMO check
        if peak > 0 and (peak - balance) / peak >= MAX_TOTAL_DD_PCT:
            skipped['ftmo_total'] += 1
            break

        day_candles = daily_candles[date]
        day_start = balance

        # Get previous trading day's indicators
        prev_date = None
        for j in range(idx - 1, -1, -1):
            d = dates_sorted[j]
            if d.weekday() < 5 and daily_ind.get(d) is not None:
                prev_date = d
                break

        # Filter B: Daily trend
        allowed_dir = None  # None = both allowed
        if use_trend_filter:
            if prev_date is None or daily_ind.get(prev_date) is None:
                skipped['no_indicator'] += 1
                continue
            ind = daily_ind[prev_date]
            allowed_dir = 'LONG' if ind['close'] > ind['sma20'] else 'SHORT'

        # Filter C: ATR daily
        if use_atr_daily_filter:
            if prev_date is None or daily_ind.get(prev_date) is None:
                skipped['no_indicator'] += 1
                continue
            ind = daily_ind[prev_date]
            if ind['daily_tr'] <= ind['atr20']:
                skipped['atr_low'] += 1
                continue

        # Asian Range
        asian = [c for c in day_candles if c['ldn_hour'] < 7]
        if len(asian) < 4:
            skipped['no_asian'] += 1
            continue

        a_high = max(c['high'] for c in asian)
        a_low = min(c['low'] for c in asian)
        a_range_pips = round((a_high - a_low) / pip_size, 1)

        if a_range_pips < p['min_asian_range']:
            skipped['range_small'] += 1
            continue
        if a_range_pips > p['max_asian_range']:
            skipped['range_large'] += 1
            continue

        # Session candles
        session = [c for c in day_candles
                   if p['session_start'] <= c['ldn_hour'] < p['session_end']]

        trade_taken = False
        for candle in session:
            if trade_taken:
                break
            if candle['rsi'] is None:
                continue

            body = abs(candle['close'] - candle['open'])
            total_range = candle['high'] - candle['low']
            if total_range == 0:
                continue
            if body / total_range < p['min_body_ratio']:
                continue

            rsi = candle['rsi']
            direction = None

            # Filter D: Breakout margin
            margin = margin_pips * pip_size if use_breakout_margin else 0

            if (candle['close'] > a_high + margin
                    and candle['close'] > candle['open']
                    and p['rsi_long_min'] < rsi <= p['rsi_long_max']):
                direction = 'LONG'
            elif (candle['close'] < a_low - margin
                  and candle['close'] < candle['open']
                  and p['rsi_short_min'] <= rsi < p['rsi_short_max']):
                direction = 'SHORT'

            if direction is None:
                continue

            # Filter B applied: trend direction check
            if allowed_dir is not None and direction != allowed_dir:
                continue

            # Filter E: ATR-based stops vs fixed
            if use_atr_stops and candle.get('atr14') is not None:
                atr_pips = candle['atr14'] / pip_size
                sl_pips = max(min_sl, min(max_sl, round(atr_pips)))
                tp_pips = sl_pips * 2
            else:
                sl_pips = p['sl_pips']
                tp_pips = p['tp_pips']

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

            exit_price = exit_reason = exit_time = None
            for nc in remaining:
                if nc['ldn_hour'] >= p['session_end']:
                    exit_price, exit_reason = nc['open'], 'TIME_EXIT'
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

            pips = ((exit_price - entry) if direction == 'LONG' else (entry - exit_price)) / pip_size
            pnl_ratio = pips / sl_pips
            pnl = balance * RISK_PER_TRADE * pnl_ratio

            daily_loss = day_start - balance
            if (daily_loss + max(0, -pnl)) / day_start > MAX_DAILY_LOSS_PCT:
                skipped['ftmo_daily'] += 1
                continue

            balance += pnl
            if balance > peak:
                peak = balance
            trade_taken = True

            trades.append({
                'date': str(date), 'direction': direction,
                'exit_reason': exit_reason,
                'sl_pips': sl_pips, 'tp_pips': tp_pips,
                'pips': round(pips, 1),
                'pnl': round(pnl, 2),
                'balance': round(balance, 2),
            })

    return trades, dict(skipped)


def quick_stats(trades):
    if not trades:
        return {'n': 0, 'pnl_pct': 0, 'wr': 0, 'pf': 0, 'dd': 0, 'weekly': 0}
    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)
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

    return {
        'n': n,
        'pnl_pct': round(total_pnl / INITIAL_BALANCE * 100, 2),
        'wr': round(len(wins) / n * 100, 1),
        'pf': round(gp / gl, 2),
        'dd': round(max_dd, 2),
        'weekly': round((total_pnl / INITIAL_BALANCE * 100) / weeks, 2),
        'weeks': round(weeks, 1),
        'tp': reasons.get('TP', 0),
        'sl': reasons.get('SL', 0),
        'time': reasons.get('TIME_EXIT', 0),
    }


# Filter definitions
FILTERS = {
    'A_NoMon':  {'use_no_monday': True},
    'B_Trend':  {'use_trend_filter': True},
    'C_ATR_D':  {'use_atr_daily_filter': True},
    'D_Margin': {'use_breakout_margin': True},
    'E_ATR_SL': {'use_atr_stops': True},
}


if __name__ == '__main__':
    print("=" * 100)
    print("  TEST SYSTEMATIQUE DES FILTRES - ASIAN RANGE BREAKOUT")
    print("=" * 100)

    # Load all data
    pair_data = {}
    for pair, filepath in FILES.items():
        candles, daily_candles, daily_ind = load_and_prepare(filepath)
        pair_data[pair] = (daily_candles, daily_ind)
        first = to_london(candles[0]['ts'])
        last = to_london(candles[-1]['ts'])
        print(f"  {pair}: {len(candles)} bougies | {first.date()} -> {last.date()}")

    all_results = {}

    # ============================================
    # 1. BASELINE (no filters)
    # ============================================
    print(f"\n{'─' * 100}")
    print(f"  {'CONFIG':<25} | {'PAIR':<8} | {'N':>4} | {'P&L%':>7} | {'WR%':>5} | {'PF':>5} | {'DD%':>5} | {'W/sem':>6} | {'TP':>3} | {'SL':>3} | {'TIME':>4}")
    print(f"{'─' * 100}")

    configs = [('BASE (no filter)', {})]
    for fname, fparams in FILTERS.items():
        configs.append((fname, fparams))

    # 2-filter combos
    filter_names = list(FILTERS.keys())
    for combo in combinations(filter_names, 2):
        label = ' + '.join(combo)
        merged = {}
        for f in combo:
            merged.update(FILTERS[f])
        configs.append((label, merged))

    # 3-filter combos
    for combo in combinations(filter_names, 3):
        label = ' + '.join(combo)
        merged = {}
        for f in combo:
            merged.update(FILTERS[f])
        configs.append((label, merged))

    for config_name, filter_kwargs in configs:
        pair_results = {}
        total_trades = []

        for pair in FILES:
            daily_candles, daily_ind = pair_data[pair]
            pip = PIP_MAP[pair]
            trades, skipped = run_filtered_backtest(
                daily_candles, daily_ind, pip, BASE_PARAMS, **filter_kwargs)
            s = quick_stats(trades)
            pair_results[pair] = s

            if trades:
                for t in trades:
                    t['pair'] = pair
                total_trades.extend(trades)

            print(f"  {config_name:<25} | {pair:<8} | {s['n']:>4} | {s['pnl_pct']:>+6.2f}% | {s['wr']:>4.1f}% | {s['pf']:>5.2f} | {s['dd']:>4.2f}% | {s['weekly']:>+5.2f}% | {s['tp']:>3} | {s['sl']:>3} | {s['time']:>4}")

        # Portfolio total
        if total_trades:
            total_trades.sort(key=lambda t: t['date'])
            ps = quick_stats(total_trades)
            print(f"  {config_name:<25} | {'TOTAL':<8} | {ps['n']:>4} | {ps['pnl_pct']:>+6.2f}% | {ps['wr']:>4.1f}% | {ps['pf']:>5.2f} | {ps['dd']:>4.2f}% | {ps['weekly']:>+5.2f}% | {ps['tp']:>3} | {ps['sl']:>3} | {ps['time']:>4}")
        print(f"{'─' * 100}")

        all_results[config_name] = {
            'pairs': pair_results,
            'total': quick_stats(total_trades) if total_trades else {'n': 0},
        }

    # ============================================
    # RANKING: Best configs by total portfolio
    # ============================================
    print(f"\n{'=' * 100}")
    print(f"  CLASSEMENT PAR SCORE (trades * weekly_return * profit_factor)")
    print(f"{'=' * 100}")

    ranked = []
    for name, res in all_results.items():
        t = res['total']
        if t['n'] >= 10:  # Minimum 10 trades
            # Score: balance trades count, weekly return, and profit factor
            score = t['n'] * max(0, t['weekly']) * max(0, t['pf'] - 1)
            ranked.append({
                'name': name, 'n': t['n'], 'pnl': t['pnl_pct'],
                'wr': t['wr'], 'pf': t['pf'], 'dd': t['dd'],
                'weekly': t['weekly'], 'score': round(score, 2),
            })

    ranked.sort(key=lambda x: x['score'], reverse=True)

    print(f"  {'#':<3} {'CONFIG':<40} | {'N':>4} | {'P&L%':>7} | {'WR%':>5} | {'PF':>5} | {'DD%':>5} | {'W/sem':>6} | {'SCORE':>7}")
    print(f"  {'─' * 95}")
    for i, r in enumerate(ranked[:15], 1):
        marker = ' ***' if i <= 3 else ''
        print(f"  {i:<3} {r['name']:<40} | {r['n']:>4} | {r['pnl']:>+6.2f}% | {r['wr']:>4.1f}% | {r['pf']:>5.2f} | {r['dd']:>4.2f}% | {r['weekly']:>+5.2f}% | {r['score']:>7.1f}{marker}")

    # Save
    outfile = '/app/backend/optimization_results/filter_systematic_test.json'
    with open(outfile, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResultats: {outfile}")
