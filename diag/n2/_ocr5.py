import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
for src, out in [(r'.reasonix\attachments\clipboard-20260808-210054.825097-000005.png', r'diag\n2\_big5.png'),
                 (r'.reasonix\attachments\clipboard-20260808-210102.127148-000006.png', r'diag\n2\_big6.png')]:
    im = Image.open(src).convert('RGB')
    big = im.resize((im.width*2, im.height*2), Image.LANCZOS)
    big.save(out)
    print('='*30, src, im.size)
    r = subprocess.run([tess, out, 'stdout', '-l', 'eng', '--psm', '6'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(r.stdout[:4000])