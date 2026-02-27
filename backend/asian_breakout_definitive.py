"""
Asian Range Breakout - TEST DEFINITIF EN BETON
================================================
Pairs: GBPJPY + USDJPY uniquement
Configs: E (ATR stops) et C+D+E (ATR Daily + Margin + ATR Stops)
Analyse: Monte Carlo 2000, Walk-Forward 4 folds, Stress 0-5 pips
FIX: spread sur TIME_EXIT / EOD exits
"""

import csv
import json
import random
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from copy import deepcopy
import math

INITIAL_BALANCE = 100_000
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS_PCT = 0.045
MAX_TOTAL_DD_PCT = 0.08

BASE = {
    'min_body_ratio': 0.60,
    'rsi_long_min': 55, 'rsi_long_max': 70,
    'rsi_short_min': 30, 'rsi_short_max': 45,
    'min_asian_range': 30, 'max_asian_range': 90,
    'session_start': 7, 'session_end': 11,
    'spread_pips': 2.0,
    'min_sl': 8, 'max_sl': 40,
    'breakout_margin': 5,
    'atr_m15_period': 14,
}

PAIRS = {
    'GBPJPY': {'pip': 0.01, 'file': '/app/backend/historical_data/GBPJPY_M15_EXTENDED.csv'},
    'USDJPY': {'pip': 0.01, 'file': '/app/backend/historical_data/USDJPY_M15_TV.csv'},
}


def london_offset(dt_utc):
    y = dt_utc.year
    d = datetime(y, 3, 31, tzinfo=timezone.utc)
    while d.weekday() != 6: d -= timedelta(days=1)
    bst_s = d.replace(hour=1)
    d = datetime(y, 10, 31, tzinfo=timezone.utc)
    while d.weekday() != 6: d -= timedelta(days=1)
    bst_e = d.replace(hour=1)
    return 1 if bst_s <= dt_utc < bst_e else 0


def to_ldn(ts):
    u = datetime.fromtimestamp(ts, tz=timezone.utc)
    return u + timedelta(hours=london_offset(u))


def load_and_enrich(filepath, atr_period=14):
    rows = []
    with open(filepath) as f:
        for r in csv.DictReader(f):
            rsi_s = r.get('RSI', '').strip()
            rows.append({
                'ts': int(r['time']),
                'o': float(r['open']), 'h': float(r['high']),
                'l': float(r['low']), 'c': float(r['close']),
                'rsi': float(rsi_s) if rsi_s else None,
            })

    # London time
    for c in rows:
        ldn = to_ldn(c['ts'])
        c['ld'] = ldn.date()
        c['lh'] = ldn.hour
        c['lm'] = ldn.minute
        c['ls'] = ldn.strftime('%Y-%m-%d %H:%M')

    # M15 ATR (Wilder smoothing)
    for i, c in enumerate(rows):
        tr = c['h'] - c['l']
        if i > 0:
            pc = rows[i-1]['c']
            tr = max(tr, abs(c['h'] - pc), abs(c['l'] - pc))
        c['tr'] = tr
        if i < atr_period - 1:
            c['atr'] = None
        elif i == atr_period - 1:
            c['atr'] = sum(rows[j]['tr'] for j in range(atr_period)) / atr_period
        else:
            c['atr'] = (rows[i-1]['atr'] * (atr_period - 1) + tr) / atr_period

    # Group by London date
    daily = defaultdict(list)
    for c in rows:
        daily[c['ld']].append(c)

    # Daily OHLC (skip partial days < 20 candles)
    dohlc = {}
    for d in sorted(daily.keys()):
        dc = daily[d]
        if len(dc) < 20:
            continue
        dohlc[d] = {
            'o': dc[0]['o'], 'h': max(c['h'] for c in dc),
            'l': min(c['l'] for c in dc), 'c': dc[-1]['c'],
        }

    # Daily TR and ATR20
    dlist = sorted(dohlc.keys())
    dind = {}
    for i, d in enumerate(dlist):
        dd = dohlc[d]
        tr = dd['h'] - dd['l']
        if i > 0:
            tr = max(tr, abs(dd['h'] - dohlc[dlist[i-1]]['c']), abs(dd['l'] - dohlc[dlist[i-1]]['c']))
        dd['tr'] = tr
        if i < 19:
            dind[d] = None
        else:
            atr20 = sum(dohlc[dlist[j]]['tr'] for j in range(i-19, i+1)) / 20
            dind[d] = {'atr20': atr20, 'dtr': tr, 'c': dd['c']}

    return rows, daily, dind


