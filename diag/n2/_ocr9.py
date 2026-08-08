import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
src = r'.reasonix\attachments\clipboard-20260808-210749.283311-000009.png'
im = Image.open(src).convert('RGB')
big = im.resize((int(im.width*2.2), int(im.height*2.2)), Image.LANCZOS)
tmp = r'diag\n2\_big9.png'
big.save(tmp)
r = subprocess.run([tess, tmp, 'stdout', '-l', 'eng', '--psm', '6'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r.stdout[:4000])