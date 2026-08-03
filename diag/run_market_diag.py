"""round6 多市场测试驱动器：串行执行 market_diag.py 各用例，避免 LLM 并发限流。"""
import subprocess, sys, time

CASES = [
    ("report", ["A"]),
    ("report", ["HK"]),
    ("report", ["US"]),
    ("advice", ["当前A股市场怎么配置？"]),
    ("symbol", ["600519", "A"]),
    ("symbol", ["510300", "ETF"]),
    ("symbol", ["513010", "HK"]),
    ("symbol", ["513500", "US"]),
    ("sector", ["半导体"]),
    ("concept", ["AI"]),
    ("index", ["沪深300"]),
]

if __name__ == "__main__":
    start = time.time()
    for i, (cmd, args) in enumerate(CASES, 1):
        t0 = time.time()
        print(f"\n========== [{i}/{len(CASES)}] {cmd} {' '.join(args)} ==========", flush=True)
        rc = subprocess.call([sys.executable, "diag/market_diag.py", cmd] + args)
        print(f"  -> exit={rc}, elapsed={time.time()-t0:.1f}s", flush=True)
    print(f"\nALL DONE in {time.time()-start:.1f}s")