def backtest(daily, dind, pip, params, use_atr_daily=False, use_margin=False):
    """Core backtest with ATR stops always on. Returns trade list."""
    p = params
    spread = p['spread_pips'] * pip
    half_spread = spread / 2
    balance = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    trades = []
    skip = defaultdict(int)

    dates = sorted(daily.keys())
    for idx, date in enumerate(dates):
        if date.weekday() >= 5:
            continue

        # FTMO total DD
        if peak > 0 and (peak - balance) / peak >= MAX_TOTAL_DD_PCT:
            skip['ftmo_total'] += 1
            break

        dc = daily[date]
        day_start = balance

        # ATR daily filter: use previous trading day
        if use_atr_daily:
            prev = None
            for j in range(idx-1, -1, -1):
                d = dates[j]
                if d.weekday() < 5 and dind.get(d) is not None:
                    prev = dind[d]
                    break
            if prev is None:
                skip['no_ind'] += 1
                continue
            if prev['dtr'] <= prev['atr20']:
                skip['atr_low'] += 1
                continue

        # Asian Range
        asian = [c for c in dc if c['lh'] < 7]
        if len(asian) < 4:
            skip['no_asian'] += 1
            continue

        ah = max(c['h'] for c in asian)
        al = min(c['l'] for c in asian)
        ar = round((ah - al) / pip, 1)

        if ar < p['min_asian_range']:
            skip['rng_small'] += 1
            continue
        if ar > p['max_asian_range']:
            skip['rng_large'] += 1
            continue

        # Session
        sess = [c for c in dc if p['session_start'] <= c['lh'] < p['session_end']]
        margin = p['breakout_margin'] * pip if use_margin else 0

        taken = False
        for candle in sess:
            if taken:
                break
            if candle['rsi'] is None or candle['atr'] is None:
                continue

            body = abs(candle['c'] - candle['o'])
            rng = candle['h'] - candle['l']
            if rng == 0:
                continue
            if body / rng < p['min_body_ratio']:
                continue

            rsi = candle['rsi']
            d = None

            if (candle['c'] > ah + margin and candle['c'] > candle['o']
                    and p['rsi_long_min'] < rsi <= p['rsi_long_max']):
                d = 'L'
            elif (candle['c'] < al - margin and candle['c'] < candle['o']
                  and p['rsi_short_min'] <= rsi < p['rsi_short_max']):
                d = 'S'

            if d is None:
                continue

            # ATR-based stops
            atr_pips = candle['atr'] / pip
            sl_p = max(p['min_sl'], min(p['max_sl'], round(atr_pips)))
            tp_p = sl_p * 2

            if d == 'L':
                entry = candle['c'] + half_spread
                sl = entry - sl_p * pip
                tp = entry + tp_p * pip
            else:
                entry = candle['c'] - half_spread
                sl = entry + sl_p * pip
                tp = entry - tp_p * pip

            # Simulate exit through remaining candles
            ei = dc.index(candle)
            rem = dc[ei+1:]

            ep = er = et = None
            for nc in rem:
                if nc['lh'] >= p['session_end']:
                    # FIX: Apply spread on market exit
                    if d == 'L':
                        ep = nc['o'] - half_spread  # sell at bid
                    else:
                        ep = nc['o'] + half_spread  # buy at ask
                    er = 'TIME'
                    et = nc['ls']
                    break
                if d == 'L':
                    if nc['l'] <= sl:
                        ep, er, et = sl, 'SL', nc['ls']
                        break
                    if nc['h'] >= tp:
                        ep, er, et = tp, 'TP', nc['ls']
                        break
                else:
                    if nc['h'] >= sl:
                        ep, er, et = sl, 'SL', nc['ls']
                        break
                    if nc['l'] <= tp:
                        ep, er, et = tp, 'TP', nc['ls']
                        break

            if ep is None:
                if rem:
                    if d == 'L':
                        ep = rem[-1]['c'] - half_spread
                    else:
                        ep = rem[-1]['c'] + half_spread
                    et = rem[-1]['ls']
                else:
                    ep = candle['c']
                    et = candle['ls']
                er = 'EOD'

            pips = ((ep - entry) if d == 'L' else (entry - ep)) / pip
            ratio = pips / sl_p
            pnl = balance * RISK_PER_TRADE * ratio

            # FTMO daily check
            dl = day_start - balance
            if (dl + max(0, -pnl)) / day_start > MAX_DAILY_LOSS_PCT:
                skip['ftmo_daily'] += 1
                continue

            balance += pnl
            if balance > peak:
                peak = balance
            taken = True

            trades.append({
                'dt': str(date), 'wd': date.weekday(),
                'dir': d, 'ep': round(entry, 5), 'xp': round(ep, 5),
                'xr': er, 'sl_p': sl_p, 'tp_p': tp_p,
                'pips': round(pips, 1), 'pnl': round(pnl, 2),
                'pct': round(ratio * RISK_PER_TRADE * 100, 3),
                'bal': round(balance, 2), 'rsi': round(rsi, 1),
                'atr': round(atr_pips, 1), 'ar': ar,
                'et': candle['ls'], 'xt': et,
                'hr': candle['lh'],
            })

        if not taken:
            skip['no_sig'] += 1

    return trades, dict(skip)


