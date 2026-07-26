import sys, os
sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
filepath = os.path.join(base, 'frontend/src/components/MarketAnalysis.vue')

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old = "const filteredIndices = ref([])\nconst selectedIndexCode = ref('')\nconst selectedIndexName = ref('')"
new = """const filteredIndices = ref([])
const filteredIndicesByTab = computed(() => {
  const list = filteredIndices.value
  if (!list.length || marketTab.value === 'global') return list
  return list.filter(idx => idx.market === marketTab.value)
})
const selectedIndexCode = ref('')
const selectedIndexName = ref('')"""

if old in content:
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('PATTERN NOT FOUND')
    idx = content.find('filteredIndices')
    if idx >= 0:
        print(repr(content[idx:idx+200]))
