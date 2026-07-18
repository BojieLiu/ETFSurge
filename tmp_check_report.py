t = open('E:\\ETF_Surge\\tmp_report.txt','r',encoding='utf-8').read()
parts = t.split('---')
# The engine tables are after the last --- (LLM before it)
engine_section = parts[-1]
print('=== 引擎表格部分（最后一段 --- 之后）===')
print(engine_section.strip()[:2000])
