<template>
  <div class="market-analysis">
    <!-- Page Header -->
    <header class="page-header">
      <h1 class="page-title">行情分析</h1>
      <p class="page-description">市场宏观研判、板块轮动分析与标的深度解读</p>
    </header>

    <!-- Section 1: Market Overview -->
    <section class="section-card">
      <div class="section-header">
        <h2 class="section-title">
          <span class="section-icon" aria-hidden="true">📊</span>
          市场综合研判
        </h2>
        <p class="section-desc">基于实时行情与宏观数据的 AI 市场环境分析</p>
      </div>

      <div class="card">
        <div class="card-body">
          <div class="action-row">
            <AppButton
              variant="primary"
              @click="generateMarketReport"
              :loading="marketLoading"
              :disabled="marketLoading"
            >
              <span class="btn-icon" aria-hidden="true" v-if="!marketLoading">🤖</span>
              <span class="animate-spin" v-else aria-hidden="true">⏳</span>
              {{ marketLoading ? '分析中...' : '生成市场研判' }}
            </AppButton>
          </div>

          <div v-if="marketLoading" class="loading-state">
            <div class="loading-spinner" aria-hidden="true"></div>
            <p>正在调用 DeepSeek 分析市场环境...</p>
          </div>

          <div v-if="marketError" class="alert alert--error" role="alert">
            <span class="alert-icon" aria-hidden="true">⚠️</span>
            <span>{{ marketError }}</span>
          </div>

          <div v-if="marketReport" class="report-container">
            <div class="report-content" v-html="renderMarkdown(marketReport)"></div>
            <div class="report-disclaimer">
              <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
              <span>本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负</span>
            </div>
          </div>

          <div v-if="!marketReport && !marketLoading && !marketError" class="empty-prompt">
            <span class="prompt-icon" aria-hidden="true">💡</span>
            <p>点击上方按钮生成当前市场环境研判报告</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 1.5: Watchlist / 自选列表 -->
    <section class="section-card">
      <div class="section-header">
        <h2 class="section-title">
          <span class="section-icon" aria-hidden="true">⭐</span>
          自选/关注列表
        </h2>
        <p class="section-desc">快速查看自选标的的实时行情，支持添加/移除/备注</p>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">
            <span class="card-title-icon" aria-hidden="true">📋</span>
            自选标的
          </h3>
          <div class="card-actions">
            <AppButton variant="ghost" size="sm" @click="showAddWatchlist = true">
              <span class="btn-icon" aria-hidden="true">➕</span>
              添加自选
            </AppButton>
          </div>
        </div>

        <div class="card-body">
          <!-- Add Watchlist Modal -->
          <div v-if="showAddWatchlist" class="modal-overlay" @click.self="showAddWatchlist = false">
            <div class="modal-dialog">
              <div class="modal-header">
                <h4>添加自选标的</h4>
                <button class="modal-close" @click="showAddWatchlist = false" aria-label="关闭">×</button>
              </div>
              <div class="modal-body">
                <div class="form-group">
                  <label class="form-label" for="wl-symbol">标的代码</label>
                  <AppInput
                    id="wl-symbol"
                    v-model="watchlistForm.symbol"
                    placeholder="如: 510050, 000001"
                    @keydown.enter="addWatchlist"
                  />
                </div>
                <div class="form-group">
                  <label class="form-label" for="wl-asset-type">资产类型</label>
                  <AppSelect
                    id="wl-asset-type"
                    v-model="watchlistForm.asset_type"
                    :options="watchlistAssetTypes"
                    placeholder="选择类型"
                  />
                </div>
                <div class="form-group">
                  <label class="form-label" for="wl-notes">备注 (可选)</label>
                  <AppInput
                    id="wl-notes"
                    v-model="watchlistForm.notes"
                    placeholder="如: 长期跟踪, 短线关注"
                    type="textarea"
                    :rows="2"
                  />
                </div>
              </div>
              <div class="modal-footer">
                <AppButton variant="ghost" @click="showAddWatchlist = false">取消</AppButton>
                <AppButton variant="primary" @click="addWatchlist" :loading="watchlistAdding">{{ watchlistAdding ? '添加中...' : '添加' }}</AppButton>
              </div>
            </div>
          </div>

          <!-- Watchlist Loading/Empty -->
          <div v-if="watchlistLoading" class="loading-state">
            <div class="loading-spinner" aria-hidden="true"></div>
            <p>加载自选列表中...</p>
          </div>

          <div v-else-if="!watchlist.length" class="empty-state">
            <div class="empty-icon" aria-hidden="true">⭐</div>
            <p class="empty-title">暂无自选标的</p>
            <p class="empty-desc">点击"添加自选"开始关注您感兴趣的标的</p>
            <AppButton variant="primary" @click="showAddWatchlist = true" class="mt-3">
              <span class="btn-icon" aria-hidden="true">➕</span>
              添加第一个自选
            </AppButton>
          </div>

          <!-- Watchlist Table -->
          <div v-else class="watchlist-table-wrapper">
            <table class="data-table watchlist-table" role="grid">
              <thead>
                <tr>
                  <th scope="col">代码</th>
                  <th scope="col">名称</th>
                  <th scope="col">类型</th>
                  <th scope="col">最新价</th>
                  <th scope="col">涨跌幅</th>
                  <th scope="col">成交量</th>
                  <th scope="col">备注</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in watchlist" :key="item.id" class="watchlist-row">
                  <td><code>{{ item.symbol }}</code></td>
                  <td><strong>{{ item.name }}</strong></td>
                  <td><span class="type-badge" :class="item.asset_type.toLowerCase()">{{ item.asset_type }}</span></td>
                  <td v-if="item.realtime" class="price-cell text-mono">
                    ¥{{ item.realtime.price?.toFixed(2) }}
                  </td>
                  <td v-else class="text-muted">—</td>
                  <td v-if="item.realtime" class="change-cell" :class="getChangeClass(item.realtime.change_pct)">
                    <span class="change-value">{{ formatChange(item.realtime.change_pct) }}</span>
                  </td>
                  <td v-else class="text-muted">—</td>
                  <td v-if="item.realtime" class="volume-cell text-mono">
                    {{ formatVolume(item.realtime.volume) }}
                  </td>
                  <td v-else class="text-muted">—</td>
                  <td class="notes-cell">
                    <span v-if="item.notes" class="notes-text">{{ item.notes }}</span>
                    <span v-else class="text-muted">—</span>
                  </td>
                  <td>
                    <div class="action-buttons">
                      <AppButton size="xs" variant="ghost" @click.stop="editWatchlist(item)" title="编辑备注">✏️</AppButton>
                      <AppButton size="xs" variant="danger" @click.stop="removeWatchlist(item.id)" title="移除">🗑️</AppButton>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 1.7: LLM Advice / AI 投资顾问 -->
    <section class="section-card">
      <div class="section-header">
        <h2 class="section-title">
          <span class="section-icon" aria-hidden="true">💬</span>
          AI 投资顾问
        </h2>
        <p class="section-desc">向 AI 提问获取投资建议，结合实时行情与组合上下文</p>
      </div>

      <div class="card">
        <div class="card-body">
          <!-- Advice Input -->
          <div class="advice-input-group">
            <AppInput
              v-model="adviceQuery"
              placeholder="输入您的投资问题，如：当前市场风格偏向成长还是价值？是否该调仓？"
              @keydown.enter="sendAdviceQuery"
              :disabled="adviceLoading"
              class="advice-input"
            />
            <AppButton
              variant="primary"
              @click="sendAdviceQuery"
              :loading="adviceLoading"
              :disabled="adviceLoading || !adviceQuery.trim()"
            >
              <span class="btn-icon" aria-hidden="true" v-if="!adviceLoading">🤖</span>
              <span class="animate-spin" v-else aria-hidden="true">⏳</span>
              {{ adviceLoading ? '思考中...' : '发送提问' }}
            </AppButton>
          </div>

          <!-- Error Display -->
          <div v-if="adviceError" class="alert alert--error" role="alert">
            <span class="alert-icon" aria-hidden="true">⚠️</span>
            <span>{{ adviceError }}</span>
          </div>

          <!-- Advice Response -->
          <div v-if="adviceResponse" class="advice-response">
            <div class="advice-content" v-html="renderMarkdown(adviceResponse)"></div>
          </div>

          <!-- Empty State -->
          <div v-if="!adviceResponse && !adviceLoading && !adviceError" class="empty-prompt">
            <span class="prompt-icon" aria-hidden="true">💡</span>
            <p>输入上方问题，AI 将结合实时行情与您的组合给出建议</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 2: Sector Analysis -->
    <section class="section-card">
      <div class="section-header">
        <h2 class="section-title">
          <span class="section-icon" aria-hidden="true">🏭</span>
          板块/概念分析
        </h2>
        <p class="section-desc">行业板块与热门概念的 AI 深度解读</p>
      </div>

      <div class="card">
        <div class="card-body">
          <!-- Sector Type Radio -->
          <div class="form-group">
            <label class="form-label">板块类型</label>
            <div class="radio-group" role="radiogroup" aria-label="板块类型">
              <label class="radio-item" v-for="type in sectorTypes" :key="type.value">
                <input
                  type="radio"
                  :value="type.value"
                  v-model="sectorType"
                  @change="onSectorTypeChange"
                  :id="`sector-${type.value}`"
                />
                <span class="radio-label">{{ type.label }}</span>
              </label>
            </div>
          </div>

          <!-- Sector Search & Select -->
          <div class="form-group">
            <label class="form-label" for="sector-search">选择板块</label>
            <div class="search-combo" ref="sectorComboRef">
              <AppInput
                id="sector-search"
                v-model="sectorQuery"
                placeholder="搜索板块/概念名称..."
                :disabled="sectorLoadingList || !sectorList.length"
                :clearable="true"
                @focus="onSectorFocus"
                @blur="onSectorBlur"
                @keydown="onSectorKeydown"
              />
              <Transition name="dropdown">
                <ul v-if="sectorDropdownOpen && filteredSectors.length" class="search-dropdown" @mousedown.prevent>
                  <li
                    v-for="(s, i) in filteredSectors"
                    :key="s.sector_code || s.plate_code"
                    :class="{ active: i === sectorActiveIndex }"
                    @click="selectSector(s)"
                    @mouseenter="sectorActiveIndex = i"
                  >
                    <span class="result-name" v-html="highlightSector(s.sector_name || s.plate_name)"></span>
                    <span class="result-code">{{ s.sector_code || s.plate_code }}</span>
                  </li>
                </ul>
              </Transition>
            </div>
            <AppButton
              variant="primary"
              @click="analyzeSector"
              :loading="sectorLoading"
              :disabled="sectorLoading || !selectedSectorCode"
            >
              <span class="btn-icon" aria-hidden="true">🔍</span>
              AI 分析板块
            </AppButton>
          </div>

          <!-- Selected Sector Badge -->
          <div v-if="selectedSectorName" class="selected-badge">
            <span class="badge-text">{{ selectedSectorName }} ({{ selectedSectorCode }})</span>
            <AppButton variant="ghost" size="xs" @click="clearSector" aria-label="清除选择">×</AppButton>
          </div>

          <!-- Loading / Error / Report -->
          <div v-if="sectorLoading" class="loading-state">
            <div class="loading-spinner" aria-hidden="true"></div>
            <p>正在分析板块...</p>
          </div>

          <div v-if="sectorError" class="alert alert--error" role="alert">
            <span class="alert-icon" aria-hidden="true">⚠️</span>
            <span>{{ sectorError }}</span>
          </div>

          <div v-if="sectorReport" class="report-container">
            <div class="report-content" v-html="renderMarkdown(sectorReport)"></div>
            <div class="report-disclaimer">
              <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
              <span>本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 3: Symbol Analysis -->
    <section class="section-card">
      <div class="section-header">
        <h2 class="section-title">
          <span class="section-icon" aria-hidden="true">📈</span>
          个股/ETF 分析
        </h2>
        <p class="section-desc">技术图表、指标叠加与 AI 标的研报</p>
      </div>

      <div class="card analysis-controls">
        <div class="card-body">
          <!-- Search Input -->
          <div class="form-group form-group--search">
            <label class="form-label" for="symbol-search">搜索标的</label>
            <div class="search-combo" ref="searchRef">
              <AppInput
                id="symbol-search"
                v-model="searchQuery"
                placeholder="搜索 ETF 或股票代码/名称..."
                :clearable="true"
                @input="onSearchInput"
                @keydown="onSearchKeydown"
                @focus="onSearchFocus"
                @blur="onSearchBlur"
              />
              <Transition name="dropdown">
                <div v-if="showDropdown && searchResults.length" class="search-dropdown">
                  <div v-if="completionFull" class="search-hint">
                    按 <kbd>Tab</kbd> 补全：{{ completionFull }}
                  </div>
                  <div
                    v-for="(r, i) in searchResults"
                    :key="r.symbol + r.type"
                    :class="{ active: i === activeIndex }"
                    @mousedown.prevent="selectSearchItem(r)"
                    @mouseenter="activeIndex = i"
                  >
                    <span class="result-symbol">{{ r.symbol }}</span>
                    <span class="result-name" v-html="highlight(r.name)"></span>
                    <span class="result-type">{{ r.type }}</span>
                  </div>
                </div>
              </Transition>
            </div>
          </div>

          <!-- Selected Symbol Badge -->
          <div v-if="selectedSearchItem" class="selected-badge">
            <span class="badge-text">{{ selectedSearchItem.name }} ({{ selectedSearchItem.symbol }})</span>
            <AppButton variant="ghost" size="xs" @click="clearSearchItem" aria-label="清除选择">×</AppButton>
          </div>

          <div class="action-row">
            <AppButton
              variant="primary"
              @click="analyzeSymbol"
              :loading="symbolLoading"
              :disabled="symbolLoading || !selectedSearchItem"
            >
              <span class="btn-icon" aria-hidden="true" v-if="!symbolLoading">🧠</span>
              <span class="animate-spin" v-else aria-hidden="true">⏳</span>
              {{ symbolLoading ? '分析中...' : 'AI 标的分析' }}
            </AppButton>
          </div>

          <!-- Chart Controls -->
          <div class="chart-controls">
            <div v-if="selectedSearchItem">
            <div class="form-group form-group--small">
              <label class="form-label" for="fa-period">周期</label>
              <AppSelect
                id="fa-period"
                v-model="faPeriod"
                :options="periodOptions"
                size="sm"
                @change="fetchFAChart"
              />
            </div>

            <div class="form-group form-group--small">
              <label class="form-label">图表类型</label>
              <div class="chart-mode-toggle" role="radiogroup" aria-label="图表类型">
                <button
                  type="button"
                  role="radio"
                  :aria-pressed="faChartMode === 'kline'"
                  :class="['mode-btn', { 'mode-btn--active': faChartMode === 'kline' }]"
                  @click="faChartMode = 'kline'"
                >
                  <span class="mode-icon" aria-hidden="true">📊</span> K 线
                </button>
                <button
                  type="button"
                  role="radio"
                  :aria-pressed="faChartMode === 'intraday'"
                  :class="['mode-btn', { 'mode-btn--active': faChartMode === 'intraday' }]"
                  @click="faChartMode = 'intraday'"
                >
                  <span class="mode-icon" aria-hidden="true">📈</span> 分时
                </button>
              </div>
            </div>

            <div class="form-group form-group--small">
              <AppButton variant="secondary" @click="fetchFAChart" :loading="faLoading">
                <span class="btn-icon" aria-hidden="true" v-if="!faLoading">🔄</span>
                <span class="animate-spin" v-else aria-hidden="true">⏳</span>
                {{ faLoading ? '加载中...' : '刷新' }}
              </AppButton>
            </div>
            </div>
          </div>

          <!-- Indicator Toggles -->
          <div v-if="faChartData" class="indicator-toggles" role="group" aria-label="技术指标叠加">
            <span class="toggles-label">叠加指标:</span>
            <div class="toggles-grid">
              <label class="toggle-item" v-for="ind in faIndicatorToggles" :key="ind.key">
                <input type="checkbox" v-model="ind.model" @change="fetchFAChart" />
                <span class="toggle-name">{{ ind.label }}</span>
              </label>
            </div>
          </div>
        </div>
        </div>

      <!-- Chart -->
      <div class="card chart-card" v-if="faChartData && !faLoading">
        <div class="card-body" style="padding: 0;">
          <v-chart :option="faChartOption" :style="{ height: faChartHeight + 'px' }" autoresize />
        </div>
      </div>

      <div v-if="faLoading" class="card loading-state">
        <div class="loading-spinner" aria-hidden="true"></div>
        <p>正在获取图表数据...</p>
      </div>

    <!-- Indicators Grid -->
      <section class="card indicators-section" v-if="faIndicatorData && !faLoading">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">📋</span>
            最新指标值
          </h2>
        </div>
        <div class="card-body">
          <div class="indicators-grid">
            <div class="indicator-item" v-for="ind in faIndicatorItems" :key="ind.key">
              <span class="indicator-label">{{ ind.label }}</span>
              <span class="indicator-value" :class="ind.class">{{ ind.value }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Signal Card -->
      <section class="card signal-section" v-if="faSignal && !faLoading">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">🎯</span>
            综合信号
          </h2>
        </div>
        <div class="card-body">
          <div class="signal-content">
            <div class="signal-badge" :class="faSignal.signal" role="status" aria-live="polite">
              <span class="signal-icon" aria-hidden="true">{{ faSignalIcon }}</span>
              <span class="signal-text">{{ faSignalText }}</span>
            </div>
            <div class="signal-score">评分: <strong>{{ faSignal.score }}</strong> / 100</div>
            <ul class="signal-reasons" v-if="faSignal.reasons?.length">
              <li v-for="(r, i) in faSignal.reasons" :key="i">{{ r }}</li>
            </ul>
          </div>
        </div>
      </section>

      <!-- AI Symbol Analysis -->
      <section class="card ai-analysis-card">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">🤖</span>
            AI 标的深度分析
          </h2>
        </div>
        <div class="card-body">
          <div v-if="symbolLoading" class="loading-state">
            <div class="loading-spinner" aria-hidden="true"></div>
            <p>正在生成深度分析报告...</p>
          </div>

          <div v-if="symbolError" class="alert alert--error" role="alert">
            <span class="alert-icon" aria-hidden="true">⚠️</span>
            <span>{{ symbolError }}</span>
          </div>

          <div v-if="symbolReport" class="report-container">
            <div class="report-content" v-html="renderMarkdown(symbolReport)"></div>
            <div class="report-disclaimer">
              <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
              <span>本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负</span>
            </div>
          </div>
        </div>
      </section>
    </section>

    <!-- Section 4: Index Analysis -->
    <section class="section-card">
      <div class="section-header">
        <h2 class="section-title">
          <span class="section-icon" aria-hidden="true">📊</span>
          指数分析
        </h2>
        <p class="section-desc">主流宽基、行业、概念指数的技术分析与 AI 研报</p>
      </div>

      <div class="card">
        <div class="card-body">
          <!-- Search Combobox -->
          <div class="form-group form-group--search">
            <label class="form-label" for="index-search">搜索指数</label>
            <div class="search-combo" ref="indexComboRef">
              <input
                type="text"
                class="search-input"
                id="index-search"
                v-model="indexQuery"
                :disabled="indexLoading"
                placeholder="输入代码或名称，如 300、沪深300、行业..."
                @input="onIndexQueryInput"
                @focus="indexDropdownOpen = true"
                @blur="onIndexBlur"
                @keydown="onIndexKeydown"
                autocomplete="off"
                aria-autocomplete="list"
                aria-controls="index-dropdown"
                aria-expanded="indexDropdownOpen"
                aria-haspopup="listbox"
              >
              <Transition name="fade">
                <ul v-if="indexDropdownOpen && filteredIndices.length" class="search-dropdown" id="index-dropdown" role="listbox" @mousedown.prevent>
                  <li
                    v-for="(idx, i) in filteredIndices"
                    :key="idx.symbol"
                    :class="{ active: i === indexActiveIndex }"
                    class="search-item"
                    role="option"
                    :aria-selected="i === indexActiveIndex"
                    @click="selectIndex(idx)"
                    @mouseenter="indexActiveIndex = i"
                  >
                    <span class="si-name" v-html="highlightIndex(idx.name)"></span>
                    <span class="si-code">{{ idx.symbol }}</span>
                    <span class="si-meta">{{ idx.market }} · {{ idx.category }}</span>
                  </li>
                </ul>
              </Transition>
            </div>
          </div>

          <!-- Selected Index Badge -->
          <div v-if="selectedIndexName" class="selected-badge">
            <span class="badge-text">{{ selectedIndexName }} ({{ selectedIndexCode }})</span>
            <AppButton variant="ghost" size="xs" @click="clearIndex" aria-label="清除选择">×</AppButton>
          </div>

          <AppButton
            variant="primary"
            @click="analyzeIndex"
            :loading="indexLoading"
            :disabled="indexLoading || !selectedIndexCode"
          >
            <span class="btn-icon" aria-hidden="true" v-if="!indexLoading">📈</span>
            <span class="animate-spin" v-else aria-hidden="true">⏳</span>
            {{ indexLoading ? '分析中...' : 'AI 分析指数' }}
          </AppButton>
        </div>

        <!-- Loading / Error / Report -->
        <div v-if="indexLoading" class="loading-state">
          <div class="loading-spinner" aria-hidden="true"></div>
          <p>正在获取指数数据并生成 AI 分析...</p>
        </div>

        <div v-if="indexError" class="alert alert--error" role="alert">
          <span class="alert-icon" aria-hidden="true">⚠️</span>
          <span>{{ indexError }}</span>
        </div>

<div v-if="indexReport" class="report-container">
            <div class="report-content" v-html="renderMarkdown(indexReport)"></div>
            <div class="report-disclaimer">
              <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
              <span>本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负</span>
            </div>
          </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import AppButton from './ui/AppButton.vue'
import AppInput from './ui/AppInput.vue'
import AppSelect from './ui/AppSelect.vue'
import { useLLMStream } from '@/composables/useLLMStream'
import { useMarketStore } from '@/stores/market'

use([CanvasRenderer, CandlestickChart, BarChart, LineChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])

// ── Helpers ──
async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

function extractList(resp) {
  if (Array.isArray(resp)) return resp
  if (resp.data && Array.isArray(resp.data)) return resp.data
  if (resp.results && Array.isArray(resp.results)) return resp.results
  return []
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&', '<': '<', '>': '>', '"': '"' }[c]))
}

function highlight(text, query) {
  const q = (query || '').trim()
  if (!q) return escapeHtml(text)
  const idx = text.toLowerCase().indexOf(q.toLowerCase())
  if (idx < 0) return escapeHtml(text)
  return `${escapeHtml(text.slice(0, idx))}<span class="hl">${escapeHtml(text.slice(idx, idx + q.length))}</span>${escapeHtml(text.slice(idx + q.length))}`
}

function renderMarkdown(md) {
  if (!md) return ''
  const lines = String(md).replace(/\r\n/g, '\n').split('\n')
  let html = ''
  let inUl = false, inOl = false
  const closeLists = () => {
    if (inUl) { html += '</ul>'; inUl = false }
    if (inOl) { html += '</ol>'; inOl = false }
  }
  const inline = (t) => escapeHtml(t)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) { closeLists(); continue }
    let m
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
      closeLists()
      const lvl = m[1].length
      const htxt = m[2]
      const riskCls = /风险/.test(htxt) ? ' md-h--risk' : ''
      html += `<h${lvl} class="md-h md-h${lvl}${riskCls}">${inline(htxt)}</h${lvl}>`
    } else if ((m = line.match(/^[-*]\s+(.*)$/))) {
      if (!inUl) { closeLists(); html += '<ul class="md-ul">'; inUl = true }
      html += `<li>${inline(m[1])}</li>`
    } else if ((m = line.match(/^\d+\.\s+(.*)$/))) {
      if (!inOl) { closeLists(); html += '<ol class="md-ol">'; inOl = true }
      html += `<li>${inline(m[1])}</li>`
    } else if (/^---+$/.test(line.trim())) {
      closeLists()
      html += '<hr class="md-hr">'
    } else {
      closeLists()
      html += `<p class="md-p">${inline(line)}</p>`
    }
  }
  closeLists()
  return html
}

