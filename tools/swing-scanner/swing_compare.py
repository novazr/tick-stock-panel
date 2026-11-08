import sys, os, json, pickle
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing_engine as E

D = sys.argv[1]
OUT = os.path.dirname(os.path.abspath(__file__))
tickers = [f[:-5] for f in os.listdir(D) if f.endswith(".json") and f != "QQQ.json"]
frames = E.load(D, tickers + ["QQQ"])
qqq = frames.pop("QQQ")
cal = qqq.index
P = E.panel(frames, cal)
qc = qqq["close"]
mkt = (qc > qc.rolling(200).mean()).to_dict()

periods = {"全样本 2017.09-2026.11": (None, None), "样本内 2017.09-2021": (None, "2021-12-31"), "样本外 2022-2026.11": ("2022-01-01", None)}
rows, runs = [], {}
names = {"pullback": "回调买入", "breakout": "突破买入", "none": "不加仓", "pyramid": "顺势加仓", "average": "回调加仓"}
for et in ["pullback", "breakout"]:
    for mode in ["none", "pyramid", "average"]:
        for mf in [False, True]:
            eq, tr, pos, pend = E.backtest(P, et, mode, market=mkt if mf else None)
            key = f"{names[et]}+{names[mode]}" + ("+大盘过滤" if mf else "")
            runs[key] = (eq, tr)
            for pn, (s, e) in periods.items():
                st = E.stats(eq, tr, s, e); st.update(策略=key, 区间=pn); rows.append(st)
# QQQ 基准
qe = (qc.loc["2017-09-01":] / qc.loc["2017-09-01":].iloc[0] * E.CAPITAL).to_frame("equity"); qe["n"] = 1
for pn, (s, e) in periods.items():
    st = E.stats(qe, pd.DataFrame(columns=["pnl", "R", "exit_date"]), s, e); st.update(策略="QQQ 买入持有", 区间=pn); rows.append(st)
res = pd.DataFrame(rows)
pd.set_option("display.width", 250)
for pn in periods:
    print(f"\n===== {pn}")
    print(res[res.区间 == pn].drop(columns="区间").set_index("策略").round(2).to_string())
res.round(3).to_csv(os.path.join(OUT, "swing_compare.csv"), index=False, encoding="utf-8-sig")
pickle.dump({"runs": runs, "qqq": qe}, open(os.path.join(OUT, "swing_runs.pkl"), "wb"))
