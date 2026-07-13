<template>
  <div class="dashboard">
    <!-- Page Header -->
    <header class="page-header">
      <h1 class="page-title">Dashboard</h1>
      <p class="page-description">实时行情监控、组合概览与智能策略分析</p>
    </header>

    <!-- Core Actions: AI Portfolio Design & Strategy Check (Interactive Panel) -->
    <section class="card core-actions">
      <div class="card-header">
        <h2 class="card-title">
          <span class="card-title-icon" aria-hidden="true">🤖</span>
          核心功能
        </h2>
      </div>

      <!-- Default: Feature Entrances -->
      <div v-if="!activeCoreFeature" class="core-actions-grid">
        <button
          class="core-action-btn"
          @click="enterDesignMode"
          :disabled="designing"
        >
          <span class="action-icon" aria-hidden="true">✨</span>
          <div class="action-content">
            <span class="action-title">AI 智能组合设计</span>
            <span class="action-desc">基于当前行情生成三种风格的 ETF 组合方案</span>
          </div>
          <span v-if="designing" class="action-loading" aria-hidden="true">⏳</span>
        </button>

        <button
          class="core-action-btn"
          @click="enterStrategyMode"
          :disabled="checkingStrategy || !store.etfs.length"
        >
          <span class="action-icon" aria-hidden="true">🎯</span>
          <div class="action-content">
            <span class="action-title">策略检查与调仓建议</span>
            <span class="action-desc" v-if="store.etfs.length">分析当前组合，给出权重调整/替换建议</span>
            <span class="action-desc empty" v-else>请先在组合管理中添加 ETF</span>
          </div>
          <span v-if="checkingStrategy" class="action-loading" aria-hidden="true">⏳</span>
        </button>
      </div>

      <!-- AI Portfolio Design Wizard / Result -->
      <div v-else-if="activeCoreFeature === 'design'" class="core-feature-panel">
        <div class="panel-header">
          <button class="panel-back" @click="exitCoreFeature" aria-label="返回">
            ← 返回
          </button>
          <h3 class="panel-title">AI 智能组合设计</h3>
        </div>

        <!-- Wizard Step -->
        <div v-if="designStep === 'wizard'" class="panel-body design-wizard">
          <p class="wizard-hint">选择生成参数，点击生成三种风格的组合方案</p>

          <div class="wizard-fields">
            <label class="wizard-field">
              <span class="field-label">风险偏好</span>
              <select v-model="designParams.riskProfile" class="wizard-select">
                <option value="balanced">均衡型</option>
                <option value="growth">成长型</option>
                <option value="conservative">稳健型</option>
              </select>
            </label>

            <label class="wizard-field">
              <span class="field-label">投资金额（元）</span>
              <AppInput
                type="number"
                v-model.number="designParams.capital"
                :min="10000"
                :step="10000"
                placeholder="例：500000"
              />
            </label>
          </div>

          <AppButton
            variant="primary"
            class="wizard-generate"
            @click="generateDesign"
            :loading="designing"
            :disabled="designing"
          >
            生成组合方案
          </AppButton>
        </div>

        <!-- Result Step -->
        <div v-else-if="designStep === 'result' && designResult?.plans?.length" class="panel-body design-result">
          <p class="result-hint">共生成 {{ designResult.plans.length }} 个方案，点击卡片查看详情并应用</p>

          <div class="design-plans-grid">
            <article
              v-for="pf in designResult.plans"
              :key="pf.style"
              class="design-plan-card"
              @click="selectPlan(pf)"
            >
              <div class="plan-header">
                <span class="plan-style-badge">{{ pf.style_label || pf.style }}</span>
                <span class="plan-score" v-if="pf.score !== undefined">评分 {{ pf.score }}</span>
              </div>

              <div class="plan-meta">
                <span class="plan-meta-item">
                  <span class="meta-label">预期年化</span>
                  <span class="meta-value">{{ (pf.expected_return * 100).toFixed(1) }}%</span>
                </span>
                <span class="plan-meta-item">
                  <span class="meta-label">最大回撤</span>
                  <span class="meta-value">{{ (pf.max_drawdown * 100).toFixed(1) }}%</span>
                </span>
                <span class="plan-meta-item">
                  <span class="meta-label">夏普比率</span>
                  <span class="meta-value">{{ pf.sharpe_ratio?.toFixed(2) || '—' }}</span>
                </span>
              </div>

              <div class="plan-allocation-preview">
                <span class="alloc-label">配置预览</span>
                <div class="alloc-bars">
                  <div
                    v-for="item in pf.allocations?.slice(0, 5) || []"
                    :key="item.symbol"
                    class="alloc-bar"
                    :style="{ width: (item.target_weight * 100) + '%' }"
                    :title="`${item.symbol} ${(item.target_weight * 100).toFixed(1)}%`"
                  ></div>
                </div>
              </div>

              <div v-if="pf.risk_warnings" class="plan-risk-warn">
                ⚠️ {{ pf.risk_warnings }}
              </div>

              <div class="plan-action">
                <AppButton
                  variant="primary"
                  size="sm"
                  @click.stop="applyPortfolioDesign(pf)"
                  :disabled="applyingPlan === pf.style"
                >
                  {{ applyingPlan === pf.style ? '应用中...' : '应用此组合' }}
                </AppButton>
              </div>
            </article>
          </div>

          <div class="panel-footer-actions">
            <AppButton variant="ghost" @click="resetDesign">重新生成</AppButton>
            <AppButton variant="ghost" @click="exitCoreFeature">完成</AppButton>
          </div>
        </div>

        <!-- Loading / Empty -->
        <div v-else class="panel-body design-loading">
          <div class="loading-spinner" v-if="designing">⏳ 正在生成方案...</div>
          <div class="empty-hint" v-else>暂无方案，请点击生成</div>
        </div>
      </div>

      <!-- Strategy Check Panel -->
      <div v-else-if="activeCoreFeature === 'strategy'" class="core-feature-panel">
        <div class="panel-header">
          <button class="panel-back" @click="exitCoreFeature" aria-label="返回">
            ← 返回
          </button>
          <h3 class="panel-title">策略检查与调仓建议</h3>
        </div>

        <div class="panel-body strategy-result" v-if="strategyResult">
          <div v-if="strategyResult.summary" class="strategy-summary">
            {{ strategyResult.summary }}
          </div>

          <div v-if="strategyResult.suggestions?.length" class="suggestions-list">
            <div
              v-for="(s, i) in strategyResult.suggestions"
              :key="i"
              class="suggestion-item"
            >
              <div class="suggestion-main">
                <span class="action-badge" :class="s.action">{{ getActionLabel(s.action) }}</span>
                <strong>{{ s.name }}</strong> <code>({{ s.symbol }})</code>
                <span v-if="s.action === 'adjust_weight'" class="weight-change">
                  {{ (s.current_weight * 100).toFixed(1) }}% → {{ (s.suggested_weight * 100).toFixed(1) }}%
                </span>
              </div>
              <div class="suggestion-reason">{{ s.reason }}</div>
            </div>
          </div>

          <div v-else class="no-suggestions">
            <span class="success-icon" aria-hidden="true">✅</span>
            当前组合配置合理，无需调整
          </div>

          <div class="panel-footer-actions" v-if="strategyResult.suggestions?.length">
            <AppButton variant="primary" @click="applySuggestions">应用全部建议</AppButton>
            <AppButton variant="ghost" @click="clearStrategyResult">关闭</AppButton>
          </div>

          <div v-else class="panel-footer-actions">
            <AppButton variant="ghost" @click="exitCoreFeature">完成</AppButton>
          </div>
        </div>

        <div v-else class="panel-body strategy-loading">
          <div class="loading-spinner" v-if="checkingStrategy">🔍 正在分析组合...</div>
          <div class="empty-hint" v-else>
            <AppButton variant="primary" @click="checkStrategy" :loading="checkingStrategy" :disabled="!store.etfs.length">
              开始检查
            </AppButton>
            <p v-if="!store.etfs.length" class="empty-note">请先在组合管理中添加 ETF</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Global Indices - Ultra Compact -->
    <section class="card global-indices-compact">
      <div class="card-header-compact">
        <h2 class="card-title">
          <span class="card-title-icon" aria-hidden="true">🌐</span>
          全球主流指数
        </h2>
        <div class="card-actions-compact">
          <span class="status-badge" v-if="marketTimer" aria-live="polite">
            <span class="status-dot" aria-hidden="true"></span>
            自动刷新
          </span>
          <AppButton variant="ghost" size="xs" @click="fetchGlobalIndices" :loading="marketLoading">
            刷新
          </AppButton>
        </div>
      </div>

      <div v-if="hasGlobalIndices" class="indices-scroll">
        <div
          class="index-card-compact"
          v-for="idx in Object.values(globalIndices).flat()"
          :key="idx.symbol"
          :class="{ unavailable: !idx.available }"
        >
          <span class="index-name-compact">{{ idx.name }}</span>
          <span class="index-price-compact" v-if="idx.available">{{ formatPrice(idx.price) }}</span>
          <span class="index-price-compact muted" v-else>—</span>
          <span class="index-change-compact" v-if="idx.available" :class="getChangeClass(idx.change_pct)">
            {{ formatChange(idx.change_pct) }}
          </span>
          <span class="index-change-compact muted" v-else>暂无</span>
        </div>
      </div>
      
      <div v-else class="indices-empty-compact">
        暂无数据，点击刷新获取
      </div>
    </section>

    <!-- Portfolio Type Tabs -->
    <div class="tabs" role="tablist" aria-label="组合类型">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        :class="['tab', { 'tab--active': activeTab === tab.value }]"
        @click="activeTab = tab.value"
        role="tab"
        :aria-selected="activeTab === tab.value"
        :aria-controls="`panel-${tab.value}`"
        :id="`tab-${tab.value}`"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Capital Input Bar -->
    <section class="card capital-bar">
      <div class="capital-inputs">
        <label v-if="activeTab === 'on_exchange'" class="input-group">
          <span class="input-label">场内仓位</span>
          <AppInput
            type="number"
            v-model.number="capitalOn"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            aria-label="场内仓位金额"
          />
        </label>
        <label v-else-if="activeTab === 'off_exchange'" class="input-group">
          <span class="input-label">场外仓位</span>
          <AppInput
            type="number"
            v-model.number="capitalOff"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            aria-label="场外仓位金额"
          />
        </label>
        <label v-else class="input-group dual">
          <span class="input-label">场内仓位</span>
          <AppInput
            type="number"
            v-model.number="capitalOn"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            size="sm"
            aria-label="场内仓位金额"
          />
          <span class="input-label">场外仓位</span>
          <AppInput
            type="number"
            v-model.number="capitalOff"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            size="sm"
            aria-label="场外仓位金额"
          />
        </label>
      </div>
      <div class="capital-actions">
        <AppButton variant="secondary" @click="refreshAll" :loading="loading">
          <span class="btn-icon" aria-hidden="true">↻</span>
          刷新
        </AppButton>
        <AppButton variant="primary" @click="checkStrategy" :loading="checkingStrategy">
          <span class="btn-icon" aria-hidden="true">🔍</span>
          检查策略
        </AppButton>
      </div>
    </section>

    <!-- Summary Cards -->
    <div class="summary-grid">
      <article class="card summary-card" v-if="activeTab === 'combined'">
        <div class="summary-icon" aria-hidden="true">💰</div>
        <div class="summary-content">
          <p class="summary-label">总仓位</p>
          <p class="summary-value" :class="loading ? 'skeleton' : ''" aria-live="polite">
            <Skeleton v-if="loading" type="text" width="120" />
            <span v-else>¥{{ formatNum(totalAll) }}</span>
          </p>
        </div>
      </article>

      <article class="card summary-card" v-if="activeTab !== 'off_exchange'">
        <div class="summary-icon" :class="pnlOn >= 0 ? 'positive' : 'negative'" aria-hidden="true">
          {{ pnlOn >= 0 ? '📈' : '📉' }}
        </div>
        <div class="summary-content">
          <p class="summary-label">场内当日盈亏</p>
          <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOn >= 0 ? 'text-success' : 'text-danger']" aria-live="polite">
            <Skeleton v-if="loading" type="text" width="120" />
            <span v-else>¥{{ formatNum(pnlOn) }}</span>
          </p>
        </div>
      </article>

      <article class="card summary-card" v-if="activeTab !== 'on_exchange'">
        <div class="summary-icon" :class="pnlOff >= 0 ? 'positive' : 'negative'" aria-hidden="true">
          {{ pnlOff >= 0 ? '📈' : '📉' }}
        </div>
        <div class="summary-content">
          <p class="summary-label">场外当日盈亏</p>
          <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOff >= 0 ? 'text-success' : 'text-danger']" aria-live="polite">
            <Skeleton v-if="loading" type="text" width="120" />
            <span v-else>¥{{ formatNum(pnlOff) }}</span>
          </p>
        </div>
      </article>
    </div>

    <!-- Loading Skeletons -->
    <div v-if="loading" class="loading-grid" aria-busy="true" aria-label="加载中">
      <div class="card skeleton-card">
        <Skeleton type="chart" height="260" />
      </div>
      <div class="card skeleton-card">
        <Skeleton type="table" rows="6" />
      </div>
    </div>

    <!-- Content -->
    <template v-else>
      <!-- On Exchange Allocation -->
      <div v-if="allocationOn?.allocations?.length && (activeTab === 'on_exchange' || activeTab === 'combined')" class="content-grid">
        <section class="card chart-card" :id="`panel-on_exchange`" role="tabpanel" aria-labelledby="tab-on_exchange">
          <div class="card-header">
            <h2 class="card-title">
              <span class="card-title-icon" aria-hidden="true">🥧</span>
              场内分配
            </h2>
            <div class="card-meta">
              <span class="meta-item">
                <span class="meta-label">现金</span>
                <span class="meta-value" :class="cashPctOn >= 0.1 ? 'text-warning' : ''">{{ (cashPctOn * 100).toFixed(1) }}%</span>
              </span>
              <span class="meta-item">
                <span class="meta-value">¥{{ formatNum(cashOn) }}</span>
              </span>
            </div>
          </div>
          <v-chart :option="pieOptionOn" :style="{ height: '280px' }" autoresize />
        </section>

        <section class="card table-card" role="tabpanel" aria-labelledby="tab-on_exchange">
          <div class="card-header">
            <h2 class="card-title">
              <span class="card-title-icon" aria-hidden="true">📋</span>
              场内 ETF 目标分配
            </h2>
          </div>
          <div class="table-responsive">
            <table class="data-table">
              <thead>
                <tr>
                  <th scope="col">代码</th>
                  <th scope="col">名称</th>
                  <th scope="col">权重</th>
                  <th scope="col">目标金额</th>
                  <th scope="col">现价</th>
                  <th scope="col">实时涨跌幅</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in allocationOn.allocations" :key="item.symbol">
                  <td><code>{{ item.symbol }}</code></td>
                  <td><strong>{{ item.name }}</strong></td>
                  <td><span class="weight-badge">{{ (item.target_weight * 100).toFixed(1) }}%</span></td>
                  <td>¥{{ formatNum(item.target_amount) }}</td>
                  <td>¥{{ formatPrice(item.current_price) }}</td>
                  <td :class="getChangeClass(item.change_pct)">
                    <span class="change-value">{{ formatChange(item.change_pct) }}</span>
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="footer-row">
                  <td colspan="2"><strong>现金仓位</strong></td>
                  <td><span class="weight-badge">{{ (cashPctOn * 100).toFixed(1) }}%</span></td>
                  <td><strong>¥{{ formatNum(cashOn) }}</strong></td>
                  <td colspan="2">—</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
      </div>

      <!-- Off Exchange Allocation -->
      <div v-if="allocationOff?.allocations?.length && (activeTab === 'off_exchange' || activeTab === 'combined')" class="content-grid">
        <section class="card chart-card" :id="`panel-off_exchange`" role="tabpanel" aria-labelledby="tab-off_exchange">
          <div class="card-header">
            <h2 class="card-title">
              <span class="card-title-icon" aria-hidden="true">🥧</span>
              场外分配
            </h2>
            <div class="card-meta">
              <span class="meta-item">
                <span class="meta-label">现金</span>
                <span class="meta-value" :class="cashPctOff >= 0.1 ? 'text-warning' : ''">{{ (cashPctOff * 100).toFixed(1) }}%</span>
              </span>
              <span class="meta-item">
                <span class="meta-value">¥{{ formatNum(cashOff) }}</span>
              </span>
            </div>
          </div>
          <v-chart :option="pieOptionOff" :style="{ height: '280px' }" autoresize />
        </section>

        <section class="card table-card" role="tabpanel" aria-labelledby="tab-off_exchange">
          <div class="card-header">
            <h2 class="card-title">
              <span class="card-title-icon" aria-hidden="true">📋</span>
              场外 ETF 目标分配
            </h2>
          </div>
          <div class="table-responsive">
            <table class="data-table">
              <thead>
                <tr>
                  <th scope="col">代码</th>
                  <th scope="col">名称</th>
                  <th scope="col">权重</th>
                  <th scope="col">目标金额</th>
                  <th scope="col">现价</th>
                  <th scope="col">实时涨跌幅</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in allocationOff.allocations" :key="item.symbol">
                  <td><code>{{ item.symbol }}</code></td>
                  <td><strong>{{ item.name }}</strong></td>
                  <td><span class="weight-badge">{{ (item.target_weight * 100).toFixed(1) }}%</span></td>
                  <td>¥{{ formatNum(item.target_amount) }}</td>
                  <td>¥{{ formatPrice(item.current_price) }}</td>
                  <td :class="getChangeClass(item.change_pct)">
                    <span class="change-value">{{ formatChange(item.change_pct) }}</span>
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="footer-row">
                  <td colspan="2"><strong>现金仓位</strong></td>
                  <td><span class="weight-badge">{{ (cashPctOff * 100).toFixed(1) }}%</span></td>
                  <td><strong>¥{{ formatNum(cashOff) }}</strong></td>
                  <td colspan="2">—</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
      </div>

      <!-- Empty State -->
      <div v-if="!allocationOn?.allocations?.length && !allocationOff?.allocations?.length" class="empty-state">
        <div class="empty-icon" aria-hidden="true">📊</div>
        <h3 class="empty-title">暂无组合数据</h3>
        <p class="empty-description">请前往「组合管理」添加 ETF，或点击下方生成智能组合</p>
        <AppButton variant="primary" @click="$router.push('/portfolio')">
          前往组合管理
        </AppButton>
      </div>

      <!-- Daily P&L Details -->
      <section class="card pnl-card" v-if="pnlItems.length">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">📊</span>
            当日盈亏明细
          </h2>
          <p class="card-subtitle" v-if="activeTab !== 'combined'">
            当前视图：{{ activeTab === 'on_exchange' ? '场内' : '场外' }} ETF
          </p>
        </div>

        <div class="table-responsive">
          <table class="data-table">
            <thead>
              <tr>
                <th scope="col">名称</th>
                <th scope="col">类型</th>
                <th scope="col">涨跌幅</th>
                <th scope="col">目标金额</th>
                <th scope="col">当日盈亏</th>
                <th v-if="activeTab === 'off_exchange' || activeTab === 'combined'" scope="col">跟踪指数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in pnlItems" :key="item.symbol">
                <td><strong>{{ item.short_name || item.name }}</strong></td>
                <td><span class="type-badge" :class="item.portfolio_type">{{ item.portfolio_type === 'on_exchange' ? '场内' : '场外' }}</span></td>
                <td :class="getChangeClass(item.change_pct)">{{ formatChange(item.change_pct) }}</td>
                <td>¥{{ formatNum(item.target_amount) }}</td>
                <td :class="getChangeClass(item.daily_pnl)">{{ formatChange(item.daily_pnl, true) }}</td>
                <td v-if="activeTab === 'off_exchange' || activeTab === 'combined'">{{ item.tracked_index || '—' }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="footer-row summary-row">
                <td colspan="2"><strong>合计</strong></td>
                <td :class="pnlWeightedChange >= 0 ? 'text-success' : 'text-danger'">{{ formatChange(pnlWeightedChange) }}</td>
                <td><strong>¥{{ formatNum(pnlTotalAmount) }}</strong></td>
                <td :class="pnlTotal >= 0 ? 'text-success' : 'text-danger'"><strong>¥{{ formatNum(pnlTotal) }}</strong></td>
                <td v-if="activeTab === 'off_exchange' || activeTab === 'combined'"></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <!-- P&L Bar Chart -->
      <section class="card chart-card" v-if="pnlItems.length">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">📈</span>
            当日盈亏分布
          </h2>
        </div>
        <v-chart :option="pnlBarOption" :style="{ height: '350px' }" autoresize />
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { usePortfolioStore } from '../stores/portfolio'
import { portfolioApi, analysisApi, marketApi } from '../api'
import { useToast } from '../stores/toast'
import { useMarketWS } from '../composables/useMarketWS'
import AppButton from './ui/AppButton.vue'
import AppInput from './ui/AppInput.vue'
import Skeleton from './ui/Skeleton.vue'

use([CanvasRenderer, PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

const store = usePortfolioStore()
const route = useRoute()
const { toast } = useToast()

// State
const activeTab = ref('combined')
const capitalOn = ref(500000)
const capitalOff = ref(500000)
const allocationOn = ref({ allocations: [] })
const allocationOff = ref({ allocations: [] })
const pnlOnData = ref({ items: [] })
const pnlOffData = ref({ items: [] })
const strategyResult = ref(null)
const checkingStrategy = ref(false)
const designResult = ref(null)
const designing = ref(false)
const globalIndices = ref({})
const marketLoading = ref(false)
const marketTimer = ref(null)

// Core Feature Panel State
const activeCoreFeature = ref<'design' | 'strategy' | null>(null)
const designStep = ref<'wizard' | 'result'>('wizard')
const designParams = ref({
  riskProfile: 'balanced',
  capital: 500000
})
const applyingPlan = ref<string | null>(null)

// Computed
const hasGlobalIndices = computed(() => Object.values(globalIndices.value).flat().length > 0)
const tabs = [
  { value: 'combined', label: '综合' },
  { value: 'on_exchange', label: '场内' },
  { value: 'off_exchange', label: '场外' }
]

const loading = computed(() => allocationOn.value.allocations.length === 0 && allocationOff.value.allocations.length === 0)

const pnlItems = computed(() => {
  if (activeTab.value === 'on_exchange') return pnlOnData.value.items || []
  if (activeTab.value === 'off_exchange') return pnlOffData.value.items || []
  return [...(pnlOnData.value.items || []), ...(pnlOffData.value.items || [])]
})

const totalAll = computed(() => {
  const on = allocationOn.value.total_amount || 0
  const off = allocationOff.value.total_amount || 0
  return on + off
})

const pnlOn = computed(() => pnlOnData.value.total_pnl || 0)
const pnlOff = computed(() => pnlOffData.value.total_pnl || 0)

const pnlTotal = computed(() => pnlItems.value.reduce((sum, item) => sum + (item.daily_pnl || 0), 0))
const pnlTotalAmount = computed(() => pnlItems.value.reduce((sum, item) => sum + (item.target_amount || 0), 0))
const pnlWeightedChange = computed(() => {
  const total = pnlTotalAmount.value
  if (!total) return 0
  return pnlItems.value.reduce((sum, item) => sum + ((item.daily_pnl || 0) / total) * 100, 0)
})

const cashPctOn = computed(() => {
  const total = capitalOn.value
  const used = allocationOn.value.total_amount || 0
  return total > 0 ? Math.max(0, (total - used) / total) : 0
})

const cashOn = computed(() => capitalOn.value - (allocationOn.value.total_amount || 0))

const cashPctOff = computed(() => {
  const total = capitalOff.value
  const used = allocationOff.value.total_amount || 0
  return total > 0 ? Math.max(0, (total - used) / total) : 0
})

const cashOff = computed(() => capitalOff.value - (allocationOff.value.total_amount || 0))

// Methods
const formatNum = (n) => (n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const formatPrice = (n) => (n || 0).toFixed(2)
const formatChange = (n, isAmount = false) => {
  const val = n || 0
  const prefix = val >= 0 && !isAmount ? '+' : ''
  const suffix = isAmount ? '' : '%'
  return `${prefix}${val.toFixed(2)}${suffix}`
}

const getChangeClass = (val) => val >= 0 ? 'text-success' : 'text-danger'
const getActionLabel = (action) => ({ adjust_weight: '调整权重', replace: '替换', no_change: '不变' }[action] || action )

const fetchGlobalIndices = async () => {
  marketLoading.value = true
  try {
    const res = await marketApi.indicesGlobal()
    globalIndices.value = res.data?.indices || res.indices || {}
  } catch (e) {
    console.error('Failed to fetch global indices:', e)
  } finally {
    marketLoading.value = false
  }
}

const refreshAll = async () => {
  await Promise.all([
    fetchAllocations(),
    fetchPnl()
  ])
}

const fetchAllocations = async () => {
  try {
    const [onRes, offRes] = await Promise.all([
      portfolioApi.getAllocation('on_exchange', capitalOn.value),
      portfolioApi.getAllocation('off_exchange', capitalOff.value)
    ])
    allocationOn.value = onRes.data || { allocations: [] }
    allocationOff.value = offRes.data || { allocations: [] }
  } catch (e) {
    toast('获取分配数据失败', 'error')
  }
}

const fetchPnl = async () => {
  try {
    const [onRes, offRes] = await Promise.all([
      portfolioApi.getPnl('on_exchange', capitalOn.value),
      portfolioApi.getPnl('off_exchange', capitalOff.value)
    ])
    pnlOnData.value = onRes.data || { items: [] }
    pnlOffData.value = offRes.data || { items: [] }
  } catch (e) {
    toast('获取盈亏数据失败', 'error')
  }
}

// Core Feature Panel Methods
const enterDesignMode = () => {
  activeCoreFeature.value = 'design'
  designStep.value = 'wizard'
  designResult.value = null
}

const enterStrategyMode = () => {
  if (!store.etfs.length) return toast('请先添加 ETF', 'warning')
  activeCoreFeature.value = 'strategy'
  checkStrategy()
}

const exitCoreFeature = () => {
  activeCoreFeature.value = null
  designStep.value = 'wizard'
  designResult.value = null
  strategyResult.value = null
}

const generateDesign = async () => {
  designing.value = true
  try {
    const res = await analysisApi.portfolioDesign({
      risk_profile: designParams.value.riskProfile,
      capital: designParams.value.capital
    })
    designResult.value = res.data
    designStep.value = 'result'
    toast('组合方案生成完成', 'success')
  } catch (e) {
    toast('生成失败', 'error')
  } finally {
    designing.value = false
  }
}

const resetDesign = () => {
  designResult.value = null
  designStep.value = 'wizard'
}

const selectPlan = (pf) => {
  // Card click handler - could expand details, but Apply button handles action
}

const checkStrategy = async () => {
  if (!store.etfs.length) return toast('请先添加 ETF', 'warning')
  checkingStrategy.value = true
  try {
    const res = await analysisApi.checkStrategy()
    strategyResult.value = res.data
    toast('策略检查完成')
  } catch (e) {
    toast('策略检查失败', 'error')
  } finally {
    checkingStrategy.value = false
  }
}

const applySuggestions = async () => {
  if (!strategyResult.value?.suggestions?.length) return
  try {
    await portfolioApi.applyStrategy(strategyResult.value.suggestions)
    toast('建议已应用', 'success')
    strategyResult.value = null
    exitCoreFeature()
    await refreshAll()
  } catch (e) {
    toast('应用失败', 'error')
  }
}

// Legacy method - delegates to generateDesign
const fetchPortfolioDesign = () => generateDesign()

const applyPortfolioDesign = async (pf) => {
  try {
    await portfolioApi.applyPortfolioDesign(pf)
    toast('组合已应用', 'success')
    designResult.value = null
    exitCoreFeature()
    await refreshAll()
  } catch (e) {
    toast('应用失败', 'error')
  }
}

// ECharts Options
const pieOptionOn = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { orient: 'vertical', left: 'left', top: 'middle', itemWidth: 12, itemHeight: 12 },
  series: [{
    name: '分配',
    type: 'pie',
    radius: ['40%', '70%'],
    avoidLabelOverlap: false,
    label: { show: false, position: 'center' },
    emphasis: { label: { show: true, fontSize: '18', fontWeight: 'bold' } },
    labelLine: { show: false },
    data: allocationOn.value.allocations?.map(a => ({
      value: a.target_amount,
      name: `${a.symbol} (${(a.target_weight * 100).toFixed(1)}%)`
    })) || []
  }],
  color: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#eab308']
}))

const pieOptionOff = computed(() => ({
  ...pieOptionOn.value,
  series: [{
    ...pieOptionOn.value.series[0],
    data: allocationOff.value.allocations?.map(a => ({
      value: a.target_amount,
      name: `${a.symbol} (${(a.target_weight * 100).toFixed(1)}%)`
    })) || []
  }]
}))

const pnlBarOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  xAxis: { type: 'category', data: pnlItems.value.map(i => i.short_name || i.name), axisLabel: { interval: 0, rotate: 30 } },
  yAxis: { type: 'value', name: '盈亏 (元)' },
  series: [{
    name: '当日盈亏',
    type: 'bar',
    data: pnlItems.value.map(i => i.daily_pnl || 0),
    itemStyle: {
      color: (params) => params.value >= 0 ? '#22c55e' : '#ef4444'
    },
    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
  }]
}))