// ── Section 1: Market Report ──
const marketReport = ref('')
const marketLoading = ref(false)
const marketError = ref('')

// Streaming hook for LLM
const { streaming: marketStreaming, fullText: marketStreamText, error: marketStreamError, disclaimer: marketStreamDisclaimer, start: startMarketStream, stop: stopMarketStream } = useLLMStream()

// Watchlist state
const watchlist = ref([])
const watchlistLoading = ref(false)
const showAddWatchlist = ref(false)
const watchlistForm = ref({
  symbol: '',
  asset_type: 'A',
  notes: '',
})
const watchlistAdding = ref(false)
const watchlistAssetTypes = [
  { value: 'A', label: 'A股 ETF/股票' },
  { value: 'HK', label: '港股 ETF/股票' },
  { value: 'US', label: '美股 ETF/股票' },
  { value: 'index', label: '指数' },
]

// LLM Advice state
const adviceQuery = ref('')
const adviceResponse = ref('')
const adviceLoading = ref(false)
const adviceError = ref('')

// LLM Advice action
async function sendAdviceQuery() {
  const query = adviceQuery.value.trim()
  if (!query || adviceLoading.value) return
  adviceLoading.value = true
  adviceResponse.value = ''
  adviceError.value = ''
  try {
    // Prepare context with market data
    const context = {
      include_market_data: true,
      include_news: true,
      portfolio_symbols: [],
    }
    const res = await analysisApi.llmAdvice(query, context)
    adviceResponse.value = res.data.advice || res.data
  } catch (e) {
    adviceError.value = '提问失败：' + (e?.message || '网络错误')
  } finally {
    adviceLoading.value = false
  }
}

