"""把扫描与回测结果整理成看板用的数据文件（每个文件是一张表）。"""
import sys, os, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing_engine as E

D, SRC, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)
d = json.load(open(SRC))
w = lambda name, rows: json.dump(rows, open(os.path.join(OUT, f"{name}.json"), "w"), ensure_ascii=False)

w("signals", d["signals"])
# 回测净值会随时间复利放大，但实盘波段资金固定为 CAPITAL：单只持仓按 MAX_WEIGHT × CAPITAL 封顶
cap = E.MAX_WEIGHT * E.CAPITAL
for p in d["positions"]:
    p["model_shares"] = p["shares"]
    lim = int(cap // p["close"])
    p["capped"] = p["shares"] > lim
    p["shares"] = min(p["shares"], lim)
    p["value"] = round(p["shares"] * p["close"])
    p["pnl"] = round((p["close"] - p["avg_cost"]) * p["shares"])
w("positions", d["positions"])
w("watch", d["watch"])
w("curve", [dict(month=x, strat=s, qqq=q) for x, s, q in zip(d["curve"]["x"], d["curve"]["strat"], d["curve"]["qqq"])])
w("yearly", d["yearly"])
w("trades", d["trades"])
cmp = [dict(strategy=r["策略"], period=r["区间"], cagr=r["年化"], mdd=r["最大回撤"], sharpe=r["夏普"],
            trades=r["交易数"], win=r["胜率"], pf=r["盈亏比"], avgR=r["平均R"]) for r in d["compare"]]
w("compare", cmp)

# 稳健性：参数敏感性 + 剔除近年新进高涨幅股票
tickers = [f[:-5] for f in os.listdir(D) if f.endswith(".json") and f != "QQQ.json"]
fr = E.load(D, tickers + ["QQQ"]); q = fr.pop("QQQ"); P = E.panel(fr, q.index)
rows = []
for s in [1.5, 2.0, 2.5]:
    for t in [2.5, 3.0, 4.0]:
        E.STOP_ATR, E.TRAIL_ATR, E.PYR_STEP = s, t, s
        eq, tr, _, _ = E.backtest(P, "pullback", "pyramid")
        a, b = E.stats(eq, tr), E.stats(eq, tr, "2022-01-01", None)
        rows.append(dict(test=f"止损 {s} ATR / 移动止损 {t} ATR" + ("（当前）" if (s, t) == (2.0, 3.0) else ""),
                         group="参数敏感性（纳指100 全部）", cagr=round(a["年化"], 2), mdd=round(a["最大回撤"], 2),
                         sharpe=round(a["夏普"], 2), oos_cagr=round(b["年化"], 2), oos_mdd=round(b["最大回撤"], 2)))
E.STOP_ATR, E.TRAIL_ATR, E.PYR_STEP = 2.0, 3.0, 2.0
excl = {'APP','PLTR','MSTR','AXON','RKLB','ALAB','NBIS','CRWV','LITE','SNDK','STX','WDC','TER','ARM','SHOP','ALNY','SPCX','HONA','FER','TRI'}
P2 = E.panel({k: v for k, v in fr.items() if k not in excl}, q.index)
names = {"pullback": "回调买入", "breakout": "突破买入", "none": "不加仓", "pyramid": "顺势加仓", "average": "回调加仓"}
for et, m in [("pullback", "pyramid"), ("pullback", "none"), ("pullback", "average"), ("breakout", "pyramid")]:
    eq, tr, _, _ = E.backtest(P2, et, m)
    a, b = E.stats(eq, tr), E.stats(eq, tr, "2022-01-01", None)
    rows.append(dict(test=f"{names[et]}+{names[m]}", group=f"剔除 {len(excl)} 只近年新进高涨幅股",
                     cagr=round(a["年化"], 2), mdd=round(a["最大回撤"], 2), sharpe=round(a["夏普"], 2),
                     oos_cagr=round(b["年化"], 2), oos_mdd=round(b["最大回撤"], 2)))
w("robust", rows)

m, t = d["meta"], d["tstats"]
best = next(r for r in cmp if r["strategy"] == "回调买入+顺势加仓" and r["period"].startswith("全样本"))
best_oos = next(r for r in cmp if r["strategy"] == "回调买入+顺势加仓" and r["period"].startswith("样本外"))
qqq_full = next(r for r in cmp if r["strategy"] == "QQQ 买入持有" and r["period"].startswith("全样本"))
bias = next(r for r in rows if r["test"] == "回调买入+顺势加仓")
summary = [dict(date=m["date"], capital=m["capital"], total=m["total"], risk=m["risk"], max_pos=m["max_pos"],
                qqq=m["qqq"], qqq_ma200=m["qqq_ma200"], qqq_vs_ma200=round((m["qqq"] / m["qqq_ma200"] - 1) * 100, 1),
                regime_ok=m["regime_ok"], n_uptrend=m["n_uptrend"], n_valid=m["n_valid"], universe=m["universe"],
                n_signals=len(d["signals"]), n_positions=len(d["positions"]), n_watch=len(d["watch"]),
                model_value=round(sum(p["value"] for p in d["positions"])),
                model_weight=round(sum(p["value"] for p in d["positions"]) / E.CAPITAL * 100, 1),
                trades=t["n"], win=t["win"], avgR=t["avgR"], avg_win_R=t["avg_win_R"], avg_loss_R=t["avg_loss_R"],
                pct_with_add=t["pct_with_add"], R_with_add=t["R_with_add"], R_no_add=t["R_no_add"],
                best_cagr=round(best["cagr"], 1), best_mdd=round(best["mdd"], 1), best_oos_cagr=round(best_oos["cagr"], 1),
                qqq_cagr=round(qqq_full["cagr"], 1), qqq_mdd=round(qqq_full["mdd"], 1),
                bias_cagr=bias["cagr"], bias_oos_cagr=bias["oos_cagr"])]
w("summary", summary)
print(json.dumps(summary[0], ensure_ascii=False)); print(json.dumps(rows, ensure_ascii=False))
for f in sorted(os.listdir(OUT)): print(f, os.path.getsize(os.path.join(OUT, f)))