// WebSocket
const { connect, disconnect, onMarketData } = useMarketWS()

onMounted(async () => {
  await Promise.all([fetchGlobalIndices(), fetchAllocations(), fetchPnl()])
  connect()
  onMarketData((data) => {
    // Update matching global index in real-time (A-share indices pushed via WS)
    for (const region of Object.keys(globalIndices.value)) {
      const list = globalIndices.value[region]
      const i = list.findIndex(m => m.symbol === data.symbol)
      if (i >= 0) {
        list[i] = { ...list[i], price: data.price, change_pct: data.change_pct, available: true }
      }
    }
  })
  marketTimer.value = setInterval(fetchGlobalIndices, 60000)
})

onUnmounted(() => {
  disconnect()
  if (marketTimer.value) clearInterval(marketTimer.value)
})

watch(() => route.path, () => {
  // Refresh on route change
  refreshAll()
})
</script>

<style scoped>
/* ==========================================
   Dashboard Styles
   ========================================== */
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

/* Page Header */
.page-header {
  margin-bottom: var(--space-2);
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  line-height: var(--line-height-tight);
  color: var(--color-text-primary);
  letter-spacing: var(--letter-spacing-tight);
}

.page-description {
  margin-top: var(--space-1);
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}

/* Card */
.card {
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}

