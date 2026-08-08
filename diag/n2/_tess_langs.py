import sys, subprocess, os
sys.stdout.reconfigure(encoding='utf-8')
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
out = subprocess.run([tess, '--list-langs'], capture_output=True, text=True, encoding='utf-8')
print('LANGS:')
print(out.stdout)
print(out.stderr)