async function fetchWatchlist() {
  watchlistLoading.value = true
  try {
    const { watchlist: storeWatchlist, fetchWatchlist } = useMarketStore()
    await storeWatchlist()
    watchlist.value = storeWatchlist.value
  } catch (e) {
    console.error('Failed to fetch watchlist:', e)
  } finally {
    watchlistLoading.value = false
  }
}

async function addWatchlist() {
  if (!watchlistForm.value.symbol || watchlistAdding.value) return
  watchlistAdding.value = true
  try {
    const { addWatchlist } = useMarketStore()
    await addWatchlist(watchlistForm.value.symbol, watchlistForm.value.asset_type, watchlistForm.value.notes)
    showAddWatchlist.value = false
    watchlistForm.value = { symbol: '', asset_type: 'A', notes: '' }
    await fetchWatchlist()
  } catch (e) {
    console.error('Add watchlist failed:', e)
  } finally {
    watchlistAdding.value = false
  }
}

async function removeWatchlist(id) {
  if (!confirm('确定要移除该自选吗？')) return
  try {
    const { removeWatchlist } = useMarketStore()
    await removeWatchlist(id)
    await fetchWatchlist()
  } catch (e) {
    console.error('Remove watchlist failed:', e)
  }
}

async function editWatchlist(item) {
  // For now, just show a prompt to edit notes
  const newNotes = prompt('编辑备注:', item.notes || '')
  if (newNotes !== null && newNotes !== item.notes) {
    const { updateWatchlist } = useMarketStore()
    updateWatchlist(item.id, { notes: newNotes })
    await fetchWatchlist()
  }
}

