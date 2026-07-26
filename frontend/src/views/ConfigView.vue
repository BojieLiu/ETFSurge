<template>
  <div class="config-page">
    <div class="page-header">
      <h1>系统配置</h1>
      <p class="subtitle">管理 API 密钥与服务配置 — 保存后即时生效，无需重启服务</p>
    </div>

    <div v-if="loading" class="loading">加载配置中...</div>

    <div v-else>
      <div v-if="saved" class="alert alert-success">配置已保存</div>
      <div v-if="saveError" class="alert alert-danger">{{ saveError }}</div>

      <div v-for="(group, gidx) in groupedItems" :key="gidx" class="config-group">
        <h2 class="group-title">{{ group.group }}</h2>
        <div class="config-card">
          <div v-for="item in group.items" :key="item.key" class="config-row">
            <div class="config-info">
              <div class="config-label">{{ item.label }}</div>
              <div class="config-desc">{{ item.description }}</div>
            </div>
            <div class="config-input-group">
              <input
                :type="item.show ? 'text' : 'password'"
                :value="getValue(item.key)"
                @input="setValue(item.key, $event.target.value)"
                :placeholder="item.configured ? '已配置' : item.placeholder || '输入密钥...'"
                class="config-input"
              />
              <button class="btn-toggle" @click="toggleShow(item.key)">
                {{ item.show ? '隐藏' : '显示' }}
              </button>
            </div>
            <div class="config-badge">
              <span v-if="item.from_env" class="badge badge-env">.env</span>
              <span v-else class="badge badge-db">已修改</span>
            </div>
          </div>
        </div>
      </div>

      <div class="config-actions">
        <button class="btn btn-primary" @click="saveConfig" :disabled="saving">
          {{ saving ? '保存中...' : '保存配置' }}
        </button>
        <button class="btn btn-secondary" @click="loadConfig">重置</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '../api/index.js'

const items = ref([])
const showMap = ref({})
const editMap = ref({})
const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const saveError = ref('')

const groupedItems = computed(() => {
  const groups = {}
  for (const item of items.value) {
    const g = item.group || '其他'
    if (!groups[g]) groups[g] = { group: g, items: [] }
    groups[g].items.push(item)
  }
  return Object.values(groups)
})

function getValue(key) {
  return editMap.value[key] ?? ''
}

function setValue(key, val) {
  editMap.value[key] = val
}

function toggleShow(key) {
  showMap.value[key] = !showMap.value[key]
}

async function loadConfig() {
  loading.value = true
  saved.value = false
  saveError.value = ''
  try {
    const resp = await adminApi.getConfig()
    const data = resp.data || resp
    items.value = (data.items || []).map((it) => ({
      ...it,
      show: false,
    }))
    editMap.value = {}
    showMap.value = {}
  } catch (e) {
    saveError.value = '加载配置失败: ' + (e.message || e)
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  saved.value = false
  saveError.value = ''
  // 只发送有改动的项
  const payload = {}
  for (const item of items.value) {
    const edited = editMap.value[item.key]
    if (edited !== undefined && edited !== (item.value || '')) {
      payload[item.key] = edited
    }
  }
  if (Object.keys(payload).length === 0) {
    saveError.value = '没有需要保存的改动'
    saving.value = false
    return
  }
  try {
    await adminApi.updateConfig(payload)
    saved.value = true
    await loadConfig()
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e) {
    saveError.value = '保存失败: ' + (e.message || e)
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.config-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 16px;
}
.page-header h1 {
  margin: 0 0 4px;
  font-size: 1.5rem;
  color: #e0e0e0;
}
.subtitle {
  color: #999;
  margin: 0 0 24px;
  font-size: 0.9rem;
}
.loading {
  text-align: center;
  padding: 48px;
  color: #999;
}
.alert {
  padding: 10px 16px;
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 0.9rem;
}
.alert-success {
  background: #1a3a2a;
  color: #4caf50;
  border: 1px solid #2e7d32;
}
.alert-danger {
  background: #3a1a1a;
  color: #f44336;
  border: 1px solid #c62828;
}
.config-group {
  margin-bottom: 24px;
}
.group-title {
  font-size: 1.1rem;
  color: #ccc;
  margin: 0 0 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #333;
}
.config-card {
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 8px;
  overflow: hidden;
}
.config-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a2a;
}
.config-row:last-child {
  border-bottom: none;
}
.config-info {
  flex: 1;
  min-width: 180px;
}
.config-label {
  font-weight: 600;
  color: #ddd;
  font-size: 0.9rem;
}
.config-desc {
  color: #888;
  font-size: 0.78rem;
  margin-top: 2px;
}
.config-input-group {
  display: flex;
  align-items: center;
  gap: 4px;
}
.config-input {
  width: 260px;
  padding: 6px 10px;
  border: 1px solid #444;
  border-radius: 4px;
  background: #252525;
  color: #e0e0e0;
  font-size: 0.85rem;
  font-family: monospace;
}
.config-input:focus {
  outline: none;
  border-color: #1976d2;
}
.btn-toggle {
  padding: 4px 8px;
  border: 1px solid #444;
  border-radius: 4px;
  background: #2a2a2a;
  color: #aaa;
  cursor: pointer;
  font-size: 0.78rem;
  white-space: nowrap;
}
.btn-toggle:hover {
  background: #333;
  color: #ddd;
}
.config-badge {
  width: 60px;
  text-align: center;
}
.badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 600;
}
.badge-env {
  background: #1a3a5c;
  color: #64b5f6;
}
.badge-db {
  background: #3a2a1a;
  color: #ffb74d;
}
.config-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}
.btn {
  padding: 10px 24px;
  border: none;
  border-radius: 6px;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-primary {
  background: #1976d2;
  color: #fff;
}
.btn-primary:hover {
  background: #1565c0;
}
.btn-primary:disabled {
  background: #444;
  color: #888;
  cursor: not-allowed;
}
.btn-secondary {
  background: #333;
  color: #ccc;
}
.btn-secondary:hover {
  background: #444;
}
</style>
