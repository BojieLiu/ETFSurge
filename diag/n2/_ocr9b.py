import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
src = r'.reasonix\attachments\clipboard-20260808-210749.283311-000009.png'
im = Image.open(src).convert('RGB')
print('size:', im.size)
w, h = im.size
# 上半部（对话框区）
for name, box in [('top', (0, 0, w, h//2)), ('mid', (0, h//4, w, h//2))]:
    crop = im.crop(box)
    big = crop.resize((crop.width*3, crop.height*3), Image.LANCZOS)
    p = fr'diag\n2\_crop_{name}.png'
    big.save(p)
    r = subprocess.run([tess, p, 'stdout', '-l', 'eng', '--psm', '6'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(f'--- {name} ---')
    print(r.stdout[:2500])