.card-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
}

.card-title-icon {
  font-size: var(--font-size-xl);
  line-height: 1;
}

.card-subtitle {
  margin: var(--space-1) 0 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-normal);
}

.card-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.card-meta {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-left: auto;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.meta-label { font-weight: var(--font-weight-medium); }
.meta-value { font-family: var(--font-family-mono); font-weight: var(--font-weight-semibold); }

/* Status Badge */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-success-700);
  background: var(--color-bg-success-subtle);
  border-radius: var(--radius-full);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-success-500);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* Market Overview */
.market-overview { }

.index-regions {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
}
.index-region { }
.region-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-2);
}
.index-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--space-3);
}
.index-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-3);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  transition: var(--transition-fast);
}
.index-card:hover {
  border-color: var(--color-brand-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.index-card.unavailable { opacity: 0.6; }
.index-name {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}
.index-price {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.index-change {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  padding: var(--space-0.5) var(--space-1.5);
  border-radius: var(--radius-full);
  width: fit-content;
}
.index-change.text-success {
  color: var(--color-success-700);
  background: var(--color-success-50);
}
.index-change.text-danger {
  color: var(--color-danger-700);
  background: var(--color-danger-50);
}
.index-change.muted {
  color: var(--color-text-tertiary);
  background: transparent;
  font-weight: var(--font-weight-normal);
}

.change-icon {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

/* Global Indices - Ultra Compact Layout */
.global-indices-compact {
  --card-padding: var(--space-4);
}
.global-indices-compact .card-header-compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}
.global-indices-compact .card-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
}
.global-indices-compact .card-title-icon {
  font-size: var(--font-size-lg);
}
.global-indices-compact .status-badge {
  font-size: 10px;
}

.indices-scroll {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  overflow: visible;
}

.index-card-compact {
  flex-shrink: 0;
  min-width: 140px;
  max-width: 160px;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-2.5);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  transition: var(--transition-fast);
  scroll-snap-align: start;
}
.index-card-compact:hover {
  border-color: var(--color-brand-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.index-card-compact.unavailable {
  opacity: 0.5;
}
.index-card-compact .index-name-compact {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.index-card-compact .index-price-compact {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  line-height: 1.2;
}
.index-card-compact .index-price-compact.muted {
  color: var(--color-text-tertiary);
  font-weight: var(--font-weight-normal);
}
.index-card-compact .index-change-compact {
  align-self: flex-start;
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  padding: var(--space-0.5) var(--space-1);
  border-radius: var(--radius-full);
  white-space: nowrap;
}
.index-card-compact .index-change-compact.text-success {
  color: var(--color-success-700);
  background: var(--color-bg-success-subtle);
}
.index-card-compact .index-change-compact.text-danger {
  color: var(--color-danger-700);
  background: var(--color-bg-danger-subtle);
}
.index-card-compact .index-change-compact.muted {
  color: var(--color-text-tertiary);
  background: transparent;
  font-weight: var(--font-weight-normal);
}

.indices-empty-compact {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6) var(--space-4);
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* Tabs */
.tabs {
  display: flex;
  gap: var(--space-1);
  background: var(--color-surface-tertiary);
  padding: var(--space-1);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border-light);
}

.tab {
  flex: 1;
  padding: var(--space-2) var(--space-4);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md);
  background: transparent;
  transition: var(--transition-fast);
}

.tab:hover {
  color: var(--color-text-primary);
}

.tab--active {
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
}

.tab:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

/* Capital Bar */
.capital-bar {
  padding: var(--space-4) var(--space-5);
}

.capital-inputs {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}

.input-group {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 200px;
}

.input-group.dual {
  flex: none;
}

.input-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.capital-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
}

/* Summary Grid */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
}

