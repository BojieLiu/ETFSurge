# -*- coding: utf-8 -*-
"""OCR 读取用户截图的因子模型页面"""
from PIL import Image
import pytesseract

p = r".reasonix/attachments/clipboard-20260807-201934.218460-000007.png"
img = Image.open(p)
print("image size:", img.size)
try:
    txt = pytesseract.image_to_string(img, lang="chi_sim+eng")
    print("=== OCR 结果 ===")
    print(txt)
except Exception as e:
    print("OCR 失败:", repr(e))
