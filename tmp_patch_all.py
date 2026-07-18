#!/usr/bin/env python3
"""批量修复：日志升级 + _warnings 传播 + prompt 规则1强化"""
import sys

# ── 1. strategy_design.py ─────────────────────────────────────
path = r"E:\ETF_Surge\backend\app\services\strategy_design.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# 1a. line 196: except Exception → add ERROR log
old = """        except Exception:
            strategies = []"""
new = """        except Exception as e:
            logger.error("[generate_full_design] generate_enhanced_design failed: %s", e)
            strategies = []"""
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("  [OK] strategy_design: line 196 ERROR log")
else:
    print("  [FAIL] strategy_design: line 196 not found")

# 1b. line ~768: WARNING → ERROR for pool_manager
old = """        logger.warning("pool_manager refresh failed: %s", e)"""
new = """        logger.error("pool_manager refresh failed: %s (will fallback to hardcoded pool)", e)"""
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("  [OK] strategy_design: pool_manager refresh log to ERROR")
else:
    print("  [FAIL] strategy_design: pool_manager refresh not found")

# 1c. line ~783: WARNING → ERROR for scan fallback
old = """            logger.warning("enhanced scan failed: %s", e)"""
new = """            logger.error("enhanced scan failed: %s (will fallback to hardcoded satellite pool)", e)"""
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("  [OK] strategy_design: enhanced scan log to ERROR")
else:
    print("  [FAIL] strategy_design: enhanced scan not found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"  strategy_design.py: {changes} change(s)")

# ── 2. llm.py ──────────────────────────────────────────────────
path = r"E:\ETF_Surge\backend\app\analysis\llm.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 2a. line ~414: except Exception → add WARNING log
old = """    except Exception:
        data = {}"""
new = """    except Exception as e:
        logger.warning("[news_impact] LLM analysis failed: %s", e)
        data = {}"""
if old in content:
    content = content.replace(old, new, 1)
    print("  [OK] llm.py: news_impact WARNING log")
else:
    print("  [FAIL] llm.py: news_impact not found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

# ── 3. design_report.md ─────────────────────────────────────────
path = r"E:\ETF_Surge\backend\app\analysis\prompts\v1\design_report.md"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = """## 规则1：不修改方案数据
- 方案中的 ETF 标的、权重、代码、层分布均由系统算法确定。
- 你**不能**改动这些数据。你的工作是**解读和补充分析**，不是重新设计。"""
new = """## 规则1：严格复制方案数据，不得以任何理由重新设计
- **方案中的 ETF 名称、代码、权重、层归属均由系统算法确定。你必须在报告中逐条原样引用这些标的，不得新增、删除、替换任何 ETF 代码。**
- 你的工作仅限于解读方案背后的配置逻辑、分析市场环境与方案的匹配度。
- 如果你认为存在更好的配置，只在「配置建议」章节用建议性语气提出（如"可考虑增加某类资产权重"），**不能在方案详解中修改具体标的**。
- 特别禁止：
  a) 引入候选池之外的 ETF（如 159934、512880 等引擎方案中未出现的代码）；
  b) 同一方案中出现两只同类型/同资产的 ETF（如两只黄金 ETF）；
  c) 改变引擎给出的层分配（核心/卫星/防御）。"""
if old in content:
    content = content.replace(old, new, 1)
    print("  [OK] design_report.md: Rule 1 strengthened")
else:
    print("  [FAIL] design_report.md: Rule 1 not found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

# ── 4. design_report.py ─────────────────────────────────────────
path = r"E:\ETF_Surge\backend\app\tasks\design_report.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 4a. 在 consistency check 中加 ERROR 日志
old = """    # 差集：LLM 写了哪些引擎没有的标的
    extra_symbols = report_symbols - engine_symbols
    if extra_symbols:"""
new = """    # 差集：LLM 写了哪些引擎没有的标的
    extra_symbols = report_symbols - engine_symbols
    if extra_symbols:
        logger.error(
            "[design_report] LLM introduced %d symbols outside engine pool: %s",
            len(extra_symbols), sorted(extra_symbols)
        )"""
if old in content:
    content = content.replace(old, new, 1)
    print("  [OK] design_report.py: consistency check ERROR log")
else:
    print("  [FAIL] design_report.py: consistency check not found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print()
print("ALL DONE")
