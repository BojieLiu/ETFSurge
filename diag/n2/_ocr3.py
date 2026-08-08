import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
p = r'.reasonix\attachments\clipboard-20260808-205951.697539-000003.png'
r = subprocess.run([tess, p, 'stdout', '-l', 'eng', '--psm', '6'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r.stdout)