.summary-card {
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  transition: var(--transition-fast);
}

.summary-card:hover {
  border-color: var(--color-brand-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.summary-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-2xl);
  border-radius: var(--radius-lg);
  background: var(--color-surface-secondary);
  flex-shrink: 0;
}

.summary-icon.positive { background: var(--color-bg-success-subtle); }
.summary-icon.negative { background: var(--color-bg-danger-subtle); }

.summary-content { flex: 1; min-width: 0; }

.summary-label {
  margin: 0 0 var(--space-1);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.summary-value {
  margin: 0;
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  line-height: var(--line-height-tight);
  white-space: nowrap;
}

.summary-value.skeleton { color: transparent; }

.text-success { color: var(--color-text-success) !important; }
.text-danger { color: var(--color-text-danger) !important; }
.text-warning { color: var(--color-text-warning) !important; }

/* Content Grid */
.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}

@media (max-width: 1024px) {
  .content-grid { grid-template-columns: 1fr; }
}

/* Chart / Table Cards */
.chart-card, .table-card {
  display: flex;
  flex-direction: column;
}

.chart-card .card-header,
.table-card .card-header {
  flex-shrink: 0;
}

.chart-card v-chart,
.table-card .table-responsive {
  flex: 1;
  min-height: 0;
}

/* Table */
.table-responsive {
  overflow-x: auto;
  padding: var(--space-4) var(--space-5);
  -webkit-overflow-scrolling: touch;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.data-table th,
.data-table td {
  padding: var(--space-3) var(--space-4);
  text-align: left;
  vertical-align: middle;
  border-bottom: 1px solid var(--color-border-light);
}

.data-table th {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  background: var(--color-surface-secondary);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}

.data-table tbody tr {
  transition: var(--transition-fast);
}

.data-table tbody tr:hover {
  background: var(--color-surface-hover);
}

.data-table td code {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  background: var(--color-surface-tertiary);
  padding: var(--space-0.5) var(--space-1);
  border-radius: var(--radius-sm);
}

.data-table .weight-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-0.5) var(--space-2);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-brand-700);
  background: var(--color-bg-brand-subtle);
  border-radius: var(--radius-full);
}

