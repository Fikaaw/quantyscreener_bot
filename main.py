"""
Altcoin Potential Screener — @quantyscreener_bot

Kirim report ke Telegram tiap 4 jam:
- Chart 3 panel (Multi-Factor Score + Funding Rate + L/S Ratio)
- Tabel TOP 30
- Trading plan dengan triple confirmation

Deploy: GitHub Actions 
"""

import os
import io
import requests
import warnings
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # non-interactive backend untuk server
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from scipy.stats import spearmanr

warnings.filterwarnings('ignore')

# ── Credentials dari environment variable (GitHub Secrets) ──
TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '8724989560')

# ── Konfigurasi ──────────────────────────────────────────────
BASE = 'https://fapi.binance.com'

SYMBOLS = [
    'SOLUSDT','ORDIUSDT','PENGUUSDT','VIRTUALUSDT','APEUSDT',
    'KAITOUSDT','ZECUSDT','BNBUSDT','BTCUSDT','ETHUSDT',
    'XRPUSDT','AVAXUSDT','ADAUSDT','DOGEUSDT','LINKUSDT',
    'DOTUSDT','NEARUSDT','ATOMUSDT','LTCUSDT','UNIUSDT',
    'AAVEUSDT','APTUSDT','ARBUSDT','OPUSDT','INJUSDT',
    'SUIUSDT','TIAUSDT','WLDUSDT','AXSUSDT','TAOUSDT',
    'ONDOUSDT','RENDERUSDT','PENDLEUSDT','LDOUSDT','TONUSDT',
]

# Tier thresholds
TIER_A_THRESHOLD = 0.60
TIER_B_THRESHOLD = 0.30
SHORT_THRESHOLD  = -0.40
NZ_THRESHOLD     = 0.004

# Triple confirmation
FR_SQUEEZE_LEVEL  = -0.30
FR_CROWDED_LEVEL  = +0.30
LS_CROWDED_LONG   = 1.50
LS_CROWDED_SHORT  = 0.70

# Risk management
TOTAL_CAPITAL = 500
MAX_RISK_PCT  = 0.025
TARGET_RR     = 2.0
WIN_RATE      = 0.55
IC_THRESHOLD  = 0.03

# FlowState colors
PINK_DARK  = '#c0155a'
PINK_MID   = '#e8327a'
PINK_LIGHT = '#f5a0c0'

SIGNAL_COLS = [
    'reversal_1d', 'liquidity_30d', 'liquidation_imbalance',
    'funding_rate_contrarian', 'vol_compression_30d', 'ls_ratio_contrarian',
    'momentum_30d', 'volume_compression_30d', 'oi_price_signal'
]


# ════════════════════════════════════════════════════════════
# DATA FETCHING
# ════════════════════════════════════════════════════════════

def get_klines(symbol, interval='1h', limit=750):
    try:
        r = requests.get(f'{BASE}/fapi/v1/klines',
            params={'symbol': symbol, 'interval': interval, 'limit': limit},
            timeout=15)
        if r.status_code != 200:
            return None
        cols = ['time','open','high','low','close','volume','close_time',
                'quote_vol','trades','taker_buy_base','taker_buy_quote','ignore']
        df = pd.DataFrame(r.json(), columns=cols)
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        for c in ['open','high','low','close','volume','taker_buy_base','quote_vol']:
            df[c] = df[c].astype(float)
        df['taker_sell_base'] = df['volume'] - df['taker_buy_base']
        return df.set_index('time')[['open','high','low','close','volume',
                                      'taker_buy_base','taker_sell_base','quote_vol']]
    except Exception:
        return None


def get_funding(symbol, limit=200):
    try:
        r = requests.get(f'{BASE}/fapi/v1/fundingRate',
            params={'symbol': symbol, 'limit': limit}, timeout=15)
        if r.status_code != 200:
            return None
        df = pd.DataFrame(r.json())
        if df.empty:
            return None
        df['fundingTime'] = pd.to_datetime(df['fundingTime'], unit='ms')
        df['fundingRate']  = df['fundingRate'].astype(float)
        return df.set_index('fundingTime')[['fundingRate']]
    except Exception:
        return None


