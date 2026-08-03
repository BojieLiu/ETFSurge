"""round6 多市场测试第二批：重跑失败项 + news-impact。"""
import subprocess, sys, time

CASES = [
    ("report", ["A"]),
    ("advice", ["当前A股市场怎么配置？"]),
    ("sector", ["半导体"]),
    ("concept", ["AI"]),
    ("index", ["沪深300"]),
    ("symbol", ["510300", "ETF"]),
    ("symbol", ["513010", "HK"]),
]

if __name__ == "__main__":
    start = time.time()
    for i, (cmd, args) in enumerate(CASES, 1):
        t0 = time.time()
        print(f"\n========== [{i}/{len(CASES)}] {cmd} {' '.join(args)} ==========", flush=True)
        rc = subprocess.call([sys.executable, "diag/market_diag.py", cmd] + args)
        print(f"  -> exit={rc}, elapsed={time.time()-t0:.1f}s", flush=True)
    print(f"\nALL DONE in {time.time()-start:.1f}s")
