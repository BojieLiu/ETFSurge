with open('E:/ETF_Surge/frontend/src/components/Dashboard.vue', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        <!-- Result Step -->
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
        </div>'''

new = '''        <!-- Result Step -->
        <div v-else-if="designStep === 'result' && designResult?.plans?.length" class="panel-body design-result">
          <p class="result-hint">共生成 {{ designResult.plans.length }} 个方案，点击卡片展开详情，再次点击收起</p>

          <div class="design-plans-grid">
            <article
              v-for="pf in designResult.plans"
              :key="pf.style"
              :class="['design-plan-card', { expanded: expandedPlan === pf.style }]"
              @click="togglePlanExpand(pf)"
            >
              <div class="plan-header">
                <span class="plan-style-badge">{{ pf.style_label || pf.style }}</span>
                <span class="plan-score" v-if="pf.score !== undefined">评分 {{ pf.score }}</span>
                <span class="expand-toggle" :class="{ rotated: expandedPlan === pf.style }">
                  <span class="expand-icon">▼</span>
                </span>
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
                  <span v-if="pf.allocations and pf.allocations.length > 5" class="alloc-more">+{{ pf.allocations.length - 5 }} 只</span>
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
                  {{ applyingPlan === pf.style ? '应用中...' : '一键应用' }}
                </AppButton>
              </div>

              <!-- Expanded Detail View -->
              <div v-if="expandedPlan === pf.style" class="plan-expanded-detail">
                <div class="detail-section">
                  <h4 class="detail-title">📊 完整持仓明细 ({{ pf.allocations?.length || 0 }} 只 ETF)</h4>
                  <div class="holdings-table-wrapper">
                    <table class="holdings-table">
                      <thead>
                        <tr>
                          <th>代码</th>
                          <th>名称</th>
                          <th>资产类别</th>
                          <th>目标权重</th>
                          <th>选入理由</th>
                          <th>仓位设置理由</th>
                          <th v-if="pf.allocations?.[0]?.tracked_index">跟踪指数</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="item in pf.allocations" :key="item.symbol">
                          <td><code>{{ item.symbol }}</code></td>
                          <td>{{ item.name }}</td>
                          <td><span class="asset-badge" :class="item.asset_class">{{ getAssetClassLabel(item.asset_class) }}</span></td>
                          <td class="weight-cell">{{ (item.target_weight * 100).toFixed(1) }}%</td>
                          <td class="rationale-cell">{{ item.selection_rationale or '—' }}</td>
                          <td class="rationale-cell">{{ item.weight_rationale or '—' }}</td>
                          <td v-if="pf.allocations?.[0]?.tracked_index">{{ item.tracked_index or '—' }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                <div class="detail-section" v-if="pf.market_analysis">
                  <h4 class="detail-title">📈 市场分析</h4>
                  <div class="analysis-grid">
                    <div class="analysis-item" v-for="(val, key) in pf.market_analysis" :key="key" v-if="val">
                      <span class="analysis-label">{{ getMarketAnalysisLabel(key) }}</span>
                      <span class="analysis-value">{{ val }}</span>
                    </div>
                  </div>
                </div>

                <div class="detail-section" v-if="pf.allocation_rationale">
                  <h4 class="detail-title">🎯 配置逻辑</h4>
                  <div class="analysis-grid">
                    <div class="analysis-item" v-for="(val, key) in pf.allocation_rationale" :key="key" v-if="val">
                      <span class="analysis-label">{{ getAllocationRationaleLabel(key) }}</span>
                      <span class="analysis-value">{{ val }}</span>
                    </div>
                  </div>
                </div>

                <div class="detail-section" v-if="pf.risk_factors?.length">
                  <h4 class="detail-title">⚠️ 风险因子</h4>
                  <ul class="risk-factors-list">
                    <li v-for="(risk, i) in pf.risk_factors" :key="i">{{ risk }}</li>
                  </ul>
                </div>

                <div class="detail-section" v-if="pf.rebalance_rules">
                  <h4 class="detail-title">🔄 再平衡规则</h4>
                  <p class="rebalance-rules">{{ pf.rebalance_rules }}</p>
                </div>
              </div>
            </article>
          </div>
        </div>'''

if old in content:
    content = content.replace(old, new)
    with open('E:/ETF_Surge/frontend/src/components/Dashboard.vue', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: Replacement done')
else:
    print('OLD NOT FOUND')
    start = content.find('<!-- Result Step -->')
    if start != -1:
        end = content.find('<div class="panel-footer-actions">', start)
        if end != -1:
            end += len('<div class="panel-footer-actions">')
            with open('E:/ETF_Surge/actual_content.txt', 'w', encoding='utf-8') as f:
                f.write(content[start:end])
            print('Actual content written to actual_content.txt')