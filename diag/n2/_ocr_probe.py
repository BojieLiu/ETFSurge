import os
for p in [r'C:\Program Files\Tesseract-OCR\tesseract.exe',
          r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe']:
    print(p, os.path.exists(p))
for mod in ['easyocr', 'rapidocr_onnxruntime', 'paddleocr', 'cnocr']:
    try:
        __import__(mod)
        print(mod, '-> available')
    except Exception as e:
        print(mod, '->', type(e).__name__)