import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
src = r'.reasonix\attachments\clipboard-20260808-210927.554371-000012.png'
im = Image.open(src).convert('RGB')
w, h = im.size
# 标题行区域（约 8%-22% 高度，含 标的名称+分类标签）
crop = im.crop((0, int(h*0.06), w, int(h*0.24)))
big = crop.resize((int(crop.width*3), int(crop.height*3)), Image.LANCZOS)
p = r'diag\n2\_crop12_title.png'
big.save(p)
r = subprocess.run([tess, p, 'stdout', '-l', 'eng', '--psm', '6'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print('--- title band ---')
print(r.stdout[:2500])