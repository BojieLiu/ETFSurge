# -*- coding: utf-8 -*-
"""单独�?EM 解析 + sina 全字段定�?IOPV"""
import asyncio
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


async def main():
    from app.factors.factor_registry import _fetch_iopv_from_em

    em = await _fetch_iopv_from_em(["510050", "510880"])
    print("em parsed:", em)

    import urllib.request

    req = urllib.request.Request(
        "http://hq.sinajs.cn/list=sh510050", headers={"Referer": "http://finance.sina.com.cn"}
    )
    raw = urllib.request.urlopen(req, timeout=8).read().decode("gbk")
    parts = raw.split('"')[1].split(",")
    print("\nsina fields (len=%d):" % len(parts))
    for i, p in enumerate(parts[:45]):
        print(f"  [{i}] = {p!r}")

    # QQ 全字段（GBK 解码�?    req2 = urllib.request.Request("http://qt.gtimg.cn/q=sh510050", headers={"User-Agent": "Mozilla/5.0"})
    raw2 = urllib.request.urlopen(req2, timeout=8).read().decode("gbk")
    parts2 = raw2.split('"')[1].split("~")
    print("\nqq fields (len=%d):" % len(parts2))
    for i, p in enumerate(parts2[:35]):
        print(f"  [{i}] = {p!r}")


asyncio.run(main())