async function generateMarketReport() {
  marketLoading.value = true
  marketReport.value = ''
  marketError.value = ''
  try {
    const result = await startMarketStream('/llm-report/stream', { symbols: null }, (token) => {
      marketReport.value += token
    })
    if (result?.disclaimer) {
      marketStreamDisclaimer.value = result.disclaimer
    }
  } catch (e) {
    marketError.value = '生成失败：' + (e?.message || '网络错误')
  } finally {
    marketLoading.value = false
  }
}

// ── Section 2: Sector Analysis ──
const sectorTypes = [
  { value: 'industry', label: '行业板块' },
  { value: 'concept', label: '概念板块' }
]
const sectorType = ref('industry')
const sectorList = ref([])
const selectedSectorCode = ref('')
const selectedSectorName = ref('')
const sectorLoadingList = ref(false)
const sectorReport = ref('')
const sectorLoading = ref(false)
const sectorError = ref('')
const sectorQuery = ref('')
const sectorDropdownOpen = ref(false)
const sectorActiveIndex = ref(-1)
const sectorComboRef = ref(null)

async function onSectorTypeChange() {
  sectorLoadingList.value = true
  sectorList.value = []
  selectedSectorCode.value = ''
  selectedSectorName.value = ''
  sectorQuery.value = ''
  sectorDropdownOpen.value = false
  sectorActiveIndex.value = -1
  sectorReport.value = ''
  try {
    const url = sectorType.value === 'industry'
      ? '/api/v1/market/sectors/industry?limit=200'
      : '/api/v1/market/sectors/concept?limit=200'
    const data = await fetchJson(url)
    sectorList.value = Array.isArray(data) ? data : []
  } catch {
    sectorList.value = []
  }
  sectorLoadingList.value = false
}

function onSectorFocus() {
  if (sectorList.value.length) {
    sectorDropdownOpen.value = true
  }
}

function onSectorBlur() {
  setTimeout(() => { sectorDropdownOpen.value = false }, 200)
}

function selectSector(s) {
  const code = s.sector_code || s.plate_code
  selectedSectorCode.value = code
  selectedSectorName.value = s.sector_name || s.plate_name || ''
  sectorQuery.value = selectedSectorName.value
  sectorDropdownOpen.value = false
  sectorActiveIndex.value = -1
}

function clearSector() {
  selectedSectorCode.value = ''
  selectedSectorName.value = ''
  sectorQuery.value = ''
  sectorDropdownOpen.value = false
  sectorActiveIndex.value = -1
}

const filteredSectors = computed(() => {
  const q = sectorQuery.value.trim().toLowerCase()
  if (!q) return sectorList.value
  return sectorList.value
    .filter(s => (s.sector_name || s.plate_name || '').toLowerCase().includes(q))
    .slice(0, 50)
})

function highlightSector(name) {
  return highlight(name, sectorQuery.value)
}

function onSectorKeydown(e) {
  const list = filteredSectors.value
  if (!sectorDropdownOpen.value || !list.length) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    sectorActiveIndex.value = (sectorActiveIndex.value + 1) % list.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    sectorActiveIndex.value = (sectorActiveIndex.value - 1 + list.length) % list.length
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = list[sectorActiveIndex.value] || list[0]
    if (item) selectSector(item)
  } else if (e.key === 'Escape') {
    sectorDropdownOpen.value = false
    sectorActiveIndex.value = -1
  }
}

const { streaming: sectorStreaming, fullText: sectorStreamText, error: sectorStreamError, disclaimer: sectorStreamDisclaimer, start: startSectorStream } = useLLMStream()

async function analyzeSector() {
  if (!selectedSectorCode.value) return
  sectorLoading.value = true
  sectorReport.value = ''
  sectorError.value = ''
  sectorStreamDisclaimer.value = ''
  try {
    const result = await startSectorStream('/sector-analysis/stream', {
      sector_code: selectedSectorCode.value,
      sector_type: sectorType.value,
      sector_name: selectedSectorName.value,
    }, (token) => {
      sectorReport.value += token
    })
    if (result?.disclaimer) {
      sectorStreamDisclaimer.value = result.disclaimer
    }
  } catch (e) {
    sectorError.value = '分析失败：' + (e?.message || '网络错误')
  } finally {
    sectorLoading.value = false
  }
}