.data-table .type-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-0.5) var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-full);
  text-transform: capitalize;
}

.data-table .type-badge.on_exchange {
  color: var(--color-info-700);
  background: var(--color-bg-info-subtle);
}

.data-table .type-badge.off_exchange {
  color: var(--color-warning-700);
  background: var(--color-bg-warning-subtle);
}

.data-table .change-value {
  font-family: var(--font-family-mono);
  font-weight: var(--font-weight-semibold);
}

.data-table .footer-row {
  background: var(--color-surface-secondary);
}

.data-table .footer-row td {
  border-top: 2px solid var(--color-border-medium);
  border-bottom: none;
  font-weight: var(--font-weight-semibold);
}

.data-table .reason-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-secondary);
}

/* Comparison Table */
.comparison-table th:first-child,
.comparison-table td:first-child {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) var(--space-6);
  text-align: center;
  background: var(--color-surface-secondary);
  border: 2px dashed var(--color-border-medium);
  border-radius: var(--radius-xl);
}

.empty-icon { font-size: var(--font-size-5xl); line-height: 1; margin-bottom: var(--space-4); }
.empty-title { margin: 0 0 var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.empty-description { margin: 0 0 var(--space-6); font-size: var(--font-size-base); color: var(--color-text-secondary); max-width: 300px; }
.empty-design { padding: var(--space-6); text-align: center; color: var(--color-text-tertiary); }
.empty-design .empty-icon { font-size: var(--font-size-3xl); margin-bottom: var(--space-3); }

/* Loading Grid */
.loading-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}

