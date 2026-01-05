import importlib, sys
sys.path.insert(0, '.')
mod = importlib.import_module('homeo_patient_app')
cls = getattr(mod, 'HomeoPatientApp', None)
if cls is None:
    print('HomeoPatientApp class not found')
    raise SystemExit(1)
methods = [
    'search_name','clear_search','open_payments_summary_window','open_add_invoice','open_view_invoices',
    'open_add_patient','edit_selected_patient','import_data','export_data','open_handwriting_input',
    'open_inventory','open_stock_adjustment','open_suppliers','open_order_list','open_shift_history','open_help',
    'delete_selected','delete_filtered','save_patient','load_patients','save_patients','open_add_clinic','change_clinic',
    'open_patient_window','add_medicine_to_selection','open_medicine_search','add_pills_action'
]
missing = []
not_callable = []
for m in methods:
    if not hasattr(cls, m):
        missing.append(m)
    else:
        attr = getattr(cls, m)
        if not callable(attr):
            not_callable.append(m)
print('Checked HomeoPatientApp methods')
print('Missing:', missing)
print('Not callable:', not_callable)
extra = ['load_medicines','save_medicines','save_inventory','_inventory_refresh']
miss = []
for e in extra:
    if not hasattr(cls, e) and not hasattr(mod, e):
        miss.append(e)
print('Extra missing (class or module):', miss)
print('\nAll methods that are present and callable (sample):')
for m in methods:
    if hasattr(cls, m) and callable(getattr(cls, m)):
        print(' -', m)