// ── Section 3: Symbol Analysis ──
const searchQuery = ref('')
const searchResults = ref([])
const showDropdown = ref(false)
const activeIndex = ref(-1)
const completionFull = ref('')
const selectedSearchItem = ref(null)
const searchRef = ref(null)
let searchTimer = null

const faPeriod = ref('daily')
const faChartMode = ref('kline')
const faChartData = ref(null)
const faIndicatorData = ref(null)
const faSignal = ref(null)
const faLoading = ref(false)

const faShowMA5 = ref(true)
const faShowMA10 = ref(true)
const faShowMA20 = ref(true)
const faShowMA60 = ref(false)
const faShowBoll = ref(false)
const faShowMACD = ref(true)

const faChartHeight = computed(() => Math.max(480, window.innerHeight - 500))

const faSignalText = computed(() => ({ buy: '买入', sell: '卖出', hold: '持有' })[faSignal.value?.signal] || '')
const faSignalIcon = computed(() => ({ buy: '⬆️', sell: '⬇️', hold: '➡️' })[faSignal.value?.signal] || '')

const symbolReport = ref('')
const symbolLoading = ref(false)
const symbolError = ref('')

const periodOptions = [
  { value: '15m', label: '15分钟' },
  { value: '30m', label: '30分钟' },
  { value: '1h', label: '1小时' },
  { value: '4h', label: '4小时' },
  { value: 'daily', label: '日线' },
  { value: 'weekly', label: '周线' },
  { value: 'monthly', label: '月线' }
]

const faIndicatorToggles = [
  { key: 'ma5', label: 'MA5', model: faShowMA5 },
  { key: 'ma10', label: 'MA10', model: faShowMA10 },
  { key: 'ma20', label: 'MA20', model: faShowMA20 },
  { key: 'ma60', label: 'MA60', model: faShowMA60 },
  { key: 'boll', label: '布林带', model: faShowBoll },
  { key: 'macd', label: 'MACD', model: faShowMACD }
]

const faIndicatorItems = computed(() => {
  if (!faIndicatorData.value) return []
  const d = faIndicatorData.value
  return [
    { key: 'ma5', label: 'MA5', value: d.ma5?.toFixed(2) ?? '--', class: '' },
    { key: 'ma10', label: 'MA10', value: d.ma10?.toFixed(2) ?? '--', class: '' },
    { key: 'ma20', label: 'MA20', value: d.ma20?.toFixed(2) ?? '--', class: '' },
    { key: 'ma60', label: 'MA60', value: d.ma60?.toFixed(2) ?? '--', class: '' },
    { key: 'rsi', label: 'RSI(14)', value: d.rsi?.toFixed(2) ?? '--', class: getRSIClass(d.rsi) },
    { key: 'macd', label: 'MACD', value: d.macd?.macd?.toFixed(4) ?? '--', class: getMACDClass(d.macd?.macd) },
    { key: 'kdj', label: 'KDJ-K', value: d.kdj?.k?.toFixed(2) ?? '--', class: '' },
    { key: 'boll-upper', label: 'BOLL上轨', value: d.bollinger?.upper?.toFixed(2) ?? '--', class: '' },
    { key: 'boll-lower', label: 'BOLL下轨', value: d.bollinger?.lower?.toFixed(2) ?? '--', class: '' }
  ]
})

function getRSIClass(rsi) {
  if (rsi == null) return ''
  if (rsi >= 70) return 'text-danger'
  if (rsi <= 30) return 'text-success'
  return ''
}

function getMACDClass(macd) {
  if (macd == null) return ''
  return macd >= 0 ? 'text-success' : 'text-danger'
}

function onSearchInput() {
  clearTimeout(searchTimer)
  activeIndex.value = -1
  completionFull.value = ''
  if (!searchQuery.value || searchQuery.value.length < 1) {
    searchResults.value = []
    showDropdown.value = false
    return
  }
  searchTimer = setTimeout(doSearch, 300)
}

function onSearchFocus() {
  if (searchResults.value.length) showDropdown.value = true
}

function onSearchBlur() {
  setTimeout(() => { showDropdown.value = false }, 200)
}

function updateCompletion() {
  const top = searchResults.value[0]
  completionFull.value = top ? `${top.name} (${top.symbol})` : ''
}

function acceptCompletion() {
  const top = searchResults.value[0]
  if (!top) return
  searchQuery.value = `${top.name} (${top.symbol})`
  activeIndex.value = 0
  completionFull.value = ''
  showDropdown.value = true
}

function onSearchKeydown(e) {
  const list = searchResults.value
  if (e.key === 'Tab' && completionFull.value) {
    e.preventDefault()
    acceptCompletion()
    return
  }
  if (!showDropdown.value || !list.length) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % list.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value - 1 + list.length) % list.length
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = list[activeIndex.value] || list[0]
    if (item) selectSearchItem(item)
  } else if (e.key === 'Escape') {
    showDropdown.value = false
    activeIndex.value = -1
  }
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  try {
    const [etfRes, stockRes] = await Promise.all([
      fetchJson(`/api/v1/market/search?keyword=${encodeURIComponent(q)}`),
      fetchJson(`/api/v1/market/search/stocks?keyword=${encodeURIComponent(q)}`)
    ])
    const etfs = extractList(etfRes).map(r => ({ symbol: r.symbol, name: r.name, type: 'ETF' }))
    const stocks = extractList(stockRes).map(r => ({ symbol: r.symbol, name: r.name, type: '股票' }))
    searchResults.value = [...etfs, ...stocks].slice(0, 20)
    activeIndex.value = -1
    updateCompletion()
    showDropdown.value = searchResults.value.length > 0
  } catch {
    searchResults.value = []
    completionFull.value = ''
  }
}

function selectSearchItem(item) {
  selectedSearchItem.value = item
  showDropdown.value = false
  activeIndex.value = -1
  completionFull.value = ''
  searchQuery.value = `${item.name} (${item.symbol})`
  fetchFAChart()
}

function clearSearchItem() {
  selectedSearchItem.value = null
  searchQuery.value = ''
  faChartData.value = null
  faIndicatorData.value = null
  faSignal.value = null
}

async function fetchFAChart() {
  if (!selectedSearchItem.value) return
  faLoading.value = true
  try {
    const sym = selectedSearchItem.value.symbol
    const at = selectedSearchItem.value?.type === 'index' ? 'index' : 'A'
    const [chartRes, indRes, sigRes] = await Promise.all([
      fetchJson(`/api/v1/market/chart/${sym}?asset_type=${at}&period=${faPeriod.value}`),
      fetchJson(`/api/v1/market/indicators/${sym}?asset_type=${at}`),
      fetchJson(`/api/v1/market/signal/${sym}?asset_type=${at}`)
    ])
    faChartData.value = chartRes.data || chartRes
    faIndicatorData.value = indRes.data || indRes
    faSignal.value = sigRes.data || sigRes
  } catch {
    faChartData.value = null
    faIndicatorData.value = null
    faSignal.value = null
  }
  faLoading.value = false
}

const { streaming: symbolStreaming, fullText: symbolStreamText, start: startSymbolStream, disclaimer: symbolStreamDisclaimer } = useLLMStream()

async function analyzeSymbol() {
  if (!selectedSearchItem.value) return
  symbolLoading.value = true
  symbolReport.value = ''
  symbolError.value = ''
  symbolStreamDisclaimer.value = ''
  try {
    const result = await startSymbolStream('/symbol-analysis/stream', {
      symbol: selectedSearchItem.value.symbol,
      name: selectedSearchItem.value.name,
      asset_type: 'A',
    }, (token) => {
      symbolReport.value += token
    })
    if (result?.disclaimer) {
      symbolStreamDisclaimer.value = result.disclaimer
    }
  } catch (e) {
    symbolError.value = '分析失败：' + (e?.message || '网络错误')
  } finally {
    symbolLoading.value = false
  }
}

