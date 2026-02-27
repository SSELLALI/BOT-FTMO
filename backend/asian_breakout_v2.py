"""
Asian Range Breakout Strategy v2 - Multi-Pair Backtester
=========================================================
Changes vs v1:
- max_asian_range: 90 -> 120 pips
- session_end: 11h -> 13h London
- max_trades_per_day: 1 -> 3
- Multi-pair support (GBPJPY + USDJPY)
"""

import csv
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import json
import sys

PIP = 0.01  # JPY pairs

INITIAL_BALANCE = 100_000
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS_PCT = 0.045
MAX_TOTAL_DD_PCT = 0.08

DEFAULT_PARAMS = {
    'sl_pips': 20,
    'tp_pips': 40,
    'min_body_ratio': 0.60,
    'rsi_long_min': 55,
    'rsi_long_max': 70,
    'rsi_short_min': 30,
    'rsi_short_max': 45,
    'min_asian_range': 30,
    'max_asian_range': 120,     # v2: was 90
    'session_start': 7,
    'session_end': 13,          # v2: was 11
    'max_trades_per_day': 3,    # v2: was 1
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


def simulate_trade(direction, entry_price, sl_price, tp_price, remaining_candles, session_end_hour):
    """Simulate a single trade through remaining candles, return exit info."""
    for nc in remaining_candles:
        # Force close at session end
        if nc['ldn_hour'] >= session_end_hour:
            return nc['open'], 'TIME_EXIT', nc['ldn_str']

        if direction == 'LONG':
            if nc['low'] <= sl_price:
                return sl_price, 'SL', nc['ldn_str']
            if nc['high'] >= tp_price:
                return tp_price, 'TP', nc['ldn_str']
        else:
            if nc['high'] >= sl_price:
                return sl_price, 'SL', nc['ldn_str']
            if nc['low'] <= tp_price:
                return tp_price, 'TP', nc['ldn_str']

    # No more candles
    if remaining_candles:
        return remaining_candles[-1]['close'], 'EOD', remaining_candles[-1]['ldn_str']
    return None, None, None


def run_backtest(candles, pair_name, params=None):
    p = {**DEFAULT_PARAMS, **(params or {})}
    spread = p['spread_pips'] * PIP

    # Annotate with London time
    for c in candles:
        ldn = to_london(c['ts'])
        c['ldn_date'] = ldn.date()
        c['ldn_hour'] = ldn.hour
        c['ldn_min'] = ldn.minute
        c['ldn_str'] = ldn.strftime('%Y-%m-%d %H:%M')

    daily = defaultdict(list)
    for c in candles:
        daily[c['ldn_date']].append(c)

    balance = INITIAL_BALANCE
    peak_balance = INITIAL_BALANCE
    trades = []
    skipped = {'no_asian': 0, 'range_small': 0, 'range_large': 0,
               'no_signal': 0, 'ftmo_daily': 0, 'ftmo_total': 0}

    for date in sorted(daily.keys()):
        if date.weekday() >= 5:
            continue

        total_dd = (peak_balance - balance) / peak_balance
        if total_dd >= MAX_TOTAL_DD_PCT:
            skipped['ftmo_total'] += 1
            break

        day_candles = daily[date]
        day_start_balance = balance

        # Asian Range (00:00 - 06:59 London)
        asian = [c for c in day_candles if c['ldn_hour'] < 7]
        if len(asian) < 4:
            skipped['no_asian'] += 1
            continue

        asian_high = max(c['high'] for c in asian)
        asian_low = min(c['low'] for c in asian)
        asian_range_pips = round((asian_high - asian_low) / PIP, 1)

        if asian_range_pips < p['min_asian_range']:
            skipped['range_small'] += 1
            continue
        if asian_range_pips > p['max_asian_range']:
            skipped['range_large'] += 1
            continue

        # Session candles for entry
        session = [c for c in day_candles
                   if p['session_start'] <= c['ldn_hour'] < p['session_end']]

        trades_today = 0
        # Track which candles are "occupied" by an active trade
        # to avoid overlapping entries while a trade is running
        blocked_until_ts = 0

        signal_found = False

        for candle in session:
            if trades_today >= p['max_trades_per_day']:
                break

            # Don't enter while a previous trade is still active
            if candle['ts'] <= blocked_until_ts:
                continue

            if candle['rsi'] is None:
                continue

            body = abs(candle['close'] - candle['open'])
            total_range = candle['high'] - candle['low']
            if total_range == 0:
                continue
            body_ratio = body / total_range

            if body_ratio < p['min_body_ratio']:
                continue

            rsi = candle['rsi']
            direction = None

            # LONG: close > Asian high, bullish candle
            if (candle['close'] > asian_high
                    and candle['close'] > candle['open']
                    and p['rsi_long_min'] < rsi <= p['rsi_long_max']):
                direction = 'LONG'

            # SHORT: close < Asian low, bearish candle
            elif (candle['close'] < asian_low
                  and candle['close'] < candle['open']
                  and p['rsi_short_min'] <= rsi < p['rsi_short_max']):
                direction = 'SHORT'

            if direction is None:
                continue

            signal_found = True

            # Entry
            if direction == 'LONG':
                entry_price = candle['close'] + spread / 2
                sl_price = entry_price - p['sl_pips'] * PIP
                tp_price = entry_price + p['tp_pips'] * PIP
            else:
                entry_price = candle['close'] - spread / 2
                sl_price = entry_price + p['sl_pips'] * PIP
                tp_price = entry_price - p['tp_pips'] * PIP

            # Remaining candles after entry
            entry_idx = day_candles.index(candle)
            remaining = day_candles[entry_idx + 1:]

            exit_price, exit_reason, exit_time_str = simulate_trade(
                direction, entry_price, sl_price, tp_price, remaining, p['session_end'])

            if exit_price is None:
                continue

            # P&L
            if direction == 'LONG':
                pips_result = (exit_price - entry_price) / PIP
            else:
                pips_result = (entry_price - exit_price) / PIP

            pnl_ratio = pips_result / p['sl_pips']
            pnl = balance * RISK_PER_TRADE * pnl_ratio
            pnl_pct = pnl_ratio * RISK_PER_TRADE * 100

            # FTMO daily loss check
            daily_loss = day_start_balance - balance
            if (daily_loss + max(0, -pnl)) / day_start_balance > MAX_DAILY_LOSS_PCT:
                skipped['ftmo_daily'] += 1
                continue

            balance += pnl
            if balance > peak_balance:
                peak_balance = balance

            # Find exit candle timestamp so we don't enter during an active trade
            for nc in remaining:
                if nc['ldn_str'] == exit_time_str:
                    blocked_until_ts = nc['ts']
                    break

            trades_today += 1
            trades.append({
                'pair': pair_name,
                'date': str(date),
                'direction': direction,
                'entry_price': round(entry_price, 3),
                'sl': round(sl_price, 3),
                'tp': round(tp_price, 3),
                'exit_price': round(exit_price, 3),
                'exit_reason': exit_reason,
                'pips': round(pips_result, 1),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'balance': round(balance, 2),
                'rsi': round(rsi, 1),
                'asian_range_pips': asian_range_pips,
                'entry_time': candle['ldn_str'],
                'exit_time': exit_time_str,
            })

        if not signal_found:
            skipped['no_signal'] += 1

    return trades, balance, skipped


def compute_stats(trades, initial_balance=INITIAL_BALANCE):
    if not trades:
        return {'error': 'No trades', 'total_trades': 0}

    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]

    total_pnl = sum(t['pnl'] for t in trades)
    total_pips = sum(t['pips'] for t in trades)
    win_rate = len(wins) / n * 100

    gross_profit = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.01
    profit_factor = gross_profit / gross_loss

    # Max drawdown
    peak = initial_balance
    max_dd = 0
    max_dd_pct = 0
    running = initial_balance
    for t in trades:
        running += t['pnl']
        if running > peak:
            peak = running
        dd = peak - running
        dd_pct = dd / peak * 100
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd = dd

    first_date = datetime.strptime(trades[0]['date'], '%Y-%m-%d')
    last_date = datetime.strptime(trades[-1]['date'], '%Y-%m-%d')
    weeks = max((last_date - first_date).days / 7, 1)
    weekly_return = (total_pnl / initial_balance * 100) / weeks

    # Consecutive
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

    reasons = {}
    for t in trades:
        reasons[t['exit_reason']] = reasons.get(t['exit_reason'], 0) + 1

    monthly = {}
    for t in trades:
        m = t['date'][:7]
        if m not in monthly:
            monthly[m] = {'trades': 0, 'pnl': 0.0, 'pips': 0.0, 'wins': 0}
        monthly[m]['trades'] += 1
        monthly[m]['pnl'] += t['pnl']
        monthly[m]['pips'] += t['pips']
        if t['pnl'] > 0:
            monthly[m]['wins'] += 1

    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']

    # Trades per day distribution
    from collections import Counter
    daily_counts = Counter(t['date'] for t in trades)
    days_1t = sum(1 for c in daily_counts.values() if c == 1)
    days_2t = sum(1 for c in daily_counts.values() if c == 2)
    days_3t = sum(1 for c in daily_counts.values() if c == 3)

    return {
        'total_trades': n,
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(win_rate, 1),
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl / initial_balance * 100, 2),
        'total_pips': round(total_pips, 1),
        'avg_pips': round(total_pips / n, 1),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown': round(max_dd, 2),
        'max_drawdown_pct': round(max_dd_pct, 2),
        'weekly_return_pct': round(weekly_return, 2),
        'weeks_tested': round(weeks, 1),
        'max_consec_wins': max_cw,
        'max_consec_losses': max_cl,
        'exit_reasons': reasons,
        'longs': len(longs),
        'shorts': len(shorts),
        'long_wr': round(len([t for t in longs if t['pnl'] > 0]) / max(len(longs), 1) * 100, 1),
        'short_wr': round(len([t for t in shorts if t['pnl'] > 0]) / max(len(shorts), 1) * 100, 1),
        'monthly': {m: {k: round(v, 2) if isinstance(v, float) else v
                        for k, v in d.items()} for m, d in sorted(monthly.items())},
        'final_balance': round(trades[-1]['balance'], 2),
        'days_with_1_trade': days_1t,
        'days_with_2_trades': days_2t,
        'days_with_3_trades': days_3t,
        'trading_days': len(daily_counts),
        'avg_trades_per_day': round(n / max(len(daily_counts), 1), 1),
    }


