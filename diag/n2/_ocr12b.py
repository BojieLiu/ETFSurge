import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
src = r'.reasonix\attachments\clipboard-20260808-210927.554371-000012.png'
im = Image.open(src).convert('RGB')
w, h = im.size
# 右上角分类标签区（标题行）
crop = im.crop((w//2, 0, w, int(h*0.18)))
big = crop.resize((crop.width*3, crop.height*3), Image.LANCZOS)
p = r'diag\n2\_crop12_top.png'
big.save(p)
r = subprocess.run([tess, p, 'stdout', '-l', 'eng', '--psm', '6'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print('--- top-right ---')
print(r.stdout[:2000])
# 左下分类区
crop2 = im.crop((0, int(h*0.0), int(w*0.6), int(h*0.12)))
big2 = crop2.resize((crop2.width*3, crop2.height*3), Image.LANCZOS)
p2 = r'diag\n2\_crop12_left.png'
big2.save(p2)
r2 = subprocess.run([tess, p2, 'stdout', '-l', 'eng', '--psm', '6'],
                    capture_output=True, text=True, encoding='utf-8', errors='replace')
print('--- top-left ---')
print(r2.stdout[:2000])