// ── Chart Option ──
function formatDate(d) {
  if (!d) return ''
  const s = String(d)
  if (s.length === 8) return s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8)
  return s
}

const faChartOption = computed(() => {
  const d = faChartData.value
  if (!d || !d.dates || !d.dates.length) return {}

  const dates = d.dates.map(formatDate)

  // Intraday
  if (faChartMode.value === 'intraday') {
    const closePrices = d.closes
    const volumes = d.volumes
    const volumeColors = d.closes.map((c, i) => (i === 0 ? '#22c55e' : c >= d.closes[i - 1] ? '#22c55e' : '#ef4444'))
    const basePrice = d.closes[0]

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params) => {
          const p = params[0]
          if (!p) return ''
          const idx = p.dataIndex
          const date = dates[idx] || ''
          const close = d.closes[idx]
          const change = ((close - basePrice) / basePrice * 100).toFixed(2)
          const vol = d.volumes[idx]
          return `<b>${date}</b><br/>收盘: ${close.toFixed(3)}<br/>涨跌幅: ${change >= 0 ? '+' : ''}${change}%<br/>成交量: ${vol || 0}`
        }
      },
      grid: [
        { left: '6%', right: '3%', top: 8, height: '60%' },
        { left: '6%', right: '3%', top: '72%', height: '18%' },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: true, rotate: 30, fontSize: 10 } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { gridIndex: 0, scale: true, splitNumber: 5, axisLabel: { fontSize: 11 } },
        { gridIndex: 1, scale: true, splitNumber: 3, axisLabel: { fontSize: 10 } }
      ],
      series: [
        {
          type: 'line', data: closePrices, xAxisIndex: 0, yAxisIndex: 0,
          name: selectedSearchItem.value?.symbol || '',
          smooth: true, symbol: 'none',
          lineStyle: { width: 2, color: '#ef4444' },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(239,68,68,0.3)' },
                { offset: 1, color: 'rgba(239,68,68,0.02)' },
              ],
            },
          },
          markLine: {
            silent: true,
            data: [{ yAxis: basePrice, label: { formatter: `开: ${basePrice.toFixed(3)}`, fontSize: 11 } }],
            lineStyle: { color: '#888', type: 'dashed', width: 1 },
          },
        },
        {
          type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1,
          name: '成交量', itemStyle: { color: (p) => volumeColors[p.dataIndex] },
        },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 }],
    }
  }

  // K-line
  const candlesticks = d.opens.map((_, i) => [d.opens[i], d.closes[i], d.lows[i], d.highs[i]])
  const volumes = d.volumes
  const volumeColors = d.closes.map((c, i) => (i === 0 ? '#22c55e' : c >= d.closes[i - 1] ? '#22c55e' : '#ef4444'))

  const gridHeights = { main: 50, volume: 22, macd: 20 }
  let mainPct = gridHeights.main
  let volPct = faShowMACD.value ? gridHeights.volume : 0
  let macdPct = faShowMACD.value ? gridHeights.macd : 0
  const totalPct = mainPct + volPct + macdPct + 10

  const grids = [
    { left: '6%', right: '3%', top: 8, height: `${mainPct / totalPct * 100}%` },
  ]
  const xAxes = [{ type: 'category', data: dates, gridIndex: 0, axisLabel: { show: true, rotate: 30, fontSize: 10 } }]
  const yAxes = [{ gridIndex: 0, scale: true, splitNumber: 4 }]
  const series = []

  series.push({
    type: 'candlestick', name: selectedSearchItem.value?.symbol || '', data: candlesticks,
    xAxisIndex: 0, yAxisIndex: 0,
    itemStyle: { color: '#22c55e', color0: '#ef4444', borderColor: '#22c55e', borderColor0: '#ef4444' },
  })

  const maConfig = [
    { key: 'ma5', show: faShowMA5.value, color: '#f59e0b', name: 'MA5' },
    { key: 'ma10', show: faShowMA10.value, color: '#3b82f6', name: 'MA10' },
    { key: 'ma20', show: faShowMA20.value, color: '#a855f7', name: 'MA20' },
    { key: 'ma60', show: faShowMA60.value, color: '#22c55e', name: 'MA60' },
  ]
  for (const cfg of maConfig) {
    if (!cfg.show) continue
    const arr = d[cfg.key] || []
    if (!arr.length) continue
    series.push({
      type: 'line', data: arr, smooth: true,
      xAxisIndex: 0, yAxisIndex: 0,
      name: cfg.name, symbol: 'none', lineStyle: { width: 1.2, color: cfg.color },
    })
  }

  if (faShowBoll.value && d.bollinger) {
    const boll = d.bollinger
    series.push({ type: 'line', data: boll.upper, smooth: true, xAxisIndex: 0, yAxisIndex: 0, name: 'BOLL上轨', symbol: 'none', lineStyle: { width: 1, color: '#94a3b8' } })
    series.push({ type: 'line', data: boll.middle, smooth: true, xAxisIndex: 0, yAxisIndex: 0, name: 'BOLL中轨', symbol: 'none', lineStyle: { width: 1.2, color: '#1e293b' } })
    series.push({ type: 'line', data: boll.lower, smooth: true, xAxisIndex: 0, yAxisIndex: 0, name: 'BOLL下轨', symbol: 'none', lineStyle: { width: 1, color: '#94a3b8' } })
  }

  if (faShowMACD.value) {
    volPct = gridHeights.volume
    const volOffset = mainPct
    grids.push({ left: '6%', right: '3%', top: `${volOffset / totalPct * 100}%`, height: `${volPct / totalPct * 100}%` })
    xAxes.push({ type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } })
    yAxes.push({ gridIndex: 1, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 } })
    series.push({ type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1, name: '成交量', itemStyle: { color: (p) => volumeColors[p.dataIndex] } })
  }

  if (faShowMACD.value && d.macd) {
    macdPct = gridHeights.macd
    const macdOffset = mainPct + volPct + 2
    grids.push({ left: '6%', right: '3%', top: `${macdOffset / totalPct * 100}%`, height: `${macdPct / totalPct * 100}%` })
    xAxes.push({ type: 'category', data: dates, gridIndex: 2, axisLabel: { rotate: 30, fontSize: 10 } })
    yAxes.push({ gridIndex: 2, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 } })
    const histColors = d.macd.histogram.map(v => (v || 0) >= 0 ? '#22c55e' : '#ef4444')
    series.push({ type: 'bar', data: d.macd.histogram, xAxisIndex: 2, yAxisIndex: 2, name: 'MACD', itemStyle: { color: (p) => histColors[p.dataIndex] } })
    series.push({ type: 'line', data: d.macd.dif, smooth: true, xAxisIndex: 2, yAxisIndex: 2, name: 'DIF', symbol: 'none', lineStyle: { width: 1.2, color: '#3b82f6' } })
    series.push({ type: 'line', data: d.macd.dea, smooth: true, xAxisIndex: 2, yAxisIndex: 2, name: 'DEA', symbol: 'none', lineStyle: { width: 1.2, color: '#f59e0b' } })
  }

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { show: true, top: 0, left: 'center', icon: 'roundRect', itemWidth: 12, itemHeight: 8 },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      { type: 'inside', xAxisIndex: xAxes.map((_, i) => i), start: 60, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true },
      { type: 'slider', xAxisIndex: xAxes.map((_, i) => i), bottom: 4, height: 18, start: 60, end: 100 },
    ],
    series,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
  }
})

// ── Section 4: Index Analysis ──
const indexQuery = ref('')
const indexDropdownOpen = ref(false)
const indexActiveIndex = ref(-1)
const indexComboRef = ref(null)
const indexList = ref([])
const filteredIndices = ref([])
const selectedIndexCode = ref('')
const selectedIndexName = ref('')
const indexLoading = ref(false)
const indexReport = ref('')
const indexError = ref('')
const indexLoadingList = ref(false)

