import sys, os
sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
filepath = os.path.join(base, 'frontend/src/components/MarketAnalysis.vue')

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# 1. filteredIndices.length -> filteredIndicesByTab.length
old1 = 'indexDropdownOpen && filteredIndices.length'
new1 = 'indexDropdownOpen && filteredIndicesByTab.length'
if old1 in content:
    content = content.replace(old1, new1)
    changes += 1
    print('Changed 1: index dropdown length')

# 2. v-for filteredIndices -> filteredIndicesByTab
old2 = 'v-for="(idx, i) in filteredIndices"'
new2 = 'v-for="(idx, i) in filteredIndicesByTab"'
if old2 in content:
    content = content.replace(old2, new2)
    changes += 1
    print('Changed 2: index v-for')

# 3. onIndexKeydown list
old3 = 'const list = filteredIndices.value\n  if (!indexDropdownOpen.value || !list.length) return'
new3 = 'const list = filteredIndicesByTab.value\n  if (!indexDropdownOpen.value || !list.length) return'
if old3 in content:
    content = content.replace(old3, new3)
    changes += 1
    print('Changed 3: onIndexKeydown')

# 4. Add watch(marketTab) before onMounted
old4 = "// Load index meta on mount\nonMounted(() => {"
new4 = """// Reload sectors and reset index navigation when market tab changes
watch(marketTab, () => {
  onSectorTypeChange()
  indexActiveIndex.value = -1
})

// Load index meta on mount
onMounted(() => {"""
if old4 in content:
    content = content.replace(old4, new4)
    changes += 1
    print('Changed 4: watch(marketTab)')

# 5. Add market-tabs CSS after .page-description
old5 = "/* Section Card */"
new5 = """/* Market Tabs */
.market-tabs { display: flex; gap: var(--space-2); margin-bottom: var(--space-6); border-bottom: 1px solid var(--color-border-light); padding-bottom: var(--space-2); }
.market-tab { padding: var(--space-2) var(--space-4); font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); border: none; background: none; cursor: pointer; border-radius: var(--radius-md); transition: var(--transition-fast); }
.market-tab:hover { background: var(--color-bg-secondary); color: var(--color-text-primary); }
.market-tab.active { background: var(--color-bg-brand-subtle); color: var(--color-brand-600); font-weight: var(--font-weight-semibold); }

/* Section Card */"""
if old5 in content:
    content = content.replace(old5, new5)
    changes += 1
    print('Changed 5: CSS')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print(f'\nTotal changes: {changes}')