def get_current_funding(symbol):
    try:
        r = requests.get(f'{BASE}/fapi/v1/premiumIndex',
            params={'symbol': symbol}, timeout=15)
        if r.status_code != 200:
            return 0.0
        return float(r.json().get('lastFundingRate', 0))
    except Exception:
        return 0.0


def get_oi(symbol, period='1h', limit=200):
    try:
        r = requests.get(f'{BASE}/futures/data/openInterestHist',
            params={'symbol': symbol, 'period': period, 'limit': limit},
            timeout=15)
        if r.status_code != 200:
            return None
        df = pd.DataFrame(r.json())
        if df.empty:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['sumOpenInterest']      = df['sumOpenInterest'].astype(float)
        df['sumOpenInterestValue'] = df['sumOpenInterestValue'].astype(float)
        return df.set_index('timestamp')[['sumOpenInterest','sumOpenInterestValue']]
    except Exception:
        return None


def get_ls_ratio(symbol, period='1h', limit=200):
    try:
        r = requests.get(f'{BASE}/futures/data/globalLongShortAccountRatio',
            params={'symbol': symbol, 'period': period, 'limit': limit},
            timeout=15)
        if r.status_code != 200:
            return None
        df = pd.DataFrame(r.json())
        if df.empty:
            return None
        df['timestamp']      = pd.to_datetime(df['timestamp'], unit='ms')
        df['longShortRatio'] = df['longShortRatio'].astype(float)
        return df.set_index('timestamp')[['longShortRatio']]
    except Exception:
        return None


def get_liquidations(symbol):
    try:
        r = requests.get(f'{BASE}/fapi/v1/allForceOrders',
            params={'symbol': symbol, 'limit': 200}, timeout=15)
        if r.status_code != 200:
            return None
        df = pd.DataFrame(r.json())
        if df.empty:
            return None
        df['time']         = pd.to_datetime(df['time'], unit='ms')
        df['origQty']      = df['origQty'].astype(float)
        df['averagePrice'] = df['averagePrice'].astype(float)
        df['usd_value']    = df['origQty'] * df['averagePrice']
        return df.set_index('time')
    except Exception:
        return None


# ════════════════════════════════════════════════════════════
# SIGNAL COMPUTATION
# ════════════════════════════════════════════════════════════

