
## 附录：决策日志

### D1 — 全市场筛选替代硬编码池
- **时间**: 2026-07-20
- **决策**: 取消 CANDIDATE_POOL 硬编码 20 只 ETF，使用 etf_scanner.full_pipeline 全市场扫描 + pool_manager 动态池
- **原因**: 硬编码池覆盖率低（仅 20 只），缺乏行业多样性，且无法根据市态动态调整
- **影响**: 候选池从 20 只扩展到 ~45 只动态池；strategy_design.py 减少 ~40 行

### D2 — 无降级路径
- **时间**: 2026-07-20
- **决策**: 删除 pool_ready → scanner → hardcoded 三层降级链
- **原因**: 降级链产出的方案无因子分和趋势数据，入选理由大量空白，不如直接报错
- **替代方案**: 原降级链意图是保证"总有方案可用"，但质量不可接受
- **影响**: strategy_design.py 减少 ~40 行；非交易时段编排器可能抛出异常

### D3 — 策略引擎剥离为纯函数
- **时间**: 2026-07-20
- **决策**: 新建 engine/ 包，allocate() 为纯函数（无 I/O 无 fallback）
- **原因**: 现有策略引擎逻辑嵌在数据采集代码中，无法独立测试，单测需 mock 8 个外部调用
- **替代方案**: 在 strategy_design.py 内部局部抽象，但引入的调用链复杂度不降反升
- **影响**: 新增 ~5 个文件，engine/ 包可纯输入输出测试

### D4 — FactorRegistry 假数据 fallback 删除
- **时间**: 2026-07-20
- **决策**: 删除 _fetch_market_data 中失败时返回合成上涨序列的逻辑
- **原因**: 合成数据使下游无法辨别因子分是真实计算还是 placeholder，导致决策依据不可追溯
- **替代方案**: 在合成数据上加标记位（is_fake），但多了每个消费者都要判断标记的复杂度
- **影响**: factor_registry.py 减少 ~7 行，编排器在数据源不可用时抛出异常

### D5 — 市场研判改为编排器唯一输入
- **时间**: 2026-07-20
- **决策**: llm-report 端点删除 _fetch_all_market() 和 _collect_news() 自采逻辑，改为编排器 market_context 作为唯一输入
- **原因**: 编排器已有全部所需数据且已缓存；旧链路自采导致重复采集和多套数据来源不一致
- **替代方案**: "有则用无则降级自采"的双轨方案，但保留自采即保留冗余代码和静默吞错模式
- **影响**: analysis.py 减少 ~80 行，llm-report 可用性依赖于编排器正常运行

### D6 — 新闻纳入数据管道
- **时间**: 2026-07-20
- **决策**: pool_manager.refresh() 新增 news 产出字段，各链路从管道读取新闻
- **原因**: 6 条链路各自独立采集资讯，造成重复；集中采集后 cache TTL 可统一控制
- **影响**: 管道产出从 8 项增至 12 项；市场研判、板块分析、资讯分析免自采新闻

### D7 — llm-advice 智能注入
- **时间**: 2026-07-20
- **决策**: AI 投资顾问端点自动从管道注入 market_context，按 query 关键词决定注入维度
- **原因**: LLM 训练数据存在截止日期，无法回答实时行情问题；全量注入 token 成本过高
- **替代方案**: 无差别全量注入（~3000 tokens），但对简单问题性价比低
- **影响**: 零额外采集成本，平均每次 +800 tokens

### D8 — 板块分析仅增强不可替代
- **时间**: 2026-07-20
- **决策**: sector_momentum 仅作为 LLM prompt 补充上下文，板块成分股仍需自采
- **原因**: compute_sector_momentum 与 fetch_industry_sectors 数据源不同、字段不同；管道不提供成分股明细
- **影响**: 板块分析复用等级定为 P2

### D9 — 个股分析候选池局限性
- **时间**: 2026-07-20
- **决策**: symbol-analysis 复用 factor_matrix 的前提是标的在候选池内，池外标的 fallback 自采
- **原因**: 候选池仅覆盖 ~45 只 ETF，无法预知用户会查询哪只个股或港美股
- **影响**: 约 30% 查询可命中 factor_matrix 免自采，其余走原路径

### D10 — 市场综合研判改为 WS async
- **时间**: 2026-07-20
- **决策**: llm-report 新增 POST /async-task?type=report 入口，后端 report_worker 异步生成
- **原因**: 耗时 15-40s，SSE 要求用户保持页面打开；WS async 用户可自由浏览
- **替代方案**: 维持 SSE stream 但用户不能离开页面
- **影响**: 新增 report_worker.py，前端可复用现有 TaskManager 状态监听

### D11 — TaskManager 泛化
- **时间**: 2026-07-20
- **决策**: DesignTaskManager → TaskManager，task_type 泛化，WorkerRegistry 注册制
- **原因**: design_tasks.py 的 task 结构含 design 专属字段，无法支持 report 等新类型
- **影响**: 3 个文件 7 处 import 更新

### D12 — Phase 2→3 设 Gate
- **时间**: 2026-07-20
- **决策**: Phase 2（FactorRegistry 修复）必须通过测试 + pool_manager 产出验证后才进 Phase 3
- **原因**: Phase 3 的新编排器依赖 Phase 2 的 FactorRegistry 产出正常因子分
- **影响**: 阻止 Phase 3 在因子系统未就绪时启动

### D13 — 前端 loading 进度条抽取通用组件
- **时间**: 2026-07-20
- **决策**: DashboardAiTools.vue 的 loading UI + 策略检查 loading 区 → 通用 TaskProgress.vue
- **原因**: 两个异步任务页面有相同进度条模式（步骤列表 + 百分比 + 文字提示），代码重复
- **影响**: 减少 ~60 行重复代码

### D14 — 数据源优于旧链路裸调
- **时间**: 2026-07-20
- **决策**: 管道数据源采用已封装降级链的服务层（market_service.get_global_indices 等），而非直接 yfinance
- **原因**: 旧链路直接调 yfinance 无降级，市场服务已封装 stooq/akshare 等更稳定来源
- **影响**: 管道数据源稳定性高于旧链路