async function loadIndexMeta() {
  indexLoadingList.value = true
  try {
    const res = await fetchJson('/api/v1/market/indices/meta')
    indexList.value = extractList(res)
    filteredIndices.value = indexList.value
  } catch {
    indexList.value = []
    filteredIndices.value = []
  } finally {
    indexLoadingList.value = false
  }
}

function onIndexQueryInput() {
  clearTimeout(searchTimer)
  const q = indexQuery.value.trim().toLowerCase()
  if (!q) {
    filteredIndices.value = indexList.value
    indexDropdownOpen.value = true
    indexActiveIndex.value = -1
    return
  }
  filteredIndices.value = indexList.value
    .filter(i => i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q))
    .slice(0, 50)
  indexDropdownOpen.value = filteredIndices.value.length > 0
  indexActiveIndex.value = -1
}

function onIndexBlur() {
  setTimeout(() => { indexDropdownOpen.value = false }, 200)
}

function selectIndex(idx) {
  selectedIndexCode.value = idx.symbol
  selectedIndexName.value = idx.name
  indexQuery.value = selectedIndexName.value
  indexDropdownOpen.value = false
  indexActiveIndex.value = -1
}

function clearIndex() {
  selectedIndexCode.value = ''
  selectedIndexName.value = ''
  indexQuery.value = ''
  indexDropdownOpen.value = false
  indexActiveIndex.value = -1
}

function highlightIndex(text) {
  return highlight(text, indexQuery.value)
}

function onIndexKeydown(e) {
  const list = filteredIndices.value
  if (!indexDropdownOpen.value || !list.length) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    indexActiveIndex.value = (indexActiveIndex.value + 1) % list.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    indexActiveIndex.value = (indexActiveIndex.value - 1 + list.length) % list.length
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = list[indexActiveIndex.value] || list[0]
    if (item) selectIndex(item)
  } else if (e.key === 'Escape') {
    indexDropdownOpen.value = false
    indexActiveIndex.value = -1
  }
}

const { streaming: indexStreaming, fullText: indexStreamText, start: startIndexStream } = useLLMStream()

async function analyzeIndex() {
  if (!selectedIndexCode.value) return
  indexLoading.value = true
  indexReport.value = ''
  indexError.value = ''
  try {
    await startIndexStream('/symbol-analysis/stream', {
      symbol: selectedIndexCode.value,
      name: selectedIndexName.value,
      asset_type: 'index',
    }, (token) => {
      indexReport.value += token
    })
  } catch (e) {
    indexError.value = '分析失败：' + (e?.message || '网络错误')
  } finally {
    indexLoading.value = false
  }
}

// Load index meta on mount
onMounted(() => {
  onSectorTypeChange()
  loadIndexMeta()
  // Fetch watchlist
  const marketStore = useMarketStore()
  marketStore.fetchWatchlist()
})

</script>

<style scoped>
/* ==========================================
   Market Analysis Styles
   ========================================== */
.market-analysis {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}

/* Page Header */
.page-header { margin-bottom: var(--space-2); }
.page-title { font-size: var(--font-size-2xl); font-weight: var(--font-weight-bold); line-height: var(--line-height-tight); color: var(--color-text-primary); letter-spacing: var(--letter-spacing-tight); }
.page-description { margin-top: var(--space-1); font-size: var(--font-size-base); color: var(--color-text-secondary); line-height: var(--line-height-relaxed); }

/* Section Card */
.section-card { }
.section-header { margin-bottom: var(--space-4); }
.section-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--space-1);
}
.section-icon { font-size: var(--font-size-2xl); line-height: 1; }
.section-desc { margin: 0; font-size: var(--font-size-sm); color: var(--color-text-secondary); }

/* Card */
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: visible; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); flex-wrap: wrap; }
.card-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.card-title-icon { font-size: var(--font-size-xl); line-height: 1; }
.card-body { padding: var(--space-5); }

/* Form Groups */
.form-group { display: flex; flex-direction: column; gap: var(--space-1.5); }
.form-group--search { flex: 1; min-width: 280px; }
.form-group--small { flex: 0 0 auto; }
.form-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }

/* Radio Group */
.radio-group { display: inline-flex; gap: var(--space-4); }
.radio-item { display: inline-flex; align-items: center; gap: var(--space-1.5); font-size: var(--font-size-sm); color: var(--color-text-secondary); cursor: pointer; }
.radio-item input { width: 16px; height: 16px; accent-color: var(--color-brand-600); }
.radio-label { font-weight: var(--font-weight-medium); }

/* Search Combo */
.search-combo { position: relative; width: 100%; }
.search-combo .input-wrapper { width: 100%; }

/* Dropdown */
.dropdown-enter-active, .dropdown-leave-active { transition: all var(--duration-fast) var(--ease-out); }
.dropdown-enter-from, .dropdown-leave-to { opacity: 0; transform: translateY(-8px); }

.search-dropdown { position: absolute; top: calc(100% + var(--space-1)); left: 0; right: auto; min-width: 340px; max-width: min(480px, 92vw); max-height: 420px; overflow-y: auto; background: var(--color-surface-primary); border: 1px solid var(--color-border-medium); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); z-index: var(--z-index-dropdown); list-style: none; padding: var(--space-1); }
.search-dropdown > div { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-fast); }
.search-dropdown > div:hover, .search-dropdown > div.active { background: var(--color-surface-hover); }
.search-dropdown li { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-fast); }
.search-dropdown li:hover, .search-dropdown li.active { background: var(--color-surface-hover); }
.search-dropdown .si-name { flex: 1; font-size: var(--font-size-sm); color: var(--color-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.search-dropdown .si-code { font-family: var(--font-family-mono); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); color: var(--color-brand-600); flex-shrink: 0; }
.search-dropdown .si-meta { font-size: var(--font-size-xs); color: var(--color-text-tertiary); flex-shrink: 0; }
.si-name { flex: 1; font-size: var(--font-size-sm); color: var(--color-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.si-code { font-family: var(--font-family-mono); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); color: var(--color-brand-600); min-width: 70px; }
.si-meta { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); padding: var(--space-0.5) var(--space-1.5); border-radius: var(--radius-full); background: var(--color-surface-tertiary); color: var(--color-text-tertiary); white-space: nowrap; }
  .result-symbol { font-family: var(--font-family-mono); font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--color-brand-600); min-width: 80px; }
  .result-name { flex: 1; font-size: var(--font-size-sm); color: var(--color-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .result-code, .result-type { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); padding: var(--space-0.5) var(--space-1.5); border-radius: var(--radius-full); background: var(--color-surface-tertiary); color: var(--color-text-tertiary); }

.search-hint { padding: var(--space-1.5) var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); background: var(--color-surface-tertiary); border-bottom: 1px solid var(--color-border-light); border-radius: var(--radius-md) var(--radius-md) 0 0; margin: calc(var(--space-1) * -1) calc(var(--space-1) * -1) var(--space-1); }
.search-hint kbd { display: inline-block; padding: var(--space-0.5) var(--space-1); font-size: 10px; font-family: var(--font-family-mono); background: var(--color-surface-primary); border: 1px solid var(--color-border-medium); border-radius: var(--radius-xs); box-shadow: var(--shadow-xs); }

/* Selected Badge */
.selected-badge { display: inline-flex; align-items: center; gap: var(--space-2); padding: var(--space-1.5) var(--space-3); font-size: var(--font-size-sm); color: var(--color-brand-700); background: var(--color-bg-brand-subtle); border-radius: var(--radius-lg); flex-wrap: wrap; }
.badge-text { font-weight: var(--font-weight-medium); }

/* Action Row */
.action-row { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; }
.action-row.center { justify-content: center; }