@media (max-width: 1024px) {
  .loading-grid { grid-template-columns: 1fr; }
}

.skeleton-card {
  padding: var(--space-5);
}

/* P&L Card */
.pnl-card { }

/* AI Design Card */
.ai-design-card { }

.ai-design-actions {
  padding: var(--space-4) var(--space-5);
  display: flex;
  justify-content: flex-end;
}

.design-result {
  padding: var(--space-5);
  border-top: 1px solid var(--color-border-light);
  animation: fade-in var(--duration-normal) var(--ease-out);
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.market-env {
  padding: var(--space-4);
  margin-bottom: var(--space-5);
  background: var(--color-bg-brand-subtle);
  border: 1px solid var(--color-brand-200);
  border-radius: var(--radius-lg);
}

.env-title {
  margin: 0 0 var(--space-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-brand-800);
}

.env-content {
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  color: var(--color-brand-700);
}

.comparison-section {
  margin-bottom: var(--space-6);
}

.section-title {
  margin: 0 0 var(--space-3);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.portfolio-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: var(--space-5);
}

@media (max-width: 768px) {
  .portfolio-grid { grid-template-columns: 1fr; }
}

.portfolio-card {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border-light);
}

.portfolio-card:hover {
  border-color: var(--color-brand-300);
  box-shadow: var(--shadow-lg);
}

