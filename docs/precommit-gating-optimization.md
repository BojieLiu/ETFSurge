# Pre-commit 门禁优化设计（纯文档提交跳过 + pytest 触发面收紧）

> **性质**：设计文档（未实施）。目标：让纯文档/元数据提交不被全量 pytest 阻塞，同时不削弱门禁对真实代码变更的防护。
> **日期**：2026-08-09 · **基线**：pre-commit 8 道门禁（255 行，.githooks/pre-commit）· 全量 pytest 1620 passed / 3:39（2026-08-09 实测，commit 5a3ba15 触发）。
> **触发原因（实证）**：commit `5a3ba15`（归档 round9 + 同步 3 处测试 docstring 路径）因 `backend/tests/*.py` 注释变更匹配 `backend/*` → 全量 pytest 1620 个用例 3:39 阻塞，而实际代码逻辑零改动。

---

## 1. 背景与问题定义

### 现状：8 道门禁的触发面

| # | 门禁 | 行号 | 触发条件 | 纯 docs 提交触发？ |
|---|---|---|---|---|
| 1 | secret 泄漏扫描 | L12-81 | 所有暂存 `.py/.md/.json/.yml/.txt/...`（白名单排除 README/AGENTS/api-contracts/.env） | ✅ 触发（毫秒级，合理保留） |
| 2 | frontend build | L82-107 | `frontend/*` | ❌ |
| 3 | API 调用覆盖 | L109-131 | `frontend/src/api/*` | ❌ |
| 4 | audit_async_blocking | L133-156 | `backend/app/*.py` | ❌ |
| 5 | mypy | L157-180 | `backend/app/*.py` | ❌ |
| 6 | docker build 冒烟 | L182-209 | `backend/requirements.txt` `backend/Dockerfile` | ❌ |
| 7 | **pytest 全量** | L210-234 | **`backend/*`（含 tests/**）** | ⚠️ 触发（若在 backend/ 下） |
| 8 | smoke_startup | L236-259 | `backend/app/*.py` `/scripts/*.py` `requirements.txt` | ❌ |

### 问题

1. **pytest 全量触发面过宽**：`backend/*` 匹配到 `backend/tests/**` —— **测试文件的 docstring/注释修改也触发全量 1620 用例 pytest**（进入本轮真实发生，3:39 阻塞）；
2. **无"纯文档/元数据"统一快捷路径**：docs/ 提交虽然只触发 secret（毫秒）+ pytest，但**只要提交里混入一个 backend/test 文件（如归档同步注释），就升级为全量测试**；
3. **门禁意图错位**：pytest 门禁的本意是"backend/app 逻辑变更后，验证无回归"。test 文件自身的变更**不改变被测代码**，全量重跑是低杠杆（写 test 时已单文件验证过）。

---

## 2. 目标与非目标

**目标**：
- 纯文档/纯元数据提交（docs、测试注释/docstring）不被全量 pytest 阻塞；
- 真实代码变更（backend/app、scripts、requirements）的门禁防护**不减弱**；
- secret 扫描**始终保留**（文档也可能泄密，如误贴 API key）——本次实测 commit 5a3ba15 secret 扫描正常工作。

**非目标**（明确不做）：
- 不引入"文档也会污染 Secret"的例外（方案 2 反对——注释可能掩盖逻辑问题，自动化豁免风险不当）；
- 不做新数据源/新门禁类型的扩展；
- 不依赖 CI（本仓库无 CI 门禁，pre-commit 是唯一防线）。

---

## 3. 设计（两处改动）

### 3.1 改动 A：纯文档/元数据短路（提前 exit 0）

在 `.githooks/pre-commit` **L12 secret 段之后、L82 frontend 段之前**插入：

```sh
# ── 纯文档/元数据短路（P4-new，2026-08-09） ──────────────────────
# docs/（含 archived/）、api-contracts/ 为文档/契约，diag/ 为诊断产物——均不改变运行代码，
# 跳过全部编译/测试门禁。注：diag/ 下是诊断脚本与产物（非运行代码），归类为"非逻辑"。
# secret 扫描在上一段已执行（文档也可能泄漏 key），故短路的仅跳过 L82 及以后。
# ⚠️ 收益说明：基线 backend/* 本来就不匹配 docs/（纯 docs 提交不触发 pytest），本段价值是
#    ① 显式语义化（无歧义）；② 防未来在 docs/ 下新增 backend 同名目录导致的意外全量回归。
DOCS_ONLY_STAGED=$(git diff --cached --name-only --diff-filter=ACM -- \
    'docs/*' 'diag/*' 'api-contracts/*' 2>/dev/null || true)
NON_DOCS_STAGED=$(git diff --cached --name-only --diff-filter=ACM -- \
    ':!docs/*' ':!diag/*' ':!api-contracts/*' 2>/dev/null || true)
if [ -n "$DOCS_ONLY_STAGED" ] && [ -z "$NON_DOCS_STAGED" ]; then
    echo "[pre-commit] 纯文档/元数据提交（docs/diag/api-contracts），跳过编译与测试门禁（secret 已检查）"
    exit 0
fi
```

**关键点**：
- **secret 段（L8-81）在短路之前** → 文档泄密仍被拦截；
- `:!` 排除路径（git pathspec magic）确保**混入非文档变更时（如 backend/x.py）不短路**，正常跑后续所有门禁；
- **文档路径规格**：统一用 `docs/` 目录前缀（匹配 docs 下任意层级，含 `archived/`），不依赖 `**` 通配——`'docs/*'` 也递归匹配子目录，语义明确；`api-contracts/`（契约文档）入短路；`diag/`（诊断产物，含 .py/.cjs/.json，均非运行代码）一并入短路。

### 3.2 方案 B：pytest 触发面收紧（backend 逻辑变更 → 全量；测试文件变更 → 只跑相关）

将 L210-234 后端测试门禁分为两档：

```sh
# ── 后端测试门禁（收紧版，2026-08-09） ──────────────────────────
if [ "${SKIP_BACKEND_TESTS}" = "1" ]; then
    echo "[pre-commit] SKIP_BACKEND_TESTS=1, 跳过后端测试"
else
    # 档 0：conftest/fixtures 变更 → 全量（影响所有测试场景）
    CONFTEST_STAGED=$(git diff --cached --name-only --diff-filter=ACM \
        -- 'backend/tests/conftest.py' 'backend/tests/db_fixtures.py' 2>/dev/null || true)
    # 档 1：逻辑变更 → 全量 pytest。
    # ⚠️ backend/app/* 不限 .py：app 下含运行时非 .py（prompts/v1/*.md ×11、factors/factor_definitions.yaml），
    #    改 LLM prompt 模板 / 因子定义也属逻辑变更，必须触发全量（review H1 修正）。
    LOGIC_STAGED=$(git diff --cached --name-only --diff-filter=ACM \
        -- 'backend/app/*' 'backend/scripts/*.py' 'backend/requirements.txt' 2>/dev/null || true)
    # 档 2：仅测试 .py 变更 → 只跑变更的测试文件（秒级）
    TEST_STAGED=$(git diff --cached --name-only --diff-filter=ACM \
        -- 'backend/tests/*.py' 2>/dev/null || true)
    # 其它 backend 变更：根级散件（.env.example/pytest.ini/*.py 骨架）+ tests 下非 .py
    # （fixture 数据/快照）→ 全量保守不短路（review M1 修正：只排除 tests/*.py，非 .py 落 OTHER）
    OTHER_BACKEND=$(git diff --cached --name-only --diff-filter=ACM \
        -- 'backend/*' ':!backend/app/*' ':!backend/scripts/*' ':!backend/tests/*.py' 2>/dev/null || true)

    if [ -n "$CONFTEST_STAGED" ] || [ -n "$LOGIC_STAGED" ] || [ -n "$OTHER_BACKEND" ]; then
        echo "[pre-commit] 检测到后端逻辑变更，执行 pytest 全量 ..."
        cd backend
        if timeout 1800 python -m pytest -x 2>&1; then
            echo "[pre-commit] ✅ pytest 全量通过"; cd ..
        else
            cd ..; echo "🚫 pytest 失败或超时"; exit 1
        fi
    elif [ -n "$TEST_STAGED" ]; then
        # 纯测试文件 .py 变更（docstring/新增用例）→ 只跑变更的测试文件
        echo "[pre-commit] 检测到仅测试文件变更，执行受影响测试 ..."
        cd backend
        # 只跑变更的测试文件（替换 1620 全量；git diff 输出 backend/tests/test_x.py → 相对路径）
        TESTS_TO_RUN=$(printf '%s\n' "$TEST_STAGED" | sed 's#^backend/##' | tr '\n' ' ')
        # ⚠️ 保留基线 -x 快速失败语义（review M3：防多条失败全跑完才报）
        if timeout 600 python -m pytest -x $TESTS_TO_RUN 2>&1; then
            echo "[pre-commit] ✅ affected tests 通过"; cd ..
        else
            cd ..; echo "🚨 affected tests 失败（见上）"; exit 1
        fi
    fi
fi
```

**变量语义（正式实现以此为准）**：
- `CONFTEST_STAGED`：`conftest.py` / `db_fixtures.py` 变更 → **全量**（fixtures 影响所有用例，单文件跑会漏测）；
- `LOGIC_STAGED`：`backend/app/*`（含非 .py：prompts/*.md、factor_definitions.yaml） / `scripts/*.py` / `requirements.txt` 变更 → **全量**（核心防护，不减弱）；
- `OTHER_BACKEND`：backend 根级散件（.env.example/pytest.ini）、scripts/ 下非 .py、**及 tests/ 下非 .py**（fixture 数据/快照）→ 保守按全量（不猜）；
- `TEST_STAGED`：**仅** `backend/tests/*.py` 变更且上述三类都为空 → **只跑变更文件**（秒级）；
- 判定顺序：`CONFTEST/LOGIC/OTHER` 任一非空 → 全量；否则纯测试 → 只跑相关。

**关键点**：
- **逻辑变更（app 含非 .py / scripts / requirements）**→ 全量 pytest **不变**（防护核心）；
- **纯测试 .py 变更**（docstring/路径注释/新增用例）→ **只跑变更的测试文件**（秒级，替代 1620/3:39）；
- 若同时含逻辑+测试变更 → 走全量（`LOGIC_STAGED` 优先）；
- timeout 从 1800 降为测试档 600 + `-x` 保留（快速失败，基线语义不变）。

---

## 4. 行为对比表

| 提交类型 | 现状 | 方案后 |
|---|---|---|
| 纯 docs/*.md（如 round13 方案文档） | secret（毫秒）+ pytest 不触发 ✅ | secret + 短路 exit 0（秒） |
| docs + backend/tests 注释同步（如 commit 5a3ba15） | secret + 全量 pytest 1620/3:39 | secret + 只跑变更 3 个测试（秒） |
| backend/app/*.py 逻辑修复 | secret + 全量 pytest | secret + 全量 pytest（不变） |
| frontend/* 组件 | secret + npm build | secret + npm build（不变） |
| requirements.txt + Dockerfile | secret + docker build + pytest | secret + docker build + pytest（不变） |
| 混合（docs + app 代码） | secret + 全量 | secret + 全量（不短路，正确） |

---

## 5. 风险与边界

1. **短路安全性**：方案 A 短路仅当 `DOCS_ONLY` 非空且 `NON_DOCS` 为空（即所有暂存文件都在 docs/diag/api-contracts 下）。`docs/*` 匹配 docs 下**所有**路径（含 docs 内 .py 示例）——docs 内文件会被成对匹配（DOCS 命中、NON_DOCS 排除），**不会**出现"docs 内 .py 被短路却不算文档"的矛盾。**决策**：docs 整体短路 exit 0（docs 内 .py 极少且为示例，不参与运行时；若未来 docs 内出现真实运行 .py，需人为改为走逻辑档，但这超出当前范围）。
2. **conftest 档**：方案 B 单独档位处理 conftest/db_fixtures（全量），防"改了 fixtures 只跑单文件"漏测。
3. **timeout 下降**：测试档 600s，若某单测自己慢仍可能 600 超时——但单文件测试通常 <1s（本轮 3 个文件 1s 内），600 余量充足。
4. **不减弱核心防护**：app/scripts/requirements 变更仍全量 pytest；mypy/audit/docker 不受影响。
5. **SKIP 变量兼容**：所有 `SKIP_*` 快捷方式保留，短路不发生（短路只影响额外提速，不影响手动跳过）。

---

## 6. 评估结论

- **推荐实施**：两处改动（A 段 L12-81 后插短路；B 段 L210-234 重写为两档 + conftest 档）。
- **收益**：命中场景（纯文档/纯测试注释）从 3:39 全量 → 秒级；核心代码保护不变。
- **不做**：方案 2（注释豁免）——不削弱自动化对"隐藏逻辑"的检测，且实现复杂。
- **不新增门禁**：本设计只改触发面，不加新门禁。

---

## 7. 落地步骤（实施时）

1. 按上文编辑 `.githooks/pre-commit`（A 段 L12 后插入短路；B 段 L210 重写为三档：逻辑全量 / 纯测试文件 / conftest 全量）；
2. 本地验证：
   - `git add docs/某.md && git commit` → 打印"纯文档短路，跳过测试"，无 pytest；
   - `git add backend/tests/test_x.py（仅注释）&& git commit` → 打印"测试文件变更，跑受影响测试"，只跑该文件；
   - `git add backend/app/某.py && git commit` → 全量 pytest 照跑；
   - `git add docs/某.md backend/app/某.py && git commit` → 不短路，全量。
3. `AGENTS.md` 或文档加注（可选）：pre-commit 门禁触发面已收窄（三类提交）。