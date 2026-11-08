"""用选定规则（回调买入 + 顺势加仓，止损 2 ATR，移动止损 3 ATR）生成看板数据 JSON。"""
import sys, os, json, pickle
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing_engine as E

D, OUTJ = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
tickers = [f[:-5] for f in os.listdir(D) if f.endswith(".json") and f != "QQQ.json"]
fr = E.load(D, tickers + ["QQQ"]); q = fr.pop("QQQ"); P = E.panel(fr, q.index)
C, A = P["close"], P["atr"]
last = C.index[-1]
qc = q["close"]; q200 = qc.rolling(200).mean()

eq, tr, pos, pend = E.backtest(P, "pullback", "pyramid")
r = lambda x, n=2: None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)

# 1) 新信号：今天收盘触发，明天开盘买入（按收盘价估算）
sig = P["sig_pullback"].loc[last].fillna(False)
cands = [t for t in sig.index[sig.values]]
cands.sort(key=lambda t: -(P["rs"].at[last, t] if not np.isnan(P["rs"].at[last, t]) else -9))
signals = []
for t in cands:
    c, a = C.at[last, t], A.at[last, t]
    sh, stop, adds, unit = E.plan_position(c, a, "pyramid", E.CAPITAL, E.CAPITAL)
    signals.append(dict(ticker=t, close=r(c), atr=r(a), atr_pct=r(a / c * 100, 1), stop=r(stop), shares=sh,
                        amount=r(sh * c, 0), weight=r(sh * c / E.CAPITAL * 100, 1), risk=r(sh * (c - stop), 0),
                        add1=r(adds[0][1]), add2=r(adds[1][1]), add_shares=unit,
                        rs6m=r(P["rs"].at[last, t] * 100, 1), ma20=r(P["ma20"].at[last, t]), ma50=r(P["ma50"].at[last, t]),
                        in_model=t in pend))

# 2) 系统模拟持仓（若从 2017 年起严格执行至今）
positions = []
for t, p in pos.items():
    c = C.at[last, t]
    nxt = p["adds"][0][1] if p["adds"] else None
    positions.append(dict(ticker=t, entry_date=str(p["entry_date"].date()), entry=r(p["entry"]), shares=p["sh"],
                          avg_cost=r(p["cost"] / p["sh"]), close=r(c), value=r(p["sh"] * c, 0),
                          pnl=r(p["sh"] * c - p["cost"], 0), pnl_pct=r((c * p["sh"] / p["cost"] - 1) * 100, 1),
                          stop=r(p["stop"]), dist_stop=r((c / p["stop"] - 1) * 100, 1), adds_done=p["n_add"],
                          next_add=r(nxt)))
positions.sort(key=lambda x: -x["value"])

# 3) 观察名单：趋势向上、正在回调（收盘在 20 日线下方、50 日线上方），重新站上 20 日线即触发
trend = (C.loc[last] > P["ma200"].loc[last]) & (P["ma50"].loc[last] > P["ma200"].loc[last])
setup = trend & (C.loc[last] <= P["ma20"].loc[last]) & (C.loc[last] > P["ma50"].loc[last])
watch = []
for t in setup.index[setup.fillna(False).values]:
    c, m20, a = C.at[last, t], P["ma20"].at[last, t], A.at[last, t]
    watch.append(dict(ticker=t, close=r(c), trigger=r(m20), gap=r((m20 / c - 1) * 100, 1), ma50=r(P["ma50"].at[last, t]),
                      atr_pct=r(a / c * 100, 1), rs6m=r(P["rs"].at[last, t] * 100, 1),
                      est_shares=int(E.RISK / (E.STOP_ATR * a)), est_stop=r(m20 - E.STOP_ATR * a)))
watch.sort(key=lambda x: x["gap"])

# 4) 回测汇总
cmp = pd.read_csv(os.path.join(HERE, "swing_compare.csv"))
cmp = cmp.replace({np.nan: None})
runs = pickle.load(open(os.path.join(HERE, "swing_runs.pkl"), "rb"))
best = runs["runs"]["回调买入+顺势加仓"][0].equity.resample("ME").last()
qq = runs["qqq"].equity.resample("ME").last()
curve = dict(x=[d.strftime("%Y-%m") for d in best.index], strat=[round(v) for v in best.values],
             qqq=[round(v) for v in qq.reindex(best.index).values])
trades = tr.sort_values("exit_date").tail(40).iloc[::-1]
tlog = [dict(ticker=x.ticker, entry_date=str(x.entry_date.date()), exit_date=str(x.exit_date.date()), entry=r(x.entry),
             exit=r(x.exit), shares=int(x.sh), adds=int(x.adds), pnl=r(x.pnl, 0), R=r(x.R)) for x in trades.itertuples()]
yearly = (eq.equity.resample("YE").last().pct_change() * 100).round(1)
yearly.iloc[0] = round((eq.equity.resample("YE").last().iloc[0] / E.CAPITAL - 1) * 100, 1)
qy = (runs["qqq"].equity.resample("YE").last().pct_change() * 100).round(1)
qy.iloc[0] = round((runs["qqq"].equity.resample("YE").last().iloc[0] / E.CAPITAL - 1) * 100, 1)
alltr = tr
out = dict(
    meta=dict(date=str(last.date()), capital=E.CAPITAL, total=300000, risk=E.RISK, max_pos=E.MAX_POS,
              stop_atr=E.STOP_ATR, trail_atr=E.TRAIL_ATR, pyr_step=E.PYR_STEP, universe=len(tickers),
              qqq=r(qc.iloc[-1]), qqq_ma200=r(q200.iloc[-1]), regime_ok=bool(qc.iloc[-1] > q200.iloc[-1]),
              n_uptrend=int(trend.sum()), n_valid=int(C.loc[last].notna().sum())),
    signals=signals, positions=positions, watch=watch, compare=cmp.to_dict("records"), curve=curve, trades=tlog,
    yearly=[dict(year=int(y.year), strat=r(v, 1), qqq=r(qy.get(y), 1)) for y, v in yearly.items()],
    tstats=dict(n=len(alltr), win=r((alltr.pnl > 0).mean() * 100, 1), avgR=r(alltr.R.mean()),
                avg_win_R=r(alltr.R[alltr.R > 0].mean()), avg_loss_R=r(alltr.R[alltr.R <= 0].mean()),
                best_R=r(alltr.R.max()), pct_with_add=r((alltr.adds > 0).mean() * 100, 1),
                R_with_add=r(alltr.R[alltr.adds > 0].mean()), R_no_add=r(alltr.R[alltr.adds == 0].mean())),
)
json.dump(out, open(OUTJ, "w"), ensure_ascii=False)
print(json.dumps(out["meta"], ensure_ascii=False))
print("signals", [(s["ticker"], s["close"], s["shares"], s["amount"], s["stop"], s["add1"]) for s in signals])
print("positions", [(p["ticker"], p["entry_date"], p["shares"], p["pnl_pct"], p["stop"], p["next_add"]) for p in positions])
print("watch", [(w["ticker"], w["close"], w["trigger"], w["gap"]) for w in watch])
print("tstats", out["tstats"])
print("yearly", out["yearly"])
