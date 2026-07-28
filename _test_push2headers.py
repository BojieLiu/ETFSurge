#!/usr/bin/env python3
"""Test push2delay API with different header configurations."""
import urllib.request, json

url = 'https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23'

# Test 1: Minimal headers (current approach)
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    r = urllib.request.urlopen(req, timeout=10)
    data = json.loads(r.read().decode())
    items = data.get('data',{}).get('diff',[])
    print(f'1. Minimal headers: {len(items)} items')
except Exception as e:
    print(f'1. Minimal headers FAILED: {e}')

# Test 2: Full browser headers
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://quote.eastmoney.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}
req2 = urllib.request.Request(url, headers=headers)
try:
    r2 = urllib.request.urlopen(req2, timeout=10)
    data2 = json.loads(r2.read().decode())
    items2 = data2.get('data',{}).get('diff',[])
    print(f'2. Browser headers: {len(items2)} items')
    if items2:
        print(f'   Sample: {items2[0]}')
except Exception as e:
    print(f'2. Browser headers FAILED: {e}')

# Test 3: Sina K-line API (used by factor_registry)
url3 = 'http://hq.sinajs.cn/list=sh510050'
req3 = urllib.request.Request(url3, headers={'User-Agent': 'Mozilla/5.0'})
try:
    r3 = urllib.request.urlopen(req3, timeout=10)
    body = r3.read().decode('gbk', errors='ignore')
    print(f'3. Sina minimal: {body[:100]}')
except Exception as e:
    print(f'3. Sina minimal FAILED: {e}')

# Test 4: Sina with proper Referer
req4 = urllib.request.Request(url3, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.sina.com.cn/',
})
try:
    r4 = urllib.request.urlopen(req4, timeout=10)
    body = r4.read().decode('gbk', errors='ignore')
    print(f'4. Sina with Referer: {body[:100]}')
except Exception as e:
    print(f'4. Sina with Referer FAILED: {e}')

# Test 5: EastMoney ETF NAV API (used by fund_fetcher)
url5 = 'http://fundgz.1234567.com.cn/js/510050.js'
req5 = urllib.request.Request(url5, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://fund.eastmoney.com/',
})
try:
    r5 = urllib.request.urlopen(req5, timeout=10)
    body = r5.read().decode('utf-8', errors='ignore')
    print(f'5. Fund NAV API: {body[:80]}')
except Exception as e:
    print(f'5. Fund NAV API FAILED: {e}')
