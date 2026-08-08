import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
def ocr(path):
    # upscale 2x for small text, single column
    r = subprocess.run([tess, path, 'stdout', '-l', 'eng', '--psm', '6'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.stdout
for p in [r'.reasonix\attachments\clipboard-20260808-205920.171661-000001.png',
          r'.reasonix\attachments\clipboard-20260808-205928.483264-000002.png']:
    print('='*30)
    print(p)
    print('='*30)
    print(ocr(p))