import os
import csv
import json
import shutil

# replicate app's storage resolution logic
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
CLINICS_FILE = os.path.join(STORAGE_DIR, 'clinics.json')
INVENTORY_TEMPLATE = os.path.join(STORAGE_DIR, 'inventory_{clinic}.csv')

# load clinics
clinics = ['KRMR', 'SKZR']
if os.path.exists(CLINICS_FILE):
    try:
        with open(CLINICS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list) and data:
                clinics = data
    except Exception:
        pass

# read master medicines
med_ids = []
meds = []
if os.path.exists(MED_FILE):
    try:
        with open(MED_FILE, 'r', newline='', encoding='utf-8') as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                mid = (r.get('MedicineID') or '').strip()
                if not mid:
                    # generate placeholder id for rows without one? prefer to skip
                    continue
                med_ids.append(mid)
                meds.append(r)
    except Exception as e:
        print('Failed to read MED_FILE:', e)
        raise SystemExit(1)
else:
    print('MED_FILE not found at', MED_FILE)
    raise SystemExit(1)

results = {}
for clinic in clinics:
    invf = INVENTORY_TEMPLATE.format(clinic=clinic)
    # backup existing
    try:
        if os.path.exists(invf):
            shutil.copy2(invf, invf + '.bak')
    except Exception:
        pass
    # load existing inventory mapping
    inv_map = {}
    if os.path.exists(invf):
        try:
            with open(invf, 'r', newline='', encoding='utf-8') as f:
                rdr = csv.DictReader(f)
                for r in rdr:
                    mid = (r.get('MedicineID') or '').strip()
                    if not mid:
                        continue
                    inv_map[mid] = {
                        'Quantity': (r.get('Quantity') or '').strip(),
                        'ReorderLevel': (r.get('ReorderLevel') or '').strip()
                    }
        except Exception:
            inv_map = {}
    # ensure every med id present
    added = 0
    for mid in med_ids:
        if mid not in inv_map:
            inv_map[mid] = {'Quantity': '', 'ReorderLevel': ''}
            added += 1
    # write inventory file
    try:
        with open(invf, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['MedicineID','Quantity','ReorderLevel'])
            w.writeheader()
            for mid in med_ids:
                r = inv_map.get(mid, {'Quantity': '', 'ReorderLevel': ''})
                w.writerow({'MedicineID': mid, 'Quantity': r.get('Quantity',''), 'ReorderLevel': r.get('ReorderLevel','')})
        results[clinic] = {'added': added, 'path': invf}
    except Exception as e:
        results[clinic] = {'error': str(e), 'path': invf}

print('Inventory sync complete')
for c,v in results.items():
    if 'error' in v:
        print(f"{c}: ERROR writing {v['path']}: {v['error']}")
    else:
        print(f"{c}: wrote {v['path']}, added {v['added']} missing rows")
print('MED_FILE:', MED_FILE)