def full_stats(trades):
    if not trades:
        return None
    n = len(trades)
    w = [t for t in trades if t['pnl'] > 0]
    l = [t for t in trades if t['pnl'] < 0]
    tp = sum(t['pnl'] for t in trades)
    tpips = sum(t['pips'] for t in trades)
    gp = sum(t['pnl'] for t in w) if w else 0
    gl = abs(sum(t['pnl'] for t in l)) if l else 0.001

    # Drawdown
    pk = INITIAL_BALANCE
    mdd = 0
    mdd_abs = 0
    eq = INITIAL_BALANCE
    eq_curve = []
    for t in trades:
        eq += t['pnl']
        eq_curve.append(round(eq, 2))
        if eq > pk:
            pk = eq
        dd = (pk - eq) / pk * 100
        if dd > mdd:
            mdd = dd
            mdd_abs = pk - eq

    fd = datetime.strptime(trades[0]['dt'], '%Y-%m-%d')
    ld = datetime.strptime(trades[-1]['dt'], '%Y-%m-%d')
    wks = max((ld - fd).days / 7, 1)

    # Exit reasons
    xr = defaultdict(int)
    for t in trades:
        xr[t['xr']] += 1

    # Monthly
    mo = defaultdict(lambda: {'n': 0, 'pnl': 0.0, 'pips': 0.0, 'w': 0})
    for t in trades:
        m = t['dt'][:7]
        mo[m]['n'] += 1
        mo[m]['pnl'] += t['pnl']
        mo[m]['pips'] += t['pips']
        if t['pnl'] > 0: mo[m]['w'] += 1

    # Weekly
    wk = defaultdict(lambda: {'n': 0, 'pnl': 0.0, 'w': 0})
    for t in trades:
        d = datetime.strptime(t['dt'], '%Y-%m-%d')
        iso = d.isocalendar()
        k = f"{iso[0]}-W{iso[1]:02d}"
        wk[k]['n'] += 1
        wk[k]['pnl'] += t['pnl']
        if t['pnl'] > 0: wk[k]['w'] += 1

    # By weekday
    wd = defaultdict(lambda: {'n': 0, 'pnl': 0.0, 'w': 0})
    days = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven']
    for t in trades:
        d = days[t['wd']]
        wd[d]['n'] += 1
        wd[d]['pnl'] += t['pnl']
        if t['pnl'] > 0: wd[d]['w'] += 1

    # By hour
    hr = defaultdict(lambda: {'n': 0, 'pnl': 0.0, 'w': 0})
    for t in trades:
        h = f"{t['hr']:02d}h"
        hr[h]['n'] += 1
        hr[h]['pnl'] += t['pnl']
        if t['pnl'] > 0: hr[h]['w'] += 1

    # Consecutive
    mcw = mcl = cw = cl = 0
    for t in trades:
        if t['pnl'] > 0: cw += 1; cl = 0
        elif t['pnl'] < 0: cl += 1; cw = 0
        else: cw = cl = 0
        mcw = max(mcw, cw); mcl = max(mcl, cl)

    # Recovery: win rate after 1,2,3 consecutive losses
    rec = {}
    for streak in [1, 2, 3]:
        count = wins = 0
        cl_count = 0
        for t in trades:
            if t['pnl'] < 0:
                cl_count += 1
            else:
                if cl_count >= streak:
                    count += 1
                    if t['pnl'] > 0:
                        wins += 1
                cl_count = 0
        rec[streak] = f"{wins}/{count}" if count > 0 else "N/A"

    # Direction
    longs = [t for t in trades if t['dir'] == 'L']
    shorts = [t for t in trades if t['dir'] == 'S']

    # Avg SL/TP
    avg_sl = round(sum(t['sl_p'] for t in trades) / n, 1)
    avg_tp = round(sum(t['tp_p'] for t in trades) / n, 1)

    # Positive weeks
    pos_wks = sum(1 for v in wk.values() if v['pnl'] > 0)
    tot_wks = len(wk)

    # Expectancy per trade
    expectancy = tp / n

    return {
        'n': n, 'wins': len(w), 'losses': len(l),
        'wr': round(len(w)/n*100, 1),
        'pf': round(gp/gl, 2),
        'pnl': round(tp, 2), 'pnl_pct': round(tp/INITIAL_BALANCE*100, 2),
        'pips': round(tpips, 1), 'avg_pips': round(tpips/n, 1),
        'mdd_pct': round(mdd, 2), 'mdd_abs': round(mdd_abs, 2),
        'wks': round(wks, 1), 'weekly': round((tp/INITIAL_BALANCE*100)/wks, 3),
        'xr': dict(xr),
        'monthly': {m: {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}
                    for m, d in sorted(mo.items())},
        'weekly_detail': {w: {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}
                          for w, d in sorted(wk.items())},
        'by_day': {d: {k: round(v, 2) if isinstance(v, float) else v for k, v in dd.items()}
                   for d, dd in wd.items()},
        'by_hour': {h: {k: round(v, 2) if isinstance(v, float) else v for k, v in dd.items()}
                    for h, dd in sorted(hr.items())},
        'mcw': mcw, 'mcl': mcl,
        'recovery': rec,
        'longs': len(longs), 'shorts': len(shorts),
        'l_wr': round(len([t for t in longs if t['pnl']>0])/max(len(longs),1)*100, 1),
        's_wr': round(len([t for t in shorts if t['pnl']>0])/max(len(shorts),1)*100, 1),
        'avg_sl': avg_sl, 'avg_tp': avg_tp,
        'avg_win': round(sum(t['pnl'] for t in w)/max(len(w),1), 2),
        'avg_loss': round(sum(t['pnl'] for t in l)/max(len(l),1), 2),
        'pos_weeks': pos_wks, 'tot_weeks': tot_wks,
        'pos_weeks_pct': round(pos_wks/max(tot_wks,1)*100, 1),
        'expectancy': round(expectancy, 2),
        'bal': round(INITIAL_BALANCE + tp, 2),
        'eq_curve': eq_curve,
    }


