import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
src = r'.reasonix\attachments\clipboard-20260808-211124.941012-000016.png'
im = Image.open(src).convert('RGB')
w, h = im.size
# 报告第三段（宏观政策）区域——大约 55%-100% 高度
crop = im.crop((0, int(h*0.50), w, h))
big = crop.resize((int(crop.width*2.2), int(crop.height*2.2)), Image.LANCZOS)
p = r'diag\n2\_crop16_macro.png'
big.save(p)
r = subprocess.run([tess, p, 'stdout', '-l', 'eng', '--psm', '6'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print('--- macro section ---')
print(r.stdout[:4500])