.pf-header {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
}

.pf-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-1) var(--space-3);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  border-radius: var(--radius-full);
  text-transform: capitalize;
}

.pf-badge.conservative { color: var(--color-info-700); background: var(--color-bg-info-subtle); }
.pf-badge.balanced { color: var(--color-success-700); background: var(--color-bg-success-subtle); }
.pf-badge.aggressive { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); }

.pf-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-top: var(--space-3);
}

.pf-meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.pf-meta-item .meta-label { font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); }

.pf-desc {
  padding: var(--space-4) var(--space-5);
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border-light);
}

.pf-guidelines {
  padding: var(--space-3) var(--space-5);
  font-size: var(--font-size-sm);
  color: var(--color-warning-700);
  background: var(--color-bg-warning-subtle);
  border-bottom: 1px solid var(--color-border-light);
}

.guideline-label { font-weight: var(--font-weight-semibold); color: var(--color-warning-800); }

.pf-cash {
  padding: var(--space-3) var(--space-5);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border-light);
}

.cash-label { font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }

.portfolio-card .table-responsive { padding: 0; flex: 1; }
.portfolio-card .data-table th { font-size: var(--font-size-xs); }
.portfolio-card .data-table td { padding: var(--space-2) var(--space-3); font-size: var(--font-size-sm); }

.pf-risk-warn {
  padding: var(--space-3) var(--space-5);
  font-size: var(--font-size-sm);
  color: var(--color-danger-700);
  background: var(--color-bg-danger-subtle);
  border-top: 1px solid var(--color-danger-200);
}

.risk-label { font-weight: var(--font-weight-semibold); color: var(--color-danger-800); }

.pf-actions {
  padding: var(--space-3) var(--space-5);
  display: flex;
  justify-content: flex-end;
}

/* Strategy Card */
.strategy-card { }

.strategy-summary {
  padding: var(--space-4) var(--space-5);
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border-light);
}

.suggestions-list {
  padding: var(--space-4) var(--space-5);
}

.suggestion-item {
  padding: var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
}

.suggestion-item:last-child { margin-bottom: 0; }

.suggestion-main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.action-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-0.5) var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  border-radius: var(--radius-full);
  text-transform: capitalize;
}

.action-badge.adjust_weight { color: var(--color-warning-700); background: var(--color-bg-warning-subtle); }
.action-badge.replace { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); }
.action-badge.no_change { color: var(--color-success-700); background: var(--color-bg-success-subtle); }

.suggestion-main strong { font-size: var(--font-size-sm); color: var(--color-text-primary); }
.suggestion-main code { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }

.weight-change {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-brand-600);
}

.suggestion-reason {
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  color: var(--color-text-secondary);
}

.no-suggestions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-6);
  color: var(--color-success-700);
  font-weight: var(--font-weight-medium);
}

.success-icon { font-size: var(--font-size-lg); }

.strategy-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border-light);
}

/* Animations */
.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Core Feature Panel Styles */
.core-feature-panel {
  animation: slideDown 0.2s ease-out;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
}

.panel-back {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.panel-back:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

.panel-title {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.panel-body {
  padding: var(--space-4) var(--space-5);
}

/* Design Wizard */
.design-wizard .wizard-hint {
  margin: 0 0 var(--space-4);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.wizard-fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.wizard-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.field-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.wizard-select {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  transition: all var(--transition-fast);
}

.wizard-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--shadow-focus);
}

.form-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin-top: var(--space-2);
}

.wizard-generate,
.wizard-submit {
  width: 100%;
  padding: var(--space-3);
}

/* Design Result Panel */
.design-result-panel .market-env {
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-info-subtle);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  font-size: var(--font-size-sm);
}

