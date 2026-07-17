# Timezone Display Policy / 时区显示规范

## 1. 概述 / Overview

统一全平台时间显示为北京时间 (UTC+8, Asia/Shanghai)，避免时间混用导致用户混淆。

Unify all platform time display to Beijing time (UTC+8, Asia/Shanghai) to prevent user confusion from mixed timezones.

---

## 2. 策略 / Policy

| Layer | Storage Format | Display Format |
|-------|---------------|----------------|
| 数据库 (DB) | `UTC DateTime` (不改变现有存储) | — |
| API 响应 | `ISO 8601 UTC` (保持现有格式) | — |
| **前端展示** | — | **`Asia/Shanghai` (北京时间)** |

### 决策理由 / Rationale

- 数据库和 API 继续使用 UTC 作为标准交换格式（不破坏现有兼容性）
- 前端终端用户展示时转换到北京时间（用户在中国境内）
- 无需后端改动，纯前端转换
- 如果以后有海外用户，扩展为根据用户时区动态显示

### Implementation

```javascript
// 前端时间格式化 — UTC → 北京时间
function formatDate(utcStr) {
  if (!utcStr) return ''
  try {
    const d = new Date(utcStr)
    return d.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
      hour12: false,
    })
  } catch { return utcStr }
}
```

---

## 3. 受影响模块 / Affected Modules

| 模块 | 位置 | 变更内容 |
|------|------|----------|
| DashboardAiTools.vue | `formatDate()` 函数 | UTC 字符串 → Asia/Shanghai 显示 |
| 其他时间显示 | 无 | 当前仅此一处显示历史记录时间 |

---

## 4. 检查表 / Checklist

| Item | Status | Notes |
|------|--------|-------|
| 转换逻辑: UTC → Asia/Shanghai | ☐ | `toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })` |
| 格式: YYYY-MM-DD HH:mm | ☐ | 24小时制，中文格式 |
| 处理 null/undefined | ☐ | 返回空字符串 |
| 处理无效日期字符串 | ☐ | 返回原值 fallback |
| 单元测试覆盖 | ☐ | `formatDate.spec.js` |
