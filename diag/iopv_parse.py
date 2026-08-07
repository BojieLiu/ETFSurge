# -*- coding: utf-8 -*-
"""验证 IOPV 三个解析函数的实际输�?""
import asyncio
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

SINA = ["sh510050", "sh510880"]
EM_SYMS = ["510050", "510880"]


async def main():
    from app.factors.factor_registry import (
        _fetch_iopv_from_sina,
        _fetch_iopv_from_qq,
        _fetch_iopv_from_em,
    )

    sina = await _fetch_iopv_from_sina(SINA)
    print("sina parsed:", sina)
    qq = await _fetch_iopv_from_qq(SINA)
    print("qq parsed:", qq)
    em = await _fetch_iopv_from_em(EM_SYMS)
    print("em parsed:", em)

    # 原始 sina 全字段找 IOPV 实际位置
    import urllib.request

    req = urllib.request.Request(
        "http://hq.sinajs.cn/list=sh510050", headers={"Referer": "http://finance.sina.com.cn"}
    )
    raw = urllib.request.urlopen(req, timeout=8).read().decode("gbk")
    parts = raw.split('"')[1].split(",")
    print("\nsina fields (len=%d):" % len(parts))
    for i, p in enumerate(parts[:40]):
        print(f"  [{i}] = {p!r}")


asyncio.run(main())

