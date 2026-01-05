import os
import csv
import uuid
import shutil

# Paths (match application's logic)
def get_storage_dir():
    _exe_dir = os.path.dirname(r"c:\Users\RASHID\Music\Taj Homeo\homeo_patient_app.py")
    _portable_marker = os.path.join(_exe_dir, 'PORTABLE')
    try:
        if os.getenv('TAJHOMEO_PORTABLE') == '1' or os.path.exists(_portable_marker):
            STORAGE_DIR = _exe_dir
        else:
            APPDATA_DIR = os.getenv('APPDATA') or os.path.expanduser('~')
            STORAGE_DIR = os.path.join(APPDATA_DIR, 'TajHomeo')
        os.makedirs(STORAGE_DIR, exist_ok=True)
    except Exception:
        STORAGE_DIR = os.path.dirname(__file__)
    return STORAGE_DIR

STORAGE_DIR = get_storage_dir()
MED_FILE = os.path.join(STORAGE_DIR, 'medicines.csv')
INVENTORY_TEMPLATE = os.path.join(STORAGE_DIR, 'inventory_{clinic}.csv')
# choose default clinic
clinic = 'KRMR'
INVENTORY_FILE = INVENTORY_TEMPLATE.format(clinic=clinic)

src = r"c:\Users\RASHID\Desktop\medicines.csv"
if not os.path.exists(src):
    print('Source file not found:', src)
    raise SystemExit(1)

# backup existing files
for p in (MED_FILE, INVENTORY_FILE):
    try:
        if os.path.exists(p):
            shutil.copy2(p, p + '.bak')
    except Exception:
        pass

# load existing master
meds = []
if os.path.exists(MED_FILE):
    try:
        with open(MED_FILE, 'r', newline='', encoding='utf-8') as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                meds.append({
                    'MedicineID': (r.get('MedicineID') or '').strip(),
                    'Name': (r.get('Name') or '').strip(),
                    'Supplier': (r.get('Supplier') or '').strip(),
                    'Price': (r.get('Price') or '').strip(),
                    'ReorderLevel': (r.get('ReorderLevel') or '').strip(),
                    'Notes': (r.get('Notes') or '').strip(),
                    'Category': (r.get('Category') or '').strip(),
                    'Quantity': (r.get('Quantity') or '').strip() if 'Quantity' in (r or {}) else ''
                })
    except Exception as e:
        print('Failed to read existing MED_FILE:', e)

added = 0
updated = 0

with open(src, 'r', newline='', encoding='utf-8') as f:
    rdr = csv.DictReader(f)
    for r in rdr:
        name = (r.get('Name') or r.get('name') or '').strip()
        if not name:
            continue
        mid = (r.get('MedicineID') or '').strip() or str(uuid.uuid4())
        ent = None
        # find by MedicineID
        for m in meds:
            if m.get('MedicineID') and m.get('MedicineID') == mid:
                ent = m
                break
        if ent is None:
            # match by name+supplier
            sname = (r.get('Supplier') or '').strip().lower()
            for m in meds:
                if (m.get('Name','').strip().lower() == name.lower()) and (m.get('Supplier','').strip().lower() == sname):
                    ent = m
                    break
        if ent is None:
            ent = {'MedicineID': mid}
            meds.append(ent)
            added += 1
        else:
            updated += 1
        ent['MedicineID'] = ent.get('MedicineID') or mid
        ent['Name'] = name
        ent['Supplier'] = (r.get('Supplier') or '').strip()
        ent['Category'] = (r.get('Category') or '').strip()
        ent['Price'] = (r.get('Price') or '').strip()
        ent['ReorderLevel'] = (r.get('ReorderLevel') or '').strip()
        ent['Notes'] = (r.get('Notes') or '').strip()
        if 'Quantity' in r:
            ent['Quantity'] = (r.get('Quantity') or '').strip()

# write master MED_FILE (fields: MedicineID,Name,Supplier,Price,ReorderLevel,Notes,Category)
fieldnames = ['MedicineID','Name','Supplier','Price','ReorderLevel','Notes','Category']
try:
    with open(MED_FILE, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for m in meds:
            if 'Category' not in m:
                m['Category'] = ''
            out = {k: m.get(k,'') for k in fieldnames}
            w.writerow(out)
    okm = True
except Exception as e:
    print('Failed to write MED_FILE:', e)
    okm = False

# write inventory file with MedicineID,Quantity,ReorderLevel
try:
    # ensure inventory directory exists
    os.makedirs(os.path.dirname(INVENTORY_FILE), exist_ok=True)
    with open(INVENTORY_FILE, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['MedicineID','Quantity','ReorderLevel'])
        w.writeheader()
        for m in meds:
            out = {'MedicineID': m.get('MedicineID',''), 'Quantity': m.get('Quantity',''), 'ReorderLevel': m.get('ReorderLevel','')}
            w.writerow(out)
    oki = True
except Exception as e:
    print('Failed to write INVENTORY_FILE:', e)
    oki = False

print(f'Done. Added: {added}, Updated: {updated}. MED_FILE saved: {okm}, INVENTORY saved: {oki}')
print('MED_FILE:', MED_FILE)
print('INVENTORY_FILE:', INVENTORY_FILE)
print('Backups saved as .bak where applicable')
