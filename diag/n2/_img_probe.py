import sys
try:
    from PIL import Image
    im = Image.open(r'.reasonix\attachments\clipboard-20260808-205920.171661-000001.png')
    print('PIL ok, size:', im.size, 'mode:', im.mode)
except Exception as e:
    print('PIL err:', e)
try:
    import pytesseract
    print('pytesseract ok')
except Exception as e:
    print('pytesseract err:', e)