def print_report(pair, stats, skipped, params):
    print("=" * 70)
    print(f"  ASIAN RANGE BREAKOUT v2 - {pair} M15")
    print("=" * 70)

    print(f"\n--- PARAMETRES v2 ---")
    print(f"  SL/TP: {params['sl_pips']}/{params['tp_pips']} pips (RR 1:{params['tp_pips']//params['sl_pips']})")
    print(f"  Session: {params['session_start']}h-{params['session_end']}h London")
    print(f"  Asian range: {params['min_asian_range']}-{params['max_asian_range']} pips")
    print(f"  Max trades/jour: {params['max_trades_per_day']}")
    print(f"  Body ratio min: {params['min_body_ratio']}")
    print(f"  RSI LONG: {params['rsi_long_min']}-{params['rsi_long_max']}")
    print(f"  RSI SHORT: {params['rsi_short_min']}-{params['rsi_short_max']}")
    print(f"  Spread: {params['spread_pips']} pips")

    print(f"\n--- RESULTATS ---")
    print(f"  Trades:            {stats['total_trades']}")
    print(f"  Win Rate:          {stats['win_rate']}%")
    print(f"  Profit Factor:     {stats['profit_factor']}")
    print(f"  P&L Total:         {stats['total_pnl']:+,.2f} ({stats['total_pnl_pct']:+.2f}%)")
    print(f"  Pips Total:        {stats['total_pips']:+.1f} (avg {stats['avg_pips']:+.1f}/trade)")
    print(f"  Max Drawdown:      {stats['max_drawdown']:,.2f} ({stats['max_drawdown_pct']:.2f}%)")
    print(f"  Semaines:          {stats['weeks_tested']}")
    print(f"  Rendement/semaine: {stats['weekly_return_pct']:+.2f}%")
    print(f"  Balance finale:    {stats['final_balance']:,.2f}")

    print(f"\n--- FREQUENCE ---")
    print(f"  Jours de trading:  {stats['trading_days']}")
    print(f"  Avg trades/jour:   {stats['avg_trades_per_day']}")
    print(f"  Jours 1 trade:     {stats['days_with_1_trade']}")
    print(f"  Jours 2 trades:    {stats['days_with_2_trades']}")
    print(f"  Jours 3 trades:    {stats['days_with_3_trades']}")

    print(f"\n--- DIRECTION ---")
    print(f"  LONG:  {stats['longs']} (WR={stats['long_wr']}%)")
    print(f"  SHORT: {stats['shorts']} (WR={stats['short_wr']}%)")

    print(f"\n--- SORTIES ---")
    for r, c in stats['exit_reasons'].items():
        pct = round(c / stats['total_trades'] * 100, 1)
        print(f"  {r:10s}: {c:3d} ({pct}%)")

    print(f"\n--- CONSECUTIFS ---")
    print(f"  Max wins:   {stats['max_consec_wins']}")
    print(f"  Max losses: {stats['max_consec_losses']}")

    print(f"\n--- MENSUEL ---")
    for month, d in stats['monthly'].items():
        wr = round(d['wins'] / max(d['trades'], 1) * 100, 1)
        print(f"  {month}: {d['trades']:2d} trades | {d['pnl']:+8,.2f} | "
              f"{d['pips']:+6.1f} pips | WR={wr}%")

    print(f"\n--- JOURS FILTRES ---")
    for reason, count in skipped.items():
        if count > 0:
            print(f"  {reason}: {count}")
    print("=" * 70)


