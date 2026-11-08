"""波段系统：组合级回测引擎 + 每日扫描。

数据：Yahoo Finance 日线，OHLC 按 adjclose/close 做分红复权。
执行：信号在 t 日收盘确认，t+1 日开盘买入；止损盘中触发（跳空低开则按开盘价成交）。
资金：波段资金 CAPITAL；单笔风险 RISK（总资金 0.5%）。
"""
import json, os, datetime as dt
import numpy as np, pandas as pd

CAPITAL = 210_000        # 波段仓 = 30 万 × 70%
RISK = 1_500             # 单笔最大风险 = 30 万 × 0.5%
COST = 0.0005            # 单边成本
MAX_POS = 10             # 最多同时持有
MAX_WEIGHT = 0.30        # 单只股票最大占波段资金比例
STOP_ATR = 2.0           # 初始止损 = 入场价 − 2 ATR
TRAIL_ATR = 3.0          # 移动止损 = 持仓以来最高收盘 − 3 ATR
PYR_STEP = 2.0           # 顺势加仓：每上涨 2 ATR 加一次
PYR_MAX = 2
AVG_STOP_ATR = 3.0       # 回调加仓模式：止损放宽到 3 ATR
AVG_STEP = 1.5           # 回调 1.5 ATR 时加第二批


def load(data_dir, tickers):
    frames = {}
    for t in tickers:
        p = os.path.join(data_dir, f"{t}.json")
        try:
            r = json.load(open(p))["chart"]["result"][0]
        except Exception:
            continue
        q = r["indicators"]["quote"][0]
        adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
        idx = pd.to_datetime([dt.datetime.fromtimestamp(x, dt.UTC).date() for x in r["timestamp"]])
        df = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close", "volume"]}, index=idx)
        df["adj"] = adj if adj else df["close"]
        df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
        f = df["adj"] / df["close"]
        for k in ["open", "high", "low", "close"]:
            df[k] = df[k] * f
        frames[t] = df
    return frames


def panel(frames, calendar):
    P = {k: pd.DataFrame({t: f[k] for t, f in frames.items()}).reindex(calendar)
         for k in ["open", "high", "low", "close", "volume"]}
    C, H, L = P["close"], P["high"], P["low"]
    tr = pd.concat([(H - L).stack(), (H - C.shift()).abs().stack(), (L - C.shift()).abs().stack()], axis=1).max(axis=1).unstack()
    P["atr"] = tr.rolling(14).mean()
    P["ma20"], P["ma50"], P["ma200"] = (C.rolling(n).mean() for n in (20, 50, 200))
    P["hh55"] = C.rolling(55).max().shift(1)
    P["rs"] = C / C.shift(126) - 1
    trend = (C > P["ma200"]) & (P["ma50"] > P["ma200"])
    P["sig_pullback"] = trend & (C.shift(1) <= P["ma20"].shift(1)) & (C > P["ma20"]) & (C > P["ma50"])
    P["sig_breakout"] = trend & (C > P["hh55"]) & (C.shift(1) <= P["hh55"].shift(1))
    return P


def plan_position(entry, atr, mode, cash, equity):
    """返回首笔股数、止损价、加仓计划。"""
    if mode == "average":
        stop = entry - AVG_STOP_ATR * atr
        per = RISK / ((AVG_STOP_ATR + (AVG_STOP_ATR - AVG_STEP)) * atr)
        adds = [("dip", entry - AVG_STEP * atr)]
    else:
        stop = entry - STOP_ATR * atr
        per = RISK / (STOP_ATR * atr)
        adds = [("up", entry + PYR_STEP * atr * (i + 1)) for i in range(PYR_MAX)] if mode == "pyramid" else []
    cap = min(cash, MAX_WEIGHT * equity) / entry
    sh = int(min(per, cap))
    if sh < 0.5 * per:          # 资金不够半仓就放弃
        sh = 0
    return sh, stop, adds, int(per)