def compute_signals(symbol):
    kl   = get_klines(symbol, '1h', 750)
    if kl is None or len(kl) < 100:
        return None, None

    fund = get_funding(symbol, 200)
    oi   = get_oi(symbol, '1h', 200)
    ls   = get_ls_ratio(symbol, '1h', 200)
    liq  = get_liquidations(symbol)
    fr_now = get_current_funding(symbol)

    df = kl.copy()
    df['fwd_return_24h'] = df['close'].pct_change(24).shift(-24)

    # 1. reversal_1d
    df['reversal_1d'] = -df['close'].pct_change(24)

    # 2. liquidity_30d
    df['liquidity_30d'] = np.log1p(df['quote_vol'].rolling(30*24).mean())

    # 3. liquidation_imbalance
    if liq is not None and len(liq) > 5:
        lb  = liq[liq['side']=='BUY']['usd_value'].resample('1h').sum().reindex(df.index, fill_value=0)
        ls_ = liq[liq['side']=='SELL']['usd_value'].resample('1h').sum().reindex(df.index, fill_value=0)
        df['liquidation_imbalance'] = (ls_ - lb) / (lb + ls_ + 1e-8)
    else:
        df['liquidation_imbalance'] = (df['taker_sell_base'] - df['taker_buy_base']) / (df['volume'] + 1e-8)

    # 4. funding_rate_contrarian
    if fund is not None and len(fund) > 10:
        fh = fund.resample('1h').ffill().reindex(df.index, method='ffill')
        fm = fh['fundingRate'].rolling(90).mean()
        fs = fh['fundingRate'].rolling(90).std()
        df['funding_rate_contrarian'] = -((fh['fundingRate'] - fm) / (fs + 1e-8))
    else:
        df['funding_rate_contrarian'] = np.nan

    # 5. vol_compression_30d
    df['vol_compression_30d'] = -(df['volume'] / (df['volume'].rolling(30*24).mean() + 1e-8))

    # 6. ls_ratio_contrarian
    if ls is not None and len(ls) > 10:
        lsh = ls.reindex(df.index, method='ffill')
        lsm = lsh['longShortRatio'].rolling(168).mean()
        lss = lsh['longShortRatio'].rolling(168).std()
        df['ls_ratio_contrarian'] = -((lsh['longShortRatio'] - lsm) / (lss + 1e-8))
    else:
        df['ls_ratio_contrarian'] = np.nan

    # 7. momentum_30d
    df['momentum_30d'] = df['close'].pct_change(30*24)

    # 8. volume_compression_30d
    vm = df['volume'].rolling(30*24).mean()
    vs = df['volume'].rolling(30*24).std()
    df['volume_compression_30d'] = vs / (vm + 1e-8)

    # 9. oi_price_signal
    if oi is not None and len(oi) > 10:
        oh = oi.reindex(df.index, method='ffill')
        df['oi_price_signal'] = oh['sumOpenInterest'].pct_change(24) - df['close'].pct_change(24)
    else:
        df['oi_price_signal'] = np.nan

    df['symbol'] = symbol

    # Metadata snapshot
    ls_now  = float(ls['longShortRatio'].iloc[-1]) if ls is not None and len(ls) > 0 else 1.0
    oi_usd  = float(oi['sumOpenInterestValue'].iloc[-1]) if oi is not None and len(oi) > 0 else 0
    vol_24h = float(df['quote_vol'].tail(24).sum())

    meta = {
        'symbol'  : symbol,
        'close'   : float(df['close'].iloc[-1]),
        'fr'      : round(fr_now * 100, 4),
        'ls'      : round(ls_now, 2),
        'oi_usd'  : oi_usd,
        'vol_24h' : vol_24h,
    }

    keep = ['close', 'volume', 'fwd_return_24h', 'symbol'] + SIGNAL_COLS
    return df[keep].dropna(subset=['fwd_return_24h', 'reversal_1d']), meta


# ════════════════════════════════════════════════════════════
# IC CALCULATION
# ════════════════════════════════════════════════════════════

def compute_ic(master):
    ic_results = {}
    for sig in SIGNAL_COLS:
        daily_ic = []
        for date, grp in master.groupby(master.index.date):
            g = grp[['fwd_return_24h', sig]].dropna()
            if len(g) >= 5:
                ic_d, _ = spearmanr(g[sig], g['fwd_return_24h'])
                if not np.isnan(ic_d):
                    daily_ic.append(ic_d)
        if not daily_ic:
            continue
        ic_mean = np.mean(daily_ic)
        ic_std  = np.std(daily_ic)
        ic_results[sig] = {
            'IC Mean'  : round(ic_mean, 4),
            'ICIR'     : round(ic_mean / ic_std if ic_std > 0 else 0, 2),
            'daily_ic' : daily_ic
        }
    return ic_results


# ════════════════════════════════════════════════════════════
# REGIME DETECTOR
# ════════════════════════════════════════════════════════════

