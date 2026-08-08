import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
src = r'.reasonix\attachments\clipboard-20260808-211052.786253-000015.png'
im = Image.open(src).convert('RGB')
print('size:', im.size)
big = im.resize((int(im.width*2), int(im.height*2)), Image.LANCZOS)
tmp = r'diag\n2\_big15.png'
big.save(tmp)
for psm in ['6', '4']:
    print(f'===== psm {psm} =====')
    r = subprocess.run([tess, tmp, 'stdout', '-l', 'eng', '--psm', psm],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(r.stdout[:4500])