/* Loading State */
.loading-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: var(--space-10); gap: var(--space-3); color: var(--color-text-secondary); text-align: center; }
.loading-spinner { width: 36px; height: 36px; border: 3px solid var(--color-border-light); border-top-color: var(--color-brand-600); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Alert */
.alert { display: inline-flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-4); border-radius: var(--radius-lg); font-size: var(--font-size-sm); }
.alert--error { color: var(--color-text-danger); background: var(--color-bg-danger-subtle); border: 1px solid var(--color-danger-200); }
.alert-icon { font-size: var(--font-size-base); flex-shrink: 0; }

/* Report Container */
.report-container { margin-top: var(--space-4); }
.report-content {
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  line-height: 1.75;
  padding: var(--space-5) var(--space-6);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  max-height: 640px;
  overflow-y: auto;
  color: var(--color-text-primary);
}
.report-content .md-h { margin: var(--space-4) 0 var(--space-2); line-height: 1.3; color: var(--color-text-primary); }
.report-content .md-h1 { font-size: var(--font-size-lg); border-bottom: 1px solid var(--color-border-light); padding-bottom: var(--space-2); }
.report-content .md-h2 { font-size: var(--font-size-base); font-weight: 600; margin: var(--space-5) 0 var(--space-2); padding: var(--space-2) var(--space-3); background: var(--color-surface-tertiary); border-left: 4px solid var(--color-brand-600); border-radius: var(--radius-md); }
.report-content .md-h3 { font-size: var(--font-size-sm); font-weight: 600; color: var(--color-text-secondary); }
.report-content .md-h--risk { background: var(--color-bg-danger-subtle); border-left-color: var(--color-text-danger); color: var(--color-text-danger); }
.report-content strong { color: var(--color-text-primary); font-weight: 700; }
.report-content .md-p { margin: var(--space-2) 0; }
.report-content .md-ul, .report-content .md-ol { margin: var(--space-2) 0; padding-left: var(--space-6); }
.report-content .md-ul { list-style: disc; }
.report-content .md-ol { list-style: decimal; }
.report-content .md-ul li, .report-content .md-ol li { margin: var(--space-1) 0; }
.report-content .md-hr { border: none; border-top: 1px dashed var(--color-border-light); margin: var(--space-5) 0; }
.report-content code { background: var(--color-surface-tertiary); padding: 1px var(--space-1); border-radius: var(--radius-xs); font-family: var(--font-family-mono); font-size: var(--font-size-xs); }

/* Report Disclaimer */
.report-disclaimer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-warning-subtle);
  border: 1px solid var(--color-warning-200);
  border-radius: var(--radius-lg);
  font-size: var(--font-size-xs);
  color: var(--color-text-warning);
}
.disclaimer-icon { font-size: var(--font-size-sm); flex-shrink: 0; }

/* Empty Prompt */
.empty-prompt { display: flex; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-8); color: var(--color-text-tertiary); text-align: center; }
.prompt-icon { font-size: var(--font-size-2xl); }

/* Chart Controls */
.chart-controls { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: flex-end; padding-top: var(--space-3); border-top: 1px solid var(--color-border-light); margin-top: var(--space-3); }

/* Indicator Toggles */
.indicator-toggles { padding-top: var(--space-4); border-top: 1px solid var(--color-border-light); margin-top: var(--space-4); }
.toggles-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); margin-right: var(--space-3); }
.toggles-grid { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.toggle-item { display: inline-flex; align-items: center; gap: var(--space-1.5); padding: var(--space-1.5) var(--space-3); font-size: var(--font-size-sm); color: var(--color-text-secondary); background: var(--color-surface-tertiary); border-radius: var(--radius-full); cursor: pointer; transition: var(--transition-fast); user-select: none; }
.toggle-item:hover { color: var(--color-text-primary); background: var(--color-surface-hover); }
.toggle-item:has(input:checked) { color: var(--color-brand-600); background: var(--color-bg-brand-subtle); }
.toggle-item input { width: 16px; height: 16px; accent-color: var(--color-brand-600); cursor: pointer; }
.toggle-name { font-weight: var(--font-weight-medium); }

/* Chart Card */
.chart-card { }
.chart-card .card-body { min-height: 480px; }

/* Indicators Section */
.indicators-section { }
.indicators-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--space-3); }
.indicator-item { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-3); background: var(--color-surface-secondary); border: 1px solid var(--color-border-light); border-radius: var(--radius-lg); transition: var(--transition-fast); }
.indicator-item:hover { border-color: var(--color-brand-300); box-shadow: var(--shadow-md); transform: translateY(-1px); }
.indicator-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.indicator-value { font-family: var(--font-family-mono); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.indicator-value.text-success { color: var(--color-text-success); }
.indicator-value.text-danger { color: var(--color-text-danger); }

/* Signal Section */
.signal-section { }
.signal-content { display: flex; flex-direction: column; align-items: center; gap: var(--space-4); text-align: center; }
.signal-badge { display: inline-flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-6); font-size: var(--font-size-xl); font-weight: var(--font-weight-bold); border-radius: var(--radius-full); }
.signal-badge.buy { color: var(--color-success-700); background: var(--color-bg-success-subtle); border: 2px solid var(--color-success-300); }
.signal-badge.sell { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border: 2px solid var(--color-danger-300); }
.signal-badge.hold { color: var(--color-warning-700); background: var(--color-bg-warning-subtle); border: 2px solid var(--color-warning-300); }
.signal-icon { font-size: var(--font-size-2xl); }
.signal-score { font-size: var(--font-size-base); color: var(--color-text-secondary); }
.signal-score strong { font-family: var(--font-family-mono); font-size: var(--font-size-xl); color: var(--color-text-primary); }
.signal-reasons { list-style: none; padding: 0; margin: var(--space-4) 0 0; display: flex; flex-direction: column; gap: var(--space-2); width: 100%; max-width: 400px; }
.signal-reasons li { padding: var(--space-2) var(--space-3); font-size: var(--font-size-sm); color: var(--color-text-secondary); background: var(--color-surface-secondary); border: 1px solid var(--color-border-light); border-radius: var(--radius-md); text-align: left; }

/* AI Analysis Card */
.ai-analysis-card { }

/* Highlight */
.hl { color: var(--color-warning-700); font-weight: var(--font-weight-bold); background: var(--color-bg-warning-subtle); border-radius: var(--radius-xs); padding: 0 2px; }

/* Chart Mode Toggle */
.chart-mode-toggle { display: inline-flex; background: var(--color-surface-tertiary); border-radius: var(--radius-md); padding: var(--space-1); gap: var(--space-1); }
.mode-btn { display: inline-flex; align-items: center; gap: var(--space-1.5); padding: var(--space-1.5) var(--space-3); font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); border-radius: var(--radius-sm); background: transparent; border: none; cursor: pointer; transition: var(--transition-fast); }
.mode-btn:hover { color: var(--color-text-primary); background: var(--color-surface-hover); }
.mode-btn--active { color: var(--color-brand-600); background: var(--color-bg-brand-subtle); }
.mode-btn:focus-visible { outline: none; box-shadow: var(--shadow-focus); }
.mode-icon { font-size: 12px; }

/* Focus Visible */
*:focus-visible { outline: none; box-shadow: var(--shadow-focus); }

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {
  .loading-spinner { animation: none; }
  *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}

/* Responsive */
@media (max-width: 1024px) {
  .chart-controls { flex-direction: column; align-items: stretch; }
  .chart-controls .form-group { width: 100%; }
  .chart-controls .btn { width: 100%; justify-content: center; }
}

@media (max-width: 768px) {
  .radio-group { flex-direction: column; gap: var(--space-2); }
  .action-row { flex-direction: column; align-items: stretch; }
  .action-row .btn { width: 100%; justify-content: center; }
  .toggles-grid { justify-content: center; }
  .indicators-grid { grid-template-columns: repeat(2, 1fr); }
  .search-combo { width: 100%; }
  .form-group--search { min-width: 0; }
}

@media (max-width: 480px) {
  .indicators-grid { grid-template-columns: 1fr; }
  .section-title { font-size: var(--font-size-lg); }
  .signal-badge { font-size: var(--font-size-lg); padding: var(--space-2) var(--space-4); }
}
</style>