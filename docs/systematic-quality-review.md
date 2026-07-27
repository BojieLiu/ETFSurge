# 绯荤粺璐ㄩ噺瀹℃煡涓庝慨澶嶆柟妗?
> 瀹℃煡鏃ユ湡: 2026-07-26
> 瀹℃煡鑼冨洿: 缁勫悎璁捐绠＄嚎銆佺瓥鐣ユ鏌ョ绾裤€佸洜瀛愭暟鎹閬撱€佸紓姝ユ墽琛屾ā鍨?
---

## 鐩綍

1. [鍙戠幇鐨勯棶棰樻眹鎬籡(#1-鍙戠幇鐨勯棶棰樻眹鎬?
2. [闂涓€锛欵vent Loop 闃诲瀵艰嚧鏈嶅姟鎸傛](#2-浜嬩欢寰幆闃诲)
3. [闂浜岋細璁捐鏂规绌哄３閫€鍖朷(#3-璁捐鏂规绌哄３閫€鍖?
4. [闂涓夛細鍥犲瓙鏁版嵁澶ч潰绉己澶盷(#4-鍥犲瓙鏁版嵁澶ч潰绉己澶?
5. [闂鍥涳細缃俊搴﹀缁堜负浣嶿(#5-缃俊搴﹀缁堜负浣?
6. [闂浜旓細缂栫爜涓庡瓨鍌ㄤ贡鐮乚(#6-缂栫爜涓庡瓨鍌ㄤ贡鐮?
7. [闂鍏細绛栫暐妫€鏌ヤ笌璁捐鐨勭郴缁熸€у亸宸甝(#7-绯荤粺鎬у亸宸?
8. [淇鏂规涓庝紭鍏堢骇](#8-淇鏂规涓庝紭鍏堢骇)

---

## 1. 鍙戠幇鐨勯棶棰樻眹鎬?
| # | 闂 | 涓ラ噸搴?| 褰卞搷闈?| 鏍瑰洜鍒嗙被 |
|---|------|--------|--------|----------|
| 1 | 浜嬩欢寰幆琚悓姝?I/O 闃诲锛屽鑷存湇鍔℃寕姝?| 馃敶 P0 | 鍏ㄧ郴缁熷彲鐢ㄦ€?| 寮傛杈圭晫杩濊 |
| 2 | 璁捐鏂规杩斿洖绌哄３锛? 鍙?ETF锛変絾鏍囪 completed | 馃敶 P0 | 缁勫悎璁捐鍔熻兘 | 缂哄皯鏈夋晥鎬ф牎楠?|
| 3 | 鍥犲瓙鏁版嵁澶ч潰绉己澶憋紙"鍥犲瓙鏁版嵁涓嶈冻"锛?| 馃煚 P1 | 绛栫暐璐ㄩ噺 | 鏁版嵁婧愬閿欑己澶?|
| 4 | 绛栫暐寤鸿缃俊搴﹀缁堜负 low | 馃煚 P1 | 鐢ㄦ埛淇′换 | 鎵撳垎/鑱氬悎闃堝€奸棶棰?|
| 5 | 涓枃鏂囨湰瀛樺偍涔辩爜锛坢ojibake锛?| 馃煚 P1 | 鎵€鏈変腑鏂囧唴瀹?| 缂栫爜浼犻€掕矾寰勬柇瑁?|
| 6 | 璁捐閫€鍖栵紙Design 219+ vs 218锛夋棤閿欒鎻愮ず | 馃煛 P2 | 鏂规鍙敤鎬?| 鐘舵€佹満璁捐缂洪櫡 |
| 7 | 甯傛€佺紦瀛樺彧鏈夎鍔ㄥ埛鏂帮紝鏃犱富鍔ㄥ～鍏呮満鍒?| 馃煛 P2 | 瀹炴椂鎬?| 鏋舵瀯璁捐 |

---

## 2. 浜嬩欢寰幆闃诲

### 2.1 鐜拌薄

鍚?`POST /api/v1/portfolio/design-async` 鍙戦€佽璁¤姹傚悗锛?1. 璇锋眰鎴愬姛杩斿洖 task_id锛堣鏄?`create_task` 瀹屾垚锛?2. 鍚庡彴 `asyncio.create_task(design_pipeline(...))` 鍚姩
3. `design_pipeline` 鈫?`generate_enhanced_design()` 鈫?`pool_manager.refresh()` 寮€濮嬫墽琛?4. **姝ゆ椂鎵€鏈夊悗缁姹傦紙鍋ュ悍妫€鏌ャ€佺瓥鐣ユ鏌ャ€佹煡璇級鍏ㄩ儴瓒呮椂**
5. 鏈嶅姟杩涚▼姝婚攣锛屽彧鑳藉己鍒?kill

### 2.2 浠ｇ爜瀹氫綅

**璋冪敤閾撅細**

```
portfolio.py:270  asyncio.create_task(design_worker(task_manager, t["task_id"]))
  鈫?task_manager.py:398  design_worker = design_pipeline
    鈫?task_manager.py:217  await asyncio.wait_for(
                            generate_enhanced_design(capital, constraints), timeout=90)
      鈫?strategy_design.py:37  await pool_manager.refresh()
        鈫?pool_manager.py:258  run_sync_long(self.scanner.full_pipeline, timeout=60)
          鈫?scanner.full_pipeline  [鍚屾 I/O: akshare, urllib, requests]
        鈫?pool_manager.py:289  await run_sync(_enrich, flat)
          鈫?_enrich  [鍚屾 I/O]
        鈫?pool_manager.py:295  await run_sync(self.classifier.batch_classify, flat)
          鈫?batch_classify  [鍚屾 I/O]
```

**鏍瑰洜锛?*

`pool_manager.refresh()` 鍐呴儴鐨?`run_sync_long()` 鍜?`run_sync()` 灏嗗悓姝ヤ换鍔℃彁浜ゅ埌绾跨▼姹犳墽琛屻€備絾鍦ㄦ煇浜涘満鏅笅鈥斺€旂壒鍒槸褰撶嚎绋嬫睜婊℃垨 I/O 鎿嶄綔杩涘叆姝婚攣鈥斺€?*绾跨▼姹犱腑鐨勫悓姝ヨ皟鐢ㄤ細鍥炲牭浜嬩欢寰幆**銆?
鍏蜂綋鏉ョ湅 `factor_registry.py` 鐨?`_fetch_market_data()`锛堢 833-872 琛岋級锛?
```python
# factor_registry.py:840-846
import urllib.request
prefixes = {"5": "sh", "6": "sh", "0": "sz", "1": "sz", "3": "sz"}
sina_list = [f"{prefixes.get(sym[0], 'sh')}{sym}" for sym in symbols]
url = f"http://hq.sinajs.cn/list={','.join(sina_list)}"
req = urllib.request.Request(url, headers={"Referer": "http://finance.sina.com.cn"})
resp = urllib.request.urlopen(req, timeout=8)  # 鈫?鍚屾闃诲锛?raw = resp.read().decode("gbk")
```

杩欐槸 `async def _fetch_market_data()` 鈥斺€?涓€涓?async 鍑芥暟锛?*鍐呴儴鐩存帴浣跨敤鍚屾 `urllib.request.urlopen()` 鏉ュ仛 HTTP 璇锋眰**銆傛病鏈?`await run_sync()` 鍖呰銆傝繖鐩存帴闃诲浜嗕簨浠跺惊鐜€?
### 2.3 淇鏂瑰悜

1. **鍞竴绾夸笂闃诲鐐逛慨澶?*锛歚factor_registry.py:844-845` 鐨?Sina IOPV 鎵归噺鑾峰彇鏀圭敤 `await run_sync()` 鍖呰锛堣缁嗘柟妗堣 `docs/archived/async-boundary-fix-plan.md 搂2.1`锛?2. **姝讳唬鐮佹竻鐞?*锛歚macro_state.py:102/143` 鐨?`_fetch_pmi_trend`/`_fetch_rate_env` 涓や釜鏈皟鐢ㄧ殑 async 鍑芥暟涓殑 akshare 璋冪敤闇€瑕佷慨澶嶄互闃插惎鐢ㄥ悗闃诲
3. **寮曞叆 CI 瀹¤**锛氭柊澧?`scripts/audit_async_blocking.py` 浣滀负 pre-commit 闂ㄧ锛孉ST 鎵弿绂佹 async def 鍐呭嚭鐜板悓姝?I/O
4. **寮傛杈圭晫鍗曞厓娴嬭瘯**锛氬湪鐜版湁 `tests/test_async_boundaries.py` 涓ˉ娴嬶紝瑕嗙洊 Sina IOPV 璺緞

---

## 3. 璁捐鏂规绌哄３閫€鍖?
### 3.1 鐜拌薄

瀵规瘮 ID=218 涓?ID=219-222 鐨勮璁℃柟妗堬細

| 缁村害 | Design 218 | Designs 219-222 |
|------|:----------:|:---------------:|
| 绛栫暐鏁伴噺 | 3 濂?| 1 濂楋紙绌哄３锛?|
| 姣忓 ETFs | 8-11 鍙?| **0 鍙?* |
| expected_return | 鏈夊€?| **null** |
| max_drawdown | 鏈夊€?| **null** |
| market_context keys | 5 涓?| 2 涓?|
| design_text 闀垮害 | 9,098 chars | **551 chars** |
| status | completed | completed 鉁?|
| report_quality | full | full 鉁?|

Designs 219-222 **鍏ㄩ儴鏍囪涓?"completed" 鍜?"full"锛屼絾瀹為檯鏃犲彲鐢ㄥ唴瀹?*鈥斺€旇繖鏄瘮澶辫触鏇翠弗閲嶇殑闂锛屽洜涓虹敤鎴风湅鍒扮殑鏄?宸插畬鎴?鍗存棤娉曟搷浣溿€?
### 3.2 浠ｇ爜瀹氫綅

**闂鍑虹幇鍦?`generate_enhanced_design()`锛坰trategy_design.py锛夌殑鍊欓€夋睜绌烘鏌ラ€昏緫涓細**

```python
# strategy_design.py:56-65
total_candidates = sum(len(v) for v in candidates.values())
if total_candidates == 0:
    return {
        "strategies": [],
        "market_context": _build_market_context(pool_manager),
        "error": "鏃犲€欓€夋爣鐨?,
        "detail": "鏁版嵁绠￠亾鏈兘鐢熸垚鍊欓€夋睜",
    }
```

褰撳€欓€夋睜涓虹┖锛屽嚱鏁拌繑鍥?`{"strategies": [], "error": "鏃犲€欓€夋爣鐨?}`銆?
**浣嗗湪璋冪敤绔紙task_manager.py:225-242锛夛細**

```python
strategies = result.get("strategies", [])
error_info = result.get("error")
if error_info:
    # 鏍囪涓?failed 鈫?姝ｇ‘
    mgr.update_task(task_id, ..., status="failed", ...)
    return

if not strategies:
    # 鏍囪涓?failed 鈫?姝ｇ‘
    mgr.update_task(task_id, ..., status="failed", ...)
    return
```

杩欓噷鐪嬭捣鏉ラ€昏緫鏄鐨勨€斺€旂┖绛栫暐浼氭姤 failed銆?*浣?Designs 219-222 鍗存樉绀?"completed" 涓旀湁 "full" 鐨?report_quality**銆?
杩欐剰鍛崇潃瑕佷箞锛?1. `generate_enhanced_design()` 杩斿洖浜?`strategies` 鍒楄〃锛屼絾閲岄潰鐨勭瓥鐣ョ己澶?ETFs锛坙ine 93-128 閭ｉ噷鍑轰簡闂锛?2. 鎴栬€?`pool_manager.refresh()` 瓒呮椂鍚庡€欓€夋睜绌轰簡锛屼絾 `pool_manager.refresh()` 鐨勫紓甯歌 `strategy_design.py:38` 鐨?`except Exception` 鍚炴帀浜?
鐪嬭璁＄绾跨殑涓婃父鈥斺€擿strategy_design.py:36-40`锛?
```python
try:
    await pool_manager.refresh()
except Exception as e:
    logger.warning("[strategy_design] pool_manager.refresh failed 鈥?pool may be stale")
```

杩欓噷铏界劧鏈夊紓甯告崟鑾蜂絾涓嶅奖鍝嶅悗缁祦绋嬨€備箣鍚?`pool_manager.get_pool("core")` 鍙兘杩斿洖绌哄垪琛ㄢ€斺€旈偅涔?`total_candidates == 0` 瑙﹀彂绌烘睜杩斿洖銆?
浣?Designs 219-222 閮芥樉绀?`status=completed, report_quality=full` 涓?`strategies` 鏈?**1 涓?*绌虹瓥鐣モ€斺€斾笉鏄┖鍒楄〃銆?
**鐪熸鐨勯棶棰樺彲鑳藉湪 `engine_allocate()` 鏂规硶涓?*鈥斺€斿鏋?`flat_candidates` 涓嶄负绌轰絾鍥犲瓙鍒嗗叏涓?0锛屽紩鎿庡彲鑳戒骇鐢熶簡鏃?ETF 鍒嗛厤鐨勭瓥鐣ユā鏉裤€傛垨鑰?`_build_plan_tables` 鍦ㄧ┖绛栫暐鍒楄〃鎯呭喌涓嬩粛鐒剁敓鎴愪簡 551 chars 鐨勬ā鏉裤€?
### 3.3 淇鏂瑰悜

1. **纭鍔?`post-condition` 鏍￠獙**锛氬湪 `strategies` 琚繑鍥炲墠锛岄獙璇佹瘡涓?strategy 鐨?etfs 鍒楄〃闈炵┖涓旇嚦灏戜竴鍙潪 CASH 鏍囩殑
2. **鐘舵€佹満涓ヨ皑鍖?*锛歚completed` 鐘舵€佸繀椤绘湁鏄庣‘鐨勫畬鎴愭潯浠跺畾涔夛紙闈炵┖绛栫暐 + 鏈夋晥鏁版嵁锛夛紝涓嶇鍚堝垯杩涘叆 `completed_with_errors` 鎴?`failed`
3. **澧炲姞 `strategy.etfs_count` 鍒板垪琛ㄥ厓鏁版嵁**锛坄GET /designs` 鐨?load_only 鏌ヨ涓級锛屽墠绔湪鍒楄〃椤靛嵆鍙瘑鍒┖澹虫柟妗?4. **瀵规瘮 Design 218 鍜?219 鐨?`elapsed_seconds`** 鈥斺€斿鏋?219 浠ュ悗鐨勮姹傞兘鏋佸揩瀹屾垚锛?2绉掞級锛岃鏄庢暟鎹閬撴牴鏈病浜у嚭鍊欓€夋睜

---

## 4. 鍥犲瓙鏁版嵁澶ч潰绉己澶?
### 4.1 鐜拌薄

浠庣瓥鐣ユ鏌?102 鐨?`holdings_analysis` 涓細

```json
{"symbol": "159338", "name": "涓瘉A500ETF", "factor_summary": "鍥犲瓙鏁版嵁涓嶈冻",
 "tech_signal": "hold", "risk_flag": null}
```

10 鍙寔浠撲腑 **鍏ㄩ儴鏄剧ず "鍥犲瓙鏁版嵁涓嶈冻"**銆俙factor_summary` 瀛楁娌℃湁杈撳嚭鍏蜂綋鐨勫洜瀛愬垎鍊硷紙姝ｅ父搴旇鏄?`"momentum: 1.23蟽锛泃echnical: 0.87蟽锛?.."` 鐨勬牸寮忥級銆?
### 4.2 浠ｇ爜瀹氫綅

**鏁版嵁缂洪櫡浼犻€掗摼锛?*

```
strategy_check() 鈫?factor_registry.compute(symbols)
  鈫?compute() line 906: market_data = await self._fetch_market_data(symbols)
    鈫?_fetch_market_data() line 782-831: 閫愪釜 symbol 鑾峰彇 K 绾挎暟鎹?      鈫?[鍚屾 urllib/akshare 璋冪敤]  鈫?鍙兘瓒呮椂/澶辫触 鈫?杩斿洖 {"_fetch_error": "..."}
    鈫?line 839-866: 鎵归噺鑾峰彇 IOPV锛圫ina 瀹炴椂琛屾儏锛?      鈫?[鍚屾 urllib.request.urlopen] 鈫?鍙兘瓒呮椂/澶辫触
  鈫?compute() line 919-922: 瀵规瘡涓?symbol 閫愪釜鍥犲瓙璁＄畻
    鈫?濡傛灉 data 涓虹┖ 鎴?key 缂哄け 鈫?row[code] = 0.0  (闈欓粯濉浂)
```

**鏍稿績璺緞锛?*

鍦?`compute()` 鍑芥暟鐨勭 919 琛岋細

```python
try:
    raw_value = computer(data)
    definition = self._factors.get(code)
    row[code] = raw_value if raw_value is not None else 0.0
except Exception as e:
    logger.debug("Factor %s failed for %s: %s", code, sym, e)
    row[code] = 0.0  # 鈫?闈欓粯澶辫触
```

濡傛灉 `data` 瀛楀吀涓虹┖锛堝洜涓?`_fetch_market_data` 鍏ㄩ儴澶辫触锛夛紝**鎵€鏈夊洜瀛愬緱鍒嗕负 0.0**銆備箣鍚庯細

```python
# line 936-958: z-score 鏍囧噯鍖?all_v = [v for _, v in _raw[code]]
if len(all_v) < 2:
    continue  # 鈫?鎵€鏈夊€间竴鏍凤紝璺宠繃鏍囧噯鍖?```

褰撴墍鏈夊€间负 0 鏃讹紝`std_v = 0`锛屾爣鍑嗗寲琚烦杩囥€傛渶缁堟墍鏈?symbol 鐨勫洜瀛愬垎鍏ㄦ槸 0銆?
鍥炲埌 `strategy_check()` 鐨?holdings_analysis 鍚庡鐞嗭紙line 505锛夛細

```python
if real_fs and isinstance(real_fs, dict) and any(v != 0 for v in real_fs.values()):
    top_factors = sorted(real_fs.items(), key=lambda x: -abs(x[1]))[:3]
    ...
else:
    # 涓嶈鐩?LLM 鐨勫洜瀛愭弿杩?鈫?LLM 璇?"鍥犲瓙鏁版嵁涓嶈冻"
```

鍥犱负鎵€鏈夊洜瀛愬垎閮芥槸 0锛宍any(v != 0)` 涓?False锛屾墍浠?LLM 鐢熸垚鐨?"鍥犲瓙鏁版嵁涓嶈冻" 涓嶄細琚鐩栥€?
### 4.3 鏍瑰洜閾?
```
澶栭儴鏁版嵁瓒呮椂/澶辫触
  鈫?_fetch_market_data 杩斿洖绌?dict
    鈫?鎵€鏈夊洜瀛愬緱鍒嗕负 0
      鈫?z-score 鏍囧噯鍖栧叏閮ㄨ烦杩?        鈫?factor_summary = "鍥犲瓙鏁版嵁涓嶈冻"
```

涓棿娌℃湁鐔旀柇銆佹病鏈夐檷绾с€佹病鏈?鑷冲皯杩斿洖閮ㄥ垎鍥犲瓙"鐨勬満鍒躲€?
### 4.4 淇鏂瑰悜

1. **鍥犲瓙绾у埆鐨勭嫭绔嬫€?*锛氭瘡涓洜瀛愮殑 `_fetch_market_data()` 搴旂嫭绔嬫墽琛岋紝涓€涓洜瀛愬け璐ヤ笉搴斿奖鍝嶅叾浠栧洜瀛?2. **寮曞叆缂撳瓨灞?*锛歚compute()` 搴斾紭鍏堜娇鐢ㄧ紦瀛?K 绾挎暟鎹紙宸叉湁 `_get_cached_kline` 浣嗘湭鍦?`compute()` 涓厹搴曪級
3. **闄嶇骇绛栫暐**锛氬綋瀹炴椂鏁版嵁鑾峰彇澶辫触鏃讹紝fallback 鍒扮紦瀛樻暟鎹紙鍗充娇杩囨湡锛夛紝鑰岄潪杩斿洖 0
4. **鍒嗗眰鎶ュ憡鏁版嵁璐ㄩ噺**锛歚factor_summary` 鍏蜂綋鍒?"momentum: 鎴愬姛, valuation: 鏁版嵁婧愯秴鏃? 鐨勭矑搴︼紝鑰岄潪绗肩粺鐨?鏁版嵁涓嶈冻"
5. **`compute()` 鐨?try/except 搴旇鍖哄垎**鈥斺€擿data` 涓虹┖鏃跺簲璇?logging warning 鑰岄潪闈欓粯濉浂

---

## 5. 缃俊搴﹀缁堜负浣?
### 5.1 鐜拌薄

妫€鏌?102 鐨?4 鏉″缓璁細

```json
{"action": "decrease", "symbol": "159338", "suggested_weight": 0.15, "confidence": "low"}
{"action": "decrease", "symbol": "518880", "suggested_weight": 0.1, "confidence": "low"}
{"action": "increase", "symbol": "513010", "suggested_weight": 0.05, "confidence": "low"}
{"action": "hold", "symbol": "510880", "suggested_weight": 0.08, "confidence": "low"}
```

**鍏ㄩ儴 `confidence: "low"`**锛屾棤娉曞尯鍒嗗缓璁殑鍙潬绋嬪害銆?
### 5.2 浠ｇ爜瀹氫綅

缃俊搴︾敱 LLM 鐢熸垚鈥斺€擿generate_strategy_check_report()` 鍦?`analysis/llm.py` 涓瀯閫?prompt 瑕佹眰 LLM 杈撳嚭 `confidence` 瀛楁銆?
**鏁版嵁浼犻€掗摼锛?*

```
strategy_check() 鈫?generate_strategy_check_report(market_data, factor_breakdowns, regime, data_quality)
  鈫?LLM prompt: 鍖呭惈 {factor_summary: "鍥犲瓙鏁版嵁涓嶈冻"} 鐨?holdings_analysis
  鈫?LLM 鐪嬪埌 "鍥犲瓙鏁版嵁涓嶈冻" 鈫?闄嶇骇鎵€鏈?confidence 涓?low
```

**鍚庡鐞嗛€昏緫锛坧ortfolio_service.py:505-508锛夛細**

```python
if real_fs and isinstance(real_fs, dict) and any(v != 0 for v in real_fs.values()):
    top_factors = sorted(real_fs.items(), key=lambda x: -abs(x[1]))[:3]
    h["factor_summary"] = "...鐪熷疄鍥犲瓙鍒?.."
else:
    # 涓嶈鐩?鈥?LLM 鐨?"鍥犲瓙鏁版嵁涓嶈冻" 淇濈暀
```

**鏍瑰洜锛?*

1. 鍥犲瓙鏁版嵁鍏ㄤ负 0 鈫?`any(v != 0)` 涓?False 鈫?鐪熷疄鍥犲瓙鍒嗕笉娉ㄥ叆 coverage
2. LLM 鏀跺埌鐨?`factor_summary` 鏄┖鐨勬垨 "鍥犲瓙鏁版嵁涓嶈冻" 鈫?缂轰箯瀹氶噺渚濇嵁 鈫?鎵€鏈?confidence = low
3. Prompt 鍐呭 confidence 鍒ゅ畾鏍囧噯涓嶆槑纭€斺€斿彧缁欎簡 "high/medium/low" 鍙€夐」浣嗘病鏈夐噺鍖栭棬妲?4. `data_quality` 鍙傛暟铏戒紶缁?LLM锛屼絾 LLM 鏄惁鏈夋晥浣跨敤浜嗗畠鍙栧喅浜?prompt 璐ㄩ噺鈥斺€斿綋鍓?prompt 鍙兘娌℃湁瑕佹眰 LLM 鍩轰簬 `filled_count/total_count` 鏍″噯 confidence

### 5.3 淇鏂瑰悜

1. **瀹氫箟鏄庣‘鐨?confidence 璁＄畻瑙勫垯**锛屽湪 `strategy_check()` 鍚庡鐞嗕腑瑕嗙洊 LLM 杈撳嚭锛堢被浼煎畠宸茬粡瑕嗙洊 factor_summary 鐨勬柟寮忥級锛?   - `filled_count / total_count > 0.8` 鈫?high
   - `0.5 鈮?ratio 鈮?0.8` 鈫?medium  
   - `ratio < 0.5` 鈫?low
   - 寤鸿璋冩暣骞呭害 > 5% 涓斿洜瀛愭暟鎹厖鍒?鈫?high
   - 寤鸿璋冩暣骞呭害 < 3% 鎴栧洜瀛愭暟鎹笉瓒?鈫?low
2. **鍦?LLM prompt 涓敞鍏ュ叿浣撶殑 `filled_count/total_count` 鎸囧紩**锛岃姹?LLM 鎹鏍″噯 confidence
3. **鍏堜慨鍥犲瓙鏁版嵁缂哄け锛圛ssue #3锛?*鈥斺€攃onfidence 闂鏈川涓婃槸鍥犲瓙鏁版嵁闂鐨勪笅娓哥棁鐘讹紝鍙湁鍥犲瓙鏁版嵁姝ｅ父鍚?confidence 鎵嶈兘鏈夌湡姝ｇ殑鎰忎箟

---

## 6. 缂栫爜涓庡瓨鍌ㄤ贡鐮?
### 6.1 鐜拌薄

API 杩斿洖鐨勪腑鏂囧瓧娈靛湪缁堢鍜屾棩蹇椾腑鏄剧ず涓?mojibake锛堜贡鐮侊級锛?
```
"positioning": "\ufffd\ufffd..."  搴斾负 "浣庢尝绋冲仴閰嶇疆"
"summary": "\ufffd\ufffd..."      搴斾负 "缁勫悎鐩墠鎸佷粨10鍙?.."
```

璁捐鏂规鐨勭瓥鐣ュ悕锛?```
"label": "\ufffd\ufffd\ufffd..."  搴斾负 "绋冲仴鍨?
"label": "\ufffd\ufffd\ufffd..."  搴斾负 "骞宠　鍨?
```

### 6.2 鍒濇璇婃柇

杩借釜 `design_text` 鐨勫啓鍏ラ摼璺細

```
generate_enhanced_design() 鈫?杩斿洖 UTF-8 Python 瀛楃涓?  鈫?_build_plan_tables(strategies) 鈫?plan_tables
    鈫?design_text = "# ETF 鏂规\n\n" + plan_tables
      鈫?PortfolioDesign(design_text=design_text)
        鈫?db.add(record) 鈫?await db.commit()
          鈫?aiosqlite
```

**寰呴獙璇佺殑鍋囪锛堟寜鍙兘鎬ф帓搴忥級锛?*

1. **缁堢/鏃ュ織缂栫爜**锛歶vicorn 鎺у埗鍙拌緭鍑虹紪鐮侀潪 UTF-8锛圵indows GBK锛夛紝瀵艰嚧鏃ュ織鍜?`backend.err` 涓殑涓枃鏄剧ず涓轰贡鐮侊紝**浣?DB 瀹為檯瀛樺偍姝ｇ‘**
2. **DB 缂栫爜**锛歛iosqlite/SQLite 鏂囦欢缂栫爜闂鈥斺€旈渶瑕?DB 杩炴帴鏃舵樉寮忚缃?`PRAGMA encoding="UTF-8"`
3. **GBK 瑙ｇ爜娈嬬暀**锛歚factor_registry.py:846` 鐨?`resp.read().decode("gbk")` 浠庢柊娴彇 IOPV 鏁版嵁锛屽鏋滄湭姝ｇ‘杞崲 UTF-8 鍙兘姹℃煋鍚庣画澶勭悊

**楠岃瘉姝ラ锛?*

```bash
# 1. 鐩存帴浠?DB 璇诲彇 design_text 楠岃瘉缂栫爜
python -c "
import aiosqlite
import asyncio
async def check():
    async with aiosqlite.connect('data/portfolio.db') as db:
        cur = await db.execute('SELECT id, design_text FROM portfolio_designs ORDER BY id DESC LIMIT 3')
        rows = await cur.fetchall()
        for r in rows:
            print(f'ID={r[0]}, text length={len(r[1])}')
            print(f'First 100 chars repr: {repr(r[1][:100])}')
asyncio.run(check())
"

# 2. 濡傛灉 DB 鍐呭姝ｇ‘浣?API 杩斿洖涔辩爜 鈫?闂鍦?fastapi/uvicorn 缂栫爜涓棿浠?# 3. 濡傛灉 DB 鍐呭灏变贡鐮?鈫?闂鍦ㄥ啓鍏ラ摼璺?```

### 6.3 淇鏂瑰悜

1. **鎵ц楠岃瘉姝ラ 1** 纭畾鏂鐐规槸鍦ㄥ啓鍏ヨ繕鏄鍑?2. 濡傛灉 DB 姝ｇ‘锛氭鏌?`uvicorn` 鍚姩缂栫爜 `PYTHONIOENCODING=utf-8`銆丗astAPI `JSONResponse` media_type 璁剧疆
3. 濡傛灉 DB 涔辩爜锛氬湪 `database.py` 鐨勮繛鎺?URL 涓鍔?`?charset=utf-8` 鎴栦娇鐢?aiosqlite pragma

---

## 7. 绯荤粺鎬у亸宸?
### 7.1 璁捐閫€鍖栦笌甯傛€佺紦瀛?
Designs 219-222 鐨?`market_context` 鍙湁 2 涓?key锛坄market_regime` 鍜?`index_realtime`锛夛紝鑰?Design 218 鏈?5 涓細

```
218: market_regime, market_sentiment, index_realtime, sector_momentum, fund_flow
219: market_regime, index_realtime
```

`_build_market_context()`锛坰trategy_design.py:192-200锛変細璋冪敤锛?- `pool_manager.get_market_sentiment()` 鈫?濡傛灉缂撳瓨杩囨湡锛岃繑鍥為粯璁ゅ€硷紙涓嶄細绌猴級
- `pool_manager.get_sector_momentum()` 鈫?濡傛灉缂撳瓨杩囨湡锛岃繑鍥?`None` 鈫?`[]`

**鍏抽敭鍙戠幇**锛歚get_market_sentiment()` 鍦ㄧ紦瀛樿繃鏈熸椂鏃犳硶寮傛鍒锋柊锛堝洜涓烘槸鍚屾鏂规硶锛夛紝鎵€浠ヨ繑鍥為粯璁ゅ€笺€備絾 `get_sector_momentum()` 杩斿洖 `None` 缁ц€岃 `_build_market_context` 杩囨护涓?`[]`銆?
杩欐剰鍛崇潃 Designs 219-222 杩愯鏃?**pool_manager 鐨?sector_momentum 缂撳瓨鍜?fund_flow 鏁版嵁閮戒负绌?*鈥斺€旇繖涓?`pool_manager.refresh()` 娌℃湁瀹屽叏鎵ц鎴愬姛鏈夊叧銆?
> **鍚堝苟璇存槑**锛氳璁￠€€鍖栵紙鍘?Issue #6锛夊拰甯傛€佺紦瀛樼┖娲烇紙鍘?Issue #7锛夋槸鍚屼竴 root cause鈥斺€旀暟鎹閬撴湭鎴愬姛鎵ц锛屽鑷寸┖澹虫柟妗?+ 绌虹紦瀛樺悓鏃跺嚭鐜般€備袱涓棶棰樺湪鏈妭鍚堝苟鍒嗘瀽銆?
### 7.2 绛栫暐妫€鏌ョ殑鍥犲瓙娉ㄥ叆缂洪櫡

绛栫暐妫€鏌ュ湪 `strategy_check()` 鐨?505 琛屽皾璇曠敤鐪熷疄鍥犲瓙鍒嗚鐩?LLM 鐢熸垚鐨勫洜瀛愭憳瑕侊細

```python
if real_fs and isinstance(real_fs, dict) and any(v != 0 for v in real_fs.values()):
    top_factors = sorted(real_fs.items(), key=lambda x: -abs(x[1]))[:3]
    factor_str = "锛?.join(f"{k}: {v:.2f}蟽" for k, v in top_factors)
    h["factor_summary"] = f"{factor_str}"
```

**闂**锛歚any(v != 0)` 鐨勯棬妲涘お浣庘€斺€斿彧鏈変竴涓洜瀛愰潪闆跺氨浼氳Е鍙戣鐩栥€備絾鏇村ソ鐨勬寚鏍囧簲璇ユ槸**闈為浂鍥犲瓙鐨勬瘮渚?*鍜?*淇″彿寮哄害**銆?
### 7.3 璁捐绠＄嚎鐨?闈欓粯闄嶇骇"鐭澘

浠?`pool_manager.refresh()` 鐨勬墽琛岃矾寰勭湅锛屼俊鍙烽噺鏈哄埗鍩烘湰瀹屾暣锛?- 60s TTL 缂撳瓨
- 30s 鍐峰嵈鏈?- 骞跺彂閿?
浣嗛棶棰樻槸锛?*褰撴墍鏈変繚鎶ら兘瑙﹀彂鍚庯紝绯荤粺"闈欓粯闄嶇骇"浜?*鈥斺€旇繑鍥炵┖缂撳瓨銆侀粯璁ゅ€笺€侀浂鍒嗭紝娌℃湁鍙戝嚭瓒冲鐨勫憡璀︺€傜敤鎴风湅鍒?"completed" 浠ヤ负鏄垚鍔熺殑锛屽疄闄呮槸绌烘礊鐨勩€?
---

## 8. 淇鏂规涓庝紭鍏堢骇

> **璺ㄦ枃妗ｄ緷璧?*锛欼ssue #1锛堜簨浠跺惊鐜樆濉烇級鐨勮缁嗕慨澶嶆柟妗堣 `docs/archived/async-boundary-fix-plan.md`锛屼互涓嬩粎鍒楁瑕併€?
### P0 鈥?蹇呴』绔嬪嵆淇

| # | 淇椤?| 娑夊強鏂囦欢 | 鍏宠仈闂 | 棰勪及宸ユ椂 |
|---|--------|----------|----------|:--------:|
| 1 | **淇 async 鍑芥暟涓殑鍞竴鍚屾 I/O**锛歚factor_registry.py:844-845` 鐨?Sina IOPV `urllib.request.urlopen` 鏀逛负 `await run_sync()` | `factor_registry.py` | Issue #1 | 0.5h |
| 2 | **璁捐鏂规 post-condition 鏍￠獙**锛氭瘡涓?strategy 蹇呴』鏈?鈮? 鍙潪 CASH ETF 鎵嶅厑璁告爣璁?completed | `task_manager.py`, `strategy_design.py` | Issue #2 | 0.5h |
| 3 | **`compute()` 绌烘暟鎹憡璀?*锛歚_fetch_market_data` 杩斿洖绌?dict 鏃?logger.error 鑰岄潪闈欓粯濉浂 | `factor_registry.py` | Issue #3 | 0.25h |

### P1 鈥?楂樹紭鍏堢骇

| # | 淇椤?| 娑夊強鏂囦欢 | 鍏宠仈闂 | 棰勪及宸ユ椂 |
|---|--------|----------|----------|:--------:|
| 4 | **缂栫爜璇婃柇**锛氭墽琛岄獙璇佹楠わ紙DB 鐩存帴璇诲彇锛夌‘瀹氭柇瑁傜偣鍦ㄥ啓鍏ヨ繕鏄鍑?| `database.py` 妫€鏌?| Issue #5 | 0.5h |
| 5 | **鍥犲瓙闄嶇骇缂撳瓨**锛歚compute()` 瀹炴椂鏁版嵁澶辫触鏃?fallback 鍒拌繃鏈?K 绾跨紦瀛?| `factor_registry.py` | Issue #3 | 0.5h |
| 6 | **缃俊搴﹁鍒欏寲**锛歚strategy_check()` 鍚庡鐞嗕腑鍩轰簬 `filled_count/total_count` 瑕嗙洊 confidence | `portfolio_service.py` | Issue #4 | 0.25h |
| 7 | **璁捐浠诲姟骞跺彂鎺у埗**锛氶檺鍒跺悓涓€鏃堕棿鍙湁涓€涓璁?妫€鏌ヤ换鍔¤繍琛?| `task_manager.py` | Issue #1 | 0.25h |
| 8 | **姝讳唬鐮佷慨澶?*锛歚macro_state.py` 鐨?`_fetch_pmi_trend`/`_fetch_rate_env` 鍔?`await run_sync()` | `macro_state.py` | Issue #1 | 0.5h |

### P2 鈥?涓湡浼樺寲

| # | 淇椤?| 娑夊強鏂囦欢 | 鍏宠仈闂 | 棰勪及宸ユ椂 |
|---|--------|----------|----------|:--------:|
| 9 | **鐘舵€佹満楠岃瘉**锛歞esign pipeline 澧炲姞 validating 闃舵锛岀┖绛栫暐鎷掑叆 completed | `task_manager.py` | Issue #2, #6 | 1h |
| 10 | **鍥犲瓙璐ㄩ噺鎶ュ憡**锛歚factor_summary` 杈撳嚭鍒板洜瀛愮骇鍒殑鍙敤鎬ц鎯?| `portfolio_service.py`, LLM prompt | Issue #3 | 0.5h |
| 11 | **璁捐鍒楄〃澧炲姞 etf_count 鍏冩暟鎹?*锛歚GET /designs` load_only 澧炲姞 ETF 璁℃暟 | `portfolio.py` | Issue #2 | 0.25h |
| 12 | **甯傛€佺紦瀛樺紓姝ュ埛鏂?*锛歚get_sector_momentum()` 缂撳瓨杩囨湡鏃跺惎鍔ㄥ紓姝ュ埛鏂?| `pool_manager.py` | Issue #6 | 0.5h |
| 13 | **鍖哄垎鏁版嵁涓嶈冻 vs 淇″彿涓€?*锛?hold" 淇″彿闇€鍖哄垎涓ょ鍦烘櫙 | `portfolio_service.py` | Issue #4 | 0.5h |
| 14 | **CI 瀹¤闂ㄧ**锛歚scripts/audit_async_blocking.py` + pre-commit 闆嗘垚 | 鏂板缓 | Issue #1 | 0.5h |

### 淇鎵ц椤哄簭

```
P0-1 (async I/O) 鈫?P0-3 (compute鍛婅) 鈫?P1-5 (鍥犲瓙缂撳瓨) 鈫?P0-2 (璁捐鏍￠獙)
                                           鈫?P1-4 (缂栫爜璇婃柇) 鈫?P1-6 (缃俊搴? 鈫?P1-7 (骞跺彂鎺у埗) 鈫?P1-8 (姝讳唬鐮?
                                           鈫?P2-9~P2-14 (楠岃瘉闃舵銆佽川閲忔姤鍛娿€佸璁￠棬绂佺瓑)
```

> **渚濊禆绾︽潫**锛歅1-6锛堢疆淇″害锛変緷璧?P1-5锛堝洜瀛愭暟鎹甯稿悗鎵嶆湁鎰忎箟锛夈€侾2-14锛圕I 闂ㄧ锛変笉渚濊禆鍏朵粬 P0/P1锛屽彲闅忔椂鎻掑叆鐜版湁宸ヤ綔娴併€?
## 9. 娴嬭瘯闃叉姢缂哄彛涓庝慨澶嶆柟妗?
> 鍏宠仈鏂囨。锛歚docs/archived/async-boundary-fix-plan.md`锛圙1 鐩存帴鐩稿叧锛夈€乣docs/implementation-master-plan.md 搂4 Phase 2.8`

鐜版湁娴嬭瘯浣撶郴锛?8 涓枃浠讹紝~360 涓敤渚嬶級澶ч噺瑕嗙洊姝ｅ父璺緞锛屼絾瀛樺湪 4 灞傜粨鏋勬€х己鍙ｅ鑷翠笂杩?6 涓棶棰樻湭琚瘑鍒€?
### 9.1 鍥涘眰缂哄彛鍥為【

涓婃枃 搂2-搂7 鐨?6 涓川閲忛棶棰樻湭琚幇鏈夋祴璇曢槻鎶や綋绯昏瘑鍒紝鏍规簮鍦?4 灞傛祴璇曠己鍙ｏ細

| 缂哄彛 | 鎻忚堪 | 浠ｇ爜绀轰緥 | 褰卞搷鐨?Issue |
|------|------|----------|:-----------:|
| **鈶?AST 鎵弿鏂瑰悜閿?* | `test_async_lint` 鍙娴?`await sync_func()` 妯″紡锛屼笉妫€娴嬬洿鎺ュ悓姝ヨ皟鐢?| `resp = urllib.request.urlopen(req)` 鍦?`async def` 鍐咃紙鏃?await锛?| #1 |
| **鈶?Mock 璺宠繃鐪熷疄璺緞** | 娴嬭瘯閫氳繃 mock 缁曡繃浜嗘暟鎹幏鍙栭摼璺紝鍙祴"濂芥暟鎹笂鐨勯€昏緫" | `registry.compute(symbols, market_data=MOCK_DATA)` 鈫?涓嶇粡杩?`_fetch_market_data` | #1, #3 |
| **鈶?鍙鏌ョ粨鏋勪笉妫€鏌ュ€?* | 鏂█姝簬"瀛楁瀛樺湪"锛屼笉楠岃瘉鍐呭璐ㄩ噺 | `assert "confidence" in result` 鈮?`assert c != "low"` | #2, #4, #6 |
| **鈶?鏃犵紪鐮?roundtrip 娴嬭瘯** | 鍐欏叆鈫掑瓨鍌ㄢ啋璇诲嚭鐨勭紪鐮佽矾寰勬棤浠讳綍闃叉姢 | 鏃犳祴璇曢獙璇?`"绋冲仴鍨? 鈫?DB 鈫?"绋冲仴鍨?` 涓€鑷?| #5 |

### 9.2 淇鏂规锛堟寜缂哄彛锛?
#### 淇 G1: AST 鎵弿澧炲己 鈥?鏂板鐩存帴鍚屾璋冪敤妫€娴?
**褰撳墠婕忔礊**锛歚test_async_lint.py` 鍙亶鍘?`ast.Await` 鑺傜偣锛屽拷鐣?`ast.Call` 鍦?`ast.AsyncFunctionDef` 涓殑鐩存帴璋冪敤銆?
```python
# test_async_lint.py 鏂板鍑芥暟
def _extract_call_name(node: ast.Call) -> str:
    """鎻愬彇鍑芥暟璋冪敤鍚嶇О锛屾敮鎸?foo.bar.baz 鏍煎紡銆?""
    parts = []
    n = node.func
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
    return '.'.join(reversed(parts))

def _is_direct_sync_call_in_async(node: ast.AST) -> list[str]:
    """妫€鏌?async def 鍑芥暟涓槸鍚︽湁鐩存帴锛堥潪 await锛夊悓姝ヨ皟鐢ㄣ€?
    鐢变簬 ast.walk 涓嶆彁渚?parent 寮曠敤锛岄渶瑕佸厛寤虹珛 parent 鏄犲皠銆?    鏇夸唬鏂规锛氬湪閬嶅巻鏃剁淮鎶や竴涓?in_await 鏍囧織鏍堛€?    """
    if not isinstance(node, ast.AsyncFunctionDef):
        return []
    violations = []
    # 鏂规锛氬厛寤?parent 鏄犲皠锛屽啀浠?Call 鑺傜偣鍚戜笂杩芥函
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            # 鐢?lineno 绮楀垽鏂€斺€旀洿绮剧‘鐨勫仛娉曪細
            # 閬嶅巻 AsyncFunctionDef 鏃舵墜鍔ㄨ窡韪?await 涓婁笅鏂?            ...
    return violations
```

> **瀹炵幇娉ㄦ剰**锛欰ST 鑺傜偣榛樿涓嶅惈 `parent` 灞炴€с€備笂杩颁吉浠ｇ爜绀烘剰閫昏緫锛屽疄闄呭疄鐜版椂闇€瑕佸湪 `ast.walk` 涓墜鍔ㄧ淮鎶や竴涓?`in_await: bool` 鏍囧織鏍堬紝鎴栦娇鐢?`ast.NodeTransformer` 鐨?`visit` 椤哄簭鎺ㄦ柇銆?
**鏂板榛戝悕鍗?*锛堝尯鍒簬 `_SYNC_PATTERNS` 鐨?`await` 鍒楄〃锛夛細

```python
_SYNC_PATTERNS_DIRECT = [
    "urllib.request.urlopen", "urllib.request.Request",
    "requests.get", "requests.post",
    "pd.read_html", "pd.read_csv",
    "yfinance", "yf.",
]
```

**鏂板娴嬭瘯**锛?
```python
def test_no_direct_sync_call_in_async_function():
    """Fail if any async def contains a direct synchronous call."""
    violations = []
    for root, dirs, files in os.walk(_APP_PATH):
        for f in files:
            if not f.endswith('.py'): continue
            with open(os.path.join(root, f)) as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                violations.extend(_is_direct_sync_call_in_async(node))
    assert len(violations) == 0, \
        f"Found {len(violations)} direct sync calls in async functions:\n" + \
        '\n'.join(violations)
```

**娑夊強鏂囦欢**锛歚tests/test_async_lint.py` | **棰勪及宸ユ椂**锛?.5h

---

#### 淇 G2: 鐪熷疄璺緞闆嗘垚娴嬭瘯 鈥?琛ヤ笂璺宠繃鐨勯偅娈甸摼璺?
**褰撳墠婕忔礊**锛氬洜瀛愯绠楀拰璁捐绠＄嚎娴嬭瘯鍏ㄩ儴缁曡繃 `_fetch_market_data()`锛岀洿鎺ユ敞鍏ラ鏋勯€犳暟鎹€備粠涓嶆祴璇?鏁版嵁婧愭寕浜?鐨勫満鏅€?
**鏂板娴嬭瘯 1锛氬洜瀛愰檷绾ц矾寰勬祴璇?*

```python
# tests/test_factor_registry.py 鏂板
async def test_compute_with_empty_fetch_returns_zeros():
    """褰?_fetch_market_data 杩斿洖绌烘椂锛屽洜瀛愬緱鍒嗗叏涓?0 浣嗕笉鎶涘紓甯搞€?""
    registry._fetch_market_data = AsyncMock(return_value={})
    result = await registry.compute(["000001", "000002"])
    for sym, scores in result.items():
        for code, val in scores.items():
            assert val == 0.0, f"{sym}.{code} = {val}, expected 0"
```

**鏂板娴嬭瘯 2锛氳璁＄紪鎺掑櫒闆嗘垚娴嬭瘯**

> **鏍囪涓?`@pytest.mark.slow`** 鈥?璇ユ祴璇曚細瑙﹀彂鐪熷疄鐨?pool_manager.refresh()锛堝惈澶栭儴缃戠粶璋冪敤锛夛紝涓嶉€傚悎 CI 蹇€熸祦姘寸嚎銆?
```python
# tests/test_design_pipeline_integration.py 鏂板
@pytest.mark.slow
async def test_generate_enhanced_design_returns_valid_strategies():
    """璋冪敤鐪熷疄缂栨帓鍣紙闈炵函寮曟搸锛夛紝楠岃瘉杈撳嚭绛栫暐瀹屾暣鎬с€?""
    result = await generate_enhanced_design(capital=500000)
    assert "strategies" in result
    assert len(result["strategies"]) >= 2  # 鑷冲皯 2 濂楁柟妗?    for s in result["strategies"]:
        etfs = [a for a in s.get("etfs", []) if a.get("symbol") != "CASH"]
        assert len(etfs) >= 3, f"Strategy {s.get('id')}: only {len(etfs)} non-CASH ETFs"
```

**鏂板娴嬭瘯 3锛氱┖姹犻檷绾ф祴璇?*

```python
# tests/test_strategy_design.py 鏂板
async def test_empty_candidate_pool_returns_error():
    """鍊欓€夋睜涓虹┖鏃讹紝缂栨帓鍣ㄨ繑鍥?error 鑰岄潪绌虹瓥鐣ャ€?""
    with patch.object(pool_manager, 'get_pool', return_value={"core": [], "satellite": [], "defense": []}):
        result = await generate_enhanced_design(capital=500000)
        assert "error" in result
        assert result["error"] == "鏃犲€欓€夋爣鐨?
```

**娑夊強鏂囦欢**锛歚tests/test_factor_registry.py`銆乣tests/test_design_pipeline_integration.py`銆乣tests/test_strategy_design.py`锛堟柊寤猴級 | **棰勪及宸ユ椂**锛?.5h

---

#### 淇 G3: 鍊肩骇璐ㄩ噺鏂█澧炲己

**褰撳墠婕忔礊**锛氭柇瑷€姝簬"瀛楁瀛樺湪"锛屼笉妫€鏌ュ瓧娈靛€肩殑鍚堢悊鎬с€?
```python
# 鐜扮姸
assert "confidence" in suggestion
assert "factor_summary" in holding

# 鐩爣
assert suggestion["confidence"] in ("high", "medium", "low")
if holding.get("factor_scores"):
    assert "蟽" in holding["factor_summary"]  # 鐪熷疄鍥犲瓙鍒嗘牸寮?```

**鍏蜂綋鏀瑰姩锛?*

| 娴嬭瘯鏂囦欢 | 鐜版湁娴嬭瘯 | 澧炲己鏂█ |
|----------|---------|---------|
| `test_strategy_check_async.py` | `test_strategy_check_returns_expected_structure` | 杩藉姞锛氶潪鍏?`low`锛堣嚦灏?1 鏉?confidence 涓?`medium` 鎴?`high`锛?|
| `test_design_optimization_plan.py` | `test_three_strategies_produced` | 杩藉姞锛歮ock 鍥犲瓙鍒嗗悗锛宖actor_summary 鏍煎紡鍚?蟽" |
| `test_pool_manager.py` | `test_refresh_populates_cache` | 杩藉姞锛歮arket_context 瀹屾暣锛堝惈 sector_momentum/market_sentiment/fund_flow锛?|

**鏂板钃濆浘**锛堥泦鎴愬埌 `verify_e2e.py` 鐨?design/strategy 绔犺妭涓紝澶嶇敤鍏?HTTP 鍩虹缁撴瀯鑰岄潪鐙珛鏂囦欢锛夛細

```python
# verify_e2e.py (娣卞寲璁捐绔犺妭鏂█)
def _check_design_content_quality():
    """璁捐鏂规璐ㄩ噺妫€鏌ワ細鈮? 濂楃瓥鐣ワ紝姣忓 鈮? 鍙潪 CASH ETF锛宒esign_text > 1000 瀛楃銆?""
    r = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=1")
    if r.status_code != 200 or not r.json():
        check("璁捐璐ㄩ噺妫€鏌?, False, "鏃犲彲鐢ㄨ璁?)
        return
    did = r.json()[0]["id"]
    detail = requests.get(f"{BASE}/api/v1/portfolio/designs/{did}").json()
    strategies = detail.get("strategies", [])
    check(f"璁捐鏂规鏁伴噺: {len(strategies)}", len(strategies) >= 2)
    for s in strategies:
        non_cash = [a for a in (s.get("etfs") or []) if a.get("symbol") != "CASH"]
        check(f"  绛栫暐 {s.get('id','?')} 闈炵幇閲戞爣鐨? {len(non_cash)} 鍙?,
              len(non_cash) >= 3)
    dt = detail.get("design_text", "")
    check(f"璁捐鏂囨湰闀垮害: {len(dt)} 瀛?, len(dt) > 1000)

def _check_factor_data_completeness():
    """鏈€鏂扮瓥鐣ユ鏌ワ細鑷冲皯 60% 鏍囩殑鏈夊畬鏁村洜瀛愭暟鎹€?""
    # 璋冪敤 strategy-checks 鎺ュ彛鑾峰彇鏈€鏂拌褰?    r = requests.get(f"{BASE}/api/v1/portfolio/strategy-checks?limit=1")
    if r.status_code != 200 or not r.json():
        check("鍥犲瓙瀹屾暣鎬ф鏌?, False, "鏃犵瓥鐣ユ鏌ヨ褰?)
        return
    data_quality = r.json()[0].get("data_quality", {})
    filled = data_quality.get("filled_count", 0)
    total = data_quality.get("total_count", 1)
    check(f"鍥犲瓙鏁版嵁瀹屾暣鐜? {filled}/{total}", filled / total > 0.6)
```

**娑夊強鏂囦欢**锛氬鏂囦欢 | **棰勪及宸ユ椂**锛?h

---

#### 淇 G4: 缂栫爜 roundtrip 娴嬭瘯

**褰撳墠婕忔礊**锛氭病鏈変换浣曟祴璇曢獙璇?涓枃鍐欏叆 DB 鈫?璇诲洖 鈫?鍐呭涓€鑷?銆?
```python
# tests/test_database.py 鏂板缓
@pytest.mark.asyncio
async def test_database_encoding_roundtrip():
    """鍐欏叆涓枃瀛楃涓诧紝璇诲洖鍚庡畬鍏ㄤ竴鑷淬€?""
    from app.database import async_session
    from app.models.portfolio_design import PortfolioDesign

    test_text = "绋冲仴鍨嬫柟妗堬細浣庢尝绋冲仴閰嶇疆锛屾帶鍒跺洖鎾わ紝閫傚悎淇濆畧鍨嬫姇璧勮€?

    async with async_session() as db:
        record = PortfolioDesign(
            capital=100000,
            risk_profile="balanced",
            design_text=test_text,
        )
        db.add(record)
        await db.commit()
        record_id = record.id

        # 閲嶆柊璇诲彇
        db2 = async_session()
        loaded = await db2.get(PortfolioDesign, record_id)
        assert loaded.design_text == test_text, \
            f"Mojibake detected!\n  wrote: {repr(test_text)}\n  read:  {repr(loaded.design_text)}"
```

**娑夊強鏂囦欢**锛歚tests/test_database.py`锛堟柊寤猴級 | **棰勪及宸ユ椂**锛?.5h

---

### 9.3 鍚勬祴璇曟枃浠舵敼鍔ㄦ竻鍗?
| 鏂囦欢 | 鏀瑰姩绫诲瀷 | 鍐呭 |
|------|----------|------|
| `tests/test_async_lint.py` | 澧炲己 | 鏂板 `test_no_direct_sync_call_in_async_function` |
| `tests/test_factor_registry.py` | 鏂板娴嬭瘯 | `test_compute_with_empty_fetch_returns_zeros` |
| `tests/test_design_pipeline_integration.py` | 鏂板娴嬭瘯 | `test_generate_enhanced_design_returns_valid_strategies` |
| `tests/test_strategy_design.py` | 鏂板缓鏂囦欢 | `test_empty_candidate_pool_returns_error` |
| `tests/test_strategy_check_async.py` | 澧炲己 | confidence 鍊肩骇鏂█杩藉姞 |
| `tests/test_design_optimization_plan.py` | 澧炲己 | factor_summary 鏍煎紡鏂█杩藉姞 |
| `tests/test_pool_manager.py` | 澧炲己 | market_context 瀹屾暣 key 鏂█ |
| `scripts/verify_e2e.py` | 澧炲己 | 鏂板 `_check_design_content_quality` + `_check_factor_data_completeness` |
| `tests/test_database.py` | 鏂板缓鏂囦欢 | 缂栫爜 roundtrip 娴嬭瘯 |

---

### 9.4 瀹炴柦鍓嶆彁鏉′欢

```
Phase 2.6 (寮傛杈圭晫淇) 蹇呴』鍏堝畬鎴?    鈫?鍚﹀垯 test_async_lint 鏂板娴嬭瘯浼氳鐪熷疄闃诲瑙﹀彂
Phase 2.7 (绯荤粺鎬ц川閲忎慨澶? 蹇呴』鍏堝畬鎴?    鈫?鍚﹀垯 test_generate_enhanced_design 浼氬洜绌烘睜/鏁版嵁缂哄け澶辫触
Phase 2.8 (娴嬭瘯闃叉姢澧炲己) 鈫?鏈柟妗?    鈫?鍙互浣滀负鐜版湁浠ｇ爜鐨勬渶鍚庝竴閬撳畨鍏ㄧ綉
鍚庣画鏃ュ父寮€鍙?```

### 闄勫綍锛氭枃浠跺紩鐢ㄧ储寮?
| 鏂囦欢 | 琛屽彿 | 璇存槑 | 鍏宠仈闂 |
|------|------|------|----------|
| `factor_registry.py` | 839-866 | Sina IOPV 鎵归噺鑾峰彇锛坲rllib.request.urlopen 闃诲锛?| Issue #1 |
| `factor_registry.py` | 906 | `compute()` 璋冪敤 `_fetch_market_data` 鍏ュ彛 | Issue #1, #3 |
| `factor_registry.py` | 919-922 | 鍥犲瓙璁＄畻澶辫触闈欓粯濉?0 | Issue #3 |
| `macro_state.py` | 94-126 | `_fetch_pmi_trend` 姝讳唬鐮?| Issue #1 |
| `macro_state.py` | 129-171 | `_fetch_rate_env` 姝讳唬鐮?| Issue #1 |
| `task_manager.py` | 225-242 | `design_pipeline` 绛栫暐缁撴灉鏍￠獙閫昏緫 | Issue #2 |
| `strategy_design.py` | 56-65 | 鍊欓€夋睜绌烘鏌?| Issue #2 |
| `portfolio_service.py` | 392-398 | `strategy_check` 鍥犲瓙鏁版嵁骞惰閲囬泦 | Issue #3 |
| `portfolio_service.py` | 505-508 | 鍥犲瓙娉ㄥ叆鍚庡鐞嗭紙all-0 璺宠繃锛?| Issue #3, #4 |
| `pool_manager.py` | 614-674 | `get_sector_momentum` / `get_market_sentiment` 缂撳瓨 | Issue #6 |

