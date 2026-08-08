# -*- coding: utf-8 -*-
"""round9: 实测 sina/qq/em 三源真实字段（UTF-8 版本）"""
import urllib.request


def probe(name, url, headers):
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=8)
        return name, resp.status, resp.read()
    except Exception as e:
        return name, "FAIL", str(e)[:150]


def dump(name, raw, decoders, sep):
    print("=" * 20, name, "=" * 20)
    for enc in decoders:
        try:
            txt = raw.decode(enc)
            break
        except Exception:
            continue
    else:
        txt = raw.decode("utf-8", errors="replace")
    for line in txt.strip().split("\n"):
        if sep not in line:
            continue
        head = line.split("=")[0]
        parts = line.split('"')[1].split(sep)
        print("  ", head, "nfields=", len(parts))
        for i, p in enumerate(parts):
            if p:
                print("    [%d]=%r" % (i, p[:40]))


name, st, raw = probe("sina", "http://hq.sinajs.cn/list=sh510050,sh510880", {"Referer": "http://finance.sina.com.cn"})
print("SINA status:", st)
if st == 200:
    dump("sina", raw, ["gbk", "utf-8"], ",")

name, st, raw = probe("qq", "http://qt.gtimg.cn/q=sh510050,sh510880", {"User-Agent": "Mozilla/5.0"})
print("QQ status:", st)
if st == 200:
    dump("qq", raw, ["gbk", "utf-8"], "~")

for host in ["push2.eastmoney.com", "push2delay.eastmoney.com"]:
    url = "https://%s/api/qt/ulist.np/get?secids=1.510050,1.510880&fields=f12,f13,f2,f236&fltt=2&invt=2" % host
    name, st, raw = probe("em-%s" % host, url, {"User-Agent": "Mozilla/5.0"})
    print("EM(%s) status: %s" % (host, st))
    if st == 200:
        print("   body:", raw[:300])

# clist/get 对照（文档称 f236 在 clist 中）
url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=3&po=1&np=1&fltt=2&invt=2&fid=f12&fs=b:MK0021&fields=f12,f13,f2,f3,f236"
name, st, raw = probe("em-clist", url, {"User-Agent": "Mozilla/5.0"})
print("EM(clist b:MK0021) status:", st)
if st == 200:
    print("   body:", raw[:600])
