import sys, os
sys.stdout.reconfigure(encoding='utf-8')

filepath = 'frontend/src/components/Dashboard.vue'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# 1. Add skeleton loading before cumulative P&L cards
old1 = '      </article>\n\n      <!-- Cumulative P&L Summary Cards -->'
new1 = """      </article>

      <!-- Cumulative P&L Loading Skeletons -->
      <template v-if="pnlHistoryLoading">
        <article class="card summary-card" v-if="activeTab !== 'off_exchange'">
          <div class="summary-content">
            <p class="summary-label">场内累计盈亏</p>
            <Skeleton type="text" width="120" />
          </div>
        </article>
        <article class="card summary-card" v-if="activeTab !== 'on_exchange'">
          <div class="summary-content">
            <p class="summary-label">场外累计盈亏</p>
            <Skeleton type="text" width="120" />
          </div>
        </article>
        <article class="card summary-card" v-if="activeTab === 'combined'">
          <div class="summary-content">
            <p class="summary-label">总累计盈亏</p>
            <Skeleton type="text" width="120" />
          </div>
        </article>
      </template>

      <!-- Cumulative P&L Summary Cards -->
      <template v-else>"""
if old1 in content:
    content = content.replace(old1, new1)
    changes += 1
    print('Changed 1: skeleton loading')
else:
    print('FAIL 1: pattern not found')

# 2. Close the v-else template
old2 = '      </article>\n    </div>\n\n    <!-- Loading Skeletons -->'
new2 = """      </article>
      </template>
    </div>

    <!-- Loading Skeletons -->"""
if old2 in content:
    content = content.replace(old2, new2)
    changes += 1
    print('Changed 2: close template')
else:
    print('FAIL 2: pattern not found')

# 3. Add responsive CSS before AI Design Card
old3 = '/* P&L Card */\n.pnl-card { }\n\n/* AI Design Card */'
new3 = """/* P&L Card */
.pnl-card { }

/* Narrow Screen Responsive */
@media (max-width: 480px) {
  .summary-grid { grid-template-columns: 1fr; }
  .tabs { flex-wrap: wrap; gap: var(--space-2); }
  .capital-inputs .input-group.dual { flex-direction: column; }
  .capital-bar { flex-direction: column; align-items: stretch; }
  .capital-actions { justify-content: stretch; }
  .capital-actions .btn { width: 100%; justify-content: center; }
  .card-title { font-size: var(--font-size-base); }
  .card-meta { flex-wrap: wrap; gap: var(--space-2); }
  .summary-value { font-size: var(--font-size-lg); }
}

@media (max-width: 360px) {
  .data-table th, .data-table td { padding: var(--space-2) var(--space-2); font-size: var(--font-size-xs); }
  .data-table.alloc-table th, .data-table.alloc-table td { padding: var(--space-1) var(--space-2); }
}

@media (min-width: 320px) {
  .dashboard { min-width: 0; }
}

/* AI Design Card */"""
if old3 in content:
    content = content.replace(old3, new3)
    changes += 1
    print('Changed 3: responsive CSS')
else:
    print('FAIL 3: pattern not found')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print(f'\nTotal changes: {changes}')
