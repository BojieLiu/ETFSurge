# Contract: Runtime Config Management / 运行时配置管理

## 1. 概述 / Overview

**功能**: 允许用户通过前端 UI 查看和修改 API Key 等运行时配置，无需编辑 `.env` 文件或重启服务。

**触发场景**: 用户打开"系统配置"页面时加载配置；修改后点击"保存"时提交。

---

## 2. 端点定义 / Endpoints

### 2.1 GET /api/v1/admin/config

获取所有可配置项的当前值（含 DB overrides + .env fallback）。

#### 响应 / Response

```json
{
  "items": [
    {
      "key": "DEEPSEEK_API_KEY",
      "label": "DeepSeek API Key",
      "group": "LLM 服务",
      "description": "DeepSeek 官方 API 密钥，用于 LLM 分析和报告生成（降级线路）",
      "value": "sk-...",
      "configured": true,
      "from_env": true
    }
  ],
  "total": 7
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| key | string | 配置键名，如 `DEEPSEEK_API_KEY` |
| label | string | 显示名称 |
| group | string | 分组，如 `LLM 服务` / `数据源` |
| description | string | 描述文本 |
| value | string | 当前值（脱敏显示），空字符串表示未配置 |
| configured | boolean | 是否已有值 |
| from_env | boolean | 是否来自 `.env` 文件（false = 来自 DB override） |

### 2.2 PUT /api/v1/admin/config

批量更新配置项，UPSERT 语义。

#### 请求 / Request

```json
{
  "DEEPSEEK_API_KEY": "sk-xxx",
  "TUSHARE_TOKEN": "yyyy"
}
```

#### 响应 / Response

```json
{
  "results": {
    "DEEPSEEK_API_KEY": "updated",
    "TUSHARE_TOKEN": "updated"
  }
}
```

只处理在 `CONFIG_ITEMS` 中定义的 key，未知 key 返回 `skipped (unknown key)`。

### 2.3 DELETE /api/v1/admin/config/{key}

删除配置项的 DB override，恢复为 `.env` 值。

#### 响应 / Response

```json
{
  "status": "deleted",
  "key": "DEEPSEEK_API_KEY"
}
```

---

## 3. 数据模型 / Data Model

### app_config 表

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| key | VARCHAR(100) | PK | 配置键名 |
| value | VARCHAR(500) | NOT NULL | 配置值 |
| updated_at | DATETIME | DEFAULT NOW() | 最后更新时间 |

---

## 4. 数据流 / Data Flow

```
启动时: init_db() → create_all (含 app_config 表) → ConfigManager.init(session_factory)
用户配置: ConfigView.vue → PUT /admin/config → admin.py → ConfigManager.set_override() → DB UPSERT
运行时读取: 各 fetcher 调用 config_manager.get(key) → DB 查询 → .env fallback
```

## Frontend-Backend Checklist

| # | 项目 | 状态 |
|---|------|------|
| 1 | `api-contracts/admin/config.md` 已创建 | ✅ |
| 2 | 后端 `PUT /admin/config` 实现 | ✅ |
| 3 | 后端 `GET /admin/config` 实现 | ✅ |
| 4 | 后端 `DELETE /admin/config/{key}` 实现 | ✅ |
| 5 | 前端 `ConfigView.vue` 创建 | ✅ |
| 6 | 前端路由 `/admin/config` 注册 | ✅ |
| 7 | 前端导航项"配置"添加 | ✅ |
| 8 | 前端 `adminApi.getConfig` / `updateConfig` | ✅ |
| 9 | 解析 `PUT` 响应中的 `results` | ✅ |