.design-result-panel .market-env h4 {
  margin: 0 0 var(--space-2);
  color: var(--color-info-800);
  font-size: var(--font-size-sm);
}

.design-result-panel .market-env p {
  margin: 0;
  color: var(--color-text-secondary);
}

.result-hint {
  margin: 0 0 var(--space-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.design-plans-grid,
.portfolio-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.design-plan-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  transition: all var(--transition-fast);
  cursor: pointer;
  background: var(--color-bg-primary);
}

.design-plan-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.plan-style-badge {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  text-transform: capitalize;
}

.plan-style-badge.balanced {
  background: var(--color-bg-primary);
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
}

.plan-style-badge.growth {
  background: var(--color-bg-success-subtle);
  color: var(--color-success-700);
  border: 1px solid var(--color-success-300);
}

.plan-style-badge.conservative {
  background: var(--color-bg-info-subtle);
  color: var(--color-info-700);
  border: 1px solid var(--color-info-300);
}

.plan-score {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
}

.plan-meta {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  font-size: var(--font-size-sm);
}

.plan-meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.meta-label {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-xs);
}

.meta-value {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  font-family: var(--font-family-mono);
}

.plan-allocation-preview {
  margin-bottom: var(--space-3);
}

.alloc-label {
  display: block;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-2);
}

.alloc-bars {
  display: flex;
  gap: 2px;
  height: 8px;
  border-radius: var(--radius-full);
  overflow: hidden;
  background: var(--color-bg-tertiary);
}

.alloc-bar {
  flex: 1;
  min-width: 0;
  transition: width var(--transition-normal);
}

.plan-risk-warn {
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg-warning-subtle);
  border: 1px solid var(--color-warning-200);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-warning-800);
  margin-bottom: var(--space-3);
}

.risk-label {
  font-weight: var(--font-weight-semibold);
}

.plan-action {
  text-align: right;
}

.design-loading,
.design-empty,
.strategy-loading,
.strategy-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
  text-align: center;
  color: var(--color-text-tertiary);
}

.loading-spinner {
  font-size: var(--font-size-2xl);
  animation: spin 1s linear infinite;
  margin-bottom: var(--space-3);
}

.empty-hint {
  font-size: var(--font-size-sm);
}

.empty-icon {
  font-size: var(--font-size-3xl);
  margin-bottom: var(--space-3);
}

.panel-footer-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border-light);
  margin-top: var(--space-4);
}

/* Strategy Panel */
.strategy-result-panel .strategy-summary {
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-info-subtle);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.suggestions-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.suggestion-item {
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-md);
  border-left: 3px solid var(--color-primary);
}

.suggestion-main {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  flex-wrap: wrap;
}

.action-badge {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  text-transform: capitalize;
}

.action-badge.adjust_weight {
  background: var(--color-bg-warning-subtle);
  color: var(--color-warning-800);
}

.action-badge.replace {
  background: var(--color-bg-danger-subtle);
  color: var(--color-danger-800);
}

.action-badge.no_change {
  background: var(--color-bg-success-subtle);
  color: var(--color-success-800);
}

.suggestion-main strong {
  font-size: var(--font-size-sm);
}

.suggestion-main code {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  background: var(--color-bg-secondary);
  padding: 1px 4px;
  border-radius: var(--radius-sm);
}

.weight-change {
  font-size: var(--font-size-xs);
  color: var(--color-primary);
  font-family: var(--font-family-mono);
  font-weight: var(--font-weight-semibold);
}

.suggestion-reason {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.no-suggestions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-6);
  color: var(--color-success-700);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
}

.success-icon {
  font-size: var(--font-size-xl);
}

.strategy-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border-light);
}

.strategy-empty p {
  margin: 0 0 var(--space-4);
  color: var(--color-text-secondary);
}

.empty-note {
  margin-top: var(--space-3) !important;
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

/* Feature Card Enhancements */
.core-action-btn.feature-card {
  position: relative;
  text-align: left;
  padding: var(--space-4);
}

.core-action-btn.feature-card .action-arrow {
  position: absolute;
  right: var(--space-4);
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--font-size-lg);
  color: var(--color-text-tertiary);
  transition: all var(--transition-fast);
}

.core-action-btn.feature-card:hover .action-arrow {
  color: var(--color-primary);
  transform: translateY(-50%) translateX(4px);
}

.core-action-btn.feature-card:disabled .action-arrow {
  opacity: 0.5;
}

.design-wizard {
  animation: slideDown 0.2s ease-out;
}

/* Feature Card Grid */
.core-actions-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-4);
}

@media (max-width: 768px) {
  .core-actions-grid {
    grid-template-columns: 1fr;
  }
  
  .design-plans-grid,
  .portfolio-cards {
    grid-template-columns: 1fr;
  }
  
  .plan-meta {
    flex-direction: column;
    gap: var(--space-2);
  }
  
  .panel-header {
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  
  .panel-footer-actions {
    flex-direction: column;
  }
  
  .panel-footer-actions .btn {
    width: 100%;
  }
}

/* Focus Visible */
*:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}

/* Responsive */
@media (max-width: 768px) {
  .card-header { flex-direction: column; align-items: flex-start; gap: var(--space-3); }
  .card-meta { margin-left: 0; width: 100%; justify-content: space-between; }
  .capital-inputs { flex-direction: column; align-items: stretch; }
  .input-group { width: 100%; }
  .capital-actions { justify-content: stretch; }
  .capital-actions .btn { flex: 1; justify-content: center; }
  .summary-grid { grid-template-columns: 1fr; }
  .market-chips { padding: var(--space-3) var(--space-4); }
  .table-responsive { padding: var(--space-3); }
  .data-table th, .data-table td { padding: var(--space-2) var(--space-3); }
  .pf-header { padding: var(--space-3) var(--space-4); }
  .pf-meta { gap: var(--space-2); }
  .portfolio-card .table-responsive { padding: var(--space-3); }
}

@media (max-width: 480px) {
  .market-chip { min-width: 160px; }
  .chip-name { max-width: 80px; }
  .tabs { padding: var(--space-0.5); }
  .tab { padding: var(--space-1.5) var(--space-2); font-size: var(--font-size-xs); }
}
</style>