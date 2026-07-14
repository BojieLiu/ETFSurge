with open('frontend/src/components/Dashboard.vue', 'r', encoding='utf-8') as f:
    content = f.read()

import re
# Find start
start = content.find('<!-- Result Step -->')
if start != -1:
    end = content.find('<div class="panel-footer-actions">', start)
    if end != -1:
        end += len('<div class="panel-footer-actions">')
        print(content[start:end])