def detect_regime(master, window=14):
    rows = []
    for date, grp in master.groupby(master.index.date):
        g = grp[['fwd_return_24h', 'momentum_30d', 'reversal_1d']].dropna()
        if len(g) < 5:
            continue
        ic_mom, _ = spearmanr(g['momentum_30d'], g['fwd_return_24h'])
        ic_rev, _ = spearmanr(g['reversal_1d'],  g['fwd_return_24h'])
        if not np.isnan(ic_mom) and not np.isnan(ic_rev):
            rows.append({'date': date, 'ic_mom': ic_mom, 'ic_rev': ic_rev})
    if not rows:
        return 'UNKNOWN', 0, 0.5

    rdf       = pd.DataFrame(rows).set_index('date')
    roll_diff = (rdf['ic_mom'].rolling(window).mean() - rdf['ic_rev'].rolling(window).mean())
    cur_score = roll_diff.iloc[-1]

    if cur_score > 0.01:
        regime = 'MOMENTUM'
        confidence = float(np.mean(roll_diff.dropna().tail(window) > 0))
    elif cur_score < -0.01:
        regime = 'REVERSAL'
        confidence = float(np.mean(roll_diff.dropna().tail(window) < 0))
    else:
        regime = 'MIXED'
        confidence = 0.5

    return regime, cur_score, confidence


def get_regime_weights(regime, confidence, ic_results):
    weights = {sig: abs(ic_results.get(sig, {}).get('IC Mean', 0.001)) for sig in SIGNAL_COLS}
    boost   = 1 + confidence * 1.5
    if regime == 'MOMENTUM':
        weights['momentum_30d']          *= boost
        weights['liquidity_30d']         *= boost * 0.8
        weights['reversal_1d']           *= 0.5
        weights['liquidation_imbalance'] *= 0.7
    elif regime == 'REVERSAL':
        weights['reversal_1d']             *= boost
        weights['liquidation_imbalance']   *= boost * 0.8
        weights['funding_rate_contrarian'] *= boost * 0.7
        weights['ls_ratio_contrarian']     *= boost * 0.7
        weights['momentum_30d']            *= 0.3
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


# ════════════════════════════════════════════════════════════
# SCORING & TIER
# ════════════════════════════════════════════════════════════

def zscore_cross(s):
    return (s - s.mean()) / (s.std() + 1e-8)


def assign_tier(score, ls_ratio):
    if score >= TIER_A_THRESHOLD:
        return 'TIER_B' if ls_ratio > LS_CROWDED_LONG else 'TIER_A'
    elif score >= TIER_B_THRESHOLD:
        return 'TIER_B'
    elif score <= SHORT_THRESHOLD:
        return 'SHORT'
    return 'NEUTRAL'


def compute_composite(master, meta_df, ic_results, regime_weights):
    cutoff = master.index.max() - pd.Timedelta(hours=24)
    snap   = master[master.index >= cutoff].groupby('symbol')[SIGNAL_COLS + ['close']].mean()

    for sig in SIGNAL_COLS:
        snap[f'{sig}_z'] = zscore_cross(snap[sig])

    score_parts = []
    for sig in SIGNAL_COLS:
        z_col     = f'{sig}_z'
        if z_col not in snap.columns:
            continue
        ic_val    = ic_results.get(sig, {}).get('IC Mean', 0)
        direction = 1 if ic_val >= 0 else -1
        weight    = regime_weights.get(sig, 0)
        score_parts.append(direction * snap[z_col] * weight)

    snap['composite_score'] = sum(score_parts)
    snap = snap.join(meta_df[['fr', 'ls', 'oi_usd', 'vol_24h']], how='left')
    snap['tier'] = snap.apply(
        lambda r: assign_tier(r['composite_score'], r.get('ls', 1.0)), axis=1
    )

    ranking = snap[['composite_score', 'close', 'fr', 'ls', 'oi_usd', 'vol_24h', 'tier']]\
                  .dropna(subset=['composite_score'])\
                  .sort_values('composite_score', ascending=False)
    ranking['rank'] = range(1, len(ranking) + 1)
    return ranking


# ════════════════════════════════════════════════════════════
# TRIPLE CONFIRMATION
# ════════════════════════════════════════════════════════════