def backtest(P, entry_type, mode, start="2017-09-01", market=None):
    C, O, H, L, A = P["close"], P["open"], P["high"], P["low"], P["atr"]
    sig = P[f"sig_{entry_type}"]
    days = C.index[C.index >= start]
    cash, positions, trades, curve = CAPITAL, {}, [], []
    pending = []
    for d in days:
        i = C.index.get_loc(d)
        # 1) 开盘：执行昨日信号
        for t in pending:
            o = O.at[d, t]
            if np.isnan(o) or t in positions or len(positions) >= MAX_POS:
                continue
            atr = A.iloc[i - 1][t]
            equity = cash + sum(p["sh"] * C.iloc[i - 1][k] for k, p in positions.items())
            sh, stop, adds, unit = plan_position(o, atr, mode, cash, equity)
            if sh == 0 or o <= stop:
                continue
            cash -= sh * o * (1 + COST)
            positions[t] = dict(sh=sh, cost=sh * o, entry=o, entry_date=d, stop=stop, atr0=atr,
                                adds=adds, unit=unit, hi=o, n_add=0)
        pending = []
        # 2) 盘中：加仓与止损
        for t in list(positions):
            p = positions[t]
            o, h, l = O.at[d, t], H.at[d, t], L.at[d, t]
            if np.isnan(o):
                continue
            if mode == "average" and p["adds"]:
                _, lvl = p["adds"][0]
                if l <= lvl and lvl > p["stop"]:
                    px = min(o, lvl)
                    sh2 = int(min(p["unit"], cash / px))
                    if sh2 > 0:
                        cash -= sh2 * px * (1 + COST); p["sh"] += sh2; p["cost"] += sh2 * px; p["n_add"] += 1
                    p["adds"] = []
            stop_px = None
            if o <= p["stop"]:
                stop_px = o
            elif l <= p["stop"]:
                stop_px = p["stop"]
            if stop_px is not None:
                cash += p["sh"] * stop_px * (1 - COST)
                pnl = p["sh"] * stop_px * (1 - COST) - p["cost"] * (1 + COST)
                trades.append(dict(ticker=t, entry_date=p["entry_date"], exit_date=d, entry=p["entry"],
                                   exit=stop_px, sh=p["sh"], adds=p["n_add"], pnl=pnl, R=pnl / RISK))
                del positions[t]
                continue
            if mode == "pyramid" and p["adds"]:
                _, lvl = p["adds"][0]
                if h >= lvl:
                    px = max(o, lvl)
                    equity = cash + sum(q["sh"] * C.iloc[i - 1][k] for k, q in positions.items())
                    room = MAX_WEIGHT * equity - p["sh"] * px
                    sh2 = int(max(0, min(p["unit"], cash / px, room / px)))
                    if sh2 > 0:
                        cash -= sh2 * px * (1 + COST); p["sh"] += sh2; p["cost"] += sh2 * px; p["n_add"] += 1
                        # 止损上移：上一档买入价（首次加仓即成本价）
                        p["stop"] = max(p["stop"], p["entry"] if p["n_add"] == 1 else lvl - PYR_STEP * p["atr0"])
                    p["adds"].pop(0)
        # 3) 收盘：更新移动止损，生成明日信号
        for t, p in positions.items():
            c, a = C.at[d, t], A.at[d, t]
            if np.isnan(c):
                continue
            p["hi"] = max(p["hi"], c)
            p["stop"] = max(p["stop"], p["hi"] - TRAIL_ATR * a)
        equity = cash + sum(p["sh"] * (C.at[d, t] if not np.isnan(C.at[d, t]) else p["entry"]) for t, p in positions.items())
        curve.append((d, equity, len(positions)))
        if market is not None and not market.get(d, True):
            continue
        s = sig.loc[d]
        cand = [t for t in s.index[s.fillna(False).values] if t not in positions and not np.isnan(A.at[d, t])]
        cand.sort(key=lambda t: -(P["rs"].at[d, t] if not np.isnan(P["rs"].at[d, t]) else -9))
        pending = cand[: max(0, MAX_POS - len(positions))]
    eq = pd.DataFrame(curve, columns=["date", "equity", "n"]).set_index("date")
    return eq, pd.DataFrame(trades), positions, pending


def stats(eq, trades, start=None, end=None):
    e = eq.equity.loc[start:end]
    r = e.pct_change().dropna()
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1
    mdd = (e / e.cummax() - 1).min()
    tr = trades
    if len(tr):
        tr = tr[(tr.exit_date >= (pd.Timestamp(start) if start else tr.exit_date.min())) &
                (tr.exit_date <= (pd.Timestamp(end) if end else tr.exit_date.max()))]
    win = (tr.pnl > 0).mean() if len(tr) else np.nan
    pf = tr.pnl[tr.pnl > 0].sum() / -tr.pnl[tr.pnl < 0].sum() if len(tr) and (tr.pnl < 0).any() else np.nan
    return dict(年化=cagr * 100, 最大回撤=mdd * 100, 夏普=r.mean() / r.std() * np.sqrt(252),
                交易数=len(tr), 胜率=win * 100, 盈亏比=pf, 平均R=tr.R.mean() if len(tr) else np.nan,
                平均持仓数=eq.n.loc[start:end].mean())
