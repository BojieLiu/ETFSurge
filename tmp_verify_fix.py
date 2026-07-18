"""设计 #65 — P6/P7 参数效果验证"""
import requests, time

BASE = 'http://127.0.0.1:8000/api/v1'
did = 65
detail = requests.get(f'{BASE}/portfolio/designs/{did}', timeout=10).json()
text = detail.get('design_text', '')
print(f'text_len: {len(text)}')
print(f'has_## 一: {"## 一" in text}')
print(f'has_## 二: {"## 二" in text}')
print(f'has_510500: {"510500" in text}')
print(f'has_511090: {"511090" in text}')
print(f'has_止损: {"止损" in text}')
print(f'has_加仓: {"加仓" in text}')
print(f'boilerplate_开头300: {"好的" in text[:300]}')
print(f'AI腔_需要指出: {"需要指出的是" in text}')
print(f'AI腔_整体来看: {"整体来看" in text}')
print()
print('=== 开场白（前300字）===')
print(text[:300])
print()
print('=== 结尾（后300字）===')
print(text[-300:])
