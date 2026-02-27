"""
Asian Range Breakout Strategy Backtester - GBPJPY M15
=====================================================
Strategy Rules:
- Timeframe: M15 only, RSI 14
- Session: 07:00-11:00 London time, max 1 trade/day
- Asian Range: 00:00-06:59 London high/low
- LONG: close > Asian high, body >= 60%, RSI 55-70
- SHORT: close < Asian low, body >= 60%, RSI 30-45
- SL: 20 pips fixed, TP: 40 pips fixed (RR 1:2)
- Force close at 11:00 if still open
- Asian range filter: 30-90 pips
- FTMO: 1% risk/trade, 4.5% daily loss, 8% total drawdown
"""

import csv
from datetime import datetime, timezone, timedelta
import json
import sys

PIP = 0.01  # JPY pair

# FTMO Rules
INITIAL_BALANCE = 100_000
RISK_PER_TRADE = 0.01       # 1%
MAX_DAILY_LOSS_PCT = 0.045  # 4.5%
MAX_TOTAL_DD_PCT = 0.08     # 8%

# Strategy defaults
DEFAULT_PARAMS = {
    'sl_pips': 20,
    'tp_pips': 40,
    'min_body_ratio': 0.60,
    'rsi_long_min': 55,
    'rsi_long_max': 70,
    'rsi_short_min': 30,
    'rsi_short_max': 45,
    'min_asian_range': 30,  # pips
    'max_asian_range': 90,  # pips
    'session_start': 7,     # London hour
    'session_end': 11,      # London hour
    'spread_pips': 2.0,     # realistic spread for GBPJPY
}


def get_london_offset(dt_utc):
    """BST: last Sunday March 01:00 UTC -> last Sunday October 01:00 UTC"""
    year = dt_utc.year

    # Last Sunday of March
    d = datetime(year, 3, 31, tzinfo=timezone.utc)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    bst_start = d.replace(hour=1)

    # Last Sunday of October
    d = datetime(year, 10, 31, tzinfo=timezone.utc)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    bst_end = d.replace(hour=1)

    if bst_start <= dt_utc < bst_end:
        return 1  # BST
    return 0  # GMT


def to_london(ts):
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    offset = get_london_offset(dt_utc)
    return dt_utc + timedelta(hours=offset)


def load_m15_data(filepath):
    candles = []
    with open(filepath) as f:
        for row in csv.DictReader(f):
            ts = int(row['time'])
            rsi_str = row.get('RSI', '').strip()
            candles.append({
                'ts': ts,
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'rsi': float(rsi_str) if rsi_str else None,
            })
    return candles