def monte_carlo(trades, n_sims=2000):
    pnl_list = [t['pnl'] / INITIAL_BALANCE for t in trades]
    results = []
    for seed in range(n_sims):
        rng = random.Random(seed)
        sh = pnl_list[:]
        rng.shuffle(sh)
        bal = INITIAL_BALANCE
        pk = INITIAL_BALANCE
        mdd = 0
        for p in sh:
            bal += bal * p
            if bal > pk: pk = bal
            dd = (pk - bal) / pk
            mdd = max(mdd, dd)
        results.append((round((bal - INITIAL_BALANCE)/INITIAL_BALANCE*100, 2), round(mdd*100, 2)))

    results.sort()
    pnls = [r[0] for r in results]
    dds = sorted([r[1] for r in results])

    prof = sum(1 for p in pnls if p > 0)
    ftmo = sum(1 for d in dds if d < 8)

    return {
        'sims': n_sims,
        'profitable': round(prof/n_sims*100, 1),
        'ftmo_safe': round(ftmo/n_sims*100, 1),
        'pnl_p5': pnls[int(n_sims*0.05)],
        'pnl_p25': pnls[int(n_sims*0.25)],
        'pnl_med': pnls[n_sims//2],
        'pnl_p75': pnls[int(n_sims*0.75)],
        'pnl_p95': pnls[int(n_sims*0.95)],
        'pnl_worst': pnls[0], 'pnl_best': pnls[-1],
        'dd_med': dds[n_sims//2],
        'dd_p75': dds[int(n_sims*0.75)],
        'dd_p95': dds[int(n_sims*0.95)],
        'dd_worst': dds[-1],
    }


def stress(daily, dind, pip, params, use_atr_daily, use_margin, spreads):
    res = []
    for sp in spreads:
        p = {**params, 'spread_pips': sp}
        t, _ = backtest(daily, dind, pip, p, use_atr_daily, use_margin)
        if t:
            s = full_stats(t)
            res.append({'sp': sp, 'n': s['n'], 'pnl': s['pnl_pct'], 'wr': s['wr'],
                        'pf': s['pf'], 'dd': s['mdd_pct'], 'wk': s['weekly']})
        else:
            res.append({'sp': sp, 'n': 0})
    return res


def walk_forward(trades, n_folds=4):
    if not trades or len(trades) < n_folds * 3:
        return []
    chunk = len(trades) // n_folds
    folds = []
    for i in range(n_folds):
        s = i * chunk
        e = s + chunk if i < n_folds - 1 else len(trades)
        ft = trades[s:e]
        if ft:
            st = full_stats(ft)
            folds.append({
                'fold': i+1,
                'period': f"{ft[0]['dt']} -> {ft[-1]['dt']}",
                'n': st['n'], 'pnl': st['pnl_pct'], 'wr': st['wr'],
                'pf': st['pf'], 'dd': st['mdd_pct'], 'wk': st['weekly'],
            })
    return folds


def print_full(pair, stats, skip, mc, st, wf, config_name):
    W = 75
    print(f"\n{'█' * W}")
    print(f"  {pair} — {config_name}")
    print(f"{'█' * W}")

    print(f"\n  ┌─ PERFORMANCE ────────────────────────────────┐")
    print(f"  │ Trades:           {stats['n']:<30}│")
    print(f"  │ Wins/Losses:      {stats['wins']}/{stats['losses']} (WR: {stats['wr']}%){' '*(18-len(f'{stats[\"wins\"]}/{stats[\"losses\"]} (WR: {stats[\"wr\"]}%)'))}│")
    print(f"  │ Profit Factor:    {stats['pf']:<30}│")
    print(f"  │ P&L:              {stats['pnl']:+,.2f} ({stats['pnl_pct']:+.2f}%){' '*(16-len(f'{stats[\"pnl\"]:+,.2f} ({stats[\"pnl_pct\"]:+.2f}%)'))}│")
    print(f"  │ Pips:             {stats['pips']:+.1f} (avg {stats['avg_pips']:+.1f}){' '*(17-len(f'{stats[\"pips\"]:+.1f} (avg {stats[\"avg_pips\"]:+.1f})'))}│")
    print(f"  │ Max Drawdown:     {stats['mdd_pct']:.2f}%{' '*(25-len(f'{stats[\"mdd_pct\"]:.2f}%'))}│")
    print(f"  │ WEEKLY RETURN:    {stats['weekly']:+.3f}%{' '*(24-len(f'{stats[\"weekly\"]:+.3f}%'))}│")
    print(f"  │ Avg SL/TP:        {stats['avg_sl']}/{stats['avg_tp']} pips{' '*(21-len(f'{stats[\"avg_sl\"]}/{stats[\"avg_tp\"]} pips'))}│")
    print(f"  │ Expectancy/trade: {stats['expectancy']:+.2f}{' '*(25-len(f'{stats[\"expectancy\"]:+.2f}'))}│")
    print(f"  │ Avg win/loss:     {stats['avg_win']:+.2f} / {stats['avg_loss']:+.2f}{' '*(13-len(f'{stats[\"avg_win\"]:+.2f} / {stats[\"avg_loss\"]:+.2f}'))}│")
    print(f"  │ Semaines pos:     {stats['pos_weeks']}/{stats['tot_weeks']} ({stats['pos_weeks_pct']}%){' '*(17-len(f'{stats[\"pos_weeks\"]}/{stats[\"tot_weeks\"]} ({stats[\"pos_weeks_pct\"]}%)'))}│")
    print(f"  └────────────────────────────────────────────────┘")

    print(f"\n  Direction: L={stats['longs']}(WR={stats['l_wr']}%) S={stats['shorts']}(WR={stats['s_wr']}%)")
    print(f"  Consec: max wins={stats['mcw']}, max losses={stats['mcl']}")
    print(f"  Recovery: apres 1L={stats['recovery'].get(1,'N/A')} 2L={stats['recovery'].get(2,'N/A')} 3L={stats['recovery'].get(3,'N/A')}")

    print(f"\n  Sorties:")
    for r, c in sorted(stats['xr'].items(), key=lambda x: -x[1]):
        print(f"    {r:6s}: {c:3d} ({c/stats['n']*100:.0f}%)")

    print(f"\n  Par jour:")
    for d in ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven']:
        v = stats['by_day'].get(d, {'n': 0, 'pnl': 0, 'w': 0})
        if v['n'] > 0:
            wr = round(v['w']/v['n']*100, 0)
            print(f"    {d}: {v['n']:2d} tr | {v['pnl']:+8,.2f} | WR={wr:.0f}%")

    print(f"\n  Par heure:")
    for h, v in sorted(stats['by_hour'].items()):
        if v['n'] > 0:
            wr = round(v['w']/v['n']*100, 0)
            print(f"    {h}: {v['n']:2d} tr | {v['pnl']:+8,.2f} | WR={wr:.0f}%")

    print(f"\n  Mensuel:")
    for m, v in stats['monthly'].items():
        wr = round(v['w']/max(v['n'],1)*100, 0)
        print(f"    {m}: {v['n']:2d} tr | {v['pnl']:+8,.2f} | {v['pips']:+6.1f}p | WR={wr:.0f}%")

    print(f"\n  Hebdomadaire:")
    for w, v in stats['weekly_detail'].items():
        wr = round(v['w']/max(v['n'],1)*100, 0)
        print(f"    {w}: {v['n']:2d} tr | {v['pnl']:+8,.2f} | WR={wr:.0f}%")

    print(f"\n  MONTE CARLO ({mc['sims']} sims):")
    print(f"    Profitable:  {mc['profitable']}%")
    print(f"    FTMO safe:   {mc['ftmo_safe']}%")
    print(f"    P&L distrib: {mc['pnl_worst']:+.2f}% [worst] | {mc['pnl_p5']:+.2f}% [P5] | "
          f"{mc['pnl_p25']:+.2f}% [P25] | {mc['pnl_med']:+.2f}% [med] | "
          f"{mc['pnl_p75']:+.2f}% [P75] | {mc['pnl_p95']:+.2f}% [P95] | {mc['pnl_best']:+.2f}% [best]")
    print(f"    DD distrib:  {mc['dd_med']:.2f}% [med] | {mc['dd_p75']:.2f}% [P75] | "
          f"{mc['dd_p95']:.2f}% [P95] | {mc['dd_worst']:.2f}% [worst]")

    print(f"\n  STRESS TEST:")
    for s in st:
        if s['n'] > 0:
            print(f"    Spread {s['sp']:.0f}p: {s['n']:3d}tr {s['pnl']:+6.2f}% WR={s['wr']}% PF={s['pf']} DD={s['dd']:.2f}% wk={s['wk']:+.3f}%")

    print(f"\n  WALK-FORWARD ({len(wf)} folds):")
    pos_folds = 0
    for f in wf:
        marker = "+" if f['pnl'] > 0 else "-"
        if f['pnl'] > 0: pos_folds += 1
        print(f"    F{f['fold']} [{marker}]: {f['period']} | {f['n']:2d}tr {f['pnl']:+.2f}% WR={f['wr']}% PF={f['pf']} DD={f['dd']:.2f}%")
    print(f"    Folds positifs: {pos_folds}/{len(wf)}")

    print(f"\n  Jours filtres: {skip}")


# ===================== MAIN =====================
if __name__ == '__main__':
    CONFIGS = {
        'CONFIG_E (ATR Stops seul)': {'atr_daily': False, 'margin': False},
        'CONFIG_CDE (ATR Daily + Margin + ATR Stops)': {'atr_daily': True, 'margin': True},
    }

    pair_data = {}
    for pair, cfg in PAIRS.items():
        rows, daily, dind = load_and_enrich(cfg['file'])
        pair_data[pair] = (daily, dind, cfg['pip'])
        f = to_ldn(rows[0]['ts'])
        l = to_ldn(rows[-1]['ts'])
        print(f"  {pair}: {len(rows)} bougies | {f.date()} -> {l.date()}")

    all_results = {}

    for cname, copts in CONFIGS.items():
        print(f"\n\n{'#' * 75}")
        print(f"#  {cname}")
        print(f"{'#' * 75}")

        all_trades = []
        config_results = {}

        for pair in PAIRS:
            daily, dind, pip = pair_data[pair]
            trades, skip = backtest(daily, dind, pip, BASE,
                                    use_atr_daily=copts['atr_daily'],
                                    use_margin=copts['margin'])
            if not trades:
                print(f"\n  {pair}: AUCUN TRADE | Filtres: {skip}")
                continue

            stats = full_stats(trades)
            mc = monte_carlo(trades, 2000)
            st_res = stress(daily, dind, pip, BASE, copts['atr_daily'], copts['margin'],
                            [0, 1, 1.5, 2, 2.5, 3, 4, 5])
            wf_res = walk_forward(trades, 4)
            print_full(pair, stats, skip, mc, st_res, wf_res, cname)

            for t in trades:
                t['pair'] = pair
            all_trades.extend(trades)
            config_results[pair] = {
                'stats': stats, 'mc': mc, 'stress': st_res,
                'wf': wf_res, 'skip': skip, 'trades': trades,
            }

        # Portfolio combined
        if all_trades:
            all_trades.sort(key=lambda t: t['dt'])
            ps = full_stats(all_trades)
            pmc = monte_carlo(all_trades, 2000)
            pwf = walk_forward(all_trades, 4)

            print(f"\n{'█' * 75}")
            print(f"  PORTFOLIO {cname}")
            print(f"{'█' * 75}")
            print(f"  Trades:          {ps['n']}")
            print(f"  Win Rate:        {ps['wr']}%")
            print(f"  Profit Factor:   {ps['pf']}")
            print(f"  P&L:             {ps['pnl']:+,.2f} ({ps['pnl_pct']:+.2f}%)")
            print(f"  Max Drawdown:    {ps['mdd_pct']:.2f}%")
            print(f"  WEEKLY RETURN:   {ps['weekly']:+.3f}%")
            print(f"  Semaines pos:    {ps['pos_weeks']}/{ps['tot_weeks']} ({ps['pos_weeks_pct']}%)")
            print(f"  MC: {pmc['profitable']}% profitable | {pmc['ftmo_safe']}% FTMO safe")
            print(f"  MC P&L: {pmc['pnl_p5']:+.2f}%[P5] {pmc['pnl_med']:+.2f}%[med] {pmc['pnl_p95']:+.2f}%[P95]")
            print(f"  MC DD:  {pmc['dd_med']:.2f}%[med] {pmc['dd_p95']:.2f}%[P95]")

            if pwf:
                print(f"  Walk-Forward:")
                pos = sum(1 for f in pwf if f['pnl'] > 0)
                for f in pwf:
                    print(f"    F{f['fold']}: {f['period']} | {f['n']:2d}tr {f['pnl']:+.2f}% PF={f['pf']}")
                print(f"  Folds positifs: {pos}/{len(pwf)}")

            for pair in PAIRS:
                if pair in config_results:
                    s = config_results[pair]['stats']
                    print(f"  {pair}: {s['n']}tr {s['pnl_pct']:+.2f}% WR={s['wr']}% PF={s['pf']} DD={s['mdd_pct']:.2f}%")

        all_results[cname] = config_results

    # Save
    out = '/app/backend/optimization_results/asian_breakout_DEFINITIVE.json'
    save = {'params': BASE, 'configs': {}}
    for cn, cr in all_results.items():
        save['configs'][cn] = {}
        for pair, pr in cr.items():
            save['configs'][cn][pair] = {
                'stats': {k: v for k, v in pr['stats'].items() if k != 'eq_curve'},
                'mc': pr['mc'], 'stress': pr['stress'], 'wf': pr['wf'],
                'skip': pr['skip'], 'trades': pr['trades'],
            }
    with open(out, 'w') as f:
        json.dump(save, f, indent=2, default=str)
    print(f"\n\nResultats definitifs: {out}")
