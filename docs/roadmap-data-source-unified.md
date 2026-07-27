# 鏁版嵁婧愮粺涓€鏀归€犳柟妗?
> 鍒涘缓鏃ユ湡: 2026-07-22 | 鐗堟湰: v3.0 | 涓婃鏇存柊: 2026-07-26
> **鍚堝苟鏇夸唬**锛氭鏂囨。鍚堝苟浜嗕互涓嬩笁浠芥柟妗堢殑浠ｇ爜鏀瑰姩閮ㄥ垎锛屾秷闄ら噸鍙犱笌鍐茬獊锛?> 1. `archived/source-registry-optimization-plan.md` 鈥?China market 鎺ュ叆 SourceRegistry
> 2. `archived/data-source-monitoring-plan.md` 鈥?鏁版嵁婧愬彲瑙傛祴鎬?> 3. `market-awareness-and-data-source-plan.md` 搂4 鈥?缇庤偂鏁版嵁婧愭浛鎹?(yfinance 鈫?Stooq)
>
> **v3.0 鐘舵€佹€昏**锛氶櫎 Phase D7锛堝墠绔洃鎺ч潰鏉匡級澶栵紝鎵€鏈?Phase (A鈫扗6) **鍧囧凡瀹炴柦**銆?> 鏈枃妗ｅ凡浠?瀹炴柦璁″垝"杞崲涓?瀹炴柦鍥為【 + 鍓╀綑浠诲姟鎸囧紩"銆?>
> **v2.0鈫抳3.0 鏇存柊璇存槑**锛?026-07-26 鍏ㄩ噺浠ｇ爜瀹¤鍙戠幇 v2.0 涓殑瀹炴柦鏂规缁濆ぇ閮ㄥ垎宸茶鍚庣画 commits 钀藉湴銆?> 淇锛歅hase A锛圫tooq 宸蹭笅绾库啋瀹為檯涓?TwelveData鈫扚innhub锛夈€?> Phase B锛? 鍑芥暟宸插叏閮ㄦ帴鍏?registry.route() + _filtered price=0 杩囨护锛夈€?> Phase C锛坧robes.py 宸插垱寤哄惈 8 鎺㈤拡锛夈€?> Phase D锛圖1-D6 宸插疄鏂斤紝浠?D7 鍓嶇椤甸潰寰呭畬鎴愶級銆?> 鍒犻櫎浜嗗宸蹭笉瀛樺湪鏂囦欢锛坰tooq_fetcher.py锛夌殑寮曠敤銆?>
> 娑夊強浠ｇ爜瀹¤鏂囦欢锛?026-07-26锛?
>   - `backend/app/fetchers/china_market.py` (961 琛岋紝3 鍑芥暟宸蹭娇鐢?registry.route + _filtered)
>   - `backend/app/services/source_registry.py` (192 琛岋紝宸插惈 route_name 鍙傛暟 + on_event 鍥炶皟 + get_states + circuit_breaker_status)
>   - ~~`backend/app/fetchers/stooq_fetcher.py`~~ **鏂囦欢宸插垹闄?*锛圫tooq CSV API 宸插叧闂繑鍥?404/Cloudflare锛?>   - `backend/app/services/source_health.py` (宸叉湁 register_probe + run_probes + health_loop 鏈哄埗)
>   - `backend/app/services/market_service.py` (982 琛岋紝`_route_us()` 浣跨敤 `TwelveData鈫扚innhub`锛屽凡绉婚櫎 Stooq/AlphaVantage/yfinance)
>   - `backend/app/main.py` (253 琛岋紝宸茶皟鐢?register_all_probes + 鎸傝浇 SourceEventStore 鍥炶皟)
>   - `backend/app/monitor/probes.py` (瀛樺湪锛屾敞鍐?8 涓帰閽堬細6 鏁版嵁婧?+ 2 绾跨▼姹? 鉁?鏂板缓瀹屾垚
>   - `backend/app/monitor/source_events.py` (瀛樺湪锛屽畬鏁?SourceEventStore 瀹炵幇) 鉁?鏂板缓瀹屾垚
>   - `backend/app/routers/admin.py` (瀛樺湪锛? 涓?sources API 绔偣宸插疄鐜?

---

## 鑳屾櫙

杩欎笁浠芥柟妗堝悇鑷鐩栦簡鏁版嵁婧愮殑涓嶅悓鏂归潰锛屼絾鍦?`SourceRegistry`銆乣china_market.py` 闄嶇骇閾俱€佺編鑲¤矾鐢辩瓑鏂归潰澶氬閲嶅彔銆傚悎骞朵负缁熶竴鏂规鍚庯紝鍙澶栨寜搴忓疄鏂姐€侀伩鍏嶅啿绐併€?
缁熶竴鏂规瑕嗙洊涓夊ぇ鐩爣锛?
1. **鎻愬崌鍥藉唴鏁版嵁璺緞闊ф€?* 鈥?mootdx/Sina/QQ 绛夋牳蹇冮檷绾ч摼鎺ュ叆鐔旀柇鍣?2. **鏇挎崲涓嶇ǔ瀹氭暟鎹簮** 鈥?yfinance 鈫?澶氭簮鐔旀柇閾撅紙TwelveData鈫扚innhub锛屽鍐呯洿杩炵ǔ瀹氾級
3. **寤虹珛鍙娴嬫€?* 鈥?鍏ㄩ摼璺簨浠惰褰?+ 鍋ュ悍鎺㈤拡锛堝鐢?`monitor/token_usage.py` 鐨勬ā寮忥級

---

## 浠ｇ爜瀹¤缁撴灉鎽樿锛?026-07-26 鏇存柊锛?
### 宸插氨缁殑鍩虹璁炬柦

| 缁勪欢 | 浣嶇疆 | 褰撳墠鐘舵€?|
|------|------|---------|
| `SourceRegistry.route()` | `services/source_registry.py:106` | 鉁?瀛樺湪锛屽凡鍚?`route_name` 鍙傛暟 + 纭け璐ユ敮鎸?|
| `SourceHealth` 鐔旀柇鍣?| `services/source_registry.py:15` | 鉁?瀛樺湪锛屽凡鍚?`on_event` 鍥炶皟 + `record_hard_failure` |
| 鍋ュ悍鎺㈤拡绯荤粺 | `services/source_health.py` | 鉁?瀛樺湪锛宍register_probe()` + `run_probes()` + `health_loop()` 瀹屾暣 |
| 宸叉敞鍐屾帰閽?| `monitor/probes.py` (via main.py:39) | 鉁?8 涓紙mootdx, sina, tencent, akshare, levistock, dongfang, threadpool_main, threadpool_akshare锛?|
| `Stooq` 鐩稿叧 | 鈥?| 鉂?**宸茬Щ闄?*锛圕SV API 鍏抽棴杩斿洖 404/Cloudflare锛屾枃浠跺凡鍒犻櫎锛?|
| 鐩戞帶妯″潡 | `monitor/token_usage.py` | 鉁?鏈?`TokenUsageStore` 妯″紡鍙鐢?|
| 缇庤偂 `_route_us()` | `market_service.py:762` | 鉁?褰撳墠涓?`TwelveData鈫扚innhub`锛堝凡绉婚櫎 Stooq/AlphaVantage/yfinance锛?|
| China market 闄嶇骇閾?| `china_market.py:444-518` | 鉁?3 鍑芥暟锛圓鑲″疄鏃?鎵归噺/娓偂锛夊潎宸蹭娇鐢?`registry.route()` |
| price=0 杩囨护 | `china_market.py:424-439` | 鉁?`_filtered()` 杈呭姪鍑芥暟鍦?provider lambda 灞傝繃婊?|
| SourceEventStore | `monitor/source_events.py` | 鉁?瀛樺湪锛屽唴瀛樼幆(5000鏉? + SQLite 寮傛鍒风洏 + 7澶╂粴鍔ㄦ竻鐞?|
| 鏁版嵁婧愮洃鎺?API | `routers/admin.py` | 鉁?4 涓鐐癸紙health/timeline/failures/circuit-breakers锛?|
| 鍓嶇鐩戞帶闈㈡澘 | 寰呮柊寤?| 鉂?**鍞竴鏈畬鎴愰」**锛圖7锛?|

### 闇€鏀归€犵殑鍏抽敭缂哄彛

| 缂哄彛 | 娑夊強鏂囦欢 | 涓ラ噸搴?| 鐘舵€?|
|------|---------|--------|:----:|
| China market 闄嶇骇閾剧‖缂栫爜鏈蛋 SR | `china_market.py` | P0 | 鉁?宸插疄鏂?|
| price=0 妫€鏌ュ湪椤跺眰鍑芥暟鑰岄潪 route 涓?| `china_market.py:371,381` | P1 | 鉁?宸插疄鏂斤紙_filtered锛?|
| 浠?2 涓帰閽堬紝缂哄皯 mootdx/sina/tencent/akshare/levistock | `main.py` | P1 | 鉁?宸插疄鏂斤紙8 鎺㈤拡锛?|
| 鏃?SourceEventStore锛屾棤鏁版嵁婧愮洃鎺?API | 闇€鏂板缓 | P2 | 鉁?D1-D6 宸插疄鏂?|
| 鏃犲墠绔暟鎹簮鐩戞帶闈㈡澘 | 闇€鏂板缓 | P2 | 鉂?**D7 寰呭疄鏂?* |
| 闈炰氦鏄撴椂娈?price=0 浼氳璇垽涓哄け璐?| `china_market.py` 鍏ㄩ儴 fetcher | P2 | 鈿狅笍 闇€鐗瑰埆娉ㄦ剰锛坃filtered 宸茬紦瑙ｄ絾闈炰氦鏄撴椂娈典粛鍙兘璇垽锛?|

---

## 鏋舵瀯姒傝锛堝綋鍓嶇姸鎬?2026-07-26锛?
```
鈹屸攢 涓氬姟璺緞 (route_name) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?A_stock_realtime / HK_stock_realtime / US_ETF   鈹?鈹?A_stock_batch / probe / sector                  鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?         鈹?璺敱锛堢粺涓€璧?SourceRegistry.route()锛?         鈻?鈹屸攢 SourceRegistry (鐔旀柇鍣? 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? route(providers, route_name="...")              鈹?鈹?    鈹溾攢 鍐峰嵈鍒ゆ柇 鈫?璺宠繃澶辫触婧?                    鈹?鈹?    鈹溾攢 璋冪敤 鈫?璁℃椂 鈫?result 鏈夋晥鎬у垽鏂?          鈹?鈹?    鈹斺攢 on_event 鍥炶皟 鈫?SourceEventStore.record() 鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?         鈹?闄嶇骇閾撅紙鎸変紭鍏堢骇锛?         鈻?鈹屸攢 鏁版嵁婧?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?A鑲″疄鏃?  mootdx 鈫?Sina                          鈹?鈹?A鑲℃壒閲?  mootdx 鈫?Tencent(QQ) 鈫?Sina           鈹?鈹?娓偂瀹炴椂:  Sina 鈫?Tencent(QQ) 鈫?涓滄柟璐㈠瘜         鈹?鈹?缇庤偂瀹炴椂:  TwelveData 鈫?Finnhub                  鈹? 鈫?v3: 绉婚櫎 Stooq/Alphavantage/yfinance
鈹?鍏ㄧ悆鎸囨暟:  Sina 鈫?TwelveData 鈫?Finnhub           鈹? 鈫?v3: 绉婚櫎 Stooq
鈹?琛屼笟鏉垮潡:  levistock 鈫?akshare                   鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?         鈹?鎺㈤拡 (姣?120s, 8 涓?
         鈻?鈹屸攢 鍙娴嬫€?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?SourceEventStore (澶嶇敤 monitor/token_usage 妯″紡) 鈹?鈹? 鈹溾攢 鍐呭瓨鐜?(5000鏉? 鈫?寮傛鍒风洏 data/source.db   鈹? 鉁?鈹? 鈹溾攢 4 涓?REST API 鈫?admin 璺敱                  鈹? 鉁?鈹? 鈹斺攢 鍓嶇鐩戞帶闈㈡澘锛堥鏍煎榻?TokenMonitor锛?       鈹? 鉂?D7 寰呭疄鏂?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?```

**涓?v2.0 鐨勫叧閿樊寮?*:
- A 鑲?娓偂闄嶇骇閾撅細**宸插叏閮ㄩ€氳繃 registry.route() 绠＄悊鐔旀柇** 鉁?- 缇庤偂瀹炴椂锛?*绉婚櫎 Stooq**锛圓PI 宸插叧锛夈€?*绉婚櫎 AlphaVantage**锛?5娆?澶╅檺棰濓級銆?*绉婚櫎 yfinance**锛堝鍐呬笉绋冲畾锛?- 褰撳墠缇庤偂閾捐矾浠呬负 `TwelveData 鈫?Finnhub`
- 宸叉敞鍐屾帰閽堬細**2 涓?鈫?8 涓?* 鉁?- SourceEventStore锛?*宸插畬鎴?* 鉁?
---

## 瀹炴柦鍥為【涓庡墿浣欎换鍔?
### Phase A 鈥?缇庤偂璺敱閲嶅啓锛堝彇浠?yfinance锛夆渽 **宸插疄鏂?*

**鏉ユ簮**: `market-awareness-and-data-source-plan.md` 搂4.1~4.5

**鐩爣**: 缇庤偂瀹炴椂/鎵归噺/鍘嗗彶鏁版嵁浠?yfinance 涓诲姏鍒囨崲涓哄鍐呯洿杩為摼璺?
**瀹炵幇鎯呭喌**:
- `_route_us()` (market_service.py:762) 鏀逛负 `TwelveData 鈫?Finnhub` 鍙屽眰閾捐矾
- Stooq CSV API 宸插叧闂紙404/Cloudflare锛夛紝`stooq_fetcher.py` 宸插垹闄?- AlphaVantage 鍥?25娆?澶╁厤璐归搴﹀お浣庣Щ鍑洪摼璺?- yfinance 鍥犲鍐呬笉绋冲畾绉诲嚭閾捐矾
- `_route_us()` 鏄?async 鍑芥暟锛屽凡浣跨敤 `registry.route()` 绠＄悊鐔旀柇 + route_name + event recording

**鍏抽敭 commit/鏀瑰姩**:
- 瀹為檯鏀瑰姩涓?v2.0 璁″垝鏈夊亸宸細鍘熸湰璁″垝寮曞叆 Stooq 鍋氫富鍔涳紝浣?Stooq API 宸叉锛涘疄闄呮敼涓虹簿绠€閾?- `_route_us()` docstring 娉ㄩ噴宸叉洿鏂帮細v3 璇存槑绉婚櫎鍘熷洜

**鍏ㄧ悆鎸囨暟閾捐矾瀵归綈**锛?026-07-26锛?.1.2锛?
- `_foreign()` 闄嶇骇閾撅細EM缂撳瓨 鈫?娓偂缂撳瓨 鈫?Sina 鈫?Sina椤甸潰 鈫?Finnhub 鈫?鍗犱綅绗?- `_route_us()` 闄嶇骇閾撅細TwelveData 鈫?Finnhub锛堥€氳繃 `registry.route()`锛?- 鍏ㄧ悆鎸囨暟涓庣編鑲?ETF 鍏辩敤 Finnhub 浣滀负鏈€缁堝厹搴曟簮锛屼絾 `_foreign()` 涓嶇粡杩?`registry.route()`锛堝墠涓ょ骇鏄唴瀛樼紦瀛橈紝涓嶉€傚悎鐔旀柇璺敱妯″紡锛?- 瀵归綈纭锛歚get_global_indices()` docstring 宸叉洿鏂帮紙yfinance鈫扚innhub锛夛紝verify_e2e.py 鏂板 US 涓夊ぇ鎸囨暟锛圫PX/IXIC/DJI锛夎鐩栨柇瑷€ + 浠锋牸闈炵┖妫€鏌?- 缁撹锛氫袱鏉￠摼璺洰鏍囦笉鍚岋紙鎵归噺闈㈡澘 vs 鍗曞彧绮剧‘锛夛紝褰撳墠鐘舵€佸凡婊¤冻闇€姹傦紝鏃犻渶缁熶竴涓哄悓涓€璺敱鏈哄埗

**楠岃瘉** (褰撳墠):
```bash
# 缇庤偂瀹炴椂
curl -s "http://localhost:8000/api/v1/market/realtime/US?symbol=SPY" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: price={d.get(\"price\",0)}' if d.get('price',0)>0 else 'NO DATA')"

# verify_e2e.py 鍏?PASS
cd backend && python scripts/verify_e2e.py
```

---

### Phase B 鈥?China market 鎺ュ叆 SourceRegistry 鉁?**宸插疄鏂?*

**鏉ユ簮**: `archived/source-registry-optimization-plan.md` 搂P0-A

**鐩爣**: `fetch_a_stock_realtime` / `fetch_a_stock_batch` / `fetch_hk_stock_realtime` 涓夊嚱鏁颁粠鎵嬪啓 if-else 鍒囨崲涓?SourceRegistry.route()

**瀹炵幇鎯呭喌**:

| 鍑芥暟 | 琛?| 闄嶇骇閾?| 宸蹭娇鐢?route() | price=0 杩囨护 |
|------|---|--------|:--------------:|:-------------:|
| `fetch_a_stock_realtime` | china_market.py:444 | mootdx 鈫?Sina | 鉁?| 鉁?(_filtered) |
| `fetch_a_stock_batch` | china_market.py:454 | mootdx 鈫?Tencent 鈫?Sina | 鉁?| 鉁?(_filtered) |
| `fetch_hk_stock_realtime` | china_market.py:510 | Sina 鈫?Tencent 鈫?涓滄柟璐㈠瘜 | 鉁?| 鉁?(_filtered) |

**鍏抽敭鎶€鏈喅绛?*:
- `_filtered(provider_fn, *args)` 鍖呰鍑芥暟鍦?china_market.py:424 瀹炵幇鈥斺€斿湪 provider lambda 灞傚仛 price=0 杩囨护锛?  涓嶄慨鏀瑰簳灞?`_mootdx_realtime`/`_sina_realtime`/`_tencent_realtime` 鍑芥暟鐨勮繑鍥炲€煎绾︺€?- `registry.route()` 鐨?`route_name` 鍙傛暟浼犻€掍笟鍔¤矾寰勫悕锛岄厤鍚?SourceEventStore 浜嬩欢杩借釜銆?
**娉ㄦ剰**: 闈炰氦鏄撴椂娈?price=0 浼氳 `_filtered` 杩囨护瀵艰嚧 route() 灏濊瘯涓嬩竴婧愩€?褰撳墠绛栫暐鏄厛璇曞畬鎵€鏈夋簮锛屽叏閮?price=0 鏃惰繑鍥?`[]`銆備氦鏄撴椂娈佃涓烘纭€?
**楠岃瘉** (褰撳墠):
```bash
# A 鑲″疄鏃?鈥?姝ｅ父杩斿洖
curl -s "http://localhost:8000/api/v1/market/realtime/A?symbol=000001" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: price={d.get(\"price\",0)}' if d.get('price',0)>0 else 'NO DATA')"

# 娓偂瀹炴椂 鈥?姝ｅ父杩斿洖
curl -s "http://localhost:8000/api/v1/market/realtime/HK?symbol=00700" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: price={d.get(\"price\",0)}' if d.get('price',0)>0 else 'NO DATA')"

# verify_e2e.py 鍏?PASS
cd backend && python scripts/verify_e2e.py
```

---

### Phase C 鈥?鍋ュ悍鎺㈤拡琛ュ叏 鉁?**宸插疄鏂?*

**鏉ユ簮**: `archived/source-registry-optimization-plan.md` 搂P0-B + `archived/data-source-monitoring-plan.md` 搂5.3

**鐩爣**: 琛ラ綈鎵€鏈夋牳蹇冩暟鎹簮鐨勪富鍔ㄥ仴搴锋帰娴嬶紝瑕嗙洊 6 涓暟鎹簮 + 2 涓嚎绋嬫睜

**瀹炵幇鎯呭喌**:
- 鏂板缓 `backend/app/monitor/probes.py` 鈥?闆嗕腑绠＄悊鍏ㄩ儴鎺㈤拡
- `main.py` 鍦?lifespan 涓皟鐢?`register_all_probes()`锛堜笉鍚唴鑱旀敞鍐岋級
- 鎺㈤拡鍚嶄笌 `SourceRegistry` 涓殑婧愬悕涓€鑷达紙鐔旀柇鐘舵€佸叡浜級
- 鎺㈤拡杩愯闂撮殧 120s锛坔ealth_loop锛?
| 姝ラ | 鎺㈤拡 | 婧愬悕 | 鎺㈡祴鍑芥暟 | 瓒呮椂 | 璇存槑 |
|------|------|------|---------|:----:|------|
| C1 | mootdx | `mootdx` | `_mootdx_realtime(["510050"])` | 8s | 50ETF锛岃交閲忓崟浠ｇ爜鏌ヨ |
| C2 | sina | `sina` | `_sina_realtime(["510050"], "A")` | 10s | 鐩磋皟 Sina 涓嬪眰 |
| C3 | tencent | `tencent` | `_tencent_realtime(["510050"], "A")` | 10s | 鐩磋皟 QQ 涓嬪眰 |
| C4 | akshare | `akshare` | `ak.stock_zh_a_hist("510050", "daily")` | 15s | 鍘嗗彶鏃ョ嚎闈炲叏閲忥紝`import akshare` 鍦?lambda 鍐呮儼鎬у姞杞?|
| C5 | levistock | `levistock` | `lv.sector_em("industry")` | 10s | 琛屼笟鏉垮潡 |
| C6 | 涓滄柟璐㈠瘜 | `dongfang` | `_em_hk_realtime(["00700"])` | 8s | 娓偂鍏滃簳婧?|
| T1 | 涓荤嚎绋嬫睜 | `threadpool_main` | `get_thread_pool_stats()` | 1s | 娲昏穬绾跨▼鈮?0%瑙嗕负鍋ュ悍 |
| T2 | akshare 绾跨▼姹?| `threadpool_akshare` | `get_akshare_pool_stats()` | 1s | 鍚屼笂 |

**楠岃瘉**:
```bash
# 鍚姩鍚庣瓑 120s锛屾煡鐪嬫棩蹇?# 鏃ュ織搴斿寘鍚? "[health] Running probes..." "[health] probe results: mootdx=OK, sina=OK, ..."
```

---

### Phase D 鈥?SourceEventStore 浜嬩欢璁板綍锛圖1-D6 鉁?宸插疄鏂? D7 鉂?寰呭疄鏂斤級

**鏉ユ簮**: `archived/data-source-monitoring-plan.md` 搂5.1~5.2

**鐩爣**: 鍏ㄩ摼璺暟鎹簮浜嬩欢璁板綍 + API 鏆撮湶 + 鍓嶇闈㈡澘

#### D1-D6 瀹炵幇鎯呭喌

| 姝ラ | 鏂囦欢 | 鏀瑰姩 | 鐘舵€?|
|------|------|------|:----:|
| D1 | `backend/app/monitor/source_events.py` | **鏂板缓** SourceEventStore 绫伙紙鍐呭瓨鐜?5000 鏉?鈫?寮傛鎵归噺鍒风洏 SQLite `data/source.db`锛?澶╂粴鍔ㄦ竻鐞嗭級 | 鉁?宸插疄鐜?|
| D2 | `backend/app/services/source_registry.py` | `SourceHealth.__init__` 宸插惈 `on_event` 鍥炶皟鍙傛暟锛沗record_success/record_failure` 宸茶皟鐢?`self._on_event`锛涙柊澧?`record_hard_failure` | 鉁?宸插疄鐜?|
| D3 | 鍚屼笂 | `SourceRegistry.set_event_callback(cb)` 宸插疄鐜帮紝鍚?`_make_source_callback` 鍖呰 | 鉁?宸插疄鐜?|
| D4 | `source_registry.py` | `route()` 宸插惈 `route_name` 鍙傛暟锛屾垚鍔?澶辫触鏃朵紶 route_name 缁欏洖璋冿紱`_route_us()` 浼?`route_name="US_ETF"`锛? 涓?china_market 鍑芥暟浼犲悇鑷?route_name | 鉁?宸插疄鐜?|
| D5 | `backend/app/main.py` | lifespan 涓皟鐢?`registry.set_event_callback(_make_event_callback())`锛宍asyncio.run_coroutine_threadsafe` 鍐欏叆 | 鉁?宸插疄鐜?|
| D6 | `backend/app/routers/admin.py` | 4 涓?API 宸插疄鐜帮細`GET /sources/health` / `/sources/events/timeline` / `/sources/events/failures` / `/sources/circuit-breakers` | 鉁?宸插疄鐜?|
| D7 | 鍓嶇 | **鏂板鏁版嵁婧愬仴搴风洃鎺ч〉闈?*锛堜笌 TokenMonitor 椋庢牸瀵归綈锛孍Charts 瓒嬪娍鍥?+ 婧愮姸鎬佽〃鏍硷級 | 鉂?**寰呭疄鏂?* |

**鏁版嵁妯″瀷** (SQLite: `data/source.db`):

```sql
CREATE TABLE IF NOT EXISTS source_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT    NOT NULL,       -- 'mootdx' / 'sina' / 'twelvedata' / ...
    route       TEXT    NOT NULL DEFAULT '',  -- 'A_stock_realtime' / 'US_ETF' / 'probe' / ...
    operation   TEXT    NOT NULL DEFAULT 'realtime',  -- 'realtime' / 'history' / 'probe'
    target      TEXT    NOT NULL DEFAULT '',  -- '000001' / 'SPY' / ...
    success     INTEGER NOT NULL,       -- 1=鎴愬姛 0=澶辫触
    duration_ms REAL    NOT NULL DEFAULT 0,
    error_message TEXT  NOT NULL DEFAULT '',
    timestamp   REAL    NOT NULL        -- Unix timestamp
);
```

**婊氬姩娓呯悊**: 姣忔棩妫€鏌ヤ竴娆★紝`DELETE FROM source_events WHERE timestamp < unixepoch('now', '-7 days')`

#### 鉁?D1-D6 楠岃瘉 (褰撳墠):

```bash
# 1. 婧愬仴搴锋瑙堬紙搴旇繑鍥炴墍鏈夋敞鍐屾簮鐨勭姸鎬侊級
curl -s "http://localhost:8000/api/v1/admin/sources/health" | python -c "import sys,json; d=json.load(sys.stdin); assert len(d)>2, 'too few sources'; [print(f'{s[\"name\"]}: {\"鉁匼" if s[\"available\"] else \"鉂孿"}') for s in d]"

# 2. 浜嬩欢鏃堕棿绾?curl -s "http://localhost:8000/api/v1/admin/sources/events/timeline?hours=1" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: {len(d)} buckets')"

# 3. 鏈€杩戝け璐?curl -s "http://localhost:8000/api/v1/admin/sources/events/failures?limit=10" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: {len(d)} failures')"

# 4. 鐔旀柇鐘舵€?curl -s "http://localhost:8000/api/v1/admin/sources/circuit-breakers" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: {len(d)} sources')"
```

#### 鉂?D7 瀹炴柦鎸囧紩

**鐩爣**: 鏂板鍓嶇鏁版嵁婧愬仴搴风洃鎺ч〉闈紝涓庣幇鏈?TokenMonitor 椋庢牸瀵归綈

**鎺ㄨ崘鍙傝€?*:
- 鍓嶇 `TokenMonitor.vue` 鐨勫竷灞€锛圗Charts + 琛ㄦ牸锛?- API 绔偣锛?  - `GET /api/v1/admin/sources/health` 鈫?婧愮姸鎬佽〃鏍?  - `GET /api/v1/admin/sources/events/timeline?hours=1` 鈫?ECharts 瓒嬪娍鍥撅紙鎴愬姛/澶辫触鍙岀嚎锛?  - `GET /api/v1/admin/sources/events/failures?limit=10` 鈫?澶辫触鍒楄〃
- `frontend/src/router/index.js` 鏂板璺敱 `/admin/sources`
- `frontend/src/App.vue` `navItems` 鏂板鍏ュ彛

**鍙傝€冨疄鐜版楠?*:
1. 鏂板缓 `frontend/src/views/SourceMonitor.vue`锛堝弬鑰?`TokenMonitor.vue` 甯冨眬 + Pinia store锛?2. 鏂板缓 `frontend/src/stores/sources.js`锛堝弬鑰?`stores/token.js` 妯″紡锛?3. 娉ㄥ唽璺敱锛歚router/index.js` 娣诲姞 `/admin/sources` 鈫?`SourceMonitor`
4. App.vue 瀵艰埅鏍忔坊鍔?鏁版嵁婧?鍏ュ彛
5. 楠岃瘉锛氬悇 API 璋冪敤姝ｅ父锛孍Charts 鎶樼嚎鍥炬樉绀烘垚鍔?澶辫触瓒嬪娍

---

## 渚濊禆鍏崇郴涓庢帹鑽愰『搴?
```
Phase A (缇庤偂璺敱)    鉁?宸插疄鏂?    鈹?Phase B (China SR)   鉁?宸插疄鏂?    鈹?Phase C (鎺㈤拡)        鉁?宸插疄鏂?    鈹?Phase D (EventStore)  鈹€鈹€鈹€ D1-D6 鉁?宸插疄鏂?| D7 鉂?寰呭疄鏂斤紙鐙珛锛屾棤鏂囦欢鍐茬獊锛?```
---

## 楠岃瘉鏍囧噯锛堟眹鎬伙級

| 闃舵 | 楠岃瘉鏂瑰紡 | 閫氳繃鏉′欢 | 澶辫触搴斿 |
|------|---------|---------|---------|
| A | curl 鍛戒护鑷姩鍖栨柇瑷€ | 缇庤偂瀹炴椂鍚?price>0 | 妫€鏌?TwelveData/Finnhub API key |
| B | curl + verify_e2e.py | A 鑲?娓偂瀹炴椂鏈夋暟鎹紝e2e 鍏?PASS | 纭闄嶇骇閾炬甯稿伐浣?|
| C | 鍚姩鏃ュ織 | 8 涓帰閽堝潎杩斿洖 OK | 閫愪釜璋冭瘯鎺㈤拡鍑芥暟锛涜秴鏃惰繃闀胯€呭鍔?timeout |
| D1-D6 | 4 涓?curl 鍛戒护 | 鍏ㄩ儴杩斿洖 200 + 鏈夋晥 JSON锛宻ource_events 琛ㄦ湁鏁版嵁 | 妫€鏌?DB 鏂囦欢鏉冮檺锛涙鏌ュ洖璋冩敞鍐岄『搴?|
| D7 | 鍓嶇娴忚 | 鏁版嵁婧愬仴搴烽〉灞曠ず姝ｇ‘ | 妫€鏌?API 杩斿洖鏍煎紡涓庡墠绔湡鏈涗竴鑷?|

---

## 鍓╀綑宸ヤ綔锛堟寜浼樺厛绾ф帓搴忥級

| # | 浠诲姟 | 婧愰樁娈?| 棰勪及 | 鍓嶇疆渚濊禆 |
|---|------|--------|:----:|---------|
| 1 | D7: 鍓嶇鏁版嵁婧愮洃鎺ч潰鏉?| Phase D7 | 4h | D6 (宸插氨缁? |

## 鍙傝€?
- 鍘熷鏂规 `archived/source-registry-optimization-plan.md` 鈥?宸插綊妗ｏ紝鍐呭宸插悎骞跺叆鏈枃妗?- 鍘熷鏂规 `archived/data-source-monitoring-plan.md` 鈥?宸插綊妗ｏ紝鍐呭宸插悎骞跺叆鏈枃妗?- 鍘熷鏂规 `market-awareness-and-data-source-plan.md` 鈥?搂4 宸插悎骞讹紝搂5 甯傚満鎰熺煡鑱斿姩寰?market-analysis 鏂规瀹炴柦鍚庤瘎浼?- 鍏ㄥ眬鎸囨暟閾捐矾鍐宠: `docs/implementation-master-plan.md` 搂3.2
- 浠ｇ爜瀹¤鏃ユ湡: 2026-07-26
- 鍚堝苟鍐宠: `docs/implementation-master-plan.md` 搂3.1