def triple_confirmation(score, fr_pct, ls_ratio, tier):
    if tier == 'NEUTRAL':
        return False, None, []

    direction  = 'LONG' if tier in ['TIER_A', 'TIER_B'] else 'SHORT'
    checks     = []
    pass_count = 0

    # Check 1: Score
    checks.append(f"Score {score:+.3f} [{tier}]")
    pass_count += 1

    # Check 2: Funding Rate
    if direction == 'LONG':
        if fr_pct < 0:
            checks.append(f"FR {fr_pct:+.2f}% negatif — squeeze candidate")
            pass_count += 1
        else:
            checks.append(f"FR {fr_pct:+.2f}% positif — crowded, hati-hati")
    else:
        if fr_pct > 0:
            checks.append(f"FR {fr_pct:+.2f}% positif — mendukung short")
            pass_count += 1
        else:
            checks.append(f"FR {fr_pct:+.2f}% negatif — short lebih berisiko")

    # Check 3: L/S Ratio
    if direction == 'LONG':
        if ls_ratio < LS_CROWDED_LONG:
            checks.append(f"L/S {ls_ratio:.2f} — tidak crowded")
            pass_count += 1
        else:
            checks.append(f"L/S {ls_ratio:.2f} — crowded long, warning!")
    else:
        if ls_ratio > LS_CROWDED_LONG:
            checks.append(f"L/S {ls_ratio:.2f} — crowded long, mendukung short")
            pass_count += 1
        else:
            checks.append(f"L/S {ls_ratio:.2f} — tidak cukup crowded untuk short")

    # Confirmed kalau minimal 2 dari 3 check pass
    confirmed = pass_count >= 2

    return confirmed, direction, checks


# ════════════════════════════════════════════════════════════
# CHART — 3 PANEL FLOWSTATE
# ════════════════════════════════════════════════════════════

