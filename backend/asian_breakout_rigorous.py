"""
Asian Range Breakout - Backtester Rigoureux v1
================================================
Parametres v1: Session 7h-11h London, 1 trade/jour max, Asian 30-90 pips
Multi-pair: GBPJPY (pip=0.01) + GBPUSD (pip=0.0001)
Includes: Monte Carlo, Stress Test, Walk-Forward splits
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

V1_PARAMS = {
    'sl_pips': 20,
    'tp_pips': 40,
    'min_body_ratio': 0.60,
    'rsi_long_min': 55,
    'rsi_long_max': 70,
    'rsi_short_min': 30,
    'rsi_short_max': 45,
    'min_asian_range': 30,
    'max_asian_range': 90,
    'session_start': 7,
    'session_end': 11,
    'max_trades_per_day': 1,
    'spread_pips': 2.0,
}

PAIR_CONFIG = {
    'GBPJPY': {'pip': 0.01,   'file': '/app/backend/historical_data/GBPJPY_M15_EXTENDED.csv'},
    'GBPUSD': {'pip': 0.0001, 'file': '/app/backend/historical_data/GBPUSD_M15_IC.csv'},
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


def run_backtest(candles, pip_size, params, balance_start=INITIAL_BALANCE):
    """Core backtest engine. Returns list of trade dicts."""
    p = params
    spread = p['spread_pips'] * pip_size

    for c in candles:
        ldn = to_london(c['ts'])
        c['ldn_date'] = ldn.date()
        c['ldn_hour'] = ldn.hour
        c['ldn_str'] = ldn.strftime('%Y-%m-%d %H:%M')

    daily = defaultdict(list)
    for c in candles:
        daily[c['ldn_date']].append(c)

    balance = balance_start
    peak = balance_start
    trades = []
    skipped = defaultdict(int)

    for date in sorted(daily.keys()):
        if date.weekday() >= 5:
            continue

        total_dd = (peak - balance) / peak if peak > 0 else 0
        if total_dd >= MAX_TOTAL_DD_PCT:
            skipped['ftmo_total'] += 1
            break

        day_candles = daily[date]
        day_start = balance

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

            if (candle['close'] > asian_high
                    and candle['close'] > candle['open']
                    and p['rsi_long_min'] < rsi <= p['rsi_long_max']):
                direction = 'LONG'
            elif (candle['close'] < asian_low
                  and candle['close'] < candle['open']
                  and p['rsi_short_min'] <= rsi < p['rsi_short_max']):
                direction = 'SHORT'

            if direction is None:
                continue

            if direction == 'LONG':
                entry = candle['close'] + spread / 2
                sl = entry - p['sl_pips'] * pip_size
                tp = entry + p['tp_pips'] * pip_size
            else:
                entry = candle['close'] - spread / 2
                sl = entry + p['sl_pips'] * pip_size
                tp = entry - p['tp_pips'] * pip_size

            idx = day_candles.index(candle)
            remaining = day_candles[idx + 1:]

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

            pnl_ratio = pips / p['sl_pips']
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
                'date': str(date),
                'direction': direction,
                'entry_price': round(entry, 5),
                'exit_price': round(exit_price, 5),
                'exit_reason': exit_reason,
                'pips': round(pips, 1),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_ratio * RISK_PER_TRADE * 100, 2),
                'balance': round(balance, 2),
                'rsi': round(rsi, 1),
                'asian_range': asian_range_pips,
                'entry_time': candle['ldn_str'],
                'exit_time': exit_time,
            })

        if not trade_taken:
            skipped['no_signal'] += 1

    return trades, balance, dict(skipped)


def calc_stats(trades, weeks_override=None):
    if not trades:
        return None
    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)
    total_pips = sum(t['pips'] for t in trades)
    gross_profit = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.001

    peak = INITIAL_BALANCE
    max_dd = 0
    running = INITIAL_BALANCE
    for t in trades:
        running += t['pnl']
        if running > peak:
            peak = running
        dd_pct = (peak - running) / peak * 100
        max_dd = max(max_dd, dd_pct)

    first_d = datetime.strptime(trades[0]['date'], '%Y-%m-%d')
    last_d = datetime.strptime(trades[-1]['date'], '%Y-%m-%d')
    weeks = weeks_override or max((last_d - first_d).days / 7, 1)

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

    max_cw, max_cl, cw, cl = 0, 0, 0, 0
    for t in trades:
        if t['pnl'] > 0:
            cw += 1; cl = 0
        elif t['pnl'] < 0:
            cl += 1; cw = 0
        else:
            cw = 0; cl = 0
        max_cw = max(max_cw, cw)
        max_cl = max(max_cl, cl)

    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']

    return {
        'total_trades': n,
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins) / n * 100, 1),
        'profit_factor': round(gross_profit / gross_loss, 2),
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl / INITIAL_BALANCE * 100, 2),
        'total_pips': round(total_pips, 1),
        'avg_pips': round(total_pips / n, 1),
        'max_dd_pct': round(max_dd, 2),
        'weekly_return': round((total_pnl / INITIAL_BALANCE * 100) / weeks, 2),
        'weeks': round(weeks, 1),
        'max_consec_wins': max_cw,
        'max_consec_losses': max_cl,
        'exit_reasons': dict(reasons),
        'longs': len(longs),
        'shorts': len(shorts),
        'long_wr': round(len([t for t in longs if t['pnl'] > 0]) / max(len(longs), 1) * 100, 1),
        'short_wr': round(len([t for t in shorts if t['pnl'] > 0]) / max(len(shorts), 1) * 100, 1),
        'monthly': {m: {k: round(v, 2) if isinstance(v, float) else v
                        for k, v in d.items()} for m, d in sorted(monthly.items())},
        'final_balance': round(INITIAL_BALANCE + total_pnl, 2),
    }


def monte_carlo(trades, n_sims=1000):
    """Shuffle trade order and measure distribution of outcomes."""
    pnl_pcts = [t['pnl'] / INITIAL_BALANCE for t in trades]
    results = []
    for seed in range(n_sims):
        random.seed(seed)
        shuffled = pnl_pcts[:]
        random.shuffle(shuffled)
        balance = INITIAL_BALANCE
        peak = INITIAL_BALANCE
        max_dd = 0
        for p in shuffled:
            balance += balance * p  # compound
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak
            max_dd = max(max_dd, dd)
        results.append({
            'final_pnl_pct': round((balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 2),
            'max_dd_pct': round(max_dd * 100, 2),
        })
    results.sort(key=lambda x: x['final_pnl_pct'])
    profitable = sum(1 for r in results if r['final_pnl_pct'] > 0)
    ftmo_safe = sum(1 for r in results if r['max_dd_pct'] < 8)
    return {
        'simulations': n_sims,
        'profitable_pct': round(profitable / n_sims * 100, 1),
        'ftmo_safe_pct': round(ftmo_safe / n_sims * 100, 1),
        'median_pnl_pct': results[n_sims // 2]['final_pnl_pct'],
        'p5_pnl_pct': results[int(n_sims * 0.05)]['final_pnl_pct'],
        'p95_pnl_pct': results[int(n_sims * 0.95)]['final_pnl_pct'],
        'median_dd_pct': sorted(results, key=lambda x: x['max_dd_pct'])[n_sims // 2]['max_dd_pct'],
        'p95_dd_pct': sorted(results, key=lambda x: x['max_dd_pct'])[int(n_sims * 0.95)]['max_dd_pct'],
        'worst_pnl_pct': results[0]['final_pnl_pct'],
        'best_pnl_pct': results[-1]['final_pnl_pct'],
    }


def stress_test(candles, pip_size, base_params, spreads=[1.0, 2.0, 3.0, 4.0]):
    """Test with different spread levels."""
    results = []
    for sp in spreads:
        p = {**base_params, 'spread_pips': sp}
        trades, bal, _ = run_backtest(deepcopy(candles), pip_size, p)
        if trades:
            s = calc_stats(trades)
            results.append({
                'spread': sp,
                'trades': s['total_trades'],
                'pnl_pct': s['total_pnl_pct'],
                'win_rate': s['win_rate'],
                'pf': s['profit_factor'],
                'max_dd': s['max_dd_pct'],
                'weekly': s['weekly_return'],
            })
        else:
            results.append({'spread': sp, 'trades': 0, 'pnl_pct': 0})
    return results


def walk_forward_split(trades, n_folds=3):
    """Simple walk-forward: split trades chronologically into folds."""
    if not trades:
        return []
    chunk = len(trades) // n_folds
    folds = []
    for i in range(n_folds):
        start = i * chunk
        end = start + chunk if i < n_folds - 1 else len(trades)
        fold_trades = trades[start:end]
        if fold_trades:
            s = calc_stats(fold_trades)
            folds.append({
                'fold': i + 1,
                'period': f"{fold_trades[0]['date']} -> {fold_trades[-1]['date']}",
                'trades': s['total_trades'],
                'pnl_pct': s['total_pnl_pct'],
                'win_rate': s['win_rate'],
                'pf': s['profit_factor'],
                'max_dd': s['max_dd_pct'],
                'weekly': s['weekly_return'],
            })
    return folds


def print_full_report(pair, stats, skipped, mc, stress, wf, params):
    W = 70
    print("=" * W)
    print(f"  ASIAN RANGE BREAKOUT v1 RIGOUREUX - {pair} M15")
    print("=" * W)

    print(f"\n{'─' * W}")
    print(f"  PARAMETRES")
    print(f"{'─' * W}")
    print(f"  SL/TP: {params['sl_pips']}/{params['tp_pips']} pips (RR 1:{params['tp_pips']//params['sl_pips']})")
    print(f"  Session: {params['session_start']}h-{params['session_end']}h | Max {params['max_trades_per_day']} trade/jour")
    print(f"  Asian: {params['min_asian_range']}-{params['max_asian_range']} pips | Body >= {params['min_body_ratio']}")
    print(f"  RSI LONG: >{params['rsi_long_min']} et <={params['rsi_long_max']} | SHORT: >={params['rsi_short_min']} et <{params['rsi_short_max']}")
    print(f"  Spread test: {params['spread_pips']} pips")

    print(f"\n{'─' * W}")
    print(f"  RESULTATS PRINCIPAUX")
    print(f"{'─' * W}")
    print(f"  Trades:             {stats['total_trades']}")
    print(f"  Wins/Losses:        {stats['wins']}/{stats['losses']} (WR: {stats['win_rate']}%)")
    print(f"  Profit Factor:      {stats['profit_factor']}")
    print(f"  P&L Total:          {stats['total_pnl']:+,.2f} ({stats['total_pnl_pct']:+.2f}%)")
    print(f"  Pips Total:         {stats['total_pips']:+.1f} (avg {stats['avg_pips']:+.1f}/trade)")
    print(f"  Max Drawdown:       {stats['max_dd_pct']:.2f}%")
    print(f"  Semaines:           {stats['weeks']}")
    print(f"  RENDEMENT/SEMAINE:  {stats['weekly_return']:+.2f}%")
    print(f"  Balance finale:     {stats['final_balance']:,.2f}")

    print(f"\n  Direction: LONG {stats['longs']} (WR={stats['long_wr']}%) | SHORT {stats['shorts']} (WR={stats['short_wr']}%)")

    print(f"\n  Sorties:")
    for r, c in stats['exit_reasons'].items():
        print(f"    {r:10s}: {c:3d} ({c/stats['total_trades']*100:.1f}%)")

    print(f"  Consecutifs: max wins={stats['max_consec_wins']}, max losses={stats['max_consec_losses']}")

    print(f"\n{'─' * W}")
    print(f"  MENSUEL")
    print(f"{'─' * W}")
    for month, d in stats['monthly'].items():
        wr = round(d['wins'] / max(d['trades'], 1) * 100, 1)
        print(f"  {month}: {d['trades']:2d} trades | {d['pnl']:+8,.2f} | {d['pips']:+6.1f} pips | WR={wr}%")

    print(f"\n{'─' * W}")
    print(f"  MONTE CARLO ({mc['simulations']} simulations)")
    print(f"{'─' * W}")
    print(f"  Profitable:     {mc['profitable_pct']}%")
    print(f"  FTMO safe:      {mc['ftmo_safe_pct']}% (DD < 8%)")
    print(f"  P&L median:     {mc['median_pnl_pct']:+.2f}%")
    print(f"  P&L P5-P95:     {mc['p5_pnl_pct']:+.2f}% -> {mc['p95_pnl_pct']:+.2f}%")
    print(f"  P&L worst/best: {mc['worst_pnl_pct']:+.2f}% / {mc['best_pnl_pct']:+.2f}%")
    print(f"  DD median:      {mc['median_dd_pct']:.2f}%")
    print(f"  DD P95:         {mc['p95_dd_pct']:.2f}%")

    print(f"\n{'─' * W}")
    print(f"  STRESS TEST (spread)")
    print(f"{'─' * W}")
    for s in stress:
        if s['trades'] > 0:
            print(f"  Spread {s['spread']:.1f}p: {s['trades']} trades, {s['pnl_pct']:+.2f}%, "
                  f"WR={s['win_rate']}%, PF={s['pf']}, DD={s['max_dd']:.2f}%, "
                  f"weekly={s['weekly']:+.2f}%")

    print(f"\n{'─' * W}")
    print(f"  WALK-FORWARD (stabilite temporelle)")
    print(f"{'─' * W}")
    for f in wf:
        print(f"  Fold {f['fold']}: {f['period']}")
        print(f"         {f['trades']} trades, {f['pnl_pct']:+.2f}%, WR={f['win_rate']}%, "
              f"PF={f['pf']}, DD={f['max_dd']:.2f}%, weekly={f['weekly']:+.2f}%")

    print(f"\n{'─' * W}")
    print(f"  JOURS FILTRES")
    print(f"{'─' * W}")
    for reason, count in skipped.items():
        if count > 0:
            print(f"  {reason}: {count}")
    print("=" * W)


if __name__ == '__main__':
    params = V1_PARAMS.copy()
    all_results = {}

    for pair, cfg in PAIR_CONFIG.items():
        print(f"\n{'#' * 70}")
        print(f"# Chargement {pair}...")
        print(f"{'#' * 70}")

        candles = load_m15(cfg['file'])
        first_ldn = to_london(candles[0]['ts'])
        last_ldn = to_london(candles[-1]['ts'])
        print(f"  {len(candles)} bougies | {first_ldn.date()} -> {last_ldn.date()}")

        # Main backtest
        trades, final_bal, skipped = run_backtest(deepcopy(candles), cfg['pip'], params)

        if not trades:
            print(f"  AUCUN TRADE pour {pair}")
            all_results[pair] = {'stats': None}
            continue

        stats = calc_stats(trades)

        # Monte Carlo
        mc = monte_carlo(trades, 1000)

        # Stress test
        stress = stress_test(candles, cfg['pip'], params, [0.0, 1.0, 2.0, 3.0, 4.0])

        # Walk-forward stability
        wf = walk_forward_split(trades, 3)

        print_full_report(pair, stats, skipped, mc, stress, wf, params)

        all_results[pair] = {
            'stats': stats,
            'skipped': skipped,
            'monte_carlo': mc,
            'stress_test': stress,
            'walk_forward': wf,
            'trades': trades,
        }

    # Portfolio combined
    all_pair_trades = []
    for pair in PAIR_CONFIG:
        if all_results[pair].get('trades'):
            for t in all_results[pair]['trades']:
                t['pair'] = pair
            all_pair_trades.extend(all_results[pair]['trades'])

    if all_pair_trades:
        all_pair_trades.sort(key=lambda t: t['date'])
        portfolio_stats = calc_stats(all_pair_trades)
        portfolio_mc = monte_carlo(all_pair_trades, 1000)

        print(f"\n{'=' * 70}")
        print(f"  PORTFOLIO COMBINE (GBPJPY + GBPUSD)")
        print(f"{'=' * 70}")
        print(f"  Trades total:       {portfolio_stats['total_trades']}")
        print(f"  Win Rate:           {portfolio_stats['win_rate']}%")
        print(f"  Profit Factor:      {portfolio_stats['profit_factor']}")
        print(f"  P&L Total:          {portfolio_stats['total_pnl']:+,.2f} ({portfolio_stats['total_pnl_pct']:+.2f}%)")
        print(f"  Max Drawdown:       {portfolio_stats['max_dd_pct']:.2f}%")
        print(f"  RENDEMENT/SEMAINE:  {portfolio_stats['weekly_return']:+.2f}%")
        print(f"  Monte Carlo: {portfolio_mc['profitable_pct']}% profitable, "
              f"FTMO safe={portfolio_mc['ftmo_safe_pct']}%")
        for pair in PAIR_CONFIG:
            s = all_results[pair].get('stats')
            if s:
                print(f"  {pair}: {s['total_trades']} trades, {s['total_pnl_pct']:+.2f}%, "
                      f"WR={s['win_rate']}%, PF={s['profit_factor']}")
        print(f"{'=' * 70}")

    # Save
    outfile = '/app/backend/optimization_results/asian_breakout_rigorous_v1.json'
    save = {'params': params}
    for pair in PAIR_CONFIG:
        r = all_results[pair]
        save[pair] = {
            'stats': r.get('stats'),
            'skipped': r.get('skipped'),
            'monte_carlo': r.get('monte_carlo'),
            'stress_test': r.get('stress_test'),
            'walk_forward': r.get('walk_forward'),
            'trades': r.get('trades', []),
        }
    if all_pair_trades:
        save['portfolio'] = {
            'stats': portfolio_stats,
            'monte_carlo': portfolio_mc,
        }

    with open(outfile, 'w') as f:
        json.dump(save, f, indent=2)
    print(f"\nResultats complets sauvegardes: {outfile}")
