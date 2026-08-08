# 合并 round10 报告三部分

import sys

parts = [
    r'diag\n2\round10_diagnosis_report.md',
    r'diag\n2\round10_part2.md',
    r'diag\n2\round10_part3.md',
]
out = r'docs\round10-container-rediagnosis.md'
with open(out, 'w', encoding='utf-8') as f:
    for i, p in enumerate(parts):
        with open(p, encoding='utf-8') as src:
            content = src.read()
            if i > 0:
                f.write('\n\n---\n\n')
            f.write(content)
print('merged ->', out)