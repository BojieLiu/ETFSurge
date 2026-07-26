import sys
sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

with open('../frontend/src/components/MarketAnalysis.vue', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
i = 0
executed = False
while i < len(lines):
    l = lines[i]
    if not executed and l.strip() == "const filteredIndices = ref([])":
        # Check next line has selectedIndexCode
        if i + 1 < len(lines) and 'selectedIndexCode' in lines[i + 1]:
            new_lines.append(l)
            new_lines.append("const filteredIndicesByTab = computed(() => {\n")
            new_lines.append("  const list = filteredIndices.value\n")
            new_lines.append("  if (!list.length || marketTab.value === 'global') return list\n")
            new_lines.append("  return list.filter(idx => idx.market === marketTab.value)\n")
            new_lines.append("})\n")
            executed = True
            i += 1
            continue
    new_lines.append(l)
    i += 1

with open('../frontend/src/components/MarketAnalysis.vue', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('OK' if executed else 'NOT FOUND')
