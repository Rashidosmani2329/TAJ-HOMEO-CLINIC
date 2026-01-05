import pytesseract
print('pytesseract', getattr(pytesseract, '__version__', 'n/a'))
try:
    print('get_tesseract_version', pytesseract.get_tesseract_version())
except Exception as e:
    print('get_tesseract_version error', e)
