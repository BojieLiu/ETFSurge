# 2026-08-11 round14 测试防护盲区系统性分析（临时工作笔记，不入库）

## 16 个问题的测试覆盖对照

| # | 问题 | 对应测试 | 为何逃逸 |
|---|---|---|---|
| 5 watchlist 8.5s | test?（watchlist 相关） | 单测 mock 慢源不存在 |
| 6 信号不一致 3/10 | test_signal_consistency.py | monkeypatch 固定"同输入"掩盖真实数据差异 |
| 7 资讯分级盲区 | test_news_classification.py | 词典用例覆盖已知关键词，未测新增未收录 |
| 8 因子伪 IC | test_factors_router 校验负 IC warn | 缺"样本 0 时 IC 应无效"断言（P0-C） |
| 9 apply-design 断裂 | test_portfolio_apply_design.py | mock 掉真实函数，输入理想 symbols+weights |
| 16 组合展示 | test_design_report_format.py | 只验 200/格式，不验布局/颜色 |
| 5 江波龙 | 无 | asset_type=stock 未入批量，无该路径测试 |
| ... | | |