def build_chart(ranking):
    shortlist = ranking[ranking['tier'].isin(['TIER_A', 'TIER_B', 'SHORT'])]\
                    .sort_values('composite_score', ascending=True)\
                    .tail(12)

    syms   = [s.replace('USDT', '') for s in shortlist.index]
    scores = shortlist['composite_score'].values
    fr_vals= shortlist['fr'].fillna(0).values
    ls_vals= shortlist['ls'].fillna(1.0).values
    tiers  = shortlist['tier'].values

    # Warna dengan gradasi
    score_colors = []
    for t, sc in zip(tiers, scores):
        if t == 'TIER_A':
            score_colors.append(PINK_DARK)
        elif t == 'TIER_B':
            alpha = min(1.0, max(0.4, sc / TIER_A_THRESHOLD))
            score_colors.append(PINK_LIGHT)
        else:
            score_colors.append('#888899')

    fr_colors = [PINK_DARK if v < FR_SQUEEZE_LEVEL
                 else (PINK_MID if v < 0
                 else PINK_LIGHT) for v in fr_vals]

    ls_colors = []
    for v in ls_vals:
        if v > LS_CROWDED_LONG:   ls_colors.append('#e74c3c')
        elif v < LS_CROWDED_SHORT: ls_colors.append(PINK_DARK)
        else:                      ls_colors.append(PINK_LIGHT)

    fig, axes = plt.subplots(1, 3, figsize=(15, max(6, len(syms) * 0.55)))
    fig.patch.set_facecolor('#ffffff')

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    fig.suptitle(
        f'Altcoin Potential Screener — {now_str}\nShortlist Kandidat Derivatif Trading',
        fontsize=11, fontweight='bold', color='#111118', y=1.03
    )

    y_pos = np.arange(len(syms))

    # Panel 1: Multi-Factor Score
    ax1 = axes[0]
    ax1.set_facecolor('#fafafa')
    ax1.barh(y_pos, scores, color=score_colors, height=0.6, edgecolor='none')
    for i, (val, t) in enumerate(zip(scores, tiers)):
        ax1.text(val + 0.01, i, f'{val:+.2f}',
                 va='center', ha='left', fontsize=8,
                 color='#111118', fontfamily='monospace')
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(syms, fontsize=8.5, color='#111118')
    ax1.set_xlabel('Multi-Factor Score', fontsize=8, color='#555566')
    ax1.set_title('Multi-Factor Score\n(IC-weighted)', fontsize=9,
                  fontweight='bold', color='#111118')
    ax1.axvline(0, color='#cccccc', lw=1)
    ax1.tick_params(labelsize=7, colors='#555566')
    for sp in ax1.spines.values(): sp.set_color('#ddddee')
    p1 = mpatches.Patch(color=PINK_DARK,  label='Tier A')
    p2 = mpatches.Patch(color=PINK_LIGHT, label='Tier B')
    ax1.legend(handles=[p1, p2], fontsize=7, loc='lower right',
               facecolor='white', edgecolor='#ddddee')

    # Panel 2: Funding Rate
    ax2 = axes[1]
    ax2.set_facecolor('#fafafa')
    ax2.barh(y_pos, fr_vals, color=fr_colors, height=0.6, edgecolor='none')
    for i, val in enumerate(fr_vals):
        ax2.text(val - 0.03 if val < 0 else val + 0.03, i,
                 f'{val:+.2f}%', va='center',
                 ha='right' if val < 0 else 'left',
                 fontsize=8, color='#111118', fontfamily='monospace')
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(syms, fontsize=8.5, color='#111118')
    ax2.set_xlabel('Funding Rate (%)', fontsize=8, color='#555566')
    ax2.set_title('Funding Rate\n(negatif = short bias = potensi squeeze)',
                  fontsize=9, fontweight='bold', color='#111118')
    ax2.axvline(0, color='#cccccc', lw=1)
    ax2.tick_params(labelsize=7, colors='#555566')
    for sp in ax2.spines.values(): sp.set_color('#ddddee')
    p3 = mpatches.Patch(color=PINK_DARK,  label='Negatif (bullish)')
    p4 = mpatches.Patch(color=PINK_LIGHT, label='Positif (crowded)')
    ax2.legend(handles=[p3, p4], fontsize=7, loc='lower right',
               facecolor='white', edgecolor='#ddddee')

    # Panel 3: L/S Ratio
    ax3 = axes[2]
    ax3.set_facecolor('#fafafa')
    ax3.barh(y_pos, ls_vals, color=ls_colors, height=0.6, edgecolor='none')
    for i, val in enumerate(ls_vals):
        ax3.text(val + 0.01, i, f'{val:.2f}',
                 va='center', ha='left', fontsize=8,
                 color='#111118', fontfamily='monospace')
    ax3.set_yticks(y_pos)
    ax3.set_yticklabels(syms, fontsize=8.5, color='#111118')
    ax3.set_xlabel('Long/Short Ratio', fontsize=8, color='#555566')
    ax3.set_title('Long/Short Ratio\n(>1.5 = crowded long = hati-hati)',
                  fontsize=9, fontweight='bold', color='#111118')
    ax3.axvline(1.0, color='#cccccc', lw=1)
    ax3.axvline(LS_CROWDED_LONG, color='#ffaaaa', lw=0.8, ls='--', alpha=0.7,
                label=f'Warning ({LS_CROWDED_LONG})')
    ax3.tick_params(labelsize=7, colors='#555566')
    for sp in ax3.spines.values(): sp.set_color('#ddddee')
    ax3.legend(fontsize=7, loc='lower right', facecolor='white', edgecolor='#ddddee')

    plt.tight_layout()

    # Simpan ke buffer (tidak perlu file di disk)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    plt.close()
    return buf


# ════════════════════════════════════════════════════════════
# TRADING PLAN
# ════════════════════════════════════════════════════════════