if __name__ == '__main__':
    pairs = {
        'GBPJPY': '/app/backend/historical_data/GBPJPY_M15_TV.csv',
        'USDJPY': '/app/backend/historical_data/USDJPY_M15_TV.csv',
    }

    params = DEFAULT_PARAMS.copy()

    all_trades = []
    all_results = {}

    for pair, filepath in pairs.items():
        print(f"\n{'#' * 70}")
        print(f"# {pair}")
        print(f"{'#' * 70}")

        candles = load_m15(filepath)
        first_ldn = to_london(candles[0]['ts'])
        last_ldn = to_london(candles[-1]['ts'])
        print(f"  {len(candles)} bougies | {first_ldn.date()} -> {last_ldn.date()}")

        trades, final_bal, skipped = run_backtest(candles, pair, params)

        if trades:
            stats = compute_stats(trades)
            print_report(pair, stats, skipped, params)
            all_trades.extend(trades)
            all_results[pair] = {'stats': stats, 'skipped': skipped, 'trades': trades}
        else:
            print(f"  AUCUN TRADE pour {pair}")
            all_results[pair] = {'stats': {'total_trades': 0}, 'skipped': skipped, 'trades': []}

    # Combined portfolio summary
    if all_trades:
        # Sort all trades by date for portfolio simulation
        all_trades.sort(key=lambda t: t['date'])

        # Recalculate portfolio P&L
        portfolio_balance = INITIAL_BALANCE
        peak = INITIAL_BALANCE
        max_dd_pct = 0
        for t in all_trades:
            pnl_ratio = t['pips'] / params['sl_pips']
            pnl = portfolio_balance * RISK_PER_TRADE * pnl_ratio
            portfolio_balance += pnl
            if portfolio_balance > peak:
                peak = portfolio_balance
            dd_pct = (peak - portfolio_balance) / peak * 100
            max_dd_pct = max(max_dd_pct, dd_pct)

        first_d = datetime.strptime(all_trades[0]['date'], '%Y-%m-%d')
        last_d = datetime.strptime(all_trades[-1]['date'], '%Y-%m-%d')
        weeks = max((last_d - first_d).days / 7, 1)
        total_pnl = portfolio_balance - INITIAL_BALANCE
        weekly_ret = (total_pnl / INITIAL_BALANCE * 100) / weeks

        print(f"\n{'=' * 70}")
        print(f"  PORTFOLIO COMBINE ({' + '.join(pairs.keys())})")
        print(f"{'=' * 70}")
        print(f"  Trades total:      {len(all_trades)}")
        print(f"  P&L Total:         {total_pnl:+,.2f} ({total_pnl/INITIAL_BALANCE*100:+.2f}%)")
        print(f"  Max Drawdown:      {max_dd_pct:.2f}%")
        print(f"  Semaines:          {weeks:.1f}")
        print(f"  Rendement/semaine: {weekly_ret:+.2f}%")
        print(f"  Balance finale:    {portfolio_balance:,.2f}")

        # Breakdown per pair
        for pair in pairs:
            if all_results[pair]['stats'].get('total_trades', 0) > 0:
                s = all_results[pair]['stats']
                print(f"  {pair}: {s['total_trades']} trades, {s['total_pnl_pct']:+.2f}%, "
                      f"WR={s['win_rate']}%, PF={s['profit_factor']}")
        print(f"{'=' * 70}")

    # Save everything
    outfile = '/app/backend/optimization_results/asian_breakout_v2_results.json'
    save_data = {
        'params': params,
        'portfolio': {
            'total_trades': len(all_trades),
            'weeks': weeks if all_trades else 0,
        },
    }
    for pair in pairs:
        r = all_results[pair]
        save_data[pair] = {
            'stats': r['stats'],
            'skipped': r['skipped'],
            'trades': r['trades'],
        }

    with open(outfile, 'w') as f:
        json.dump(save_data, f, indent=2)
    print(f"\nResultats sauvegardes: {outfile}")
