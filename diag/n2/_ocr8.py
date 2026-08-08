import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
src = r'.reasonix\attachments\clipboard-20260808-210140.837941-000008.png'
im = Image.open(src).convert('RGB')
big = im.resize((im.width*2, im.height*2), Image.LANCZOS)
tmp = r'diag\n2\_big8.png'
big.save(tmp)
for psm in ['6', '4']:
    print(f'===== psm {psm} =====')
    r = subprocess.run([tess, tmp, 'stdout', '-l', 'eng', '--psm', psm],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(r.stdout[:5000])