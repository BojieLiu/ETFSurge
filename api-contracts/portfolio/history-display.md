# History Display Fix / 历史记录展示修正

## 1. 概述 / Overview

历史记录列表中 `risk_profile` 字段直接暴露数据库原始值（"balanced"），对用户无意义。
改为展示固定的 "3 套方案" 文本，因为组合设计流水线始终生成防御型/平衡型/进攻型三套方案。

The history list currently displays the raw `risk_profile` DB value ("balanced"),
which has no business meaning since the design pipeline always generates 3 plans.
Replace with static "3 套方案" text.

---

## 2. 变更内容 / Changes

| 位置 | 文件 | 修改 |
|------|------|------|
| 历史面板列表 | `DashboardAiTools.vue` L52 | `{{ h.risk_profile }}` → `3 套方案` |
| 历史抽屉列表 | `DashboardAiTools.vue` L275 | `{{ h.risk_profile }}` → `3 套方案` |

---

## 3. 检查表 / Checklist

| Item | Status | Notes |
|------|--------|-------|
| 主面板 history list | ☐ | L52 替换 |
| 抽屉 history list | ☐ | L275 替换 |
| 无 API 变更 | ☐ | 纯前端文案 |
| 单元测试通过 | ☐ | formatDate、全量 |
| LSP 无错误 | ☐ | |
