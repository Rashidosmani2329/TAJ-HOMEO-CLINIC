"""
Simple OCR + invoice parsing helper.
Usage:
  1. Save your invoice image to the project folder, e.g. `invoice_sample.jpg`.
  2. Install dependencies (see requirements.txt) and Tesseract engine.
  3. Run: python tools/ocr_invoice.py ../invoice_sample.jpg

This script uses pytesseract + Pillow and heuristics to extract supplier, date, items, total, status.
"""
import sys
import re
import difflib
from PIL import Image

try:
    import pytesseract
except Exception:
    pytesseract = None


def parse_invoice_text(text, known_suppliers=None):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    fulltext = '\n'.join(lines)
    result = {
        'supplier': None,
        'date': None,
        'items': [],
        'total': None,
        'status': None,
        'raw_lines': lines,
    }

    # Supplier detection
    if known_suppliers:
        suppliers_list = [s for s in known_suppliers if s]
        ftlower = fulltext.lower()
        for sup in suppliers_list:
            if sup.lower() in ftlower:
                result['supplier'] = sup
                break
        if not result['supplier']:
            snippet = ' '.join(lines[:5])
            close = difflib.get_close_matches(snippet, suppliers_list, n=1, cutoff=0.6)
            if close:
                result['supplier'] = close[0]
            else:
                for ln in lines:
                    close = difflib.get_close_matches(ln, suppliers_list, n=1, cutoff=0.6)
                    if close:
                        result['supplier'] = close[0]
                        break

    # Date detection
    date_patterns = [r"(\d{4}-\d{2}-\d{2})", r"(\d{2}/\d{2}/\d{4})", r"(\d{2}-\d{2}-\d{4})", r"(\d{1,2} [A-Za-z]{3,9} \d{4})"]
    for pat in date_patterns:
        m = re.search(pat, fulltext)
        if m:
            result['date'] = m.group(1)
            break

    # Amounts and items
    amt_re = re.compile(r"(?<!\d)(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{1,2})?")
    items = []
    amounts_all = []
    for ln in lines:
        ln_clean = ln.replace('Rs.', '').replace('Rs', '').replace('INR', '')
        am = amt_re.findall(ln_clean.replace(',', ''))
        if am:
            try:
                price = am[-1]
                pv = float(price)
            except Exception:
                continue
            desc = re.sub(re.escape(price), '', ln_clean, flags=re.IGNORECASE).strip()
            desc = re.sub(r"\b(Qty|Qty:|Qty\.|Quantity|Total|Subtotal|Invoice|Amount)\b", '', desc, flags=re.IGNORECASE).strip(' :-')
            if desc == '' or re.search(r'total', ln, re.I):
                amounts_all.append(pv)
                continue
            items.append({'desc': desc, 'price': f"{pv:.2f}"})
            amounts_all.append(pv)
    result['items'] = items

    # Total
    total_val = None
    for ln in lines:
        if re.search(r'total', ln, re.I):
            am = amt_re.findall(ln.replace(',', ''))
            if am:
                try:
                    total_val = float(am[-1])
                    break
                except Exception:
                    pass
    if total_val is None and amounts_all:
        total_val = max(amounts_all)
    if total_val is not None:
        result['total'] = f"{total_val:.2f}"

    # Status
    if re.search(r'paid|paid in full|payment received', fulltext, re.I):
        result['status'] = 'Done'
    elif re.search(r'due|balance|outstanding', fulltext, re.I):
        result['status'] = 'Due'

    return result


def ocr_image(path, known_suppliers=None):
    if pytesseract is None:
        raise RuntimeError('pytesseract not installed or Tesseract not available')
    img = Image.open(path)
    text = pytesseract.image_to_string(img)
    return parse_invoice_text(text, known_suppliers=known_suppliers)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python tools/ocr_invoice.py <image_path>')
        sys.exit(1)
    path = sys.argv[1]
    try:
        res = ocr_image(path)
    except Exception as e:
        print('OCR failed:', e)
        sys.exit(2)
    import json
    print(json.dumps(res, indent=2))