def run_backtest(candles, params=None):
    p = {**DEFAULT_PARAMS, **(params or {})}
    spread = p['spread_pips'] * PIP

    # Annotate candles with London time
    for c in candles:
        ldn = to_london(c['ts'])
        c['ldn_date'] = ldn.date()
        c['ldn_hour'] = ldn.hour
        c['ldn_min'] = ldn.minute
        c['ldn_str'] = ldn.strftime('%Y-%m-%d %H:%M')

    # Group by London date
    from collections import defaultdict
    daily = defaultdict(list)
    for c in candles:
        daily[c['ldn_date']].append(c)

    balance = INITIAL_BALANCE
    peak_balance = INITIAL_BALANCE
    trades = []
    skipped_reasons = {'no_asian': 0, 'range_small': 0, 'range_large': 0,
                       'no_signal': 0, 'ftmo_daily': 0, 'ftmo_total': 0}

    for date in sorted(daily.keys()):
        # Skip weekends
        if date.weekday() >= 5:
            continue

        day_candles = daily[date]

        # FTMO total drawdown check
        total_dd = (peak_balance - balance) / peak_balance
        if total_dd >= MAX_TOTAL_DD_PCT:
            skipped_reasons['ftmo_total'] += 1
            break

        day_start_balance = balance

        # 1. Asian Range (00:00 - 06:59 London)
        asian = [c for c in day_candles if c['ldn_hour'] < 7]
        if len(asian) < 4:  # Need minimum candles
            skipped_reasons['no_asian'] += 1
            continue

        asian_high = max(c['high'] for c in asian)
        asian_low = min(c['low'] for c in asian)
        asian_range_pips = round((asian_high - asian_low) / PIP, 1)

        if asian_range_pips < p['min_asian_range']:
            skipped_reasons['range_small'] += 1
            continue
        if asian_range_pips > p['max_asian_range']:
            skipped_reasons['range_large'] += 1
            continue

        # 2. Session candles (07:00 - 10:59 London) for entry search
        session = [c for c in day_candles
                   if p['session_start'] <= c['ldn_hour'] < p['session_end']]

        trade_taken = False

        for i, candle in enumerate(session):
            if trade_taken:
                break
            if candle['rsi'] is None:
                continue

            # Candle body analysis
            body = abs(candle['close'] - candle['open'])
            total_range = candle['high'] - candle['low']
            if total_range == 0:
                continue
            body_ratio = body / total_range

            if body_ratio < p['min_body_ratio']:
                continue

            rsi = candle['rsi']
            direction = None

            # LONG: close above Asian high, bullish candle
            if (candle['close'] > asian_high
                    and candle['close'] > candle['open']
                    and p['rsi_long_min'] < rsi <= p['rsi_long_max']):
                direction = 'LONG'

            # SHORT: close below Asian low, bearish candle
            elif (candle['close'] < asian_low
                  and candle['close'] < candle['open']
                  and p['rsi_short_min'] <= rsi < p['rsi_short_max']):
                direction = 'SHORT'

            if direction is None:
                continue

            # Entry at close of breakout candle (+ spread for long, - spread for short)
            if direction == 'LONG':
                entry_price = candle['close'] + spread / 2  # ask
                sl_price = entry_price - p['sl_pips'] * PIP
                tp_price = entry_price + p['tp_pips'] * PIP
            else:
                entry_price = candle['close'] - spread / 2  # bid
                sl_price = entry_price + p['sl_pips'] * PIP
                tp_price = entry_price - p['tp_pips'] * PIP

            # Risk/position sizing
            risk_amount = balance * RISK_PER_TRADE

            # Find exit: scan all candles after entry on this day
            entry_candle_idx = day_candles.index(candle)
            remaining = day_candles[entry_candle_idx + 1:]

            exit_price = None
            exit_reason = None
            exit_time_str = None

            for nc in remaining:
                # Force close at session_end
                if nc['ldn_hour'] >= p['session_end']:
                    exit_price = nc['open']  # close at market open of 11:00 candle
                    exit_reason = 'TIME_EXIT'
                    exit_time_str = nc['ldn_str']
                    break

                if direction == 'LONG':
                    # Check SL first (conservative)
                    if nc['low'] <= sl_price:
                        exit_price = sl_price
                        exit_reason = 'SL'
                        exit_time_str = nc['ldn_str']
                        break
                    if nc['high'] >= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TP'
                        exit_time_str = nc['ldn_str']
                        break
                else:  # SHORT
                    if nc['high'] >= sl_price:
                        exit_price = sl_price
                        exit_reason = 'SL'
                        exit_time_str = nc['ldn_str']
                        break
                    if nc['low'] <= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TP'
                        exit_time_str = nc['ldn_str']
                        break

            if exit_price is None:
                # No more candles for the day
                if remaining:
                    exit_price = remaining[-1]['close']
                    exit_time_str = remaining[-1]['ldn_str']
                else:
                    exit_price = candle['close']
                    exit_time_str = candle['ldn_str']
                exit_reason = 'EOD'

            # Calculate P&L in pips
            if direction == 'LONG':
                pips_result = (exit_price - entry_price) / PIP
            else:
                pips_result = (entry_price - exit_price) / PIP

            # P&L in money: proportional to risk
            pnl_ratio = pips_result / p['sl_pips']  # 1.0 = full risk, 2.0 = TP
            pnl = risk_amount * pnl_ratio
            pnl_pct = pnl_ratio * RISK_PER_TRADE * 100  # as % of balance

            # FTMO daily loss check
            daily_loss_so_far = day_start_balance - balance
            if (daily_loss_so_far + max(0, -pnl)) / day_start_balance > MAX_DAILY_LOSS_PCT:
                skipped_reasons['ftmo_daily'] += 1
                continue

            balance += pnl
            if balance > peak_balance:
                peak_balance = balance

            trade_taken = True
            trades.append({
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

        if not trade_taken:
            skipped_reasons['no_signal'] += 1

    return trades, balance, skipped_reasons


def compute_stats(trades, initial_balance=INITIAL_BALANCE):
    if not trades:
        return {'error': 'No trades'}

    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    breakevens = [t for t in trades if t['pnl'] == 0]

    total_pnl = sum(t['pnl'] for t in trades)
    total_pips = sum(t['pips'] for t in trades)
    win_rate = len(wins) / n * 100

    gross_profit = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.01
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

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

    # Weekly return estimate
    if len(trades) >= 2:
        first_date = datetime.strptime(trades[0]['date'], '%Y-%m-%d')
        last_date = datetime.strptime(trades[-1]['date'], '%Y-%m-%d')
        weeks = max((last_date - first_date).days / 7, 1)
    else:
        weeks = 1
    weekly_return = (total_pnl / initial_balance * 100) / weeks

    # Consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    curr_w = 0
    curr_l = 0
    for t in trades:
        if t['pnl'] > 0:
            curr_w += 1
            curr_l = 0
        elif t['pnl'] < 0:
            curr_l += 1
            curr_w = 0
        else:
            curr_w = 0
            curr_l = 0
        max_consec_wins = max(max_consec_wins, curr_w)
        max_consec_losses = max(max_consec_losses, curr_l)

    # Exit reasons
    reasons = {}
    for t in trades:
        r = t['exit_reason']
        reasons[r] = reasons.get(r, 0) + 1

    # Monthly breakdown
    monthly = {}
    for t in trades:
        month = t['date'][:7]
        if month not in monthly:
            monthly[month] = {'trades': 0, 'pnl': 0, 'pips': 0, 'wins': 0}
        monthly[month]['trades'] += 1
        monthly[month]['pnl'] += t['pnl']
        monthly[month]['pips'] += t['pips']
        if t['pnl'] > 0:
            monthly[month]['wins'] += 1

    # Direction breakdown
    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']

    return {
        'total_trades': n,
        'wins': len(wins),
        'losses': len(losses),
        'breakevens': len(breakevens),
        'win_rate': round(win_rate, 1),
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl / initial_balance * 100, 2),
        'total_pips': round(total_pips, 1),
        'avg_pips': round(total_pips / n, 1),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown': round(max_dd, 2),
        'max_drawdown_pct': round(max_dd_pct, 2),
        'weekly_return_pct': round(weekly_return, 2),
        'max_consec_wins': max_consec_wins,
        'max_consec_losses': max_consec_losses,
        'exit_reasons': reasons,
        'longs': len(longs),
        'shorts': len(shorts),
        'long_win_rate': round(len([t for t in longs if t['pnl'] > 0]) / max(len(longs), 1) * 100, 1),
        'short_win_rate': round(len([t for t in shorts if t['pnl'] > 0]) / max(len(shorts), 1) * 100, 1),
        'avg_win_pips': round(sum(t['pips'] for t in wins) / max(len(wins), 1), 1),
        'avg_loss_pips': round(sum(t['pips'] for t in losses) / max(len(losses), 1), 1),
        'monthly': {m: {k: round(v, 2) if isinstance(v, float) else v
                        for k, v in d.items()} for m, d in sorted(monthly.items())},
        'weeks_tested': round((datetime.strptime(trades[-1]['date'], '%Y-%m-%d') -
                               datetime.strptime(trades[0]['date'], '%Y-%m-%d')).days / 7, 1) if len(trades) >= 2 else 0,
        'final_balance': round(trades[-1]['balance'], 2),
    }


def print_report(stats, skipped, params):
    print("=" * 70)
    print("  ASIAN RANGE BREAKOUT - GBPJPY M15 - RAPPORT DE BACKTEST")
    print("=" * 70)

    print(f"\n--- PARAMETRES ---")
    for k, v in params.items():
        print(f"  {k}: {v}")

    print(f"\n--- RESULTATS GLOBAUX ---")
    print(f"  Trades total:      {stats['total_trades']}")
    print(f"  Wins/Losses/BE:    {stats['wins']}/{stats['losses']}/{stats['breakevens']}")
    print(f"  Win Rate:          {stats['win_rate']}%")
    print(f"  Profit Factor:     {stats['profit_factor']}")
    print(f"  P&L Total:         {stats['total_pnl']:+,.2f} ({stats['total_pnl_pct']:+.2f}%)")
    print(f"  Pips Total:        {stats['total_pips']:+.1f}")
    print(f"  Avg Pips/Trade:    {stats['avg_pips']:+.1f}")
    print(f"  Max Drawdown:      {stats['max_drawdown']:,.2f} ({stats['max_drawdown_pct']:.2f}%)")
    print(f"  Semaines testees:  {stats['weeks_tested']}")
    print(f"  Rendement/semaine: {stats['weekly_return_pct']:+.2f}%")
    print(f"  Balance finale:    {stats['final_balance']:,.2f}")

    print(f"\n--- DIRECTION ---")
    print(f"  LONG:  {stats['longs']} trades, WR={stats['long_win_rate']}%")
    print(f"  SHORT: {stats['shorts']} trades, WR={stats['short_win_rate']}%")

    print(f"\n--- SORTIES ---")
    for reason, count in stats['exit_reasons'].items():
        print(f"  {reason}: {count}")

    print(f"\n--- CONSECUTIFS ---")
    print(f"  Max wins consecutifs:   {stats['max_consec_wins']}")
    print(f"  Max losses consecutifs: {stats['max_consec_losses']}")

    print(f"\n--- MENSUEL ---")
    for month, d in stats['monthly'].items():
        wr = round(d['wins'] / max(d['trades'], 1) * 100, 1)
        print(f"  {month}: {d['trades']} trades, {d['pnl']:+,.2f}, "
              f"{d['pips']:+.1f} pips, WR={wr}%")

    print(f"\n--- JOURS IGNORES ---")
    for reason, count in skipped.items():
        print(f"  {reason}: {count}")
    print("=" * 70)


if __name__ == '__main__':
    print("Chargement des donnees M15...")
    candles = load_m15_data('/app/backend/historical_data/GBPJPY_M15_TV.csv')
    print(f"  {len(candles)} bougies chargees")

    first_ldn = to_london(candles[0]['ts'])
    last_ldn = to_london(candles[-1]['ts'])
    print(f"  Periode: {first_ldn.date()} -> {last_ldn.date()}")

    params = DEFAULT_PARAMS.copy()

    # Allow spread override from CLI
    if len(sys.argv) > 1:
        params['spread_pips'] = float(sys.argv[1])

    print(f"\nExecution du backtest (spread={params['spread_pips']} pips)...")
    trades, final_balance, skipped = run_backtest(candles, params)

    if not trades:
        print("\nAUCUN TRADE GENERE!")
        print(f"Raisons: {skipped}")
    else:
        stats = compute_stats(trades)
        print_report(stats, skipped, params)

        # Save results
        results = {
            'params': params,
            'stats': stats,
            'skipped': skipped,
            'trades': trades,
        }
        outfile = '/app/backend/optimization_results/asian_breakout_backtest.json'
        with open(outfile, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResultats sauvegardes: {outfile}")

        # Print last 10 trades
        print(f"\n--- 10 DERNIERS TRADES ---")
        for t in trades[-10:]:
            print(f"  {t['date']} {t['direction']:5s} | Entry: {t['entry_time']} @ {t['entry_price']} "
                  f"| Exit: {t['exit_reason']:9s} @ {t['exit_price']} | {t['pips']:+.1f} pips "
                  f"| {t['pnl_pct']:+.2f}% | RSI={t['rsi']} | Range={t['asian_range_pips']}p")