def build_plan(symbol, entry, capital, sl_pct, rr, win_rate, direction='LONG'):
    sl     = entry * (1 - sl_pct) if direction == 'LONG' else entry * (1 + sl_pct)
    tp     = entry * (1 + sl_pct * rr) if direction == 'LONG' else entry * (1 - sl_pct * rr)
    risk   = capital * sl_pct
    reward = capital * sl_pct * rr
    ev     = (win_rate * reward) - ((1 - win_rate) * risk)
    kelly  = max(0, min((win_rate * rr - (1 - win_rate)) / rr, 0.25))
    return dict(
        symbol=symbol, direction=direction,
        entry=round(entry, 6), sl=round(sl, 6), tp=round(tp, 6),
        sl_pct=round(sl_pct * 100, 2), tp_pct=round(sl_pct * rr * 100, 2),
        capital=round(capital, 2), risk=round(risk, 2),
        reward=round(reward, 2), ev=round(ev, 2),
        kelly=round(kelly * 100, 1), ev_pos=ev > 0
    )


# ════════════════════════════════════════════════════════════
# TELEGRAM SENDER
# ════════════════════════════════════════════════════════════

def send_photo(token, chat_id, buf, caption=''):
    url = f'https://api.telegram.org/bot{token}/sendPhoto'
    buf.seek(0)
    r = requests.post(url,
        data={'chat_id': chat_id, 'caption': caption},
        files={'photo': ('screener.png', buf, 'image/png')},
        timeout=30)
    return r.status_code == 200


def send_message(token, chat_id, text):
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    # Split kalau terlalu panjang (Telegram max 4096 chars)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        r = requests.post(url,
            json={'chat_id': chat_id, 'text': chunk},
            timeout=30)
        if r.status_code != 200:
            print(f'Telegram error: {r.json()}')
    return True


def format_usd(val):
    if val >= 1e9: return f'${val/1e9:.1f}B'
    if val >= 1e6: return f'${val/1e6:.1f}M'
    if val >= 1e3: return f'${val/1e3:.1f}K'
    return f'${val:.0f}'


def format_report(ranking, plans, regime, confidence, regime_score):
    now = datetime.now().strftime('%d %b %Y %H:%M')

    msg  = f'ALTCOIN SCREENER — {now} WIB\n'
    msg += f'Regime: {regime} ({confidence:.0%}) | Score: {regime_score:+.4f}\n'
    msg += '─' * 38 + '\n\n'

    # Confirmed candidates
    longs  = [p for p in plans if p['direction'] == 'LONG']
    shorts = [p for p in plans if p['direction'] == 'SHORT']

    if longs:
        msg += 'LONG CANDIDATES\n'
        for p in longs:
            row = ranking.loc[p['symbol']]
            ev_tag = 'EV+' if p['ev_pos'] else 'EV-'
            msg += f"  {p['symbol'].replace('USDT','')} [{row['tier']}]\n"
            msg += f"  Entry ${p['entry']} | SL ${p['sl']} | TP ${p['tp']}\n"
            msg += f"  FR={row['fr']:+.2f}% | L/S={row['ls']:.2f} | [{ev_tag}] EV=${p['ev']:+.2f}\n\n"

    if shorts:
        msg += 'SHORT CANDIDATES\n'
        for p in shorts:
            row = ranking.loc[p['symbol']]
            ev_tag = 'EV+' if p['ev_pos'] else 'EV-'
            msg += f"  {p['symbol'].replace('USDT','')} [SHORT]\n"
            msg += f"  Entry ${p['entry']} | SL ${p['sl']} | TP ${p['tp']}\n"
            msg += f"  FR={row['fr']:+.2f}% | L/S={row['ls']:.2f} | [{ev_tag}] EV=${p['ev']:+.2f}\n\n"

    if not longs and not shorts:
        msg += 'Tidak ada kandidat yang lolos triple confirmation saat ini.\n\n'

    # Risk summary
    if plans:
        total_risk = sum(p['risk'] for p in plans)
        total_ev   = sum(p['ev'] for p in plans)
        msg += f'RISK SUMMARY\n'
        msg += f'  Max loss : -${total_risk:.2f}\n'
        msg += f'  Total EV : +${total_ev:.2f}\n\n'

    # TOP 10
    msg += 'TOP 10 SCORE\n'
    for sym, row in ranking.head(10).iterrows():
        sym_s  = sym.replace('USDT', '')
        tier_s = {'TIER_A':'A','TIER_B':'B','SHORT':'S','NEUTRAL':'N'}.get(row['tier'], '?')
        msg += f"  {sym_s:<10} {row['composite_score']:+.3f} [{tier_s}] FR={row.get('fr',0):+.2f}%\n"

    msg += '\nData valid intraday saja. Update tiap 4 jam.'
    return msg


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════

def main():
    print(f'[{datetime.now().strftime("%H:%M:%S")}] Screener started')

    if not TELEGRAM_TOKEN:
        print('ERROR: TELEGRAM_TOKEN tidak ditemukan di environment variable')
        return

    # 1. Fetch semua koin
    print('Fetching data...')
    all_data, all_meta, failed = [], [], []

    for sym in SYMBOLS:
        print(f'  {sym}...', end=' ', flush=True)
        df, meta = compute_signals(sym)
        if df is not None and len(df) > 20 and meta is not None:
            all_data.append(df)
            all_meta.append(meta)
            print(f'OK | FR={meta["fr"]:+.2f}% | L/S={meta["ls"]:.2f}')
        else:
            failed.append(sym)
            print('SKIP')

    if not all_data:
        send_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                     'ERROR: Tidak ada data berhasil diambil. Cek koneksi.')
        return

    master  = pd.concat(all_data)
    meta_df = pd.DataFrame(all_meta).set_index('symbol')
    print(f'Master: {len(master):,} rows | {master["symbol"].nunique()} coins')
    if failed:
        print(f'Failed: {failed}')

    # 2. IC
    print('Computing IC...')
    ic_results = compute_ic(master)

    # 3. Regime
    print('Detecting regime...')
    regime, regime_score, confidence = detect_regime(master)
    regime_weights = get_regime_weights(regime, confidence, ic_results)
    print(f'Regime: {regime} ({confidence:.0%})')

    # 4. Scoring & ranking
    print('Computing scores...')
    ranking = compute_composite(master, meta_df, ic_results, regime_weights)

    # 5. Triple confirmation
    print('Running triple confirmation...')
    plans = []
    score_total = ranking[ranking['tier'] != 'NEUTRAL']['composite_score'].abs().sum()

    for sym, row in ranking[ranking['tier'] != 'NEUTRAL'].iterrows():
        confirmed, direction, checks = triple_confirmation(
            row['composite_score'],
            row.get('fr', 0),
            row.get('ls', 1.0),
            row['tier']
        )
        if confirmed and direction:
            alloc = (abs(row['composite_score']) / score_total) * TOTAL_CAPITAL if score_total > 0 else 100
            p = build_plan(sym, row['close'], alloc,
                           MAX_RISK_PCT, TARGET_RR, WIN_RATE, direction)
            plans.append(p)
            print(f'  CONFIRMED: {sym} {direction}')

    # 6. Build chart
    print('Building chart...')
    chart_buf = build_chart(ranking)

    # 7. Format report
    report = format_report(ranking, plans, regime, confidence, regime_score)

    # 8. Kirim ke Telegram
    print('Sending to Telegram...')
    now_str = datetime.now().strftime('%d %b %Y %H:%M WIB')
    ok_photo = send_photo(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                          chart_buf, caption=f'Screener Update — {now_str}')
    ok_text  = send_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, report)

    if ok_photo and ok_text:
        print('SUCCESS: Report sent to Telegram')
    else:
        print('WARNING: Some messages failed')

    print(f'[{datetime.now().strftime("%H:%M:%S")}] Done')


if __name__ == '__main__':
    main()
