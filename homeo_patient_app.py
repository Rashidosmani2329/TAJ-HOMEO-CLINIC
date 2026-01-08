import os
import csv
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import re
import calendar
import uuid
import difflib
from PIL import Image, ImageTk, ImageDraw, ImageFont
import pytesseract
import hashlib
import json

# Application version
APP_VERSION = '1.23'
# URL returning JSON update metadata examples:
# - SHA256: {"version":"1.24","url":"https://.../TajHomeoApp_portable_v1.24.exe","sha256":"..."}
# - MIFFI24: {"version":"1.24","url":"https://.../TajHomeoApp_portable_v1.24.exe","miffi24":"0012ab"}
# Leave blank to disable automatic online checks. Replace <user> with your GitHub username.
UPDATE_METADATA_URL = 'https://rashidosmani2329.github.io/TajHomeoApp/update.json'
# winsound is Windows-only; use if available for beep
try:
    import winsound
except Exception:
    winsound = None

# Create a safe Toplevel subclass used across the app so every new window
# is sized to the workarea (doesn't overlap the taskbar) and gains a small
# bottom margin. Replacing `tk.Toplevel` ensures all call sites benefit.
try:
    def _bottom_offset_pixels(cm=3.0):
        """Return pixel height for `cm` centimeters on Windows, else 0.

        Attempts `GetDpiForSystem`, then falls back to `GetDeviceCaps`.
        Returns 0 on non-Windows platforms or on failure.
        """
        try:
            if os.name != 'nt':
                return 0
            import ctypes
            dpi = None
            try:
                dpi = ctypes.windll.user32.GetDpiForSystem()
            except Exception:
                dpi = None
            if not dpi or dpi <= 0:
                try:
                    hdc = ctypes.windll.user32.GetDC(0)
                    LOGPIXELSX = 88
                    dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
                    ctypes.windll.user32.ReleaseDC(0, hdc)
                except Exception:
                    dpi = 96
            if not dpi or dpi <= 0:
                dpi = 96
            inches = float(cm) / 2.54
            return int(round(inches * dpi))
        except Exception:
            return 0

    _OrigToplevel = tk.Toplevel
    class _SafeToplevel(_OrigToplevel):
        def __init__(self, *a, **kw):
            # special kw to allow small/compact dialogs that shouldn't be
            # resized to the full workarea. Pop here so super() receives
            # only valid tkinter options.
            compact = kw.pop('compact', False)
            fixed_geometry = kw.pop('fixed_geometry', None)
            super().__init__(*a, **kw)
            try:
                # compute workarea if possible
                left, top, right, bottom = 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
                try:
                    import ctypes
                    from ctypes import wintypes
                    rect = wintypes.RECT()
                    SPI_GETWORKAREA = 0x0030
                    res = ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
                    if res:
                        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
                except Exception:
                    pass
                try:
                    # Use a 3cm bottom offset on Windows so the window stays above the taskbar
                    margin = _bottom_offset_pixels(3.0)
                except Exception:
                    margin = 0
                # If caller requested a compact dialog, skip the large workarea
                # geometry and leave sizing to the dialog code below.
                if compact:
                    # if a fixed geometry was given, apply it
                    if fixed_geometry:
                        try:
                            self.geometry(fixed_geometry)
                        except Exception:
                            pass
                    # don't add a bottom spacer for compact dialogs
                else:
                    w = max(100, right - left)
                    h = max(100, (bottom - top) - margin)
                    try:
                        self.geometry(f"{w}x{h}+{left}+{top}")
                        # ensure internal layout can't grow beyond this size
                        self.update_idletasks()
                        try:
                            self.minsize(w, h)
                        except Exception:
                            pass
                        # Do not pack a spacer into the Toplevel — mixing `pack`
                        # with `grid` in the same master causes widgets to disappear
                        # for dialogs that use `grid`. We already set geometry and
                        # minsize to reserve the visual margin, so avoid adding a
                        # packed spacer here.
                    except Exception:
                        pass
            except Exception:
                pass
    tk.Toplevel = _SafeToplevel
except Exception:
    pass

# Prefer a bundled Tesseract shipped alongside the EXE, else fall back to common install path
try:
    _exe_dir = _get_exe_dir()
    bundled_tess = os.path.join(_exe_dir, 'Tesseract-OCR', 'tesseract.exe')
    if os.path.exists(bundled_tess):
        pytesseract.pytesseract.tesseract_cmd = bundled_tess
    else:
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
except Exception:
    try:
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    except Exception:
        pass

# Detect whether Tesseract is actually available to pytesseract at runtime
OCR_AVAILABLE = False
try:
    # calling get_tesseract_version will raise if the binary isn't found
    _ver = pytesseract.get_tesseract_version()
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# If initial detection failed, try a few common install locations and retry
if not OCR_AVAILABLE:
    common_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Tesseract\tesseract.exe",
        os.path.join(os.getenv('LOCALAPPDATA',''), 'Programs', 'Tesseract-OCR', 'tesseract.exe')
    ]
    for p in common_paths:
        try:
            if p and os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                try:
                    _ver = pytesseract.get_tesseract_version()
                    OCR_AVAILABLE = True
                    break
                except Exception:
                    # continue trying other paths
                    continue
        except Exception:
            continue

# Use a writable application data directory for persistent CSVs so EXE builds
# (PyInstaller) and installed apps can reliably read/write data. Prefer %APPDATA% on Windows.
import sys
import shutil
try:
    import ctypes
    from ctypes import wintypes
except Exception:
    ctypes = None
    wintypes = None

# Determine resource / executable directory
def _get_exe_dir():
    if getattr(sys, 'frozen', False):
        # When frozen by PyInstaller, use the executable directory
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)

# By default store user-editable data in %APPDATA% so installs keep data separate from the app.
# the environment variable `TAJHOMEO_PORTABLE=1` is set, use the executable folder instead
# so the app is portable (copy the whole folder to another device and data moves with it).
_exe_dir = _get_exe_dir()
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

# Copy bundled defaults into STORAGE_DIR on first run so data files exist and are writable.
def _copy_default_if_missing(fname):
    src_dir = getattr(sys, '_MEIPASS', None) or _exe_dir or os.path.dirname(__file__)
    src = os.path.join(src_dir, fname)
    dst = os.path.join(STORAGE_DIR, fname)
    try:
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copy2(src, dst)
    except Exception:
        pass

# Files the app expects to exist in STORAGE_DIR on first run; copy bundled samples if missing
_defaults = [
    'patients.csv',
    'visits.csv',
    'medicines.csv',
    'invoices.csv',
    'suppliers.csv',
    'stock_adjustments.csv',
    'shifts.csv',
    'clinics.json',
    'order_list.csv',
]

for _f in _defaults:
    _copy_default_if_missing(_f)

# --- Security helpers (PIN / security questions) ---------------------------------
def _load_security():
    try:
        if os.path.exists(SECURITY_FILE):
            with open(SECURITY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_security(data):
    try:
        with open(SECURITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return True
    except Exception:
        return False

def _hash_code(code, salt_hex):
    try:
        b = bytes.fromhex(salt_hex) + (code or '').encode('utf-8')
        return hashlib.sha256(b).hexdigest()
    except Exception:
        return ''

def _set_new_code(code, questions):
    # questions: list of {'q':..., 'a':...}
    salt = os.urandom(16).hex()
    data = {'salt': salt, 'code_hash': _hash_code(code, salt), 'questions': questions}
    return _save_security(data)

def _verify_code(attempt):
    data = _load_security()
    if not data or 'code_hash' not in data or 'salt' not in data:
        return False
    return _hash_code(attempt, data.get('salt','')) == data.get('code_hash','')


# primary CSV files stored in the writable storage directory
DATA_FILE = os.path.join(STORAGE_DIR, "patients.csv")
VISITS_FILE = os.path.join(STORAGE_DIR, "visits.csv")
MED_FILE = os.path.join(STORAGE_DIR, "medicines.csv")

# Templates for clinic-specific files. MED_FILE is the shared master medicine DB.
BASE_DIR = STORAGE_DIR
DATA_TEMPLATE = os.path.join(BASE_DIR, 'patients_{clinic}.csv')
VISITS_TEMPLATE = os.path.join(BASE_DIR, 'visits_{clinic}.csv')
SUPPLIERS_TEMPLATE = os.path.join(BASE_DIR, 'suppliers_{clinic}.csv')
STOCK_ADJ_TEMPLATE = os.path.join(BASE_DIR, 'stock_adjustments_{clinic}.csv')
SHIFTS_TEMPLATE = os.path.join(BASE_DIR, 'shifts_{clinic}.csv')
INVENTORY_TEMPLATE = os.path.join(BASE_DIR, 'inventory_{clinic}.csv')
CLINICS_FILE = os.path.join(BASE_DIR, 'clinics.json')
SECURITY_FILE = os.path.join(BASE_DIR, 'security.json')

# additional data files
SUPPLIERS_FILE = os.path.join(BASE_DIR, "suppliers.csv")
STOCK_ADJ_FILE = os.path.join(BASE_DIR, "stock_adjustments.csv")
SHIFTS_FILE = os.path.join(BASE_DIR, "shifts.csv")
INVOICES_FILE = os.path.join(BASE_DIR, "invoices.csv")
# persistent order list (created when user confirms an order)
ORDER_FILE = os.path.join(BASE_DIR, 'order_list.csv')
CATEGORIES_FILE = os.path.join(BASE_DIR, 'categories.csv')
ORDER_META_FILE = os.path.join(BASE_DIR, 'order_meta.json')

def _load_order_meta():
    try:
        if os.path.exists(ORDER_META_FILE):
            with open(ORDER_META_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {'unread': 0}

def _save_order_meta(data):
    try:
        with open(ORDER_META_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return True
    except Exception:
        return False

def _check_low_stock_and_notify(app):
    """Scan `app.medicines` for low-stock items (<=3) and notify once per item.

    Uses `ORDER_META_FILE` to remember which items were already notified so
    doctors are notified only when an item first becomes low.
    """
    try:
        # Use a stable identifier for items; prefer MedicineID but fall back to Name
        low_keys = set()
        for m in getattr(app, 'medicines', []):
            qraw = (m.get('Quantity') or '').strip()
            try:
                qv = float(qraw) if qraw != '' else 0.0
            except Exception:
                qv = 0.0
            if qv <= 3:
                mid = (m.get('MedicineID') or '').strip()
                if mid:
                    key = f"ID::{mid}"
                else:
                    # fallback to name-based key so items without IDs still notify
                    name = (m.get('Name') or '').strip()
                    if not name:
                        continue
                    key = f"NAME::{name}"
                low_keys.add(key)
        if not low_keys:
            return
        meta = _load_order_meta()
        notified = set(meta.get('notified', []) or [])
        # determine newly-low keys
        new_low = low_keys - notified
        if not new_low:
            return
        # update meta: mark these keys as notified and increment unread by new items
        notified = notified.union(new_low)
        meta['notified'] = list(notified)
        meta['unread'] = int(meta.get('unread', 0) or 0) + len(new_low)
        _save_order_meta(meta)
        try:
            app.order_unread = int(meta.get('unread', 0) or 0)
            try:
                app._update_order_badge()
            except Exception:
                pass
        except Exception:
            pass
        # build a readable list of newly low item names
        names = []
        for key in new_low:
            if key.startswith('ID::'):
                mid = key.split('::', 1)[1]
                m = next((x for x in getattr(app, 'medicines', []) if (x.get('MedicineID') or '').strip() == mid), None)
            else:
                name = key.split('::', 1)[1]
                m = next((x for x in getattr(app, 'medicines', []) if (x.get('Name') or '').strip() == name), None)
            if m:
                names.append(m.get('Name',''))
        if names:
            # non-blocking toast with a short beep so workflow isn't interrupted
            try:
                _show_toast(app, 'Low stock:\n' + '\n'.join(names))
            except Exception:
                try:
                    messagebox.showinfo('Low stock alert', 'The following items are low in stock and appear in the Order List:\n' + '\n'.join(names))
                except Exception:
                    pass
    except Exception:
        pass

def _show_toast(app, text, duration=4000):
    """Show a small non-blocking toast window near the app and play a beep."""
    try:
        # create lightweight Toplevel
        t = tk.Toplevel(app)
        t.overrideredirect(True)
        try:
            t.attributes('-topmost', True)
        except Exception:
            pass
        frm = ttk.Frame(t, relief='solid', borderwidth=1)
        frm.pack(fill=tk.BOTH, expand=True)
        lbl = ttk.Label(frm, text=text, justify='left')
        lbl.pack(padx=8, pady=6)
        # position bottom-right of main window
        try:
            app.update_idletasks()
            ax = app.winfo_rootx()
            ay = app.winfo_rooty()
            aw = app.winfo_width()
            ah = app.winfo_height()
            tw = 300
            th = min(120, 20 * (text.count('\n') + 1) + 20)
            x = ax + max(aw - tw - 20, 20)
            y = ay + max(ah - th - 40, 40)
            t.geometry(f"{tw}x{th}+{x}+{y}")
        except Exception:
            pass
        # ensure toast is on top and visible
        try:
            t.lift()
            t.attributes('-topmost', True)
        except Exception:
            pass
        # beep once with robust fallbacks on Windows
        try:
            if winsound:
                try:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:
                    try:
                        winsound.Beep(1000, 180)
                    except Exception:
                        try:
                            import ctypes
                            ctypes.windll.user32.MessageBeep(0x00000030)
                        except Exception:
                            app.bell()
            else:
                try:
                    import ctypes
                    ctypes.windll.user32.MessageBeep(0x00000030)
                except Exception:
                    app.bell()
        except Exception:
            pass
        # auto-destroy after duration
        try:
            app.after(int(duration), lambda: t.destroy())
        except Exception:
            pass
    except Exception:
        try:
            app.bell()
        except Exception:
            pass

class HomeoPatientApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # include version in window title
        try:
            self.title(f"Taj Homeo - v{APP_VERSION}")
        except Exception:
            self.title("Taj Homeo")
        try:
            self.geometry("1000x700")
        except Exception:
            pass

        try:
            # Ensure window is visible and maximized within workarea (does not cover taskbar)
            try:
                self.state('normal')
            except Exception:
                pass
            try:
                self.deiconify()
            except Exception:
                pass
            try:
                self.maximize_window(self)
            except Exception:
                pass
            try:
                # Re-apply after short delay in case the window manager changes state
                self.after(250, lambda: self.maximize_window(self))
            except Exception:
                pass
            try:
                self.update_idletasks()
                self.lift()
                self.focus_force()
            except Exception:
                pass
        except Exception:
            pass

        # Configure fonts and ttk styles:
        # - Keep buttons at Arial 16 bold and headers (tree headings and form labels) at Arial 18 bold
        # - Set the rest of the app to use Arial 12 as the default
        try:
            style = ttk.Style()
            # Fonts: use Arial 11 bold as the app default (buttons, labels, tree rows)
            default_font = ('Arial', 11, 'bold')
            button_font = default_font
            header_font = ('Arial', 14)
            # Keep Treeview rows at the default app font (do not override globally)

            # Configure the named Tk default font to be used by widgets that reference 'TkDefaultFont'
            try:
                tkfont.nametofont('TkDefaultFont').configure(family='Arial', size=11, weight='bold')
            except Exception:
                pass
            try:
                # apply as default for widgets created without explicit font
                self.option_add('*Font', default_font)
            except Exception:
                pass

            # Buttons: keep bold larger font
            try:
                style.configure('TButton', font=button_font, padding=(4, 2), borderwidth=1, background='#2a6f97', foreground='black')
                style.map('TButton',
                          background=[('active', '#1f5a78'), ('!active', '#2a6f97')],
                          foreground=[('disabled', 'gray'), ('!disabled', 'black')],
                          relief=[('pressed', 'sunken'), ('!pressed', 'raised')])
            except Exception:
                try:
                    style.map('TButton', relief=[('pressed', 'sunken'), ('!pressed', 'raised')])
                except Exception:
                    pass

            # Headers: keep Treeview headings and form labels larger/bold
            try:
                style.configure('Treeview.Heading', font=header_font)
            except Exception:
                pass
            try:
                style.configure('FormLabel.TLabel', font=header_font)
            except Exception:
                pass

            # Keep Treeview rows using the default font
            try:
                style.configure('Treeview', font=default_font)
            except Exception:
                pass
            # Patient tree style (explicit) uses default size 12 as requested
            try:
                style.configure('Patient.Treeview', font=default_font)
            except Exception:
                pass

            # Ensure selection shows high-contrast text for treeviews
            try:
                style.map('Treeview',
                          background=[('selected', '#1f5a78'), ('!selected', '')],
                          foreground=[('selected', 'white'), ('!selected', 'black')])
            except Exception:
                pass
        except Exception:
            pass

        # in-memory stores
        self.patients = []
        self.medicines = []
        self.suppliers = []
        self.last_deleted = []
        # If True, the main patient list will remain empty until the user performs a search.
        # This prevents showing patient names on the landing page before an explicit search.
        self.require_search_before_show = True

        # order notification state
        try:
            meta = _load_order_meta()
            self.order_unread = int(meta.get('unread', 0) or 0)
        except Exception:
            self.order_unread = 0
        self.order_button = None

        # simple form vars used by some methods
        self.search_var = tk.StringVar()
        self.title_var = tk.StringVar(value="MR")
        self.name_var = tk.StringVar()
        self.age_var = tk.StringVar()
        self.mobile_var = tk.StringVar()
        # address text (kept hidden unless used by dialogs)
        self.address_txt = tk.Text(self, height=3, width=40)

        # undo button placeholder (some functions expect it)
        self.undo_btn = ttk.Button(self, text='Undo', state='disabled', command=lambda: None)

        # main patient tree
        cols = ('Title', 'Name', 'Age', 'Mobile', 'Address')
        self.tree = ttk.Treeview(self, columns=cols, show='headings', height=20, style='Patient.Treeview')
        for c in cols:
            self.tree.heading(c, text=c, anchor='w')
        # Set column widths based on requested character counts for landing page
        try:
            f = tkfont.nametofont('TkDefaultFont')
        except Exception:
            f = tkfont.Font(family='Arial', size=11)
        char_map = {'Title': 4, 'Name': 25, 'Age': 3, 'Mobile': 13, 'Address': 30}
        padding = 12
        for c in cols:
            cnt = char_map.get(c, 12)
            try:
                w = f.measure('M' * cnt) + padding
            except Exception:
                w = 120
            self.tree.column(c, width=w, anchor='w')
        self.tree.bind('<Double-1>', self.open_patient_window)
        # Ensure selected row is readable across themes by applying a 'sel' tag
        try:
            self.tree.tag_configure('sel', background='#1f5a78', foreground='white')
            def _main_tree_sel(evt):
                tr = evt.widget
                # clear sel tag on all top-level items
                try:
                    for iid in tr.get_children(''):
                        tr.tag_remove('sel', iid)
                except Exception:
                    pass
                # apply sel tag to selected items
                try:
                    for s in tr.selection():
                        tr.tag_add('sel', s)
                except Exception:
                    pass
            self.tree.bind('<<TreeviewSelect>>', _main_tree_sel)
        except Exception:
            pass

        # basic layout: controls on top, tree below
        # Marquee banner (scrolling clinic name)
        marquee_frame = ttk.Frame(self, padding=2)
        marquee_frame.pack(fill=tk.X)
        # include clinic and doctor name in marquee
        self.marquee_var = tk.StringVar(value='  TAJ HOMEO CLINIC  DR FAQRUDDIN FAKHIR  ')
        # increase font size by 4 points and make bold
        marquee_label = ttk.Label(marquee_frame, textvariable=self.marquee_var, anchor='w', font=('TkDefaultFont', 14, 'bold'), foreground='white', background='#2a6f97')
        marquee_label.pack(fill=tk.X)

        # Top toolbar: two stacked rows of buttons (no scroller) so buttons are always visible
        toolbar_container = ttk.Frame(self)
        toolbar_container.pack(fill=tk.X)
        topf = ttk.Frame(toolbar_container, padding=6)
        topf.pack(fill=tk.X)
        # track rows/items created by toolbar
        topf._toolbar_rows = []

        # Clinic selector (per-clinic patient/visits/shifts/inventory storage)
        self.clinics = []
        self.load_clinics()
        if not self.clinics:
            # default clinics
            self.clinics = ['KRMR', 'SKZR']
        self.clinic_var = tk.StringVar(value=self.clinics[0])
        ttk.Label(topf, text='Clinic:').pack(side=tk.LEFT)
        cb = ttk.Combobox(topf, textvariable=self.clinic_var, values=self.clinics, width=8, state='readonly')
        cb.pack(side=tk.LEFT, padx=6)
        ttk.Button(topf, text='Switch', command=lambda: self.change_clinic(self.clinic_var.get())).pack(side=tk.LEFT)
        ttk.Button(topf, text='Add Clinic', command=lambda: self.open_add_clinic()).pack(side=tk.LEFT, padx=(6,0))

        ttk.Label(topf, text='Search:').pack(side=tk.LEFT, padx=(12,0))
        ttk.Entry(topf, textvariable=self.search_var, width=15).pack(side=tk.LEFT, padx=6)
        # Prepare small icons to save space (kept as PhotoImage to avoid GC)
        def _make_icon(color, letter=None):
            try:
                img = Image.new('RGBA', (16,16), (0,0,0,0))
                draw = ImageDraw.Draw(img)
                draw.ellipse((1,1,14,14), fill=color)
                if letter:
                    try:
                        font = ImageFont.load_default()
                        w,h = draw.textsize(letter, font=font)
                        draw.text(((16-w)/2, (16-h)/2), letter, font=font, fill='white')
                    except Exception:
                        pass
                return ImageTk.PhotoImage(img)
            except Exception:
                return None

        self._icons = {
            'search': _make_icon('#2a6f97', 'S'),
            'clear': _make_icon('#666', 'C'),
            'payments': _make_icon('#4caf50', 'P'),
            'add_invoice': _make_icon('#ff9800', '+'),
            'view_invoices': _make_icon('#3f51b5', 'V'),
            'add_patient': _make_icon('#009688', '+'),
            'inventory': _make_icon('#795548', 'I'),
            'stock_adj': _make_icon('#9c27b0', 'A'),
            'suppliers': _make_icon('#607d8b', 'S'),
            'order_list': _make_icon('#f44336', 'O'),
            'shifts': _make_icon('#ff5722', 'H'),
        }

        # Create toolbar button specifications — actual Button widgets are created per-layout
        created_toolbar_specs = []
        def _add_tb(text, cmd, icon_key=None, short=None):
            label = short or text
            img = self._icons.get(icon_key) if icon_key else None
            created_toolbar_specs.append({'label': label, 'cmd': cmd, 'img': img, 'full_text': text})
            return None

        _add_tb('Search', self.search_name, icon_key='search', short='Srch')
        _add_tb('Clear', self.clear_search, icon_key='clear', short='Clr')
        _add_tb('View All Patients', lambda: self.view_all_patients(), icon_key=None, short='All')
        # Payments summary and invoice actions
        _add_tb('Payments', self.open_payments_summary_window, icon_key='payments', short='Pay')
        _add_tb('Add Invoice', lambda: self.open_add_invoice(), icon_key='add_invoice', short='Inv+')
        _add_tb('View Invoices', self.open_view_invoices, icon_key='view_invoices', short='Invs')
        # Add Patient button (opens dialog to add a patient to current clinic)
        _add_tb('Add Patient', lambda: self.open_add_patient(), icon_key='add_patient', short='AddP')
        _add_tb('Edit Patient', self.edit_selected_patient, icon_key=None, short='EditP')
        _add_tb('Delete Patient', self.delete_selected_patient, icon_key=None, short='DelP')
        _add_tb('Check Updates', lambda: self.check_for_updates(show_prompt=True), icon_key=None, short='Upd')
        # Data import/export
        _add_tb('Import Data', self.import_data, icon_key=None, short='Import')
        _add_tb('Export Data', self.export_data, icon_key=None, short='Export')
        _add_tb('Pen Input', lambda: self.open_handwriting_input(), icon_key=None, short='Pen')
        # Right-side actions (we include them in the wrap layout as well)
        _add_tb('Inventory', self.open_inventory, icon_key='inventory', short='Invy')
        _add_tb('Stock Adj', self.open_stock_adjustment, icon_key='stock_adj', short='Adj')
        _add_tb('Suppliers', self.open_suppliers, icon_key='suppliers', short='Sup')
        _add_tb('Order List', self.open_order_list, icon_key='order_list', short='Orders')
        _add_tb('Shifts', self.open_shift_history, icon_key='shifts', short='Shifts')
        # Help: show detailed descriptions of toolbar buttons and app workflow
        _add_tb('Help', lambda: self.open_help(), icon_key=None, short='Help')

        # Three-row toolbar layout: create three stacked rows, distribute buttons evenly,
        # show full button names and do not use icons.
        topf._toolbar_items = []
        try:
            # Keep Search, Add Patient, Edit Patient, Shifts as visible buttons; group the rest under a single 'More' menu
            kept_keys = {'Search', 'Add Patient', 'Edit Patient', 'Shifts'}
            kept_specs = [s for s in created_toolbar_specs if s.get('full_text') in kept_keys]
            grouped_specs = [s for s in created_toolbar_specs if s not in kept_specs]

            # build display list: kept specs in original order, plus a More button for grouped specs
            display_specs = list(kept_specs)
            # Ensure 'Shifts' appears immediately after 'Edit Patient' when both exist
            try:
                ep_idx = next((i for i,s in enumerate(display_specs) if s.get('full_text')=='Edit Patient'), None)
                sh_idx = next((i for i,s in enumerate(display_specs) if s.get('full_text')=='Shifts'), None)
                if ep_idx is not None and sh_idx is not None and sh_idx != ep_idx + 1:
                    sh_spec = display_specs.pop(sh_idx)
                    display_specs.insert(ep_idx + 1, sh_spec)
            except Exception:
                pass
            if grouped_specs:
                def _make_more_cmd(grouped):
                    def _cmd(btn):
                        # show a popup menu near the button
                        try:
                            menu = tk.Menu(self, tearoff=0)
                            for sp in grouped:
                                lab = sp.get('full_text') or sp.get('label')
                                # wrap command to close menu after running
                                def mkcmd(c):
                                    return lambda: c()
                                try:
                                    menu.add_command(label=lab, command=mkcmd(sp['cmd']))
                                except Exception:
                                    try:
                                        menu.add_command(label=lab, command=lambda: None)
                                    except Exception:
                                        pass
                            # position menu at bottom-left of the More button
                            x = btn.winfo_rootx()
                            y = btn.winfo_rooty() + btn.winfo_height()
                            menu.tk_popup(x, y)
                        except Exception:
                            pass
                    return _cmd

                more_spec = {'label': 'More', 'cmd': None, 'img': None, 'full_text': 'More', 'grouped': grouped_specs}
                display_specs.append(more_spec)

            # compute sizes for 3 rows (distribute remainder to first rows)
            n = len(display_specs)
            base = n // 3
            rem = n % 3
            sizes = [base + (1 if i < rem else 0) for i in range(3)]
            slices = []
            idx = 0
            for s in sizes:
                slices.append(display_specs[idx:idx+s])
                idx += s

            rows = [ttk.Frame(topf) for _ in range(3)]
            for r in rows:
                r.pack(fill=tk.X, anchor='w')

            for row_specs, row_frame in zip(slices, rows):
                for spec in row_specs:
                    try:
                        # always use full text label and do not attach images
                        if spec.get('full_text') == 'More':
                            # create More button and attach popup behaviour
                            b = ttk.Button(row_frame, text='More')
                            grouped = spec.get('grouped', []) or []
                            def _make_handler(btn, grouped_items):
                                def _handler():
                                    try:
                                        menu = tk.Menu(self, tearoff=0)
                                        for sp in grouped_items:
                                            lab = sp.get('full_text') or sp.get('label')
                                            cmd = sp.get('cmd')
                                            if callable(cmd):
                                                try:
                                                    menu.add_command(label=lab, command=cmd)
                                                except Exception:
                                                    menu.add_command(label=lab, command=lambda: None)
                                            else:
                                                menu.add_command(label=lab, command=lambda: None)
                                        x = btn.winfo_rootx()
                                        y = btn.winfo_rooty() + btn.winfo_height()
                                        menu.tk_popup(x, y)
                                    except Exception:
                                        pass
                                return _handler
                            b.config(command=_make_handler(b, grouped))
                        else:
                            b = ttk.Button(row_frame, text=spec.get('full_text', spec.get('label')), command=spec['cmd'])
                        b.pack(side=tk.LEFT, padx=6, pady=4)
                        topf._toolbar_items.append(b)
                        # keep reference to Order List button so we can show unread badge
                        try:
                            if spec.get('full_text','') == 'Order List':
                                self.order_button = b
                                # apply badge if needed
                                if getattr(self, 'order_unread', 0):
                                    b.config(text=f"Order List ({self.order_unread})")
                        except Exception:
                            pass
                    except Exception:
                        try:
                            b.destroy()
                        except Exception:
                            pass
                        continue
        except Exception:
            # fallback: single-row pack if anything unexpected happens
            for spec in created_toolbar_specs:
                try:
                    b = ttk.Button(topf, text=spec.get('full_text', spec.get('label')), command=spec['cmd'])
                    b.pack(side=tk.LEFT, padx=6, pady=4)
                    topf._toolbar_items.append(b)
                    try:
                        if spec.get('full_text','') == 'Order List':
                            self.order_button = b
                            if getattr(self, 'order_unread', 0):
                                b.config(text=f"Order List ({self.order_unread})")
                    except Exception:
                        pass
                except Exception:
                    try:
                        b.destroy()
                    except Exception:
                        pass
                    continue

        # place the main tree over a Canvas so we can draw grid lines (vertical + horizontal)
        tree_container = ttk.Frame(self)
        # increase top padding so the toolbar (3 rows) does not overlap the tree
        tree_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=(12,6))
        # background canvas for grid lines
        grid_canvas = tk.Canvas(tree_container, bg='white', highlightthickness=0)
        grid_canvas.grid(row=0, column=0, sticky='nsew')
        # recreate the Treeview as a child of the container (to avoid mixing pack/grid on the same master)
        try:
            # destroy previous tree (it was created as child of self)
            try:
                self.tree.destroy()
            except Exception:
                pass
            self.tree = ttk.Treeview(tree_container, columns=cols, show='headings', height=20, style='Patient.Treeview')
            for c in cols:
                self.tree.heading(c, text=c, anchor='w')
                self.tree.column(c, width=120, anchor='w')
            self.tree.bind('<Double-1>', self.open_patient_window)
            # Ensure selected row is readable across themes by applying a 'sel' tag
            try:
                self.tree.tag_configure('sel', background='#1f5a78', foreground='white')
                def _main_tree_sel(evt):
                    tr = evt.widget
                    try:
                        for iid in tr.get_children(''):
                            tr.tag_remove('sel', iid)
                    except Exception:
                        pass
                    try:
                        for s in tr.selection():
                            tr.tag_add('sel', s)
                    except Exception:
                        pass
                self.tree.bind('<<TreeviewSelect>>', _main_tree_sel)
            except Exception:
                pass
        except Exception:
            pass
        # put tree on top of canvas
        self.tree.grid(row=0, column=0, sticky='nsew')
        tree_container.rowconfigure(0, weight=1)
        tree_container.columnconfigure(0, weight=1)
        # ensure canvas is below the tree
        try:
            grid_canvas.lower(self.tree)
        except Exception:
            pass

        # draw grid lines: vertical lines at column boundaries and horizontal lines after each row
        def draw_tree_grid():
            try:
                grid_canvas.delete('gridline')
                w = tree_container.winfo_width()
                h = tree_container.winfo_height()
                if w <= 0 or h <= 0:
                    return
                # vertical lines: compute cumulative column widths
                x = 0
                for col in ('Title','Name','Age','Mobile','Address'):
                    width = int(self.tree.column(col, option='width') or 0)
                    x += width
                    # draw vertical separator
                    grid_canvas.create_line(x, 0, x, h, fill='#d0d0d0', tags='gridline')

                # horizontal lines: after each visible item's bbox
                for iid in self.tree.get_children(''):
                    bbox = self.tree.bbox(iid)
                    if not bbox:
                        continue
                    y = bbox[1] + bbox[3]
                    # draw a clear separator line after each row (slightly inset and thicker)
                    try:
                        grid_canvas.create_line(6, y, max(w-6, 0), y, fill='#a9a9a9', width=2, tags='gridline')
                    except Exception:
                        grid_canvas.create_line(0, y, w, y, fill='#d0d0d0', tags='gridline')
            except Exception:
                pass

        # bind redraw on resize and exposure; also schedule periodic refresh to handle scrolling
        self.tree.bind('<Configure>', lambda e: draw_tree_grid())
        self.tree.bind('<Expose>', lambda e: draw_tree_grid())
        tree_container.bind('<Configure>', lambda e: draw_tree_grid())
        # periodic refresh
        def periodic():
            try:
                draw_tree_grid()
            finally:
                self.after(400, periodic)
        self.after(400, periodic)

        # Developer credit footer
        try:
            self.developer_info = f"RASHID OSMANI MOHAMMAD — SOFTWARE DEVELOPER   v{APP_VERSION}"
            footer = ttk.Frame(self, padding=(4,2))
            footer.pack(fill=tk.X, side=tk.BOTTOM)
            # make developer credit bold and slightly larger for emphasis
            dev_label = ttk.Label(footer, text=self.developer_info, font=('TkDefaultFont', 11, 'bold'), foreground='#222222')
            # center the developer credit in the footer
            dev_label.pack(anchor='center', pady=4)
        except Exception:
            pass

        # initialize clinic-specific file paths and load persisted data
        # attempt to auto-import a medicines.csv placed on Desktop or app folder
        try:
            res = _auto_import_medicines_from_common_locations()
            try:
                if res:
                    messagebox.showinfo('Import', f"Auto-imported medicines from {res.get('src')} — added {res.get('added')} new, updated {res.get('updated')}")
            except Exception:
                pass
        except Exception:
            pass

        try:
            self.change_clinic(self.clinic_var.get())
        except Exception:
            # fallback: set default clinic files directly
            try:
                self.change_clinic(self.clinics[0])
            except Exception:
                pass

        # Schedule update check shortly after startup (non-blocking)
        try:
            self.after(2500, lambda: self.check_for_updates(show_prompt=False))
        except Exception:
            pass

        # keep marquee text static (no scrolling)
        try:
            # ensure marquee_var exists and contains the full clinic text
            if not hasattr(self, 'marquee_var'):
                self.marquee_var = tk.StringVar(value='  TAJ HOMEO CLINIC  DR FAQRUDDIN FAKHIR  ')
            else:
                self.marquee_var.set('  TAJ HOMEO CLINIC  DR FAQRUDDIN FAKHIR  ')
            # ensure any running marquee is stopped
            try:
                self.marquee_running = False
                if hasattr(self, 'marquee_after_id') and self.marquee_after_id:
                    try:
                        self.after_cancel(self.marquee_after_id)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass

        # Bind app close handler and prompt for starting a shift shortly after startup
        try:
            try:
                self.protocol("WM_DELETE_WINDOW", self._on_app_close)
            except Exception:
                pass
            try:
                self.after(300, self._prompt_start_shift_if_needed)
            except Exception:
                pass
        except Exception:
            pass

    def maximize_window(self, win):
        """Attempt to maximize a Toplevel or root window on the current platform.

        Uses the most compatible approaches for Windows/Linux/macOS.
        """
        # Prefer using the Windows workarea so the window does not overlap the taskbar.
        try:
            left, top, right, bottom = 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()
            try:
                if ctypes is not None and wintypes is not None:
                    rect = wintypes.RECT()
                    SPI_GETWORKAREA = 0x0030
                    res = ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
                    if res:
                        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
            except Exception:
                pass
            # use exact workarea height minus a 3cm offset on Windows so the window
            # remains slightly above the taskbar.
            try:
                margin = _bottom_offset_pixels(3.0)
            except Exception:
                margin = 0
            w = max(100, right - left)
            h = max(100, (bottom - top) - margin)
            win.geometry(f"{w}x{h}+{left}+{top}")
            try:
                win.update_idletasks()
            except Exception:
                pass
            try:
                win.minsize(w, h)
            except Exception:
                pass
            return
        except Exception:
            pass
        # Fallback: try zoomed state (some platforms accept it)
        try:
            win.state('zoomed')
            return
        except Exception:
            pass

    def make_modal(self, win, parent=None):
        """Make `win` a modal dialog relative to `parent` (or self).

        Sets transient, grabs input and focuses the dialog. Ensures grab is
        released when the window is closed.
        """
        try:
            par = parent or self
            try:
                win.transient(par)
            except Exception:
                pass
            try:
                win.grab_set()
            except Exception:
                pass
            try:
                win.focus_force()
            except Exception:
                pass

            def _on_close():
                try:
                    win.grab_release()
                except Exception:
                    pass
                try:
                    win.destroy()
                except Exception:
                    pass

            try:
                win.protocol('WM_DELETE_WINDOW', _on_close)
            except Exception:
                pass
        except Exception:
            pass
        try:
            # Some X11/ttk builds accept -zoomed attribute
            win.attributes('-zoomed', True)
            return
        except Exception:
            pass
            try:
                # Fallback: use workarea so we don't cover the taskbar on Windows
                left, top, right, bottom = 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()
                try:
                    if ctypes is not None and wintypes is not None:
                        rect = wintypes.RECT()
                        SPI_GETWORKAREA = 0x0030
                        res = ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
                        if res:
                            left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
                except Exception:
                    pass
                try:
                    margin = max(80, int(win.winfo_screenheight() * 0.05))
                except Exception:
                    margin = 80
                w = max(100, right - left)
                h = max(100, (bottom - top) - margin)
                win.geometry(f"{w}x{h}+{left}+{top}")
            except Exception:
                pass
        except Exception:
            pass

    def _close_all_child_toplevels(self):
        """Destroy all Toplevel windows except the main application window."""
        try:
            # Query Tcl for children of the root window
            names = []
            try:
                out = self.tk.eval('winfo children .')
                if out:
                    names = out.split()
            except Exception:
                names = []
            for n in names:
                try:
                    w = self.nametowidget(n)
                    if isinstance(w, tk.Toplevel) and w is not self:
                        try:
                            w.destroy()
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

    def _update_order_badge(self):
        try:
            if hasattr(self, 'order_button') and self.order_button:
                if getattr(self, 'order_unread', 0):
                    self.order_button.config(text=f"Order List ({self.order_unread})")
                else:
                    self.order_button.config(text='Order List')
        except Exception:
            pass

    # --- Shift helpers and app lifecycle hooks ------------------------------
    def _read_shifts_file(self):
        """Read SHIFTS_FILE and return list of rows for current clinic."""
        rows = []
        if not os.path.exists(SHIFTS_FILE):
            return rows
        try:
            with open(SHIFTS_FILE, 'r', newline='', encoding='utf-8') as f:
                rdr = csv.DictReader(f)
                fnames = rdr.fieldnames or []
                has_clinic_field = any((n or '').strip().lower() == 'clinic' for n in fnames)
                for r in rdr:
                    if has_clinic_field:
                        clinic_val = (r.get('Clinic') or '').strip()
                        if clinic_val == getattr(self, 'current_clinic', '') or clinic_val == '':
                            rows.append(r)
                    else:
                        rows.append(r)
        except Exception:
            return []
        return rows

    def start_shift(self, operator=None, notes=None):
        """Start a new shift and record a Marker (current visit-row-count).

        Returns ShiftID on success, None on failure.
        """
        op = (operator or 'Dr.Fakhir')
        notes = (notes or datetime.today().strftime('%Y-%m-%d'))
        sid = str(uuid.uuid4())
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # compute current visit count as marker
        try:
            visit_count = 0
            if os.path.exists(VISITS_FILE):
                with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as vf:
                    vr = csv.DictReader(vf)
                    for _ in vr:
                        visit_count += 1
        except Exception:
            visit_count = 0
        first = not os.path.exists(SHIFTS_FILE)
        try:
            with open(SHIFTS_FILE, 'a', newline='', encoding='utf-8') as f:
                    fieldnames = ['ShiftID','Operator','Start','End','Notes','Marker','EndMarker','Clinic']
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    if first:
                        w.writeheader()
                    w.writerow({'ShiftID': sid, 'Operator': op, 'Start': now, 'End': '', 'Notes': notes, 'Marker': str(visit_count), 'EndMarker': '', 'Clinic': getattr(self, 'current_clinic', '')})
            return sid
        except Exception:
            return None

    def end_all_open_shifts(self):
        """Set End to now for all open shifts for current clinic. Returns number ended."""
        if not os.path.exists(SHIFTS_FILE):
            return 0
        try:
            with open(SHIFTS_FILE, 'r', newline='', encoding='utf-8') as f:
                rdr = csv.DictReader(f)
                rows = list(rdr)
                fieldnames = rdr.fieldnames or []
            changed = 0
            for r in rows:
                clinic_val = (r.get('Clinic') or '').strip()
                if clinic_val != getattr(self, 'current_clinic', '') and clinic_val != '':
                    continue
                if not (r.get('End') or '').strip():
                    r['End'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    # record end-marker as visit count at the time of closing
                    try:
                        end_count = 0
                        if os.path.exists(VISITS_FILE):
                            with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as vf:
                                vr = csv.DictReader(vf)
                                for _ in vr:
                                    end_count += 1
                        r['EndMarker'] = str(end_count)
                    except Exception:
                        r['EndMarker'] = r.get('EndMarker','')
                    changed += 1
            if changed:
                # ensure Marker and EndMarker present in header
                out_fields = ['ShiftID','Operator','Start','End','Notes','Marker','EndMarker','Clinic']
                with open(SHIFTS_FILE, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=out_fields)
                    w.writeheader()
                    for r in rows:
                        out = {k: r.get(k, '') for k in out_fields}
                        w.writerow(out)
            return changed
        except Exception:
            return 0

    def _prompt_start_shift_if_needed(self):
        """On app start: if there's no open shift for current clinic, ask to start one."""
        try:
            shifts = self._read_shifts_file()
            open_exists = any((not (r.get('End') or '').strip()) for r in shifts)
            if not open_exists:
                ans = messagebox.askyesno('Start Shift', 'No active shift found. Start shift now?')
                if ans:
                    self.start_shift()
        except Exception:
            pass

    def _on_app_close(self):
        """Handle app close: notify about open shifts and optionally end them."""
        try:
            shifts = self._read_shifts_file()
            open_shifts = [r for r in shifts if not (r.get('End') or '').strip()]
            if open_shifts:
                res = messagebox.askyesnocancel('Open Shifts', 'There are open shifts. End them and close?\nYes = End and close, No = Close without ending, Cancel = Abort')
                if res is None:
                    return
                if res is True:
                    self.end_all_open_shifts()
                    try:
                        self.destroy()
                    except Exception:
                        pass
                    return
                if res is False:
                    try:
                        self.destroy()
                    except Exception:
                        pass
                    return
            # no open shifts, just close
            try:
                self.destroy()
            except Exception:
                pass
        except Exception:
            try:
                self.destroy()
            except Exception:
                pass

    def open_help(self):
        """Show detailed help describing what each toolbar button does."""
        try:
            top = tk.Toplevel(self)
            top.title('Application Help')
            try:
                top.geometry('720x520')
            except Exception:
                pass
            frm = ttk.Frame(top, padding=8)
            frm.pack(fill=tk.BOTH, expand=True)

            # compute font: use Times New Roman with size = TkDefaultFont.size + 2
            try:
                default_font = tkfont.nametofont('TkDefaultFont')
                fsize = int(default_font.cget('size') or 10) + 2
            except Exception:
                fsize = 12
            help_font = ('Times New Roman', fsize)
            txt = tk.Text(frm, wrap='word', state='normal', font=help_font)
            txt.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
            sb = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=txt.yview)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            txt.configure(yscrollcommand=sb.set)

            help_items = [
                ('Search', 'Search patients by Name. Type a name and click Search to filter the patient list.'),
                ('Clear', 'Clear the current search filter and show all patients.'),
                ('Payments', 'Open payments summary window to view and manage received payments.'),
                ('Add Invoice', 'Create a new supplier invoice (for stock purchases).'),
                ('View Invoices', 'View and search previously recorded invoices.'),
                ('Add Patient', 'Open a dialog to add a new patient for the current clinic.'),
                ('Edit Patient', 'Edit the selected patient in the main list.'),
                ('Import Data', 'Import CSV files (single file or a folder) for patients, medicines, visits, invoices, suppliers, stock adjustments, and shifts.'),
                ('Export Data', 'Export selected or all CSV files for backup or transfer to another device.'),
                ('Inventory', 'Open inventory screen to view and edit per-clinic medicine quantities.'),
                ('Stock Adj', 'Record stock adjustments (additions, sales, corrections) to keep inventory accurate.'),
                ('Suppliers', 'Manage supplier records and contacts.'),
                ('Order List', 'Shows medicines with low stock; you can edit suggested order quantities and confirm orders.'),
                ('Shifts', 'Open Shift History: start/end shifts and view summaries for visits, payments and stockouts.'),
                ('Help', 'Open this help dialog with descriptions of app buttons and workflows.')
            ]

            txt.insert(tk.END, 'Taj Homeo — Quick Help\n\n')
            txt.insert(tk.END, 'How to use the main toolbar and common workflows:\n\n')
            for title, desc in help_items:
                txt.insert(tk.END, f"{title}:\n")
                txt.insert(tk.END, f"  {desc}\n\n")

            txt.insert(tk.END, 'Notes:\n')
            txt.insert(tk.END, ' - Shifts: start a shift when the doctor arrives. The app will record only visits created after the shift start.\n')
            txt.insert(tk.END, ' - Inventory & Order List: when a medicine quantity falls below its reorder level, it appears in the Order List and a non-blocking notification is shown.\n')
            txt.insert(tk.END, ' - Security: Payments require a PIN; use the Forgot flow to reset via security questions. Answers are case-sensitive.\n')
            txt.insert(tk.END, '\nCredits: Developed by Rashid Osmani Mohammad (Software Developer)\n')

            txt.configure(state='disabled')

            btns = ttk.Frame(top, padding=6)
            btns.pack(fill=tk.X)
            ttk.Button(btns, text='Close', command=top.destroy).pack(side=tk.RIGHT)
        except Exception:
            try:
                messagebox.showinfo('Help', 'Open the README or contact support for help.')
            except Exception:
                pass

    def _refresh_order_view(self):
        """Refresh the open Order List window/tree to reflect current medicine quantities."""
        try:
            if not hasattr(self, 'order_top') or not self.order_top:
                return
            # if there's no tree (message shown), reopen the list contents
            tree = getattr(self, 'order_tree', None)
            # recompute low-stock list
            low = []
            for m in self.medicines:
                qraw = (m.get('Quantity') or '').strip()
                try:
                    qv = float(qraw) if qraw != '' else 0.0
                except Exception:
                    qv = 0.0
                if qv <= 3:
                    desired_raw = (m.get('ReorderLevel') or '').strip()
                    try:
                        desired = int(float(desired_raw)) if desired_raw != '' else 30
                    except Exception:
                        desired = 30
                    try:
                        cur_int = int(qv)
                    except Exception:
                        cur_int = int(float(qv)) if qv else 0
                    suggested = max(desired - cur_int, 1)
                    low.append((m, qv, suggested))
            low.sort(key=lambda t: t[1])
            # if tree missing, create a fresh order list view by closing and reopening
            if tree is None:
                try:
                    # close current order window and reopen
                    self.order_top.destroy()
                    self.order_top = None
                except Exception:
                    pass
                return
            # update tree rows: ensure items present for low meds and removed otherwise
            present_ids = set(tree.get_children())
            new_ids = set()
            for m, qv, suggested in low:
                mid = m.get('MedicineID','')
                new_ids.add(mid)
                qty_display = (f"{qv:.0f}" if float(qv).is_integer() else f"{qv}")
                vals = (m.get('Name',''), m.get('Supplier',''), qty_display, m.get('ReorderLevel',''), str(suggested), m.get('Notes',''))
                if mid in present_ids:
                    # update values
                    try:
                        tree.item(mid, values=vals)
                    except Exception:
                        pass
                else:
                    try:
                        tree.insert('', tk.END, iid=mid, values=vals)
                    except Exception:
                        pass
            # remove rows no longer low
            for iid in list(present_ids):
                if iid not in new_ids:
                    try:
                        tree.delete(iid)
                    except Exception:
                        pass
            # update count label if present
            try:
                if hasattr(self, 'order_count_label') and self.order_count_label:
                    self.order_count_label.config(text=f"Items to order: {len(low)}")
            except Exception:
                pass
        except Exception:
            pass

    # --- Marquee banner ---
    def start_marquee(self, text='  TAJ HOMEO CLINIC  DR FAQRUDDIN FAKHIR  ', delay=150):
        """Start a simple marquee banner at top of the main window.

        `text` is the message to scroll; `delay` is milliseconds between steps.
        """
        try:
            self.marquee_text = text
            self.marquee_delay = int(delay)
            # create the marquee variables if not present
            if not hasattr(self, 'marquee_var'):
                self.marquee_var = tk.StringVar(value=self.marquee_text)
            else:
                self.marquee_var.set(self.marquee_text)
            self.marquee_running = True
            # start animation
            def _step():
                if not getattr(self, 'marquee_running', False):
                    return
                s = self.marquee_var.get()
                if not s:
                    s = self.marquee_text
                # rotate left by one char
                s = s[1:] + s[0]
                try:
                    self.marquee_var.set(s)
                except Exception:
                    pass
                try:
                    self.marquee_after_id = self.after(self.marquee_delay, _step)
                except Exception:
                    # ignore if window closing
                    pass
            # cancel previous if any
            try:
                if hasattr(self, 'marquee_after_id') and self.marquee_after_id:
                    self.after_cancel(self.marquee_after_id)
            except Exception:
                pass
            _step()
        except Exception:
            pass

    def stop_marquee(self):
        try:
            self.marquee_running = False
            if hasattr(self, 'marquee_after_id') and self.marquee_after_id:
                self.after_cancel(self.marquee_after_id)
        except Exception:
            pass

    def _parse_version(self, v):
        """Parse a version string like '1.23' into a tuple of ints (1,23)."""
        try:
            parts = str(v).strip().split('.')
            return tuple(int(p) for p in parts)
        except Exception:
            # fallback: treat non-numeric as 0
            nums = re.findall(r'\d+', str(v))
            if nums:
                return tuple(int(n) for n in nums)
            return (0,)

    def _is_remote_newer(self, remote_v, local_v):
        try:
            r = self._parse_version(remote_v)
            l = self._parse_version(local_v)
            return r > l
        except Exception:
            return False

    def _download_file(self, url, dst_path, progress_cb=None, timeout=30):
        try:
            import urllib.request
            import shutil
            req = urllib.request.Request(url, headers={'User-Agent':'TajHomeoUpdater/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # stream to file
                with open(dst_path, 'wb') as out:
                    shutil.copyfileobj(resp, out)
            return True
        except Exception:
            return False

    def _sha256_of_file(self, path):
        try:
            import hashlib
            h = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def _miffi24_of_file(self, path):
        """Compute a MIFFI24 checksum for a file.

        MIFFI24 is implemented here as the lower 24 bits of the CRC32
        (hex, zero-padded to 6 characters). This provides a compact
        24-bit checksum suitable for quick verification. If you have a
        different MIFFI24 specification, replace this implementation.
        """
        try:
            import zlib
            h = 0
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h = zlib.crc32(chunk, h)
            v = h & 0xFFFFFF
            return format(v, '06x')
        except Exception:
            return None

    def download_and_apply_update(self, download_url, expected_hash=None, hash_type='sha256'):
        """Download the new EXE to a temp file, verify the provided hash
        (supports 'sha256' and 'miffi24'), create a small batch updater to
        atomically replace the running EXE, launch the batch detached and
        exit the app so the batch can replace the file. This uses only
        Windows shell commands (cmd) so no external binary is required.
        """
        try:
            import tempfile, os, sys, subprocess
            tmp = tempfile.gettempdir()
            new_name = os.path.join(tmp, f"TajHomeoApp_new.exe")
            ok = self._download_file(download_url, new_name)
            if not ok:
                messagebox.showerror('Update', 'Failed to download update.')
                return False
            if expected_hash:
                got = None
                if str(hash_type).lower() in ('sha256','sha-256','sha'):
                    got = self._sha256_of_file(new_name)
                elif str(hash_type).lower() in ('miffi24','miffi-24'):
                    got = self._miffi24_of_file(new_name)
                else:
                    # unknown hash type: attempt sha256 by default
                    got = self._sha256_of_file(new_name)
                if not got or got.lower() != str(expected_hash).strip().lower():
                    try:
                        os.remove(new_name)
                    except Exception:
                        pass
                    messagebox.showerror('Update', 'Downloaded file failed checksum verification.')
                    return False

            # Determine running EXE path
            if getattr(sys, 'frozen', False):
                running_exe = sys.executable
            else:
                # running from source: just inform user where file is
                messagebox.showinfo('Update', f'Update downloaded to: {new_name}\nYou are running from source; replace files manually.')
                return True

            running_exe = os.path.abspath(running_exe)
            backup = running_exe + '.bak'
            # Create batch script to wait for app to exit, replace EXE, restart app
            batch_path = os.path.join(tmp, 'taj_update.cmd')
            # Use simple loop with tasklist to detect running process
            proc_name = os.path.basename(running_exe)
            batch_lines = []
            batch_lines.append('@echo off')
            batch_lines.append('setlocal')
            batch_lines.append(f'set NEW="{new_name}"')
            batch_lines.append(f'set OLD="{running_exe}"')
            batch_lines.append(f'set BAK="{backup}"')
            batch_lines.append(':waitloop')
            batch_lines.append(f'tasklist /FI "IMAGENAME eq {proc_name}" | findstr /I "{proc_name}" >nul')
            batch_lines.append('if %errorlevel%==0 (')
            batch_lines.append('  timeout /t 1 /nobreak >nul')
            batch_lines.append('  goto waitloop')
            batch_lines.append(')')
            batch_lines.append('rem backup old exe')
            batch_lines.append('if exist %OLD% copy /Y %OLD% %BAK% >nul 2>&1')
            batch_lines.append('rem replace')
            batch_lines.append('move /Y %NEW% %OLD% >nul 2>&1')
            batch_lines.append('rem restart')
            batch_lines.append(f'start "" %OLD%')
            batch_lines.append('endlocal')
            batch_lines.append('del "%~f0"')
            try:
                with open(batch_path, 'w', encoding='utf-8') as bf:
                    bf.write('\r\n'.join(batch_lines))
            except Exception:
                messagebox.showerror('Update', 'Failed to create updater script.')
                return False

            # Launch the batch detached using cmd start so it runs independently
            try:
                subprocess.Popen(['cmd', '/c', 'start', '', batch_path], close_fds=True)
            except Exception:
                try:
                    # fallback: run without start
                    subprocess.Popen(['cmd', '/c', batch_path], close_fds=True)
                except Exception:
                    messagebox.showerror('Update', 'Failed to launch updater.')
                    return False

            # Exit the app to allow the updater to replace the EXE
            try:
                self.destroy()
            except Exception:
                pass
            try:
                sys.exit(0)
            except Exception:
                os._exit(0)
        except Exception:
            messagebox.showerror('Update', 'Unexpected error during update.')
            return False

    def check_for_updates(self, show_prompt=False):
        """Check UPDATE_METADATA_URL for a newer version. If show_prompt True, prompt user.
        If a newer version is found, offer to open the download URL in the browser.
        """
        if not UPDATE_METADATA_URL:
            return False
        try:
            import json, urllib.request, webbrowser
            req = urllib.request.Request(UPDATE_METADATA_URL, headers={'User-Agent':'TajHomeoUpdater/1.0'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
            try:
                meta = json.loads(data.decode('utf-8'))
            except Exception:
                meta = None
            if not meta:
                return False
            remote_version = meta.get('version') or meta.get('ver') or ''
            download_url = meta.get('url') or meta.get('download') or ''
            if not remote_version or not download_url:
                return False
            if self._is_remote_newer(remote_version, APP_VERSION):
                msg = f"A new version ({remote_version}) is available.\n\nCurrent: {APP_VERSION}\nDo you want to download and install it now?"
                if show_prompt:
                    if messagebox.askyesno('Update Available', msg):
                        # proceed to download and attempt in-app update
                        try:
                            # ask for confirmation to download+install
                            do_install = messagebox.askyesno('Install Update', 'Download update and replace application now? The app will close during install.')
                            if do_install:
                                # perform download and apply (runs external updater batch)
                                # prefer MIFFI24 if provided in metadata, otherwise fall back to sha256
                                hash_value = None
                                hash_type = 'sha256'
                                if meta.get('miffi24'):
                                    hash_value = meta.get('miffi24')
                                    hash_type = 'miffi24'
                                else:
                                    hash_value = meta.get('sha256') or meta.get('sha')
                                    hash_type = 'sha256'
                                self.download_and_apply_update(download_url, expected_hash=hash_value, hash_type=hash_type)
                        except Exception:
                            try:
                                webbrowser.open(download_url)
                            except Exception:
                                try:
                                    messagebox.showinfo('Update', f'Please visit: {download_url}')
                                except Exception:
                                    pass
                else:
                    # silent notification (non-blocking popup)
                    try:
                        self.after(100, lambda: messagebox.showinfo('Update Available', f"New version {remote_version} available. Use 'Check Updates' to download/install."))
                    except Exception:
                        pass
                return True
            else:
                if show_prompt:
                    try:
                        messagebox.showinfo('Up to date', f'Your app is up to date (v{APP_VERSION}).')
                    except Exception:
                        pass
                return False
        except Exception:
            if show_prompt:
                try:
                    messagebox.showwarning('Update Check Failed', 'Failed to check for updates (network or server error).')
                except Exception:
                    pass
            return False


    def refresh_tree(self, rows=None):
        """Clear the tree and load rows. If rows is None, load from self.patients."""
        for i in self.tree.get_children():
            self.tree.delete(i)
        # If the app is configured to require a search before showing patients,
        # and no explicit rows were passed, do not populate the tree.
        if getattr(self, 'require_search_before_show', False) and rows is None:
            return
        source = rows if rows is not None else self.patients
        for r in source:
            # expect r to be [title, name, age, address, mobile] or [title,name,age,mobile,address]
            # our in-memory format: [title, name, age, address, mobile]
            try:
                self.tree.insert("", tk.END, values=(r[0], r[1], r[2], r[4] if len(r) > 4 else '', r[3] if len(r) > 3 else ''))
            except Exception:
                # fallback for older formats
                vals = tuple(r[:5])
                self.tree.insert("", tk.END, values=vals)
        try:
            # after populating, adjust column widths to fit contents
            self._adjust_main_tree_columns()
        except Exception:
            pass

    def clear_form(self):
        self.title_var.set("MR")
        self.name_var.set("")
        self.age_var.set("")
        self.mobile_var.set("")
        self.address_txt.delete("1.0", tk.END)

    def validate(self, title, name, age, address):
        if not name.strip():
            messagebox.showwarning("Validation", "Please enter the patient's name.")
            return False
        if not age.strip():
            messagebox.showwarning("Validation", "Please enter the patient's age.")
            return False
        try:
            a = int(age)
            if a < 0 or a > 150:
                messagebox.showwarning("Validation", "Please enter a realistic age.")
                return False
        except ValueError:
            messagebox.showwarning("Validation", "Age must be a number.")
            return False
        return True

    def _adjust_main_tree_columns(self):
        """Auto-fit main patient tree columns to their content and headers.

        Measures text width using the app font and sets column widths with padding.
        """
        try:
            cols = self.tree['columns']
            # choose a font for measurement: treeview uses TkDefaultFont or the global option
            try:
                f = tkfont.nametofont('TkDefaultFont')
            except Exception:
                f = tkfont.Font(family='Arial', size=18)
            pad = 16
            for col in cols:
                # header text
                try:
                    hdr = self.tree.heading(col).get('text') or str(col)
                except Exception:
                    hdr = str(col)
                max_w = f.measure(str(hdr))
                # check every row
                try:
                    for iid in self.tree.get_children(''):
                        cell = self.tree.set(iid, col) or ''
                        w = f.measure(str(cell))
                        if w > max_w:
                            max_w = w
                except Exception:
                    pass
                # set width with padding
                try:
                    self.tree.column(col, width=max(80, max_w + pad))
                except Exception:
                    pass
        except Exception:
            pass

    def save_patient(self):
        title = self.title_var.get()
        name = self.name_var.get().strip()
        age = self.age_var.get().strip()
        address = self.address_txt.get("1.0", tk.END).strip()
        mobile = self.mobile_var.get().strip()

        if not self.validate(title, name, age, address):
            return

        # Append to CSV
        first_write = not os.path.exists(DATA_FILE)
        try:
            with open(DATA_FILE, "a", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                if first_write:
                    writer.writerow(["Title", "Name", "Age", "Address", "Mobile"])
                writer.writerow([title, name, age, address, mobile])
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save patient: {e}")
            return

        messagebox.showinfo("Saved", "Patient saved successfully.")
        # update in-memory list and refresh
        self.patients.append([title, name, age, address, mobile])
        self.refresh_tree()
        self.clear_form()

    def open_add_patient(self):
        """Open a dialog to add a patient for the current clinic.

        This writes to `DATA_FILE` (which is clinic-aware via `change_clinic`) and
        updates the in-memory `self.patients` then refreshes the main tree.
        """
        top = tk.Toplevel(self)
        # ensure the shift window is above the main window and dialogs are parented to it
        try:
            top.transient(self)
            top.lift()
        except Exception:
            pass
        self.maximize_window(top)
        self.maximize_window(top)
        top.transient(self)
        top.title('Add Patient')
        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text='Title:', style='FormLabel.TLabel').grid(row=0, column=0, sticky='w')
        title_var = tk.StringVar(value='MR')
        ttk.Combobox(frm, textvariable=title_var, values=('MR','MRS','MISS','DR'), width=8, state='readonly', font=('TkDefaultFont', 10)).grid(row=0, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frm, text='Name:', style='FormLabel.TLabel').grid(row=1, column=0, sticky='w')
        name_var = tk.StringVar()
        ttk.Entry(frm, textvariable=name_var, width=36, font=('TkDefaultFont', 10)).grid(row=1, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frm, text='Age:', style='FormLabel.TLabel').grid(row=2, column=0, sticky='w')
        age_var = tk.StringVar()
        ttk.Entry(frm, textvariable=age_var, width=10, font=('TkDefaultFont', 10)).grid(row=2, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frm, text='Mobile:', style='FormLabel.TLabel').grid(row=3, column=0, sticky='w')
        mobile_var = tk.StringVar()
        ttk.Entry(frm, textvariable=mobile_var, width=20, font=('TkDefaultFont', 10)).grid(row=3, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frm, text='Address:', style='FormLabel.TLabel').grid(row=4, column=0, sticky='nw')
        addr_txt = tk.Text(frm, width=36, height=4, font=('TkDefaultFont', 10))
        addr_txt.grid(row=4, column=1, sticky='w', padx=6, pady=4)

        def do_save():
            title = (title_var.get() or '').strip()
            name = (name_var.get() or '').strip()
            age = (age_var.get() or '').strip()
            mobile = (mobile_var.get() or '').strip()
            address = addr_txt.get('1.0', tk.END).strip()
            # validate using existing validate helper
            if not self.validate(title, name, age, address):
                return
            # append to clinic DATA_FILE
            first_write = not os.path.exists(DATA_FILE)
            try:
                with open(DATA_FILE, 'a', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    if first_write:
                        w.writerow(["Title","Name","Age","Address","Mobile"])
                    w.writerow([title, name, age, address, mobile])
            except Exception as e:
                messagebox.showerror('Save Error', f'Failed to save patient: {e}')
                return
            # update in-memory and UI
            self.patients.append([title, name, age, address, mobile])
            try:
                self.refresh_tree()
            except Exception:
                pass
            messagebox.showinfo('Saved','Patient saved successfully.')
            try:
                self._close_all_child_toplevels()
            except Exception:
                try:
                    top.destroy()
                except Exception:
                    pass

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text='Save', command=do_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Cancel', command=top.destroy).pack(side=tk.LEFT, padx=6)

    def add_tree_item(self, row):
        self.tree.insert("", tk.END, values=row)

    def delete_selected_patient(self):
        """Delete the currently selected patient from the current clinic file (or other clinic file if needed)."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Delete Patient', 'Please select a patient to delete.')
            return
        item = sel[0]
        vals = self.tree.item(item, 'values')
        if not vals or len(vals) < 2:
            messagebox.showerror('Delete Patient', 'Invalid selection.')
            return
        if not messagebox.askyesno('Confirm', f"Delete patient {vals[0]} {vals[1]}?"):
            return

        # Try to remove from in-memory current-clinic list first
        removed = False
        try:
            new_list = []
            for p in (self.patients or []):
                try:
                    if len(p) >= 5 and p[0] == vals[0] and p[1] == vals[1] and str(p[2]) == str(vals[2]) and (p[4] == vals[3]) and (p[3] == vals[4]):
                        removed = True
                        continue
                except Exception:
                    pass
                new_list.append(p)
            if removed:
                self.patients = new_list
                # rewrite DATA_FILE
                try:
                    with open(DATA_FILE, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow(['Title','Name','Age','Address','Mobile'])
                        for r in self.patients:
                            w.writerow([r[0], r[1], r[2], r[3] if len(r)>3 else '', r[4] if len(r)>4 else ''])
                except Exception as e:
                    messagebox.showerror('Delete','Failed to update patients file: ' + str(e))
                    return
                self.refresh_tree()
                messagebox.showinfo('Deleted','Patient removed successfully')
                return
        except Exception:
            pass

        # If not found in current clinic list, attempt to delete from another clinic file using clinic tag in Address
        try:
            addr_field = vals[4] if len(vals) > 4 else ''
            m = re.search(r'\[([^\]]+)\]$', addr_field)
            clinic_tag = m.group(1) if m else None
        except Exception:
            clinic_tag = None
        if clinic_tag:
            target_path = DATA_TEMPLATE.format(clinic=clinic_tag)
            if os.path.exists(target_path):
                try:
                    with open(target_path, 'r', newline='', encoding='utf-8') as f:
                        rdr = csv.reader(f)
                        hdr = next(rdr, None)
                        rows = list(rdr)
                except Exception:
                    rows = []

                addr_plain = re.sub(r'\s*\[' + re.escape(clinic_tag) + r'\]\s*$', '', addr_field).strip()
                target_idx = None
                for ridx, row in enumerate(rows):
                    try:
                        r = list(row) + [''] * (5 - len(row))
                        if r[0] == vals[0] and r[1] == vals[1] and str(r[2]) == str(vals[2]) and (r[4] == vals[3]) and (r[3] == addr_plain):
                            target_idx = ridx
                            break
                    except Exception:
                        continue
                if target_idx is None:
                    messagebox.showerror('Delete Patient', 'Selected patient not found in clinic file.')
                    return
                try:
                    rows.pop(target_idx)
                    with open(target_path, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        if hdr:
                            w.writerow(hdr)
                        for row in rows:
                            w.writerow(row)
                    messagebox.showinfo('Deleted','Patient removed from clinic file')
                    try:
                        self.load_patients()
                        self.refresh_tree()
                    except Exception:
                        pass
                    return
                except Exception as e:
                    messagebox.showerror('Delete','Failed to delete patient: ' + str(e))
                    return

        messagebox.showerror('Delete Patient', 'Failed to locate and delete the selected patient.')

    def edit_selected_patient(self):
        """Open the selected patient in an edit dialog and save changes."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Edit Patient", "Please select a patient to edit.")
            return

        def delete_selected_patient(self):
            """Delete the currently selected patient from the current clinic file (or other clinic file if needed)."""
            sel = self.tree.selection()
            if not sel:
                messagebox.showinfo('Delete Patient', 'Please select a patient to delete.')
                return
            item = sel[0]
            vals = self.tree.item(item, 'values')
            if not vals or len(vals) < 2:
                messagebox.showerror('Delete Patient', 'Invalid selection.')
                return
            if not messagebox.askyesno('Confirm', f"Delete patient {vals[0]} {vals[1]}?"):
                return

            # Try to remove from in-memory current-clinic list first
            removed = False
            try:
                new_list = []
                for p in (self.patients or []):
                    try:
                        if len(p) >= 5 and p[0] == vals[0] and p[1] == vals[1] and str(p[2]) == str(vals[2]) and (p[4] == vals[3]) and (p[3] == vals[4]):
                            removed = True
                            continue
                    except Exception:
                        pass
                    new_list.append(p)
                if removed:
                    self.patients = new_list
                    # rewrite DATA_FILE
                    try:
                        with open(DATA_FILE, 'w', newline='', encoding='utf-8') as f:
                            w = csv.writer(f)
                            w.writerow(['Title','Name','Age','Address','Mobile'])
                            for r in self.patients:
                                w.writerow([r[0], r[1], r[2], r[3] if len(r)>3 else '', r[4] if len(r)>4 else ''])
                    except Exception as e:
                        messagebox.showerror('Delete','Failed to update patients file: ' + str(e))
                        return
                    self.refresh_tree()
                    messagebox.showinfo('Deleted','Patient removed successfully')
                    return
            except Exception:
                pass

            # If not found in current clinic list, attempt to delete from another clinic file using clinic tag in Address
            try:
                addr_field = vals[4] if len(vals) > 4 else ''
                m = re.search(r'\[([^\]]+)\]$', addr_field)
                clinic_tag = m.group(1) if m else None
            except Exception:
                clinic_tag = None
            if clinic_tag:
                target_path = DATA_TEMPLATE.format(clinic=clinic_tag)
                if os.path.exists(target_path):
                    try:
                        with open(target_path, 'r', newline='', encoding='utf-8') as f:
                            rdr = csv.reader(f)
                            hdr = next(rdr, None)
                            rows = list(rdr)
                    except Exception:
                        rows = []

                    addr_plain = re.sub(r'\s*\[' + re.escape(clinic_tag) + r'\]\s*$', '', addr_field).strip()
                    target_idx = None
                    for ridx, row in enumerate(rows):
                        try:
                            r = list(row) + [''] * (5 - len(row))
                            if r[0] == vals[0] and r[1] == vals[1] and str(r[2]) == str(vals[2]) and (r[4] == vals[3]) and (r[3] == addr_plain):
                                target_idx = ridx
                                break
                        except Exception:
                            continue
                    if target_idx is None:
                        messagebox.showerror('Delete Patient', 'Selected patient not found in clinic file.')
                        return
                    try:
                        rows.pop(target_idx)
                        with open(target_path, 'w', newline='', encoding='utf-8') as f:
                            w = csv.writer(f)
                            if hdr:
                                w.writerow(hdr)
                            for row in rows:
                                w.writerow(row)
                        messagebox.showinfo('Deleted','Patient removed from clinic file')
                        try:
                            self.load_patients()
                            self.refresh_tree()
                        except Exception:
                            pass
                        return
                    except Exception as e:
                        messagebox.showerror('Delete','Failed to delete patient: ' + str(e))
                        return

            messagebox.showerror('Delete Patient', 'Failed to locate and delete the selected patient.')
        item = sel[0]
        vals = self.tree.item(item, 'values')
        # tree values: (Title, Name, Age, Mobile, Address)
        # find the first matching patient in self.patients
        found_idx = None
        for idx, p in enumerate(self.patients):
            try:
                if len(p) >= 5 and p[0] == vals[0] and p[1] == vals[1] and str(p[2]) == str(vals[2]) and p[4] == vals[3] and p[3] == vals[4]:
                    found_idx = idx
                    break
            except Exception:
                continue

        if found_idx is None:
            # Selected patient wasn't found in in-memory current-clinic list.
            # Attempt to edit patient from other clinics if the search result included a clinic tag in the Address (e.g. "Address [KRMR]").
            try:
                addr_field = vals[4] if len(vals) > 4 else ''
                m = re.search(r'\[([^\]]+)\]$', addr_field)
                clinic_tag = m.group(1) if m else None
            except Exception:
                clinic_tag = None
            if clinic_tag:
                target_path = DATA_TEMPLATE.format(clinic=clinic_tag)
                if os.path.exists(target_path):
                    try:
                        with open(target_path, 'r', newline='', encoding='utf-8') as f:
                            rdr = csv.reader(f)
                            hdr = next(rdr, None)
                            rows = list(rdr)
                    except Exception:
                        rows = []

                    # address as stored in file won't contain the appended [CLINIC]
                    addr_plain = re.sub(r'\s*\[' + re.escape(clinic_tag) + r'\]\s*$', '', addr_field).strip()
                    target_row_idx = None
                    for ridx, row in enumerate(rows):
                        try:
                            r = list(row) + [''] * (5 - len(row))
                            if r[0] == vals[0] and r[1] == vals[1] and str(r[2]) == str(vals[2]) and (r[4] == vals[3]) and (r[3] == addr_plain):
                                target_row_idx = ridx
                                break
                        except Exception:
                            continue

                    if target_row_idx is None:
                        messagebox.showerror("Edit Patient", "Selected patient not found in data file.")
                        return

                    # Open an edit dialog similar to the in-memory edit, but operate on the file rows
                    orig = list(rows[target_row_idx]) + [''] * (5 - len(rows[target_row_idx]))

                    top = tk.Toplevel(self)
                    self.maximize_window(top)
                    top.transient(self)
                    top.title('Edit Patient')
                    frm = ttk.Frame(top, padding=8)
                    frm.pack(fill=tk.BOTH, expand=True)

                    ttk.Label(frm, text='Title:', style='FormLabel.TLabel').grid(row=0, column=0, sticky='w')
                    title_var = tk.StringVar(value=orig[0] if len(orig) > 0 else 'MR')
                    ttk.Combobox(frm, textvariable=title_var, values=('MR','MRS','MISS','DR'), width=8, state='readonly', font=('TkDefaultFont', 10)).grid(row=0, column=1, sticky='w', padx=6, pady=4)

                    ttk.Label(frm, text='Name:', style='FormLabel.TLabel').grid(row=1, column=0, sticky='w')
                    name_var = tk.StringVar(value=orig[1] if len(orig) > 1 else '')
                    ttk.Entry(frm, textvariable=name_var, width=36, font=('TkDefaultFont', 10)).grid(row=1, column=1, sticky='w', padx=6, pady=4)
                    
                    def do_delete_from_file():
                        if not messagebox.askyesno('Confirm', 'Delete this patient from file?'):
                            return
                        try:
                            # remove the target row and rewrite file
                            rows.pop(target_row_idx)
                            with open(target_path, 'w', newline='', encoding='utf-8') as f:
                                w = csv.writer(f)
                                if hdr:
                                    w.writerow(hdr)
                                for row in rows:
                                    w.writerow(row)
                            messagebox.showinfo('Deleted', 'Patient deleted from file')
                            top.destroy()
                            try:
                                self.load_patients()
                                self.refresh_tree()
                            except Exception:
                                pass
                        except Exception as e:
                            messagebox.showerror('Delete','Failed to delete patient: ' + str(e))

                    ttk.Button(frm, text='Delete from File', command=do_delete_from_file).grid(row=6, column=0, columnspan=2, pady=8)

                    ttk.Label(frm, text='Age:', style='FormLabel.TLabel').grid(row=2, column=0, sticky='w')
                    age_var = tk.StringVar(value=orig[2] if len(orig) > 2 else '')
                    ttk.Entry(frm, textvariable=age_var, width=10, font=('TkDefaultFont', 10)).grid(row=2, column=1, sticky='w', padx=6, pady=4)

                    ttk.Label(frm, text='Mobile:', style='FormLabel.TLabel').grid(row=3, column=0, sticky='w')
                    mobile_var = tk.StringVar(value=orig[4] if len(orig) > 4 else '')
                    ttk.Entry(frm, textvariable=mobile_var, width=20, font=('TkDefaultFont', 10)).grid(row=3, column=1, sticky='w', padx=6, pady=4)

                    ttk.Label(frm, text='Address:', style='FormLabel.TLabel').grid(row=4, column=0, sticky='nw')
                    addr_txt = tk.Text(frm, width=36, height=4, font=('TkDefaultFont', 10))
                    addr_txt.grid(row=4, column=1, sticky='w', padx=6, pady=4)
                    try:
                        addr_txt.insert('1.0', orig[3] if len(orig) > 3 else '')
                    except Exception:
                        pass

                    def do_save_edit_external():
                        title = (title_var.get() or '').strip()
                        name = (name_var.get() or '').strip()
                        age = (age_var.get() or '').strip()
                        mobile = (mobile_var.get() or '').strip()
                        address = addr_txt.get('1.0', tk.END).strip()
                        if not self.validate(title, name, age, address):
                            return
                        # update rows and rewrite target file
                        try:
                            rows[target_row_idx] = [title, name, age, address, mobile]
                            with open(target_path, 'w', newline='', encoding='utf-8') as f:
                                w = csv.writer(f)
                                if hdr:
                                    try:
                                        w.writerow(hdr)
                                    except Exception:
                                        pass
                                for r in rows:
                                    w.writerow(r)
                        except Exception as e:
                            messagebox.showerror('Save Error', f'Failed to update patient file: {e}')
                            return
                        try:
                            top.destroy()
                        except Exception:
                            pass
                        messagebox.showinfo('Saved', 'Patient updated successfully.')

                    btns = ttk.Frame(frm)
                    btns.grid(row=5, column=0, columnspan=2, pady=(8,0))
                    ttk.Button(btns, text='Save', command=do_save_edit_external).pack(side=tk.LEFT, padx=6)
                    ttk.Button(btns, text='Cancel', command=top.destroy).pack(side=tk.LEFT, padx=6)
                    return
            # fallback: show original error
            messagebox.showerror("Edit Patient", "Selected patient not found in data file.")
            return

        orig = self.patients[found_idx]

        top = tk.Toplevel(self)
        self.maximize_window(top)
        top.transient(self)
        top.title('Edit Patient')
        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text='Title:', style='FormLabel.TLabel').grid(row=0, column=0, sticky='w')
        title_var = tk.StringVar(value=orig[0] if len(orig) > 0 else 'MR')
        ttk.Combobox(frm, textvariable=title_var, values=('MR','MRS','MISS','DR'), width=8, state='readonly', font=('TkDefaultFont', 10)).grid(row=0, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frm, text='Name:', style='FormLabel.TLabel').grid(row=1, column=0, sticky='w')
        name_var = tk.StringVar(value=orig[1] if len(orig) > 1 else '')
        ttk.Entry(frm, textvariable=name_var, width=36, font=('TkDefaultFont', 10)).grid(row=1, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frm, text='Age:', style='FormLabel.TLabel').grid(row=2, column=0, sticky='w')
        age_var = tk.StringVar(value=orig[2] if len(orig) > 2 else '')
        ttk.Entry(frm, textvariable=age_var, width=10, font=('TkDefaultFont', 10)).grid(row=2, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frm, text='Mobile:', style='FormLabel.TLabel').grid(row=3, column=0, sticky='w')
        mobile_var = tk.StringVar(value=orig[4] if len(orig) > 4 else '')
        ttk.Entry(frm, textvariable=mobile_var, width=20, font=('TkDefaultFont', 10)).grid(row=3, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frm, text='Address:', style='FormLabel.TLabel').grid(row=4, column=0, sticky='nw')
        addr_txt = tk.Text(frm, width=36, height=4, font=('TkDefaultFont', 10))
        addr_txt.grid(row=4, column=1, sticky='w', padx=6, pady=4)
        # prefill address
        try:
            addr_txt.insert('1.0', orig[3] if len(orig) > 3 else '')
        except Exception:
            pass

        def do_save_edit():
            title = (title_var.get() or '').strip()
            name = (name_var.get() or '').strip()
            age = (age_var.get() or '').strip()
            mobile = (mobile_var.get() or '').strip()
            address = addr_txt.get('1.0', tk.END).strip()
            if not self.validate(title, name, age, address):
                return
            # update in-memory
            try:
                self.patients[found_idx] = [title, name, age, address, mobile]
            except Exception as e:
                messagebox.showerror('Edit Error', f'Failed to update in-memory record: {e}')
                return
            # rewrite CSV
            try:
                with open(DATA_FILE, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Title", "Name", "Age", "Address", "Mobile"])
                    for p in self.patients:
                        # ensure length
                        if len(p) >= 5:
                            writer.writerow([p[0], p[1], p[2], p[3], p[4]])
                        else:
                            # pad missing fields
                            row = list(p) + [''] * (5 - len(p))
                            writer.writerow(row)
            except Exception as e:
                messagebox.showerror('Save Error', f'Failed to update patient file: {e}')
                return
            try:
                self.refresh_tree()
            except Exception:
                pass
            messagebox.showinfo('Saved', 'Patient updated successfully.')
            try:
                self._close_all_child_toplevels()
            except Exception:
                try:
                    top.destroy()
                except Exception:
                    pass

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text='Save', command=do_save_edit).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Cancel', command=top.destroy).pack(side=tk.LEFT, padx=6)

    def load_patients(self):
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, "r", newline='', encoding="utf-8") as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                self.patients = []
                for r in reader:
                    # support older files with no mobile column
                    if len(r) >= 5:
                        self.patients.append([r[0], r[1], r[2], r[3], r[4]])
                    elif len(r) >= 4:
                        self.patients.append([r[0], r[1], r[2], r[3], ''])
            self.refresh_tree()
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load patients: {e}")

    def save_patients(self):
        """Write current in-memory patients to `DATA_FILE`."""
        try:
            with open(DATA_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Title", "Name", "Age", "Address", "Mobile"])
                for p in self.patients:
                    if not p:
                        continue
                    row = list(p[:5])
                    if len(row) < 5:
                        row += [''] * (5 - len(row))
                    writer.writerow(row)
            return True
        except Exception as e:
            try:
                messagebox.showerror('Save Error', f'Failed to save patients: {e}')
            except Exception:
                pass
            return False

    def import_data(self):
        """Import patient rows from selected CSV file(s) and append to current data.

        Prompts the user to import specific CSV files (choose files) or import all CSVs
        from a folder (choose folder)."""
        # ask whether user wants to import specific files (Yes) or all CSVs from folder (No)
        resp = messagebox.askyesno('Import Mode', 'Import specific CSV file(s)?\n\nYes = choose specific file(s).\nNo = select a folder and import all CSV files from it.')
        imported_files = 0
        if resp:
            paths = filedialog.askopenfilenames(title='Import CSV files', filetypes=[('CSV files','*.csv'),('All files','*.*')])
            if not paths:
                return
            sources = list(paths)
        else:
            folder = filedialog.askdirectory(title='Select folder containing CSV files to import')
            if not folder:
                return
            sources = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith('.csv')]

        # Handle each CSV: merge/append patient rows for patient files; otherwise copy into STORAGE_DIR and reload datasets.
        appended_rows = 0
        for p in sources:
            try:
                fname = os.path.basename(p)
                lcname = fname.lower()

                if lcname.startswith('patients'):
                    # Merge patient rows: read file and append rows to self.patients
                    try:
                        with open(p, 'r', newline='', encoding='utf-8') as f:
                            rdr = csv.reader(f)
                            _ = next(rdr, None)
                            for r in rdr:
                                if not r:
                                    continue
                                row = list(r)
                                if len(row) < 5:
                                    row += [''] * (5 - len(row))
                                name = (row[1] or '').strip()
                                mobile = (row[4] or '').strip()
                                # check for existing patient with same name+mobile (case-insensitive)
                                exists = False
                                try:
                                    for ex in self.patients:
                                        ex_name = (ex[1] or '').strip().lower() if len(ex) > 1 else ''
                                        ex_mobile = (ex[4] or '').strip().lower() if len(ex) > 4 else ''
                                        if ex_name == name.lower() and ex_mobile == mobile.lower():
                                            exists = True
                                            break
                                except Exception:
                                    exists = False

                                if exists:
                                    # Ask user whether to add duplicate, skip, or cancel import
                                    resp = messagebox.askyesnocancel('Duplicate', f'Patient "{name}" with mobile "{mobile}" already exists.\n\nYes = add anyway, No = skip this row, Cancel = stop importing.')
                                    if resp is None:
                                        # Cancel import
                                        raise KeyboardInterrupt('User cancelled import')
                                    if resp is False:
                                        # skip this row
                                        continue
                                    # else True -> add duplicate

                                self.patients.append([row[0], row[1], row[2], row[3], row[4]])
                                appended_rows += 1
                    except KeyboardInterrupt:
                        # user cancelled; stop processing further files
                        break
                    except Exception as e:
                        messagebox.showwarning('Import Warning', f'Failed to merge patients from {fname}: {e}')
                else:
                    # copy other CSV types into storage (overwrite)
                    dst = os.path.join(STORAGE_DIR, fname)
                    shutil.copy2(p, dst)
                    imported_files += 1
                    # reload specific datasets if present
                    try:
                        # For any imported CSV, detect Supplier/Category headers and harvest values
                        try:
                            with open(dst, 'r', newline='', encoding='utf-8') as mf:
                                rdr = csv.DictReader(mf)
                                headers = [h.lower() for h in (rdr.fieldnames or [])]
                                found_suppliers = set()
                                found_categories = set()
                                if 'supplier' in headers or 'category' in headers:
                                    for r in rdr:
                                        if 'supplier' in headers:
                                            try:
                                                s = (r.get('Supplier') or '').strip()
                                            except Exception:
                                                s = ''
                                            if s:
                                                found_suppliers.add(s)
                                        if 'category' in headers:
                                            try:
                                                c = (r.get('Category') or '').strip()
                                            except Exception:
                                                c = ''
                                            if c:
                                                found_categories.add(c)
                                # add suppliers
                                if found_suppliers:
                                    try:
                                        self.load_suppliers()
                                    except Exception:
                                        self.suppliers = []
                                    low_seen = { (s.get('Name') or '').strip().lower() for s in (self.suppliers or []) }
                                    added_any = False
                                    for nm in sorted(found_suppliers):
                                        if nm.strip().lower() not in low_seen:
                                            self.suppliers.append({'SupplierID': str(uuid.uuid4()), 'Name': nm.strip(), 'Contact': '', 'Notes': ''})
                                            added_any = True
                                    if added_any:
                                        try:
                                            self.save_suppliers()
                                        except Exception:
                                            pass
                                # add categories
                                if found_categories:
                                    try:
                                        self.load_categories()
                                    except Exception:
                                        self.categories = []
                                    low_cat = { (c or '').strip().lower() for c in (self.categories or []) }
                                    added_cat = False
                                    for c in sorted(found_categories):
                                        if c.strip().lower() not in low_cat:
                                            self.categories.append(c.strip())
                                            added_cat = True
                                    if added_cat:
                                        try:
                                            self.save_categories()
                                        except Exception:
                                            pass
                        except Exception:
                            pass
                        # special reloads
                        if lcname.startswith('medicines') and hasattr(self, 'load_medicines'):
                            try:
                                self.load_medicines()
                            except Exception:
                                pass
                        if lcname.startswith('suppliers') and hasattr(self, 'load_suppliers'):
                            self.load_suppliers()
                        # visits/invoices/etc. are read on demand from their files
                    except Exception:
                        pass
            except Exception as e:
                messagebox.showwarning('Import Warning', f'Failed to import {os.path.basename(p)}: {e}')

        if appended_rows:
            try:
                self.save_patients()
            except Exception:
                pass
            try:
                self.refresh_tree()
            except Exception:
                pass
            messagebox.showinfo('Import Complete', f'Appended {appended_rows} patient row(s).')

        if imported_files:
            messagebox.showinfo('Import Complete', f'Imported {imported_files} CSV file(s) into storage.')

    def export_data(self):
        """Export current patients or all CSVs.

        Prompts whether to export specific (current patients CSV) or export all CSV files
        from the storage directory to a destination folder."""
        resp = messagebox.askyesno('Export Mode', 'Export current patients only?\n\nYes = export current patients CSV.\nNo = export ALL CSV files from storage folder to a chosen folder.')
        if resp:
            default_name = f"patients_export_{datetime.now().strftime('%Y%m%d')}.csv"
            path = filedialog.asksaveasfilename(title='Export Patients CSV', defaultextension='.csv', filetypes=[('CSV files','*.csv')], initialfile=default_name)
            if not path:
                return
            try:
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Title", "Name", "Age", "Address", "Mobile"])
                    for p in self.patients:
                        if not p:
                            continue
                        row = list(p[:5])
                        if len(row) < 5:
                            row += [''] * (5 - len(row))
                        writer.writerow(row)
                messagebox.showinfo('Export Complete', f'Exported {len(self.patients)} records to {os.path.basename(path)}')
            except Exception as e:
                messagebox.showerror('Export Error', f'Failed to export data: {e}')
        else:
            dest = filedialog.askdirectory(title='Select destination folder to export ALL CSV files')
            if not dest:
                return
            copied = 0
            try:
                for fname in os.listdir(STORAGE_DIR):
                    if not fname.lower().endswith('.csv'):
                        continue
                    src = os.path.join(STORAGE_DIR, fname)
                    dst = os.path.join(dest, fname)
                    try:
                        shutil.copy2(src, dst)
                        copied += 1
                    except Exception:
                        pass
                messagebox.showinfo('Export Complete', f'Copied {copied} CSV files to {dest}')
            except Exception as e:
                messagebox.showerror('Export Error', f'Failed to export all CSVs: {e}')

    def load_medicines(self):
        """Load master medicines from `MED_FILE` and overlay per-clinic inventory from `INVENTORY_FILE`.

        The master `MED_FILE` holds definitions (MedicineID, Name, Supplier, Price, Notes).
        The per-clinic `INVENTORY_FILE` (set by `change_clinic`) holds per-med quantities and reorder levels
        and is used to populate the `Quantity` and `ReorderLevel` fields shown in the UI.
        """
        self.medicines = []
        # load master definitions
        try:
            if os.path.exists(MED_FILE):
                with open(MED_FILE, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    for r in rdr:
                        name = (r.get('Name') or '').strip()
                        supplier = ((r.get('Supplier') or r.get('Batch') or '')).strip()
                        mid = (r.get('MedicineID') or '').strip()
                        # generate a stable id for records missing MedicineID so Treeview iids aren't empty
                        if not mid and name:
                            try:
                                mid = str(uuid.uuid5(uuid.NAMESPACE_DNS, (name + '|' + supplier)))
                            except Exception:
                                mid = str(uuid.uuid4())
                            needs_save_back = True
                        self.medicines.append({
                            'MedicineID': mid or '',
                            'Name': name,
                            'Supplier': supplier,
                            'Price': r.get('Price','').strip(),
                            'Notes': r.get('Notes','').strip(),
                            'Category': r.get('Category','').strip(),
                            # default empty; will be overlaid from inventory file
                            'Quantity': '',
                            'ReorderLevel': r.get('ReorderLevel','').strip(),
                        })
        except Exception:
            self.medicines = []
            return

        # overlay per-clinic inventory quantities if present
        try:
            inv_map = {}
            if 'INVENTORY_FILE' in globals() and os.path.exists(INVENTORY_FILE):
                with open(INVENTORY_FILE, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    for r in rdr:
                        mid = (r.get('MedicineID') or '').strip()
                        if not mid:
                            continue
                        inv_map[mid] = {
                            'Quantity': (r.get('Quantity') or '').strip(),
                            'ReorderLevel': (r.get('ReorderLevel') or '').strip()
                        }
            # apply overlay
            for m in self.medicines:
                mid = m.get('MedicineID','')
                if mid and mid in inv_map:
                    m['Quantity'] = inv_map[mid].get('Quantity','')
                    # if inventory file provides a reorder level, prefer it
                    if inv_map[mid].get('ReorderLevel',''):
                        m['ReorderLevel'] = inv_map[mid].get('ReorderLevel','')
        except Exception:
            # non-fatal; leave quantities blank
            pass
        # Notify if loading shows items already low
        try:
            _check_low_stock_and_notify(self)
        except Exception:
            pass
        # if we generated MedicineIDs for missing rows, persist the master file so inventory overlay works
        try:
            if 'needs_save_back' in locals() and needs_save_back:
                try:
                    self.save_medicines()
                except Exception:
                    pass
        except Exception:
            pass

    def save_medicines(self):
        """Write master medicine definitions to `MED_FILE` (rewrite).

        NOTE: Quantities are saved to the per-clinic `INVENTORY_FILE`. The master
        `MED_FILE` contains definitions (MedicineID, Name, Supplier, Price, ReorderLevel, Notes).
        """
        fieldnames = ['MedicineID','Name','Supplier','Price','ReorderLevel','Notes','Category']
        try:
            with open(MED_FILE, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                for m in self.medicines:
                    # ensure Category is present for older records
                    if 'Category' not in m:
                        m['Category'] = ''
                    out = {k: m.get(k,'') for k in fieldnames}
                    w.writerow(out)
            return True
        except Exception:
            return False

    def save_inventory(self):
        """Write per-clinic inventory to `INVENTORY_FILE` (rewrite).

        Inventory rows contain: MedicineID, Quantity, ReorderLevel
        """
        try:
            if 'INVENTORY_FILE' not in globals() or not INVENTORY_FILE:
                return False
            fieldnames = ['MedicineID','Quantity','ReorderLevel']
            with open(INVENTORY_FILE, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                for m in self.medicines:
                    out = {'MedicineID': m.get('MedicineID',''), 'Quantity': m.get('Quantity',''), 'ReorderLevel': m.get('ReorderLevel','')}
                    w.writerow(out)
            # attempt to refresh any open order list so it shows exact quantities
            try:
                self._refresh_order_view()
            except Exception:
                pass
            # refresh inventory UI if open
            try:
                if hasattr(self, '_inventory_refresh') and callable(self._inventory_refresh):
                    try:
                        self._inventory_refresh()
                    except Exception:
                        pass
            except Exception:
                pass
            # after saving inventory, check for newly low items and notify
            try:
                _check_low_stock_and_notify(self)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def load_suppliers(self):
        """Load suppliers from SUPPLIERS_FILE into self.suppliers (list of dicts)."""
        self.suppliers = []
        # First, try to read suppliers file if present and dedupe by name
        if os.path.exists(SUPPLIERS_FILE):
            try:
                seen = set()
                with open(SUPPLIERS_FILE, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    for r in rdr:
                        name = (r.get('Name','') or '').strip()
                        if not name:
                            continue
                        key = name.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        self.suppliers.append({
                            'SupplierID': r.get('SupplierID','').strip() or str(uuid.uuid4()),
                            'Name': name,
                            'Contact': (r.get('Contact','') or '').strip(),
                            'Notes': (r.get('Notes','') or '').strip(),
                        })
                return
            except Exception:
                self.suppliers = []

        # Fallback: build unique supplier list from medicines
        seen = set()
        for m in self.medicines:
            name = (m.get('Supplier') or '').strip()
            if not name:
                continue
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            self.suppliers.append({'SupplierID': str(uuid.uuid4()), 'Name': name, 'Contact': '', 'Notes': ''})

    def load_categories(self):
        """Load categories from CATEGORIES_FILE into `self.categories` or derive from medicines."""
        self.categories = []
        if os.path.exists(CATEGORIES_FILE):
            try:
                seen = set()
                with open(CATEGORIES_FILE, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.reader(f)
                    for row in rdr:
                        if not row:
                            continue
                        name = (row[0] or '').strip()
                        if not name:
                            continue
                        key = name.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        self.categories.append(name)
                return
            except Exception:
                self.categories = []
        # fallback: build from medicines
        try:
            cats = sorted({(m.get('Category') or '').strip() for m in self.medicines if (m.get('Category') or '').strip()})
            self.categories = cats
        except Exception:
            self.categories = []

    def save_categories(self):
        """Persist `self.categories` to CATEGORIES_FILE (one per line)."""
        try:
            # dedupe and write
            seen = set()
            out = []
            for c in (self.categories or []):
                name = (c or '').strip()
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(name)
            with open(CATEGORIES_FILE, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                for c in out:
                    w.writerow([c])
            # keep memory representation canonical
            self.categories = out
            return True
        except Exception:
            return False

    def load_clinics(self):
        """Load known clinics from `clinics.json` if present."""
        try:
            if os.path.exists(CLINICS_FILE):
                import json
                with open(CLINICS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.clinics = data
                        return
        except Exception:
            pass

    def save_clinics(self):
        """Persist clinic list to `clinics.json`."""
        try:
            import json
            with open(CLINICS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.clinics, f)
            return True
        except Exception:
            return False

    def open_add_clinic(self):
        top = tk.Toplevel(self)
        self.maximize_window(top)
        top.transient(self)
        top.title('Add Clinic')
        ttk.Label(top, text='Clinic Code (e.g. KRMR):').grid(row=0, column=0, padx=8, pady=8)
        code_var = tk.StringVar()
        ttk.Entry(top, textvariable=code_var, width=16).grid(row=0, column=1, padx=8, pady=8)

        def do_add():
            code = (code_var.get() or '').strip().upper()
            if not code:
                messagebox.showwarning('Input','Enter clinic code')
                return
            if any(not c.isalnum() and '_' not in c for c in [code]):
                # allow alnum and underscore
                pass
            if code in self.clinics:
                messagebox.showinfo('Exists','Clinic already exists')
                return
            # add and persist
            self.clinics.append(code)
            self.save_clinics()
            # create empty clinic files
            try:
                dataf = DATA_TEMPLATE.format(clinic=code)
                if not os.path.exists(dataf):
                    with open(dataf, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow(["Title","Name","Age","Address","Mobile"])
                visitsf = VISITS_TEMPLATE.format(clinic=code)
                if not os.path.exists(visitsf):
                    with open(visitsf, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow(['VisitID','Title','Name','Date','Prescription','Notes','PaymentAmount','PaymentMethod','TotalFee','PaymentStatus'])
                suppf = SUPPLIERS_TEMPLATE.format(clinic=code)
                if not os.path.exists(suppf):
                    with open(suppf, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow(['SupplierID','Name','Contact','Notes'])
                adjf = STOCK_ADJ_TEMPLATE.format(clinic=code)
                if not os.path.exists(adjf):
                    with open(adjf, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow(['AdjustmentID','MedicineID','Name','Supplier','OldQty','Change','NewQty','Mode','Reason','Date','User'])
                shiftsf = SHIFTS_TEMPLATE.format(clinic=code)
                if not os.path.exists(shiftsf):
                    with open(shiftsf, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        # include Marker column to record visit-row-count at shift start
                        w.writerow(['ShiftID','Operator','Start','End','Notes','Marker','Clinic'])
                invf = INVENTORY_TEMPLATE.format(clinic=code)
                if not os.path.exists(invf):
                    with open(invf, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow(['MedicineID','Quantity','ReorderLevel'])
            except Exception:
                pass
            # update combobox values
            try:
                # find combobox widget by walking children of main frame
                for child in self.winfo_children():
                    if isinstance(child, ttk.Frame):
                        for grand in child.winfo_children():
                            if isinstance(grand, ttk.Combobox):
                                grand['values'] = self.clinics
                                break
                        break
            except Exception:
                pass
            top.destroy()

        ttk.Button(top, text='Add', command=do_add).grid(row=1, column=0, columnspan=2, pady=8)

    def change_clinic(self, clinic):
        """Switch current clinic context and set clinic-specific file paths.

        After switching, reload clinic-scoped data (patients, suppliers, inventory overlay).
        """
        if not clinic:
            return
        self.current_clinic = clinic
        global DATA_FILE, VISITS_FILE, SUPPLIERS_FILE, STOCK_ADJ_FILE, SHIFTS_FILE, INVENTORY_FILE
        DATA_FILE = DATA_TEMPLATE.format(clinic=clinic)
        VISITS_FILE = VISITS_TEMPLATE.format(clinic=clinic)
        SUPPLIERS_FILE = SUPPLIERS_TEMPLATE.format(clinic=clinic)
        STOCK_ADJ_FILE = STOCK_ADJ_TEMPLATE.format(clinic=clinic)
        SHIFTS_FILE = SHIFTS_TEMPLATE.format(clinic=clinic)
        INVENTORY_FILE = INVENTORY_TEMPLATE.format(clinic=clinic)

        # ensure files exist (create empty with headers where appropriate)
        try:
            # patients header
            if not os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(["Title", "Name", "Age", "Address", "Mobile"])
        except Exception:
            pass

        # If master MED_FILE still contains Quantity (older format), and inventory file
        # for this clinic does not yet exist, migrate quantities into the clinic inventory.
        try:
            if os.path.exists(MED_FILE) and not os.path.exists(INVENTORY_FILE):
                with open(MED_FILE, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    if rdr.fieldnames and 'Quantity' in rdr.fieldnames:
                        # write inventory file with MedicineID, Quantity, ReorderLevel
                        with open(INVENTORY_FILE, 'w', newline='', encoding='utf-8') as out:
                            w = csv.DictWriter(out, fieldnames=['MedicineID','Quantity','ReorderLevel'])
                            w.writeheader()
                            for r in rdr:
                                mid = (r.get('MedicineID') or '').strip()
                                qty = (r.get('Quantity') or '').strip()
                                rl = (r.get('ReorderLevel') or '').strip()
                                if not mid:
                                    continue
                                w.writerow({'MedicineID': mid, 'Quantity': qty, 'ReorderLevel': rl})
        except Exception:
            pass

        # load clinic-scoped data
        try:
            self.load_medicines()
        except Exception:
            self.medicines = []
        try:
            self.load_suppliers()
        except Exception:
            self.suppliers = []
        try:
            self.load_categories()
        except Exception:
            self.suppliers = []
        try:
            self.load_patients()
        except Exception:
            self.patients = []

    def save_suppliers(self):
        """Write self.suppliers to SUPPLIERS_FILE (rewrite)."""
        fieldnames = ['SupplierID','Name','Contact','Notes']
        try:
            # dedupe self.suppliers by name (case-insensitive) before writing
            deduped = []
            seen = set()
            for s in (self.suppliers or []):
                name = (s.get('Name','') or '').strip()
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                out = {k: s.get(k,'') for k in fieldnames}
                # ensure SupplierID exists
                if not out.get('SupplierID'):
                    out['SupplierID'] = str(uuid.uuid4())
                deduped.append(out)
            with open(SUPPLIERS_FILE, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                for out in deduped:
                    w.writerow(out)
            # update in-memory list to deduped canonical form
            self.suppliers = deduped
            return True
        except Exception:
            return False

    def open_suppliers(self):
        """Open Suppliers window showing known suppliers with simple CRUD."""
        top = tk.Toplevel(self)
        self.maximize_window(top)
        top.title('Suppliers')
        top.geometry('560x360')

        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        cols = ('Name','Contact','Notes')
        tree = ttk.Treeview(frm, columns=cols, show='headings')
        for c in cols:
            tree.heading(c, text=c, anchor='w')
        tree.column('Name', width=180, anchor='w')
        tree.column('Contact', width=140, anchor='w')
        tree.column('Notes', width=200, anchor='w')
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vs = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=vs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)

        def refresh():
            for i in tree.get_children():
                tree.delete(i)
            for s in self.suppliers:
                tree.insert('', tk.END, iid=s.get('SupplierID',''), values=(s.get('Name',''), s.get('Contact',''), s.get('Notes','')))

        def add_supplier():
            dlg = tk.Toplevel(top)
            self.maximize_window(dlg)
            self.maximize_window(dlg)
            dlg.transient(top)
            dlg.title('Add Supplier')
            labels = ['Name','Contact','Notes']
            fields = {}
            for r,lab in enumerate(labels):
                ttk.Label(dlg, text=lab+':').grid(row=r, column=0, sticky='w', padx=6, pady=4)
                if lab == 'Notes':
                    txt = tk.Text(dlg, width=40, height=4)
                    txt.grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = txt
                else:
                    sv = tk.StringVar()
                    ttk.Entry(dlg, textvariable=sv, width=36).grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = sv

            def do_add():
                name = fields['Name'].get().strip()
                if not name:
                    messagebox.showwarning('Input','Name required')
                    return
                # check for duplicate name (case-insensitive)
                lname = name.lower()
                for s in (self.suppliers or []):
                    if (s.get('Name') or '').strip().lower() == lname:
                        messagebox.showinfo('Exists', 'Supplier already exists')
                        dlg.destroy()
                        refresh()
                        return
                sid = str(uuid.uuid4())
                entry = {'SupplierID': sid, 'Name': name, 'Contact': fields['Contact'].get().strip(), 'Notes': fields['Notes'].get('1.0', tk.END).strip() if isinstance(fields['Notes'], tk.Text) else fields['Notes'].get().strip()}
                self.suppliers.append(entry)
                ok = self.save_suppliers()
                if not ok:
                    messagebox.showerror('Save','Failed to save suppliers')
                    return
                dlg.destroy()
                refresh()

            ttk.Button(dlg, text='Save', command=do_add).grid(row=len(labels), column=0, columnspan=2, pady=8)

        def delete_supplier():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Delete','Select a supplier to delete')
                return
            if not messagebox.askyesno('Confirm','Delete selected supplier?'):
                return
            sid = sel[0]
            self.suppliers = [s for s in self.suppliers if s.get('SupplierID') != sid]
            ok = self.save_suppliers()
            if not ok:
                messagebox.showerror('Delete','Failed to update suppliers file')
                return
            refresh()

        btns = ttk.Frame(top, padding=6)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text='Add', command=add_supplier).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Delete', command=delete_supplier).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Close', command=top.destroy).pack(side=tk.RIGHT)

        refresh()

    def search_name(self):
        query = self.search_var.get().strip().lower()
        if not query:
            # no query -> do not show patients (respect landing-page behavior)
            self.require_search_before_show = True
            self.refresh_tree([])
            return
        # allow tree to show results after a user-initiated search
        self.require_search_before_show = False

        results = []
        # Search across all clinics' patient files (DATA_TEMPLATE)
        clinics = getattr(self, 'clinics', []) or [getattr(self, 'current_clinic', '')]
        for c in clinics:
            if not c:
                continue
            path = DATA_TEMPLATE.format(clinic=c)
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    # support files without headers by falling back to reader
                    if not rdr.fieldnames:
                        f.seek(0)
                        reader = csv.reader(f)
                        for r in reader:
                            if len(r) < 2:
                                continue
                            title = r[0].strip()
                            name = r[1].strip()
                            age = r[2].strip() if len(r) > 2 else ''
                            address = r[3].strip() if len(r) > 3 else ''
                            mobile = r[4].strip() if len(r) > 4 else ''
                            hay = ' '.join([title, name, age, address, mobile]).lower()
                            if query in hay:
                                # insert clinic marker into address to indicate source
                                addr = f"{address} [{c}]" if address else f"[{c}]"
                                results.append([title, name, age, addr, mobile])
                    else:
                        for r in rdr:
                            name = (r.get('Name') or '').strip()
                            mobile = (r.get('Mobile') or '').strip()
                            title = (r.get('Title') or '').strip()
                            age = (r.get('Age') or '').strip()
                            address = (r.get('Address') or '').strip()
                            hay = ' '.join([title, name, age, address, mobile]).lower()
                            if query in hay:
                                addr = f"{address} [{c}]" if address else f"[{c}]"
                                results.append([title, name, age, addr, mobile])
            except Exception:
                continue

        # Also ensure any in-memory current-clinic patients that might not be in files are considered
        try:
            for p in self.patients:
                title = (p[0] or '').strip()
                name = (p[1] or '').strip()
                age = str(p[2]) if len(p) > 2 else ''
                address = (p[3] if len(p) > 3 else '')
                mobile = (p[4] or '').strip() if len(p) > 4 else ''
                hay = ' '.join([title, name, age, address, mobile]).lower()
                if query in hay:
                    # mark as current clinic
                    addr = f"{address} [{getattr(self,'current_clinic','')}]" if address else f"[{getattr(self,'current_clinic','')}]"
                    results.append([title, name, age, addr, mobile])
        except Exception:
            pass

        # remove duplicates by (name,mobile,clinic)
        seen = set()
        unique = []
        for r in results:
            key = (r[1].lower(), r[4], r[3])
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)

        self.refresh_tree(unique)
        try:
            # clear any selection so patient details are not shown automatically
            for s in list(self.tree.selection()):
                try:
                    self.tree.selection_remove(s)
                except Exception:
                    pass
        except Exception:
            pass

    def clear_search(self):
        self.search_var.set("")
        # clear search and hide patient list until the user searches again
        self.require_search_before_show = True
        self.refresh_tree([])

    def view_all_patients(self):
        """Load and display all patients from all clinics and current in-memory list.

        This method ignores the "require_search_before_show" landing behaviour
        and shows a combined, de-duplicated list of patients across clinics.
        """
        results = []
        clinics = getattr(self, 'clinics', []) or [getattr(self, 'current_clinic', '')]
        for c in clinics:
            if not c:
                continue
            path = DATA_TEMPLATE.format(clinic=c)
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    if not rdr.fieldnames:
                        f.seek(0)
                        reader = csv.reader(f)
                        for r in reader:
                            if len(r) < 2:
                                continue
                            title = r[0].strip()
                            name = r[1].strip()
                            age = r[2].strip() if len(r) > 2 else ''
                            address = r[3].strip() if len(r) > 3 else ''
                            mobile = r[4].strip() if len(r) > 4 else ''
                            addr = f"{address} [{c}]" if address else f"[{c}]"
                            results.append([title, name, age, addr, mobile])
                    else:
                        for r in rdr:
                            title = (r.get('Title') or '').strip()
                            name = (r.get('Name') or '').strip()
                            age = (r.get('Age') or '').strip()
                            address = (r.get('Address') or '').strip()
                            mobile = (r.get('Mobile') or '').strip()
                            addr = f"{address} [{c}]" if address else f"[{c}]"
                            results.append([title, name, age, addr, mobile])
            except Exception:
                continue

        # include any in-memory patients (mark as current clinic)
        try:
            for p in self.patients:
                title = (p[0] or '').strip()
                name = (p[1] or '').strip()
                age = str(p[2]) if len(p) > 2 else ''
                address = (p[3] if len(p) > 3 else '')
                mobile = (p[4] or '').strip() if len(p) > 4 else ''
                addr = f"{address} [{getattr(self,'current_clinic','')}]" if address else f"[{getattr(self,'current_clinic','')}]"
                results.append([title, name, age, addr, mobile])
        except Exception:
            pass

        # de-duplicate by (name,mobile,clinic)
        seen = set()
        unique = []
        for r in results:
            key = (r[1].lower(), r[4], r[3])
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)

        self.require_search_before_show = False
        self.refresh_tree(unique)

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Delete", "No patient selected to delete.")
            return

        if not messagebox.askyesno("Confirm Delete", "Delete selected patient(s)? This cannot be undone."):
            return

        removed_rows = []
        for item in selected:
            vals = self.tree.item(item, "values")
            # find and remove first matching patient in self.patients
            for idx, p in enumerate(self.patients):
                # p format: [title,name,age,address,mobile]
                if len(p) >= 5 and p[0] == vals[0] and p[1] == vals[1] and str(p[2]) == str(vals[2]) and p[4] == vals[3] and p[3] == vals[4]:
                    removed_rows.append(p)
                    del self.patients[idx]
                    break

        removed_count = len(removed_rows)
        if removed_count == 0:
            messagebox.showinfo("Delete", "No matching patients found to delete.")
            return

        # Save last deleted for undo
        self.last_deleted = removed_rows
        try:
            self.undo_btn.config(state="normal")
        except Exception:
            pass

        # Rewrite CSV from self.patients
        try:
            with open(DATA_FILE, "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Title", "Name", "Age", "Address", "Mobile"])
                for p in self.patients:
                    writer.writerow([p[0], p[1], p[2], p[3], p[4]])
        except Exception as e:
            messagebox.showerror("Delete Error", f"Failed to update data file: {e}")
            return

        self.refresh_tree()
        messagebox.showinfo("Delete", f"Deleted {removed_count} patient(s).")

    def delete_filtered(self):
        # Get all currently displayed items in the tree
        items = self.tree.get_children()
        if not items:
            messagebox.showinfo("Delete Filtered", "No patients are currently displayed to delete.")
            return

        if not messagebox.askyesno("Confirm Delete", f"Delete all {len(items)} displayed patient(s)? This cannot be undone."):
            return

        removed_rows = []
        # For each displayed tree item, remove one matching entry from self.patients
        for item in items:
            vals = self.tree.item(item, "values")
            for idx, p in enumerate(list(self.patients)):
                if len(p) >= 5 and p[0] == vals[0] and p[1] == vals[1] and str(p[2]) == str(vals[2]) and p[4] == vals[3] and p[3] == vals[4]:
                    removed_rows.append(p)
                    try:
                        self.patients.pop(idx)
                        break
                    except Exception:
                        continue

        removed_count = len(removed_rows)
        if removed_count == 0:
            messagebox.showinfo("Delete Filtered", "No matching patients were removed.")
            return

        # Save last deleted for undo
        self.last_deleted = removed_rows
        try:
            self.undo_btn.config(state="normal")
        except Exception:
            pass

        # Rewrite CSV from self.patients
        try:
            with open(DATA_FILE, "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Title", "Name", "Age", "Address", "Mobile"])
                for p in self.patients:
                    writer.writerow([p[0], p[1], p[2], p[3], p[4]])
        except Exception as e:
            messagebox.showerror("Delete Error", f"Failed to update data file: {e}")
            return

        self.refresh_tree()
        messagebox.showinfo("Delete Filtered", f"Deleted {removed_count} patient(s).")

    def undo_delete(self):
        if not self.last_deleted:
            messagebox.showinfo("Undo", "Nothing to undo.")
            return

        # Restore deleted rows to in-memory list (append at end)
        for row in self.last_deleted:
            self.patients.append(row)

        # Rewrite CSV from self.patients
        try:
            with open(DATA_FILE, "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Title", "Name", "Age", "Address", "Mobile"])
                for p in self.patients:
                    writer.writerow([p[0], p[1], p[2], p[3], p[4]])
        except Exception as e:
            messagebox.showerror("Undo Error", f"Failed to update data file: {e}")
            return

        restored_count = len(self.last_deleted)
        # clear undo buffer
        self.last_deleted = []
        try:
            self.undo_btn.config(state="disabled")
        except Exception:
            pass

        self.refresh_tree()
        messagebox.showinfo("Undo", f"Restored {restored_count} patient(s).")

    # --- Visits / Prescriptions ---
    def load_visits_for(self, title, name):
        """Return list of visits (dict) for given title+name sorted by date desc."""
        visits = []
        if not os.path.exists(VISITS_FILE):
            return visits
        try:
            with open(VISITS_FILE, "r", newline='', encoding="utf-8") as f:
                reader = csv.DictReader(f)
                q_title = (title or '').strip().lower()
                q_name = (name or '').strip().lower()
                for r in reader:
                    r_title = (r.get('Title') or '').strip().lower()
                    r_name = (r.get('Name') or '').strip().lower()
                    if r_title == q_title and r_name == q_name:
                        visits.append(r)
                    elif r_name == q_name:
                        # fallback: match by name only if title doesn't match
                        visits.append(r)
        except Exception:
            return []
        # sort by Date descending if present
        try:
            visits.sort(key=lambda v: datetime.strptime(v.get('Date',''), "%Y-%m-%d"), reverse=True)
        except Exception:
            pass
        return visits

    def append_visit(self, title, name, date, prescription, notes, payment_amount, payment_method, total_fee='', payment_status=''):
        # New expected fields: include VisitID, TotalFee and PaymentStatus for due tracking
        expected_fields = ['VisitID','Title','Name','Date','Prescription','Notes','PaymentAmount','PaymentMethod','TotalFee','PaymentStatus']
        try:
            # If file exists, ensure header contains expected fields; if not, rewrite with extended header
            if os.path.exists(VISITS_FILE):
                with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    existing_header = next(reader, None)
                if existing_header is None:
                    # empty file; will write header when appending
                    pass
                else:
                    if not set(expected_fields).issubset(set(existing_header)):
                        # read existing rows and rewrite file with new header
                        rows = []
                        with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                            rdr = csv.DictReader(f)
                            for r in rdr:
                                rows.append(r)
                        with open(VISITS_FILE, 'w', newline='', encoding='utf-8') as f:
                            w = csv.DictWriter(f, fieldnames=expected_fields)
                            w.writeheader()
                            for r in rows:
                                out = {k: r.get(k, '') for k in expected_fields}
                                w.writerow(out)

            first_write = not os.path.exists(VISITS_FILE)
            with open(VISITS_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=expected_fields)
                if first_write:
                    writer.writeheader()
                try:
                    pa = float(payment_amount) if str(payment_amount).strip() != '' else 0.0
                except Exception:
                    pa = 0.0
                tf = ''
                if str(total_fee).strip() != '':
                    try:
                        tfv = float(total_fee)
                        tf = f"{tfv:.2f}"
                    except Exception:
                        tf = ''
                # determine payment status if not provided
                pstat = payment_status or ''
                if not pstat:
                    if tf != '':
                        try:
                            tfv = float(tf)
                            if pa >= tfv and tfv > 0:
                                pstat = 'Paid'
                            elif pa > 0 and pa < tfv:
                                pstat = 'Partial'
                            else:
                                pstat = 'Due'
                        except Exception:
                            pstat = 'Due' if pa == 0 else 'Paid'
                    else:
                        pstat = 'Paid' if pa > 0 else 'Due'

                visit_id = str(uuid.uuid4())
                writer.writerow({
                    'VisitID': visit_id,
                    'Title': title,
                    'Name': name,
                    'Date': date,
                    'Prescription': prescription,
                    'Notes': notes,
                    'PaymentAmount': f"{pa:.2f}" if pa else '',
                    'PaymentMethod': payment_method,
                    'TotalFee': tf,
                    'PaymentStatus': pstat,
                })
            return True
        except Exception as e:
            messagebox.showerror("Save Visit", f"Failed to save visit: {e}")
            return False

    def ensure_visit_ids(self):
        """Make sure every row in VISITS_FILE has a VisitID; rewrite file if necessary."""
        if not os.path.exists(VISITS_FILE):
            return
        expected_fields = ['VisitID','Title','Name','Date','Prescription','Notes','PaymentAmount','PaymentMethod','TotalFee','PaymentStatus']
        try:
            with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                rdr = csv.DictReader(f)
                rows = list(rdr)
                fieldnames = rdr.fieldnames or []

            need_rewrite = False
            if 'VisitID' not in fieldnames:
                need_rewrite = True
            for r in rows:
                if not r.get('VisitID'):
                    r['VisitID'] = str(uuid.uuid4())
                    need_rewrite = True

            if need_rewrite:
                with open(VISITS_FILE, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=expected_fields)
                    w.writeheader()
                    for r in rows:
                        out = {k: r.get(k, '') for k in expected_fields}
                        w.writerow(out)
        except Exception:
            # non-fatal, skip
            return

    def update_visit_payment(self, visit_id, add_amount, method):
        """Add a payment amount to a visit identified by visit_id. Returns True on success."""
        if not os.path.exists(VISITS_FILE):
            return False
        expected_fields = ['VisitID','Title','Name','Date','Prescription','Notes','PaymentAmount','PaymentMethod','TotalFee','PaymentStatus']
        try:
            updated = False
            with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                rdr = csv.DictReader(f)
                rows = list(rdr)

            for r in rows:
                if r.get('VisitID') == visit_id:
                    # current paid
                    cur = r.get('PaymentAmount','').strip()
                    try:
                        curv = float(cur) if cur else 0.0
                    except Exception:
                        curv = 0.0
                    newv = curv + float(add_amount)
                    r['PaymentAmount'] = f"{newv:.2f}"
                    # update method
                    if method:
                        r['PaymentMethod'] = method
                    # compute status
                    try:
                        tf = float(r.get('TotalFee','')) if r.get('TotalFee','').strip() != '' else 0.0
                    except Exception:
                        tf = 0.0
                    if tf > 0:
                        if newv >= tf:
                            r['PaymentStatus'] = 'Paid'
                        elif newv > 0:
                            r['PaymentStatus'] = 'Partial'
                        else:
                            r['PaymentStatus'] = 'Due'
                    else:
                        r['PaymentStatus'] = 'Paid' if newv > 0 else 'Due'
                    updated = True
                    break

            if not updated:
                return False

            with open(VISITS_FILE, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=expected_fields)
                w.writeheader()
                for r in rows:
                    out = {k: r.get(k, '') for k in expected_fields}
                    w.writerow(out)
            return True
        except Exception:
            return False

    def update_visit_payment_by_fields(self, title, name, date, prescription, add_amount, method):
        """Find a visit row by Title+Name+Date+Prescription (case-insensitive for text fields)
        and add `add_amount` to its PaymentAmount. Returns True on success."""
        if not os.path.exists(VISITS_FILE):
            return False
        expected_fields = ['VisitID','Title','Name','Date','Prescription','Notes','PaymentAmount','PaymentMethod','TotalFee','PaymentStatus']
        try:
            with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                rdr = csv.DictReader(f)
                rows = list(rdr)

            matched = False
            for r in rows:
                r_title = (r.get('Title') or '').strip().lower()
                r_name = (r.get('Name') or '').strip().lower()
                r_date = (r.get('Date') or '').strip()
                r_pres = (r.get('Prescription') or '').strip().lower()
                if r_title == (title or '').strip().lower() and r_name == (name or '').strip().lower() and r_date == (date or '').strip() and r_pres == (prescription or '').strip().lower():
                    # found; update
                    cur = r.get('PaymentAmount','').strip()
                    try:
                        curv = float(cur) if cur else 0.0
                    except Exception:
                        curv = 0.0
                    newv = curv + float(add_amount)
                    r['PaymentAmount'] = f"{newv:.2f}"
                    if method:
                        r['PaymentMethod'] = method
                    # recompute status
                    try:
                        tf = float(r.get('TotalFee','')) if r.get('TotalFee','').strip() != '' else 0.0
                    except Exception:
                        tf = 0.0
                    if tf > 0:
                        if newv >= tf:
                            r['PaymentStatus'] = 'Paid'
                        elif newv > 0:
                            r['PaymentStatus'] = 'Partial'
                        else:
                            r['PaymentStatus'] = 'Due'
                    else:
                        r['PaymentStatus'] = 'Paid' if newv > 0 else 'Due'
                    matched = True
                    break

            if not matched:
                return False

            with open(VISITS_FILE, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=expected_fields)
                w.writeheader()
                for r in rows:
                    out = {k: r.get(k, '') for k in expected_fields}
                    w.writerow(out)
            return True
        except Exception:
            return False

    def add_due_to_visit_by_fields(self, title, name, date, prescription, add_amount):
        """Find a visit by Title+Name+Date+Prescription and add add_amount to TotalFee."""
        if not os.path.exists(VISITS_FILE):
            return False
        expected_fields = ['VisitID','Title','Name','Date','Prescription','Notes','PaymentAmount','PaymentMethod','TotalFee','PaymentStatus']
        try:
            with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                rdr = csv.DictReader(f)
                rows = list(rdr)

            matched = False
            for r in rows:
                r_title = (r.get('Title') or '').strip().lower()
                r_name = (r.get('Name') or '').strip().lower()
                r_date = (r.get('Date') or '').strip()
                r_pres = (r.get('Prescription') or '').strip().lower()
                if r_title == (title or '').strip().lower() and r_name == (name or '').strip().lower() and r_date == (date or '').strip() and r_pres == (prescription or '').strip().lower():
                    # increase TotalFee
                    cur = r.get('TotalFee','').strip()
                    try:
                        curv = float(cur) if cur else 0.0
                    except Exception:
                        curv = 0.0
                    newtf = curv + float(add_amount)
                    r['TotalFee'] = f"{newtf:.2f}"
                    # recompute status based on existing PaymentAmount
                    try:
                        pa = float(r.get('PaymentAmount','')) if r.get('PaymentAmount','').strip() != '' else 0.0
                    except Exception:
                        pa = 0.0
                    if newtf > 0:
                        if pa >= newtf:
                            r['PaymentStatus'] = 'Paid'
                        elif pa > 0:
                            r['PaymentStatus'] = 'Partial'
                        else:
                            r['PaymentStatus'] = 'Due'
                    else:
                        r['PaymentStatus'] = 'Paid' if pa > 0 else 'Due'
                    matched = True
                    break

            if not matched:
                return False

            with open(VISITS_FILE, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=expected_fields)
                w.writeheader()
                for r in rows:
                    out = {k: r.get(k, '') for k in expected_fields}
                    w.writerow(out)
            return True
        except Exception:
            return False

    def open_patient_window(self, event=None):
        # Determine selected patient (by selection or double-click row)
        selected_item = None
        if event is not None and hasattr(event, 'widget'):
            # double-click: get item under cursor
            item = event.widget.identify_row(event.y)
            if item:
                selected_item = item
        if not selected_item:
            sel = self.tree.selection()
            if sel:
                selected_item = sel[0]

        if not selected_item:
            messagebox.showinfo("Patient", "Please select a patient first.")
            return

        vals = self.tree.item(selected_item, 'values')
        if not vals or len(vals) < 2:
            messagebox.showerror("Patient", "Invalid patient selection.")
            return
        title, name = vals[0], vals[1]

        top = tk.Toplevel(self)
        self.maximize_window(top)
        top.title(f"{title} {name} — History & Prescribe")
        top.geometry("760x520")
        # Make visit window modal so landing page stays in background
        try:
            self.make_modal(top, parent=self)
        except Exception:
            pass

        # Ensure visits have VisitID values
        self.ensure_visit_ids()

        # Visits list
        vf = ttk.LabelFrame(top, text="Previous Visits / Medications", padding=8)
        vf.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8,4))

        cols = ('Date','Prescription','Notes','Total','Paid','Due','Method','Status')
        # create a Treeview style with increased rowheight to allow showing two lines
        try:
            s = ttk.Style()
            s.configure('TwoLine.Treeview', rowheight=40)
            vtree = ttk.Treeview(vf, columns=cols, show='headings', height=8, style='TwoLine.Treeview')
        except Exception:
            vtree = ttk.Treeview(vf, columns=cols, show='headings', height=8)
        for c in cols:
            vtree.heading(c, text=c, anchor='w')
        vtree.column('Date', width=100, anchor='w')
        vtree.column('Prescription', width=260, anchor='w')
        vtree.column('Notes', width=200, anchor='w')
        vtree.column('Total', width=80, anchor='w')
        vtree.column('Paid', width=80, anchor='w')
        vtree.column('Due', width=80, anchor='w')
        vtree.column('Method', width=80, anchor='w')
        vtree.column('Status', width=80, anchor='w')
        vtree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Vertical scrollbar
        vscroll = ttk.Scrollbar(vf, orient=tk.VERTICAL, command=vtree.yview)
        vtree.configure(yscroll=vscroll.set)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        # Horizontal scrollbar
        hscroll = ttk.Scrollbar(vf, orient=tk.HORIZONTAL, command=vtree.xview)
        vtree.configure(xscroll=hscroll.set)
        # Pack horizontal scrollbar below tree
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)

        # Add a readable details box for the selected visit so contents are always visible
        try:
            # height increased so two-line prescriptions are visible in the details area
            details_txt = tk.Text(vf, height=5, wrap='word', font=('TkDefaultFont', 10), background='white', foreground='black')
            details_txt.pack(fill=tk.X, padx=6, pady=(6,0))
            details_txt.insert('1.0', '')
            details_txt.config(state='disabled')
        except Exception:
            details_txt = None

        # Auto-resize visit tree columns to fit available width when window resizes
        def adjust_vtree_columns(event=None):
            try:
                total_w = vf.winfo_width()
                # reserve space for vertical scrollbar and small padding
                reserve = 40
                avail = max(total_w - reserve, 200)
                # fixed width columns
                fixed = {'Date':100, 'Total':70, 'Paid':70, 'Due':70, 'Method':70, 'Status':70}
                fixed_sum = sum(fixed.values())
                remaining = max(avail - fixed_sum, 100)
                # allocate 60% to Prescription, 40% to Notes
                pres_w = int(remaining * 0.6)
                notes_w = remaining - pres_w
                # apply widths
                try:
                    vtree.column('Date', width=fixed['Date'])
                    vtree.column('Prescription', width=pres_w)
                    vtree.column('Notes', width=notes_w)
                    vtree.column('Total', width=fixed['Total'])
                    vtree.column('Paid', width=fixed['Paid'])
                    vtree.column('Due', width=fixed['Due'])
                    vtree.column('Method', width=fixed['Method'])
                    vtree.column('Status', width=fixed['Status'])
                except Exception:
                    pass
            except Exception:
                pass

        # bind resize to container
        vf.bind('<Configure>', adjust_vtree_columns)
        top.bind('<Configure>', adjust_vtree_columns)
        # initial adjust
        vf.after(50, adjust_vtree_columns)
        # make selected row readable regardless of theme by tagging
        try:
            vtree.tag_configure('sel', background='#1f5a78', foreground='white')
            def _vtree_sel(evt):
                tr = evt.widget
                try:
                    for iid in tr.get_children(''):
                        tr.tag_remove('sel', iid)
                except Exception:
                    pass
                sel_items = []
                try:
                    for s in tr.selection():
                        tr.tag_add('sel', s)
                        sel_items.append(s)
                except Exception:
                    pass
                # populate readable details box
                try:
                    if details_txt is not None:
                        details_txt.config(state='normal')
                        details_txt.delete('1.0', 'end')
                        if sel_items:
                            # show first selected item's columns
                            iid = sel_items[0]
                            vals = tr.item(iid, 'values')
                            hdrs = cols
                            # Build details; but if prescription/notes are multiline, expand height
                            pres = vals[1] if len(vals) > 1 else ''
                            notes = vals[2] if len(vals) > 2 else ''
                            pres_lines = len(str(pres).splitlines()) if pres else 0
                            notes_lines = len(str(notes).splitlines()) if notes else 0
                            total_lines = max(pres_lines, notes_lines)
                            # compute desired height: headers + content, clamp between 3 and 12
                            desired = min(max(3, total_lines + 1), 12)
                            try:
                                details_txt.config(state='normal')
                                details_txt.delete('1.0', 'end')
                                # insert only Prescription and Notes for readability
                                lines = []
                                lines.append(f"Prescription:")
                                lines.append(str(pres))
                                lines.append('')
                                lines.append('Notes:')
                                lines.append(str(notes))
                                details_txt.insert('1.0', '\n'.join(lines))
                                details_txt.config(height=desired)
                            except Exception:
                                pass
                        try:
                            details_txt.config(state='disabled')
                        except Exception:
                            pass
                except Exception:
                    pass
            vtree.bind('<<TreeviewSelect>>', _vtree_sel)
        except Exception:
            pass

        # Double-click a visit to open a full details dialog (shows full prescription/notes)
        def open_visit_full_details(event=None):
            sel = vtree.selection()
            if not sel:
                # try identify under cursor
                if event is not None and hasattr(event, 'y'):
                    iid = vtree.identify_row(event.y)
                    if iid:
                        sel = (iid,)
            if not sel:
                return
            iid = sel[0]
            vals = vtree.item(iid, 'values')
            # fields: Date, Prescription, Notes, Total, Paid, Due, Method, Status
            vdate = vals[0] if len(vals) > 0 else ''
            vpres = vals[1] if len(vals) > 1 else ''
            vnotes = vals[2] if len(vals) > 2 else ''
            vtotal = vals[3] if len(vals) > 3 else ''
            vpaid = vals[4] if len(vals) > 4 else ''
            vdue = vals[5] if len(vals) > 5 else ''
            vmethod = vals[6] if len(vals) > 6 else ''
            vstatus = vals[7] if len(vals) > 7 else ''

            # If prescription or notes contain multiple lines, show a simplified dialog
            # that displays only Prescription and Notes for easier reading.
            multi_pres = isinstance(vpres, str) and ("\n" in vpres or len(vpres.splitlines()) > 1)
            multi_notes = isinstance(vnotes, str) and ("\n" in vnotes or len(vnotes.splitlines()) > 1)
            dlg = tk.Toplevel(top)
            self.maximize_window(dlg)
            if multi_pres or multi_notes:
                dlg.title('Prescription & Notes')
                frm = ttk.Frame(dlg, padding=8)
                frm.pack(fill=tk.BOTH, expand=True)
                if vpres:
                    ttk.Label(frm, text='Prescription:').pack(anchor='w')
                    pt = tk.Text(frm, wrap='word', height=8, font=('TkDefaultFont', 11), bg='white', fg='black')
                    pt.pack(fill=tk.BOTH, expand=False, pady=(0,6))
                    try:
                        pt.insert('1.0', vpres)
                    except Exception:
                        pt.insert('1.0', str(vpres))
                    pt.config(state='disabled')
                if vnotes:
                    ttk.Label(frm, text='Notes:').pack(anchor='w')
                    nt = tk.Text(frm, wrap='word', height=6, font=('TkDefaultFont', 11), bg='white', fg='black')
                    nt.pack(fill=tk.BOTH, expand=True, pady=(0,6))
                    try:
                        nt.insert('1.0', vnotes)
                    except Exception:
                        nt.insert('1.0', str(vnotes))
                    nt.config(state='disabled')
                ttk.Button(frm, text='Close', command=dlg.destroy).pack(pady=(6,0))
            else:
                dlg.title(f"Visit Details - {vdate}")
                frm = ttk.Frame(dlg, padding=8)
                frm.pack(fill=tk.BOTH, expand=True)
                ttk.Label(frm, text=f"Date: {vdate}").pack(anchor='w')
                ttk.Label(frm, text=f"Total: {vtotal}    Paid: {vpaid}    Due: {vdue}    Method: {vmethod}    Status: {vstatus}").pack(anchor='w', pady=(0,6))
                ttk.Label(frm, text='Prescription:').pack(anchor='w')
                pt = tk.Text(frm, wrap='word', height=8, font=('TkDefaultFont', 10), bg='white', fg='black')
                pt.pack(fill=tk.BOTH, expand=False, pady=(0,6))
                try:
                    pt.insert('1.0', vpres)
                except Exception:
                    pt.insert('1.0', str(vpres))
                pt.config(state='disabled')
                ttk.Label(frm, text='Notes:').pack(anchor='w')
                nt = tk.Text(frm, wrap='word', height=6, font=('TkDefaultFont', 10), bg='white', fg='black')
                nt.pack(fill=tk.BOTH, expand=True, pady=(0,6))
                try:
                    nt.insert('1.0', vnotes)
                except Exception:
                    nt.insert('1.0', str(vnotes))
                nt.config(state='disabled')
                ttk.Button(frm, text='Close', command=dlg.destroy).pack(pady=(6,0))

        try:
            vtree.bind('<Double-1>', open_visit_full_details)
        except Exception:
            pass

        # visit controls
        vbtn_frame = ttk.Frame(vf)
        vbtn_frame.pack(fill=tk.X, pady=(6,0))

        # Create buttons but lay them out with wrapping if they don't fit in one row.
        # This improves readability on narrow windows by moving excess buttons to a second line.
        btn_defs = []

        def refresh_visits():
            for i in vtree.get_children():
                vtree.delete(i)
            # Load all visits then filter to only those matching the selected patient
            # configure highlight tag
            try:
                vtree.tag_configure('match', background='#e6ffe6')
                vtree.tag_configure('due', background='#ffe6e6')
            except Exception:
                pass

            if os.path.exists(VISITS_FILE):
                try:
                    with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                        rdr = csv.DictReader(f)
                        rows = list(rdr)
                except Exception:
                    rows = []
            else:
                rows = []

            q_title = (title or '').strip().lower()
            q_name = (name or '').strip().lower()

            # collect only patient-specific rows
            patient_rows = []
            for r in rows:
                r_title = (r.get('Title') or '').strip().lower()
                r_name = (r.get('Name') or '').strip().lower()
                is_match = False
                if r_title == q_title and r_name == q_name:
                    is_match = True
                elif r_name == q_name:
                    # fallback: match by name only if title doesn't match exactly
                    is_match = True
                if not is_match:
                    continue
                patient_rows.append(r)

            # insert only patient rows into the tree
            first_iid = None
            first_multiline_iid = None
            for r in patient_rows:
                vid = r.get('VisitID') or str(uuid.uuid4())
                date_s = r.get('Date','')
                pres = r.get('Prescription','')
                notes = r.get('Notes','')
                total = r.get('TotalFee','')
                paid = r.get('PaymentAmount','')
                method = r.get('PaymentMethod','')
                status = r.get('PaymentStatus','')

                # compute due
                try:
                    tf = float(total) if str(total).strip() != '' else 0.0
                    pa = float(paid) if str(paid).strip() != '' else 0.0
                    due_val = f"{max(tf - pa, 0.0):.2f}" if tf > 0 else (f"{max(-pa,0.0):.2f}" if pa < 0 else '')
                except Exception:
                    due_val = ''

                # determine due state
                is_due = False
                try:
                    tfv = float(total) if str(total).strip() != '' else 0.0
                    pav = float(paid) if str(paid).strip() != '' else 0.0
                    if tfv - pav > 0.0:
                        is_due = True
                except Exception:
                    is_due = False

                tags = ('match',)
                if is_due:
                    tags = ('match','due')

                try:
                    vtree.insert('', tk.END, iid=vid, values=(date_s, pres, notes, total or '', paid or '', due_val, method or '', status or ''), tags=tags)
                except Exception:
                    vtree.insert('', tk.END, values=(date_s, pres, notes, total or '', paid or '', due_val, method or '', status or ''), tags=tags)
                # detect multiline prescription/notes
                try:
                    pres_lines = len(str(pres).splitlines()) if pres is not None else 0
                    notes_lines = len(str(notes).splitlines()) if notes is not None else 0
                    if (pres_lines > 1 or notes_lines > 1) and not first_multiline_iid:
                        first_multiline_iid = vid
                except Exception:
                    pass
                if not first_iid:
                    first_iid = vid

            # if any multiline entries exist, auto-select the first multiline item so details show expanded
            target_iid = first_multiline_iid or first_iid
            if target_iid:
                try:
                    vtree.see(target_iid)
                    vtree.selection_set(target_iid)
                except Exception:
                    pass

            # compute and show total due for this patient from the displayed visit rows
            total_due = 0.0
            try:
                for iid in vtree.get_children():
                    try:
                        vals = vtree.item(iid, 'values')
                        due_val = vals[5] if len(vals) > 5 else ''
                        status = (vals[7] if len(vals) > 7 else '').strip().lower()
                        dv = 0.0
                        if str(due_val).strip() != '':
                            try:
                                dv = float(str(due_val).strip())
                            except Exception:
                                dv = 0.0
                        # include if status indicates due/partial and there is a positive due
                        if status in ('due', 'partial') and dv > 0.0:
                            total_due += dv
                    except Exception:
                        continue
            except Exception:
                total_due = 0.0
            try:
                total_due_var.set(f"Total Due: {total_due:.2f}")
                try:
                    if total_due > 0.0:
                        total_due_lbl.configure(foreground='red', font=('Arial', 11, 'bold'))
                    else:
                        total_due_lbl.configure(foreground='black', font=('Arial', 11, 'normal'))
                except Exception:
                    pass
            except Exception:
                pass

        def add_payment_action():
            sel = vtree.selection()
            if not sel:
                messagebox.showinfo('Payment', 'Select a visit to add payment to.')
                return
            vid = sel[0]

            pay_top = tk.Toplevel(top)
            self.maximize_window(pay_top)
            self.maximize_window(pay_top)
            pay_top.transient(top)
            pay_top.title('Record Payment')
            ttk.Label(pay_top, text='Amount:').grid(row=0, column=0, padx=8, pady=8)
            amt_var = tk.StringVar()
            ttk.Entry(pay_top, textvariable=amt_var).grid(row=0, column=1, padx=8, pady=8)
            ttk.Label(pay_top, text='Method:').grid(row=1, column=0, padx=8, pady=8)
            pm = tk.StringVar(value='Cash')
            ttk.Combobox(pay_top, textvariable=pm, values=('Cash','Card','Mobile'), state='readonly').grid(row=1, column=1, padx=8, pady=8)

            def do_add():
                val = amt_var.get().strip()
                if not val:
                    messagebox.showwarning('Input', 'Enter amount')
                    return
                try:
                    av = float(val)
                except Exception:
                    messagebox.showwarning('Input', 'Amount must be a number')
                    return
                # prefer matching by fields (title+name+date+prescription) so visits stay linked by name
                vals = vtree.item(vid, 'values')
                visit_date = vals[0] if len(vals) > 0 else ''
                visit_presc = vals[1] if len(vals) > 1 else ''
                ok = self.update_visit_payment_by_fields(title, name, visit_date, visit_presc, av, pm.get())
                if ok:
                    messagebox.showinfo('Saved','Payment recorded')
                    try:
                        self._close_all_child_toplevels()
                    except Exception:
                        try:
                            pay_top.destroy()
                        except Exception:
                            pass
                    refresh_visits()
                else:
                    messagebox.showerror('Error','Failed to record payment')

            ttk.Button(pay_top, text='Save', command=do_add).grid(row=2, column=0, columnspan=2, pady=(6,8))

        # Prescription helpers: build preview text and save to PDF (uses reportlab if available)
        def build_prescription_text():
            try:
                header = f"Taj Homeo Clinic\nDoctor: DR FAQRUDDIN FAKHIR\n\nPatient: {title} {name}\nDate: {date_var.get()}\n\n"
            except Exception:
                header = f"Taj Homeo Clinic\n\nPatient: {title} {name}\nDate: {date_var.get()}\n\n"
            presc = ''
            try:
                presc = presc_txt.get('1.0', 'end').strip()
            except Exception:
                presc = ''
            meds_lines = ''
            try:
                if selected_meds:
                    meds_lines = '\nMedicines:\n'
                    for md in selected_meds:
                        meds_lines += f"- {md.get('Name','')} x{md.get('Qty','')} @ {md.get('Price','')}\n"
            except Exception:
                meds_lines = ''
            footer = '\n\n\n(Signature)\n'
            return header + presc + meds_lines + footer

        def save_prescription_pdf_action(content=None):
            # Ask user for filename
            if content is None:
                content = build_prescription_text()
            try:
                default_name = f"prescription_{name.replace(' ','_')}_{date_var.get()}.pdf"
            except Exception:
                default_name = 'prescription.pdf'
            path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF','*.pdf'),('All','*.*')], initialfile=default_name)
            if not path:
                return
            try:
                # try reportlab
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas
                c = canvas.Canvas(path, pagesize=A4)
                width, height = A4
                x = 40
                y = height - 50
                for line in content.splitlines():
                    # simple wrap handling: split long lines
                    if len(line) > 90:
                        for i in range(0, len(line), 90):
                            c.drawString(x, y, line[i:i+90])
                            y -= 14
                            if y < 50:
                                c.showPage(); y = height - 50
                    else:
                        c.drawString(x, y, line)
                        y -= 14
                        if y < 50:
                            c.showPage(); y = height - 50
                c.save()
                messagebox.showinfo('Saved', f'Prescription saved to {path}')
            except Exception:
                # fallback: save plain text
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    messagebox.showinfo('Saved', f'Saved as text to {path} (install reportlab for PDF)')
                except Exception as ee:
                    messagebox.showerror('Save Error', f'Failed to save prescription: {ee}')

        def create_prescription_action():
            content = build_prescription_text()
            ptop = tk.Toplevel(top)
            self.maximize_window(ptop)
            ptop.title('Prescription Preview')
            txt = tk.Text(ptop, wrap='word', font=('TkDefaultFont', 10))
            txt.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
            txt.insert('1.0', content)
            txt.config(state='disabled')
            bframe = ttk.Frame(ptop)
            bframe.pack(fill=tk.X)
            ttk.Button(bframe, text='Save as PDF', command=lambda: save_prescription_pdf_action(content)).pack(side=tk.RIGHT, padx=6, pady=6)
            ttk.Button(bframe, text='Close', command=ptop.destroy).pack(side=tk.RIGHT, padx=6, pady=6)

        # define button set for actions and create widgets (but don't pack them directly)
        btn_defs = [
            ('Create Prescription', create_prescription_action),
            ('Save as PDF', lambda: save_prescription_pdf_action(None)),
            ('Add Payment', add_payment_action),
            ('Add Due', lambda: add_due_action()),
            ('Refresh', refresh_visits),
        ]
        created_buttons = []
        for txt, cmd in btn_defs:
            b = ttk.Button(vbtn_frame, text=txt, command=cmd)
            created_buttons.append(b)

        def _layout_buttons_wrap():
            # remove previous packing for children (keeps widgets but unpacks them)
            for ch in vbtn_frame.winfo_children():
                ch.pack_forget()
            # create rows as needed
            rows = []
            def _new_row():
                r = ttk.Frame(vbtn_frame)
                r.pack(fill=tk.X, anchor='w')
                rows.append(r)
                return r

            current_row = _new_row()
            # ensure geometry info is updated
            vbtn_frame.update_idletasks()
            avail = vbtn_frame.winfo_width() or vbtn_frame.winfo_reqwidth() or top.winfo_width()
            cum = 0
            for b in created_buttons:
                b.update_idletasks()
                w = b.winfo_reqwidth() or 80
                # if button doesn't fit on current row and row already has buttons, wrap
                if cum > 0 and (cum + w + 12) > avail:
                    current_row = _new_row()
                    cum = 0
                b.pack(in_=current_row, side=tk.LEFT, padx=6, pady=2)
                cum += w + 12

        # schedule layout after widgets have been realized
        vbtn_frame.after(50, _layout_buttons_wrap)

        # Total Due label for the patient (prominent red when > 0)
        total_due_var = tk.StringVar(value='Total Due: 0.00')
        total_due_lbl = ttk.Label(vbtn_frame, textvariable=total_due_var)
        total_due_lbl.pack(side=tk.RIGHT, padx=8)

        # populate visits immediately
        refresh_visits()

        def add_due_action():
            sel = vtree.selection()
            if not sel:
                messagebox.showinfo('Add Due', 'Select a visit to add due to, or create a new visit via the form.')
                return
            vid = sel[0]
            vals = vtree.item(vid, 'values')
            visit_date = vals[0] if len(vals) > 0 else ''
            visit_presc = vals[1] if len(vals) > 1 else ''

            due_top = tk.Toplevel(top)
            self.maximize_window(due_top)
            self.maximize_window(due_top)
            due_top.transient(top)
            due_top.title('Add Due Amount')
            ttk.Label(due_top, text='Amount to add to Total Fee:').grid(row=0, column=0, padx=8, pady=8)
            amt_var = tk.StringVar()
            ttk.Entry(due_top, textvariable=amt_var).grid(row=0, column=1, padx=8, pady=8)

            def do_add_due():
                v = amt_var.get().strip()
                if not v:
                    messagebox.showwarning('Input', 'Enter amount')
                    return
                try:
                    av = float(v)
                except Exception:
                    messagebox.showwarning('Input', 'Amount must be a number')
                    return
                ok = self.add_due_to_visit_by_fields(title, name, visit_date, visit_presc, av)
                if ok:
                    messagebox.showinfo('Saved', 'Due added')
                    try:
                        self._close_all_child_toplevels()
                    except Exception:
                        try:
                            due_top.destroy()
                        except Exception:
                            pass
                    refresh_visits()
                else:
                    messagebox.showerror('Error', 'Failed to add due')

            ttk.Button(due_top, text='Save', command=do_add_due).grid(row=1, column=0, columnspan=2, pady=(6,8))

        # Prescribe / Payment form
        form = ttk.LabelFrame(top, text="Add Prescription / Payment", padding=8)
        form.pack(fill=tk.X, padx=8, pady=(0,8))

        ttk.Label(form, text="Date (YYYY-MM-DD):").grid(row=0, column=0, sticky='w')
        date_var = tk.StringVar(value=datetime.today().strftime('%Y-%m-%d'))
        ttk.Entry(form, textvariable=date_var, width=16).grid(row=0, column=1, sticky='w')

        ttk.Label(form, text="Prescription:").grid(row=1, column=0, sticky='nw', pady=(6,0))
        # Prescription area with Pen button so users can type or use pen input
        presc_wrap = ttk.Frame(form)
        presc_wrap.grid(row=1, column=1, pady=(6,0), sticky='we')
        # Ensure prescription text area is readable and can show multiple lines
        presc_txt = tk.Text(presc_wrap, width=60, height=6, wrap='word', font=('TkDefaultFont', 10), bg='white', fg='black')
        presc_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        try:
            ttk.Button(presc_wrap, text='Pen', width=6, command=lambda: self.open_handwriting_input(target_widget=presc_txt)).pack(side=tk.LEFT, padx=(6,0), pady=2)
        except Exception:
            pass
        try:
            form.grid_columnconfigure(1, weight=1)
        except Exception:
            pass

        # Keyboard shortcuts: Ctrl+P opens Pen Input for focused text widgets
        try:
            def _bind_ctrlp_to(widget):
                try:
                    widget.bind('<Control-p>', lambda e: self.open_handwriting_input(target_widget=widget))
                except Exception:
                    pass
            # Bind once the widgets exist
            try:
                _bind_ctrlp_to(presc_txt)
            except Exception:
                pass
            try:
                _bind_ctrlp_to(notes_txt)
            except Exception:
                pass
        except Exception:
            pass

        # Selected medicines for this prescription (will be used to compute total and adjust stock)
        selected_meds = []  # list of dicts: {'MedicineID','Name','Qty','Price','Supplier'}
        meds_frame = ttk.Frame(form)
        meds_frame.grid(row=1, column=2, rowspan=4, padx=(12,0), sticky='n')
        ttk.Label(meds_frame, text='Medicines', font=('TkDefaultFont', 10, 'bold')).pack(anchor='w')
        meds_cols = ('Name','Qty','Price')
        meds_tree = ttk.Treeview(meds_frame, columns=meds_cols, show='headings', height=8)
        for c in meds_cols:
            meds_tree.heading(c, text=c, anchor='w')
            meds_tree.column(c, width=100, anchor='w')
        meds_tree.pack(fill=tk.BOTH, expand=False)

        meds_btns = ttk.Frame(meds_frame)
        meds_btns.pack(fill=tk.X, pady=(6,0))

        def refresh_meds_selection():
            for i in meds_tree.get_children():
                meds_tree.delete(i)
            for idx,md in enumerate(selected_meds):
                meds_tree.insert('', tk.END, iid=str(idx), values=(md.get('Name',''), str(md.get('Qty','')), f"{float(md.get('Price',0)):.2f}"))
            # update total_var
            total = 0.0
            for md in selected_meds:
                try:
                    total += float(md.get('Price',0)) * float(md.get('Qty',0))
                except Exception:
                    continue
            total_var.set(f"{total:.2f}")

        # Auto-fit meds tree columns to meds_frame width
        def adjust_meds_columns(event=None):
            try:
                w = meds_frame.winfo_width()
                if w <= 0:
                    return
                # simple proportional widths
                name_w = int(w * 0.6)
                qty_w = int(w * 0.2)
                price_w = max(w - name_w - qty_w - 10, 50)
                meds_tree.column('Name', width=name_w)
                meds_tree.column('Qty', width=qty_w)
                meds_tree.column('Price', width=price_w)
            except Exception:
                pass

        meds_frame.bind('<Configure>', adjust_meds_columns)
        meds_frame.after(50, adjust_meds_columns)
        # make selected meds entries readable
        try:
            meds_tree.tag_configure('sel', background='#1f5a78', foreground='white')
            def _meds_sel(evt):
                tr = evt.widget
                try:
                    for iid in tr.get_children(''):
                        tr.tag_remove('sel', iid)
                except Exception:
                    pass
                try:
                    for s in tr.selection():
                        tr.tag_add('sel', s)
                except Exception:
                    pass
            meds_tree.bind('<<TreeviewSelect>>', _meds_sel)
        except Exception:
            pass

        def add_medicine_to_selection(mid, name, price, supplier):
            # ask quantity
            # create a compact dialog (won't be expanded to workarea)
            qdlg = tk.Toplevel(top, compact=True)
            qdlg.title('Quantity')
            # make it tight to contents
            qdlg.resizable(False, False)
            lbl = ttk.Label(qdlg, text=f'Quantity for {name}:')
            lbl.grid(row=0, column=0, padx=6, pady=6)
            qvar = tk.StringVar(value='1')
            ent = ttk.Entry(qdlg, textvariable=qvar, width=8)
            ent.grid(row=0, column=1, padx=6, pady=6)

            def do_q():
                v = qvar.get().strip()
                try:
                    q = float(v)
                except Exception:
                    messagebox.showwarning('Input','Quantity must be a number')
                    return
                selected_meds.append({'MedicineID': mid, 'Name': name, 'Qty': q, 'Price': float(price), 'Supplier': supplier})
                qdlg.destroy()
                refresh_meds_selection()
                # append a short line to prescription area describing this medicine
                try:
                    line = f"{name}  Qty:{q}  Price:{float(price):.2f}\n"
                    presc_txt.insert(tk.END, line)
                    presc_txt.see(tk.END)
                except Exception:
                    pass

            ttk.Button(qdlg, text='OK', command=do_q).grid(row=1, column=0, columnspan=2, pady=6)

            # size the dialog to fit label + entry snugly
            try:
                qdlg.update_idletasks()
                # measure label width in pixels
                try:
                    f = tkfont.Font(font=lbl.cget('font'))
                    lbl_w = f.measure(lbl.cget('text'))
                    char_w = f.measure('0') or 7
                except Exception:
                    lbl_w = lbl.winfo_reqwidth()
                    char_w = 7
                ent_chars = 8
                ent_w = ent_chars * char_w
                pad = 40
                total_w = lbl_w + ent_w + pad
                total_h = qdlg.winfo_reqheight() + 10
                screen_w = qdlg.winfo_screenwidth()
                screen_h = qdlg.winfo_screenheight()
                x = max(0, (screen_w - total_w) // 2)
                y = max(0, (screen_h - total_h) // 3)
                qdlg.geometry(f"{int(total_w)}x{int(total_h)}+{int(x)}+{int(y)}")
            except Exception:
                pass

        def open_medicine_search():
            # Dialog listing all medicines and allowing selection
            sdlg = tk.Toplevel(top)
            # allow minimize/maximize and resizing so decorations are visible
            sdlg.resizable(True, True)
            sdlg.title('Add Medicine')
            sdlg.geometry('600x360')

            sf = ttk.Frame(sdlg, padding=6)
            sf.pack(fill=tk.BOTH, expand=True)

            search_var2 = tk.StringVar()
            ttk.Entry(sf, textvariable=search_var2, width=15).pack(fill=tk.X, padx=6, pady=(0,6))

            cols = ('Name','Supplier','Avail','Price')
            stree = ttk.Treeview(sf, columns=cols, show='headings')
            for c in cols:
                stree.heading(c, text=c, anchor='w')
                stree.column(c, width=120, anchor='w')
            stree.pack(fill=tk.BOTH, expand=True)

            def refresh_stree():
                q = search_var2.get().strip().lower()
                for i in stree.get_children():
                    stree.delete(i)
                for m in self.medicines:
                    name = m.get('Name','')
                    if q and q not in name.lower():
                        continue
                    try:
                        avail = float((m.get('Quantity') or '').strip()) if (m.get('Quantity') or '').strip() != '' else 0.0
                    except Exception:
                        avail = 0.0
                    price = m.get('Price','')
                    stree.insert('', tk.END, iid=m.get('MedicineID',''), values=(name, m.get('Supplier',''), f"{avail:.2f}" if isinstance(avail,float) else avail, price))

            def do_add_from_search():
                sel = stree.selection()
                if not sel:
                    messagebox.showinfo('Select','Select a medicine to add')
                    return
                mid = sel[0]
                m = next((x for x in self.medicines if x.get('MedicineID')==mid), None)
                if not m:
                    messagebox.showerror('Error','Medicine not found')
                    return
                add_medicine_to_selection(m.get('MedicineID',''), m.get('Name',''), m.get('Price','') or '0', m.get('Supplier',''))

            ttk.Button(sf, text='Add Selected', command=do_add_from_search).pack(side=tk.LEFT, padx=6, pady=6)
            ttk.Button(sf, text='Close', command=sdlg.destroy).pack(side=tk.RIGHT, padx=6, pady=6)
            search_var2.trace_add('write', lambda *a: refresh_stree())
            refresh_stree()

        def remove_selected_med():
            sel = meds_tree.selection()
            if not sel:
                messagebox.showinfo('Remove','Select an item to remove')
                return
            idx = int(sel[0])
            try:
                # pop the selected med and remove a matching line from the prescription text
                md = selected_meds.pop(idx)
            except Exception:
                md = None
            try:
                if md:
                    # remove ALL lines in prescription that contain the med name and a Qty: marker
                    full = presc_txt.get('1.0', tk.END)
                    lines = full.splitlines(True)
                    name = (md.get('Name') or '').strip()
                    try:
                        new_lines = []
                        for line in lines:
                            try:
                                if name and name in line and 'Qty:' in line:
                                    # skip this line (remove all matches)
                                    continue
                            except Exception:
                                pass
                            new_lines.append(line)
                        if len(new_lines) != len(lines):
                            presc_txt.delete('1.0', tk.END)
                            presc_txt.insert('1.0', ''.join(new_lines))
                    except Exception:
                        pass
            except Exception:
                pass
            refresh_meds_selection()

        ttk.Button(meds_btns, text='Add', command=open_medicine_search).pack(side=tk.LEFT, padx=6)
        ttk.Button(meds_btns, text='Remove', command=remove_selected_med).pack(side=tk.LEFT, padx=6)
        def add_pills_action():
            # Show a selection dialog listing medicines that match 'mother tincture' (case-insensitive)
            matches = []
            for m in self.medicines:
                name = (m.get('Name') or '').strip()
                cat = (m.get('Category') or '').strip()
                key = f"{name} {cat}".lower()
                if 'mother tincture' in key:
                    matches.append(m)

            if not matches:
                messagebox.showinfo('Pills', 'No mother tincture medicines found')
                return

            dlg = tk.Toplevel(top)
            dlg.title('Select Mother Tincture Medicines')
            dlg.geometry('560x360')
            frm = ttk.Frame(dlg, padding=6)
            frm.pack(fill=tk.BOTH, expand=True)

            cols = ('Name', 'Category', 'Price')
            mtree = ttk.Treeview(frm, columns=cols, show='headings', selectmode='extended')
            for c in cols:
                mtree.heading(c, text=c)
                mtree.column(c, width=160, anchor='w')
            mtree.pack(fill=tk.BOTH, expand=True)

            for m in matches:
                mid = (m.get('MedicineID') or '').strip()
                vals = (m.get('Name',''), m.get('Category',''), m.get('Price',''))
                if mid and mid not in mtree.get_children():
                    mtree.insert('', tk.END, iid=mid, values=vals)
                else:
                    mtree.insert('', tk.END, values=vals)

            btnf = ttk.Frame(dlg)
            btnf.pack(fill=tk.X)

            def do_add_selected():
                sel = mtree.selection()
                if not sel:
                    messagebox.showinfo('Select', 'Select one or more medicines to add')
                    return
                # add each selected med with default pill price 30.00 and Qty 1
                for mid in sel:
                    m = next((x for x in matches if (x.get('MedicineID') or '') == mid), None)
                    if not m:
                        # also check global list fallback
                        m = next((x for x in self.medicines if (x.get('MedicineID') or '') == mid), None)
                    if not m:
                        continue
                    name = (m.get('Name') or '').strip()
                    price = 30.0
                    selected_meds.append({'MedicineID': m.get('MedicineID',''), 'Name': name, 'Qty': 1.0, 'Price': price, 'Supplier': m.get('Supplier','')})
                    try:
                        presc_txt.insert(tk.END, f"{name}  Qty:1  Price:{price:.2f}\n")
                    except Exception:
                        pass

                refresh_meds_selection()
                try:
                    presc_txt.see(tk.END)
                except Exception:
                    pass
                try:
                    dlg.destroy()
                except Exception:
                    pass

            ttk.Button(btnf, text='Add Selected', command=do_add_selected).pack(side=tk.LEFT, padx=6, pady=6)
            ttk.Button(btnf, text='Close', command=dlg.destroy).pack(side=tk.RIGHT, padx=6, pady=6)

        ttk.Button(meds_btns, text='Pills', command=add_pills_action).pack(side=tk.LEFT, padx=6)

        ttk.Label(form, text="Notes:").grid(row=2, column=0, sticky='nw', pady=(6,0))
        notes_wrap = ttk.Frame(form)
        notes_wrap.grid(row=2, column=1, pady=(6,0), sticky='we')
        notes_txt = tk.Text(notes_wrap, width=60, height=3, wrap='word', font=('TkDefaultFont', 10), bg='white', fg='black')
        notes_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        try:
            ttk.Button(notes_wrap, text='Pen', width=6, command=lambda: self.open_handwriting_input(target_widget=notes_txt)).pack(side=tk.LEFT, padx=(6,0), pady=2)
        except Exception:
            pass

        ttk.Label(form, text="Total Fee:").grid(row=3, column=0, sticky='w', pady=(6,0))
        total_var = tk.StringVar()
        ttk.Entry(form, textvariable=total_var, width=16).grid(row=3, column=1, sticky='w', pady=(6,0))

        ttk.Label(form, text="Amount Paid:").grid(row=4, column=0, sticky='w', pady=(6,0))
        paid_var = tk.StringVar()
        ttk.Entry(form, textvariable=paid_var, width=16).grid(row=4, column=1, sticky='w', pady=(6,0))

        ttk.Label(form, text="Payment Method:").grid(row=3, column=1, sticky='e', padx=(0,120))
        pay_method = tk.StringVar(value='Cash')
        pm_combo = ttk.Combobox(form, textvariable=pay_method, values=('Cash','Card','Mobile','Due'), state='readonly', width=10)
        pm_combo.grid(row=3, column=1, sticky='e', padx=(0,12))

        ttk.Label(form, text="Due: ").grid(row=4, column=1, sticky='e', padx=(0,120))
        due_var = tk.StringVar(value='0.00')
        ttk.Label(form, textvariable=due_var).grid(row=4, column=1, sticky='e', padx=(0,12))

        # live update of Due as total/paid change
        def recalc_due(*args):
            try:
                tfv = float(total_var.get()) if total_var.get().strip() != '' else 0.0
            except Exception:
                tfv = 0.0
            try:
                pav = float(paid_var.get()) if paid_var.get().strip() != '' else 0.0
            except Exception:
                pav = 0.0
            if tfv > 0:
                due_var.set(f"{max(tfv - pav, 0.0):.2f}")
            else:
                due_var.set('0.00' if pav > 0 else '0.00')

        total_var.trace_add('write', recalc_due)
        paid_var.trace_add('write', recalc_due)

        btns = ttk.Frame(form)
        btns.grid(row=4, column=0, columnspan=2, pady=(10,0))

        def save_visit_action():
            date = date_var.get().strip()
            presc = presc_txt.get('1.0', tk.END).strip()
            notes = notes_txt.get('1.0', tk.END).strip()
            pay = paid_var.get().strip()
            total = total_var.get().strip()
            method = pay_method.get().strip()
            # basic validation
            if not presc:
                messagebox.showwarning('Validation','Please enter prescription text.')
                return
            # validate date
            try:
                datetime.strptime(date, '%Y-%m-%d')
            except Exception:
                messagebox.showwarning('Validation','Date must be YYYY-MM-DD')
                return
            # validate numeric fields
            if total:
                try:
                    float(total)
                except Exception:
                    messagebox.showwarning('Validation','Total fee must be a number')
                    return
            if pay:
                try:
                    float(pay)
                except Exception:
                    messagebox.showwarning('Validation','Amount paid must be a number')
                    return

            # determine payment status
            pstat = ''
            try:
                tfv = float(total) if total else 0.0
                pav = float(pay) if pay else 0.0
                if tfv > 0:
                    if pav >= tfv:
                        pstat = 'Paid'
                    elif pav > 0:
                        pstat = 'Partial'
                    else:
                        pstat = 'Due'
                else:
                    pstat = 'Paid' if pav > 0 else 'Due'
            except Exception:
                pstat = 'Due' if not pay else 'Paid'

            ok = self.append_visit(title, name, date, presc, notes, pay, method, total_fee=total, payment_status=pstat)
            if ok:
                # compute due to display
                try:
                    tfv = float(total) if total else 0.0
                except Exception:
                    tfv = 0.0
                try:
                    pav = float(pay) if pay else 0.0
                except Exception:
                    pav = 0.0
                due_display = f"{max(tfv - pav, 0.0):.2f}" if tfv > 0 else ('' if pav>0 else '')
                vtree.insert('', 0, values=(date, presc, notes, (f"{tfv:.2f}" if tfv else ''), (f"{pav:.2f}" if pav else ''), due_display, method, pstat))

                # If user explicitly selected medicines, use that list to deduct stock and record audit.
                try:
                    adjustments_made = False
                    if selected_meds:
                        patient_title = title
                        patient_name = name
                        for md in selected_meds:
                            mid = md.get('MedicineID','')
                            name_m = md.get('Name','')
                            qty = float(md.get('Qty',0))
                            price = float(md.get('Price',0))
                            # find medicine in inventory
                            m = next((x for x in self.medicines if x.get('MedicineID')==mid), None)
                            if not m:
                                continue
                            old_raw = (m.get('Quantity') or '').strip()
                            try:
                                oldv = float(old_raw) if old_raw != '' else 0.0
                            except Exception:
                                oldv = 0.0
                            newv = oldv - qty
                            # append audit entry
                            try:
                                adj_id = str(uuid.uuid4())
                                when = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                first_write = not os.path.exists(STOCK_ADJ_FILE)
                                with open(STOCK_ADJ_FILE, 'a', newline='', encoding='utf-8') as f:
                                    fieldnames = ['AdjustmentID','MedicineID','Name','Supplier','OldQty','Change','NewQty','Mode','Reason','Date','User']
                                    w = csv.DictWriter(f, fieldnames=fieldnames)
                                    if first_write:
                                        w.writeheader()
                                    reason = f"Sale (visit) to {patient_title} {patient_name} on {date}"
                                    change_val = -float(qty)
                                    w.writerow({'AdjustmentID': adj_id, 'MedicineID': mid, 'Name': name_m, 'Supplier': m.get('Supplier',''), 'OldQty': f"{oldv:.2f}", 'Change': f"{change_val:.2f}", 'NewQty': f"{newv:.2f}", 'Mode': 'sale', 'Reason': reason, 'Date': when, 'User': ''})
                            except Exception:
                                pass
                            # update in-memory quantity
                            if abs(newv - round(newv)) < 1e-9:
                                new_str = str(int(round(newv)))
                            else:
                                new_str = f"{newv:.2f}"
                            m['Quantity'] = new_str
                            adjustments_made = True
                        if adjustments_made:
                            try:
                                self.save_inventory()
                            except Exception:
                                pass
                except Exception:
                    pass

                # close the visit window after saving and return to landing page
                try:
                    messagebox.showinfo('Saved','Visit saved')
                except Exception:
                    pass
                try:
                    self._close_all_child_toplevels()
                except Exception:
                    try:
                        top.destroy()
                    except Exception:
                        pass

        ttk.Button(btns, text='Save Visit', command=save_visit_action).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text='Close', command=top.destroy).pack(side=tk.LEFT, padx=8)
        
    def open_handwriting_input(self, target_widget=None):
        """Open a simple pen/canvas dialog, OCR the strokes, and insert text into
        the given `target_widget` (a `tk.Text` or `tk.Entry`). If `target_widget`
        is None, the currently focused widget will be used.
        """
        try:
            # establish parent: prefer target_widget's toplevel if available
            parent = None
            try:
                if target_widget is not None:
                    parent = target_widget.winfo_toplevel()
            except Exception:
                parent = None
            if parent is None:
                parent = self
            dlg = tk.Toplevel(parent)
            dlg.title('Pen Input')
            # choose a reasonable default size and center over parent (not fullscreen)
            try:
                screen_w = dlg.winfo_screenwidth()
                screen_h = dlg.winfo_screenheight()
                # leave some room for taskbar and margins
                max_w = max(640, min(1000, screen_w - 200))
                max_h = max(360, min(700, screen_h - 200))
                # try to center over parent
                try:
                    parent.update_idletasks()
                    px = parent.winfo_rootx()
                    py = parent.winfo_rooty()
                    pw = parent.winfo_width() or (screen_w // 2)
                    ph = parent.winfo_height() or (screen_h // 2)
                    x = px + max(20, (pw - max_w) // 2)
                    y = py + max(20, (ph - max_h) // 2)
                except Exception:
                    x = max(20, (screen_w - max_w) // 2)
                    y = max(20, (screen_h - max_h) // 2)
                dlg.geometry(f"{max_w}x{max_h}+{x}+{y}")
                dlg.minsize(400, 240)
                dlg.resizable(True, True)
                # Post-map enforcement: some window managers may override geometry
                def _enforce_size():
                    try:
                        dlg.update_idletasks()
                        try:
                            dlg.state('normal')
                        except Exception:
                            pass
                        try:
                            dlg.attributes('-fullscreen', False)
                        except Exception:
                            pass
                        try:
                            dlg.attributes('-zoomed', False)
                        except Exception:
                            pass
                        dlg.geometry(f"{max_w}x{max_h}+{x}+{y}")
                        try:
                            dlg.lift()
                        except Exception:
                            pass
                    except Exception:
                        pass
                try:
                    dlg.after(120, _enforce_size)
                except Exception:
                    pass
            except Exception:
                try:
                    dlg.geometry('640x420')
                except Exception:
                    pass
            try:
                dlg.transient(parent)
            except Exception:
                pass
            # Force non-maximized state and disable fullscreen attributes where possible
            try:
                dlg.update_idletasks()
                try:
                    dlg.state('normal')
                except Exception:
                    pass
                try:
                    dlg.attributes('-fullscreen', False)
                except Exception:
                    pass
                try:
                    dlg.attributes('-zoomed', False)
                except Exception:
                    pass
            except Exception:
                pass
            try:
                # ensure modal behavior but avoid maximizing the dialog
                self.make_modal(dlg, parent=parent)
            except Exception:
                pass
            try:
                dlg.lift()
            except Exception:
                pass
            # drawing canvas
            c = tk.Canvas(dlg, bg='white', highlightthickness=1)
            c.pack(fill=tk.BOTH, expand=True)

            strokes = []
            last = {'x': None, 'y': None}

            def on_down(ev):
                last['x'], last['y'] = ev.x, ev.y

            def on_move(ev):
                x, y = ev.x, ev.y
                if last['x'] is not None and last['y'] is not None:
                    try:
                        c.create_line(last['x'], last['y'], x, y, width=3, capstyle='round', smooth=True)
                        strokes.append((last['x'], last['y'], x, y))
                    except Exception:
                        pass
                last['x'], last['y'] = x, y

            def on_up(ev):
                last['x'], last['y'] = None, None

            c.bind('<Button-1>', on_down)
            c.bind('<B1-Motion>', on_move)
            c.bind('<ButtonRelease-1>', on_up)

            # controls
            ctrl = ttk.Frame(dlg)
            ctrl.pack(fill=tk.X)

            def do_clear():
                try:
                    c.delete('all')
                    strokes.clear()
                except Exception:
                    pass

            def do_convert():
                if not OCR_AVAILABLE:
                    messagebox.showerror('OCR Not Available', 'Tesseract/pytesseract not available on this system.')
                    return
                try:
                    c.update_idletasks()
                    w = max(c.winfo_width(), 10)
                    h = max(c.winfo_height(), 10)
                    img = Image.new('RGB', (w, h), 'white')
                    draw = ImageDraw.Draw(img)
                    if strokes:
                        for seg in strokes:
                            try:
                                draw.line(seg, fill='black', width=6)
                            except Exception:
                                pass
                    else:
                        # Fallback: capture the canvas contents from screen if possible
                        try:
                            from PIL import ImageGrab
                            # compute absolute bbox of canvas
                            x0 = c.winfo_rootx()
                            y0 = c.winfo_rooty()
                            x1 = x0 + c.winfo_width()
                            y1 = y0 + c.winfo_height()
                            grab = ImageGrab.grab(bbox=(x0, y0, x1, y1))
                            # convert to white-background RGB
                            img = Image.new('RGB', grab.size, 'white')
                            img.paste(grab)
                            draw = ImageDraw.Draw(img)
                        except Exception:
                            # as last resort, continue with blank image
                            pass
                    # optional crop to content bbox
                    try:
                        bbox = img.convert('L').point(lambda p: 255 if p < 250 else 0).getbbox()
                        if bbox:
                            img = img.crop(bbox)
                    except Exception:
                        pass
                    # OCR
                    try:
                        # Preprocess image for better handwriting OCR:
                        proc = img.convert('L')
                        try:
                            from PIL import ImageOps, ImageFilter, ImageEnhance
                        except Exception:
                            ImageOps = None
                            ImageFilter = None
                            ImageEnhance = None
                        try:
                            if ImageEnhance is not None:
                                proc = ImageEnhance.Contrast(proc).enhance(2.0)
                                proc = ImageEnhance.Sharpness(proc).enhance(1.5)
                        except Exception:
                            pass
                        try:
                            # threshold to black/white to strengthen strokes
                            proc = proc.point(lambda p: 0 if p < 200 else 255)
                        except Exception:
                            pass
                        try:
                            # scale up for tesseract
                            scale = 3
                            proc = proc.resize((max(100, proc.width * scale), max(40, proc.height * scale)), resample=Image.BICUBIC)
                        except Exception:
                            pass
                        try:
                            if ImageFilter is not None:
                                proc = proc.filter(ImageFilter.MedianFilter(size=3))
                        except Exception:
                            pass

                        # try a few tesseract modes suitable for short handwritten phrases
                        text = ''
                        try:
                            text = pytesseract.image_to_string(proc, config='--psm 6') or ''
                        except Exception:
                            text = ''
                        if not text.strip():
                            try:
                                text = pytesseract.image_to_string(proc, config='--psm 11') or ''
                            except Exception:
                                text = ''
                        if not text.strip():
                            try:
                                text = pytesseract.image_to_string(proc, config='--psm 7') or ''
                            except Exception:
                                text = ''
                        # final fallback: original image
                        if not text.strip():
                            try:
                                text = pytesseract.image_to_string(img) or ''
                            except Exception:
                                text = ''
                        if not text or not str(text).strip():
                            # if still empty, inform user and return
                            try:
                                # write debug log that OCR returned empty
                                log_path = os.path.join(STORAGE_DIR, 'pen_debug.txt')
                                with open(log_path, 'a', encoding='utf-8') as _lf:
                                    _lf.write('--- PEN DEBUG OCR EMPTY ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '\n')
                                    _lf.write('Proc size: %dx%d img size: %dx%d\n' % (proc.width if hasattr(proc,'width') else 0, proc.height if hasattr(proc,'height') else 0, img.width, img.height))
                                    _lf.write('\n')
                            except Exception:
                                pass
                            messagebox.showinfo('No Text', 'No text detected. Try writing more clearly, heavier strokes, or write larger.')
                            return
                    except Exception as e:
                        messagebox.showerror('OCR Error', f'OCR failed: {e}')
                        return
                    if not text or not str(text).strip():
                        messagebox.showinfo('No Text', 'No text detected. Try writing more clearly or heavier strokes.')
                        return
                    # Attempt direct insertion first (best-effort) then show preview for edit
                    try:
                        tgt_direct = target_widget
                        if tgt_direct is None:
                            try:
                                tgt_direct = self.focus_get()
                            except Exception:
                                tgt_direct = None
                        if tgt_direct is not None:
                            try:
                                if isinstance(tgt_direct, tk.Text):
                                    try:
                                        tgt_direct.insert(tk.INSERT, text)
                                    except Exception:
                                        tgt_direct.insert('end', text)
                                    try:
                                        tgt_direct.configure(font=('Times New Roman', 11))
                                    except Exception:
                                        pass
                                elif isinstance(tgt_direct, tk.Entry):
                                    try:
                                        cur = tgt_direct.index(tk.INSERT)
                                    except Exception:
                                        cur = tk.END
                                    try:
                                        tgt_direct.insert(cur, text.strip())
                                    except Exception:
                                        try:
                                            tgt_direct.insert(0, text.strip())
                                        except Exception:
                                            pass
                                    try:
                                        tgt_direct.configure(font=('Times New Roman', 11))
                                    except Exception:
                                        pass
                                # notify user briefly that insertion was attempted
                                try:
                                    messagebox.showinfo('Pen Input', 'Inserted recognized text into the active field.')
                                except Exception:
                                    pass
                            except Exception:
                                pass

                    except Exception:
                        pass

                    # Show recognized text to user for confirmation/edit before inserting
                    try:
                        preview = tk.Toplevel(dlg)
                        preview.title('Recognized Text — Confirm')
                        preview.geometry('480x320')
                        try:
                            preview.deiconify(); preview.lift(); preview.focus_force()
                        except Exception:
                            pass
                        try:
                            preview.transient(dlg)
                        except Exception:
                            pass
                        try:
                            self.make_modal(preview, parent=dlg)
                        except Exception:
                            pass
                        txt_preview = tk.Text(preview, wrap='word', font=('Times New Roman', 12))
                        txt_preview.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
                        txt_preview.insert('1.0', text)
                        try:
                            # write debug log that OCR produced text and preview created
                            log_path = os.path.join(STORAGE_DIR, 'pen_debug.txt')
                            with open(log_path, 'a', encoding='utf-8') as _lf:
                                _lf.write('--- PEN DEBUG OCR RESULT ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '\n')
                                _lf.write(text + '\n\n')
                        except Exception:
                            pass
                        # buttons
                        def do_insert_preview():
                            val = txt_preview.get('1.0', 'end').rstrip()
                            try:
                                tgt = target_widget or self.focus_get()
                            except Exception:
                                tgt = target_widget

                            # DEBUG: show OCR and target widget info before insertion
                            # write persistent debug log so we can inspect even if dialogs get blocked
                            try:
                                log_path = os.path.join(STORAGE_DIR, 'pen_debug.txt')
                                ws_path = os.path.join(os.path.dirname(__file__), 'pen_debug_workspace.txt')
                                for path in (log_path, ws_path):
                                    try:
                                        with open(path, 'a', encoding='utf-8') as _lf:
                                            _lf.write('--- PEN DEBUG ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '\n')
                                            _lf.write('OCR:\n')
                                            _lf.write(val + '\n')
                                            try:
                                                _lf.write('Target repr: ' + repr(tgt) + '\n')
                                            except Exception:
                                                _lf.write('Target repr: <unreprable>\n')
                                            try:
                                                _lf.write('Type: ' + str(type(tgt)) + '\n')
                                            except Exception:
                                                pass
                                            try:
                                                _lf.write('Is Text: ' + str(isinstance(tgt, tk.Text)) + '\n')
                                            except Exception:
                                                pass
                                            try:
                                                _lf.write('Is Entry: ' + str(isinstance(tgt, tk.Entry)) + '\n')
                                            except Exception:
                                                pass
                                            try:
                                                st = tgt.cget('state')
                                                _lf.write('State: ' + str(st) + '\n')
                                            except Exception:
                                                _lf.write('State: <unknown>\n')
                                            try:
                                                f = self.focus_get()
                                                _lf.write('Focus repr: ' + repr(f) + '\n')
                                            except Exception:
                                                pass
                                            try:
                                                _lf.write('Main geometry: ' + self.geometry() + '\n')
                                            except Exception:
                                                pass
                                            try:
                                                _lf.write('Dlg geometry: ' + dlg.geometry() + '\n')
                                            except Exception:
                                                pass
                                            _lf.write('\n')
                                    except Exception:
                                        pass
                                try:
                                    messagebox.showinfo('Debug saved', f'Pen debug written to: {log_path} and {ws_path}')
                                except Exception:
                                    pass
                            except Exception:
                                pass

                            def _perform_insert():
                                try:
                                    if isinstance(tgt, tk.Text):
                                        try:
                                            tgt.focus_set()
                                        except Exception:
                                            pass
                                        tgt.insert(tk.INSERT, val)
                                        try:
                                            tgt.configure(font=('Times New Roman', 11))
                                        except Exception:
                                            pass
                                    elif isinstance(tgt, tk.Entry):
                                        try:
                                            tgt.focus_set()
                                        except Exception:
                                            pass
                                        try:
                                            cur = tgt.index(tk.INSERT)
                                        except Exception:
                                            cur = tk.END
                                        tgt.insert(cur, val)
                                        try:
                                            tgt.configure(font=('Times New Roman', 11))
                                        except Exception:
                                            pass
                                    else:
                                        try:
                                            self.clipboard_clear(); self.clipboard_append(val)
                                            messagebox.showinfo('Text Copied', 'Recognized text copied to clipboard.')
                                        except Exception:
                                            pass
                                except Exception:
                                    try:
                                        messagebox.showerror('Insert Error', 'Failed to insert text into target.')
                                    except Exception:
                                        pass

                            try:
                                # destroy preview first so grab is released, then perform insertion on parent
                                preview.destroy()
                            except Exception:
                                pass
                            try:
                                # schedule insertion slightly later on the main loop of the parent dlg
                                try:
                                    dlg.after(50, _perform_insert)
                                except Exception:
                                    # fallback to self.after
                                    self.after(50, _perform_insert)
                            except Exception:
                                _perform_insert()
                            finally:
                                try:
                                    dlg.destroy()
                                except Exception:
                                    pass

                        def do_cancel_preview():
                            try:
                                preview.destroy()
                            except Exception:
                                pass

                        btnf = ttk.Frame(preview)
                        btnf.pack(fill=tk.X)
                        ttk.Button(btnf, text='Insert', command=do_insert_preview).pack(side=tk.RIGHT, padx=6, pady=6)
                        ttk.Button(btnf, text='Cancel', command=do_cancel_preview).pack(side=tk.RIGHT, padx=6, pady=6)
                        # return control to user; do not auto-close dlg yet
                        return
                    except Exception:
                        # if preview fails, fall back to direct insertion
                        pass
                    # determine target widget
                    tgt = target_widget
                    if tgt is None:
                        try:
                            tgt = self.focus_get()
                        except Exception:
                            tgt = None
                    # insert appropriately
                    try:
                        if isinstance(tgt, tk.Text):
                            try:
                                # insert preserving current selection/insertion point
                                try:
                                    tgt.insert(tk.INSERT, text)
                                except Exception:
                                    tgt.insert('end', text)
                                try:
                                    tgt.configure(font=('Times New Roman', 11))
                                except Exception:
                                    pass
                            except Exception:
                                tgt.insert('end', text)
                        elif isinstance(tgt, tk.Entry):
                            try:
                                cur = tgt.index(tk.INSERT)
                            except Exception:
                                cur = tk.END
                            try:
                                tgt.insert(cur, text.strip())
                                try:
                                    tgt.config(font=('Times New Roman', 11))
                                except Exception:
                                    pass
                            except Exception:
                                try:
                                    tgt.insert(0, text.strip())
                                except Exception:
                                    pass
                        else:
                            # fallback: if target is None or unknown, copy to clipboard and show
                            try:
                                self.clipboard_clear(); self.clipboard_append(text)
                            except Exception:
                                pass
                            messagebox.showinfo('Text Copied', 'Recognized text copied to clipboard.')
                    except Exception:
                        try:
                            messagebox.showerror('Insert Error', 'Failed to insert recognized text into the target field.')
                        except Exception:
                            pass
                finally:
                    try:
                        dlg.destroy()
                    except Exception:
                        pass

            ttk.Button(ctrl, text='Clear', command=do_clear).pack(side=tk.LEFT, padx=6, pady=6)
            ttk.Button(ctrl, text='Convert & Insert', command=do_convert).pack(side=tk.LEFT, padx=6, pady=6)
            ttk.Button(ctrl, text='Close', command=dlg.destroy).pack(side=tk.RIGHT, padx=6, pady=6)

        except Exception as e:
            try:
                messagebox.showerror('Pen Input Error', f'Failed to open pen input: {e}')
            except Exception:
                pass

    def open_payments_summary_window(self):
        """Open a window that aggregates payments per day for a selected date range (max 12 months).

        Require security code authorization before showing payments.
        """
        # require authorization
        try:
            if not self.ensure_payments_authorized():
                return
        except Exception:
            return
        top = tk.Toplevel(self)
        self.maximize_window(top)
        top.title("Payments Summary")
        top.geometry("620x480")

        ctrl = ttk.Frame(top, padding=8)
        ctrl.pack(fill=tk.X)

        ttk.Label(ctrl, text="From (YYYY-MM-DD):").pack(side=tk.LEFT)
        from_var = tk.StringVar(value=(datetime.today().replace(day=1)).strftime('%Y-%m-%d'))
        ttk.Entry(ctrl, textvariable=from_var, width=14).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(ctrl, text='Pick', width=4, command=lambda: self.pick_date(top, from_var)).pack(side=tk.LEFT, padx=(6,12))

        ttk.Label(ctrl, text="To (YYYY-MM-DD):").pack(side=tk.LEFT)
        to_var = tk.StringVar(value=datetime.today().strftime('%Y-%m-%d'))
        ttk.Entry(ctrl, textvariable=to_var, width=14).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(ctrl, text='Pick', width=4, command=lambda: self.pick_date(top, to_var)).pack(side=tk.LEFT, padx=(6,12))

        # Aggregation selector: Daily or Monthly
        ttk.Label(ctrl, text="Aggregate:").pack(side=tk.LEFT)
        agg_var = tk.StringVar(value='Daily')
        agg_combo = ttk.Combobox(ctrl, textvariable=agg_var, values=('Daily','Monthly'), state='readonly', width=10)
        agg_combo.pack(side=tk.LEFT, padx=(6,12))

        def show_summary():
            # parse dates
            try:
                dfrom = datetime.strptime(from_var.get().strip(), '%Y-%m-%d')
                dto = datetime.strptime(to_var.get().strip(), '%Y-%m-%d')
            except Exception:
                messagebox.showwarning('Date Error', 'Dates must be in YYYY-MM-DD format')
                return
            if dfrom > dto:
                messagebox.showwarning('Date Error', 'From date must be before To date')
                return
            # enforce max span: 20 years (~20*366 days)
            max_days = 20 * 366
            if (dto - dfrom).days > max_days:
                messagebox.showwarning('Range Error', 'Please select a range of 20 years or less')
                return

            # aggregate payments per day
            totals = {}
            if os.path.exists(VISITS_FILE):
                try:
                    with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for r in reader:
                            dt = r.get('Date','').strip()
                            if not dt:
                                continue
                            try:
                                d = datetime.strptime(dt, '%Y-%m-%d')
                            except Exception:
                                continue
                            if d < dfrom or d > dto:
                                continue
                            amt = r.get('PaymentAmount','').strip()
                            if not amt:
                                continue
                            try:
                                a = float(amt)
                            except Exception:
                                continue
                            if agg_var.get() == 'Monthly':
                                key = d.strftime('%Y-%m')
                            else:
                                key = dt  # daily key as YYYY-MM-DD
                            totals[key] = totals.get(key, 0.0) + a
                except Exception as e:
                    messagebox.showerror('Error', f'Failed to read visits: {e}')
                    return

            # clear tree
            for i in pay_tree.get_children():
                pay_tree.delete(i)

            # populate sorted by period ascending
            total_sum = 0.0
            if agg_var.get() == 'Monthly':
                # keys are YYYY-MM; sort by year-month
                for key in sorted(totals.keys()):
                    amt = totals[key]
                    # display as 'Mon YYYY'
                    try:
                        dkey = datetime.strptime(key + '-01', '%Y-%m-%d')
                        display = dkey.strftime('%b %Y')
                    except Exception:
                        display = key
                    pay_tree.insert('', tk.END, values=(display, f"{amt:.2f}"))
                    total_sum += amt
            else:
                for date_key in sorted(totals.keys()):
                    amt = totals[date_key]
                    pay_tree.insert('', tk.END, values=(date_key, f"{amt:.2f}"))
                    total_sum += amt

            total_var.set(f"Total: {total_sum:.2f}")

        ttk.Button(ctrl, text='Show', command=show_summary).pack(side=tk.LEFT, padx=6)
        ttk.Button(ctrl, text='Close', command=top.destroy).pack(side=tk.RIGHT)

        # results
        res_frame = ttk.Frame(top, padding=8)
        res_frame.pack(fill=tk.BOTH, expand=True)

        cols = ('Date','TotalReceived')
        pay_tree = ttk.Treeview(res_frame, columns=cols, show='headings')
        pay_tree.heading('Date', text='Date', anchor='w')
        pay_tree.heading('TotalReceived', text='Total Received', anchor='w')
        pay_tree.column('Date', width=120, anchor='w')
        pay_tree.column('TotalReceived', width=120, anchor='w')
        pay_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        s = ttk.Scrollbar(res_frame, orient=tk.VERTICAL, command=pay_tree.yview)
        pay_tree.configure(yscroll=s.set)
        s.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.Frame(top, padding=8)
        bottom.pack(fill=tk.X)
        total_var = tk.StringVar(value='Total: 0.00')
        ttk.Label(bottom, textvariable=total_var, font=('TkDefaultFont', 11, 'bold')).pack(side=tk.RIGHT)

        # auto-show for default dates
        show_summary()

    # --- Admin / Inventory Stubs ---
    def ensure_payments_authorized(self):
        """Return True if user is authorized to view payment summaries.

        If no security code exists, offer to create one. If code exists, prompt for code
        and support 'Forgot' which validates security questions (case-sensitive answers).
        """
        sec = _load_security()
        # no security configured -> ask to create
        if not sec or 'code_hash' not in sec:
            create = messagebox.askyesno('Security Setup', 'No security code set.\nDo you want to create a security code now?')
            if not create:
                return False
            return self.create_security_window()

        # prompt for code
        return self._prompt_code_dialog()

    def create_security_window(self):
        top = tk.Toplevel(self)
        top.transient(self)
        top.title('Create Security Code')
        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text='Enter new security code:').grid(row=0, column=0, sticky='w')
        code_var = tk.StringVar()
        ttk.Entry(frm, textvariable=code_var, show='*').grid(row=0, column=1, sticky='ew')

        ttk.Label(frm, text='Confirm code:').grid(row=1, column=0, sticky='w')
        confirm_var = tk.StringVar()
        ttk.Entry(frm, textvariable=confirm_var, show='*').grid(row=1, column=1, sticky='ew')

        ttk.Separator(frm).grid(row=2, column=0, columnspan=2, sticky='ew', pady=6)
        ttk.Label(frm, text='Security Question 1:').grid(row=3, column=0, sticky='w')
        q1_var = tk.StringVar(value='What is your mother\'s maiden name?')
        ttk.Entry(frm, textvariable=q1_var).grid(row=3, column=1, sticky='ew')
        ttk.Label(frm, text='Answer 1 (case sensitive):').grid(row=4, column=0, sticky='w')
        a1_var = tk.StringVar()
        ttk.Entry(frm, textvariable=a1_var, show='').grid(row=4, column=1, sticky='ew')

        ttk.Label(frm, text='Security Question 2:').grid(row=5, column=0, sticky='w')
        q2_var = tk.StringVar(value='What was the name of your first school?')
        ttk.Entry(frm, textvariable=q2_var).grid(row=5, column=1, sticky='ew')
        ttk.Label(frm, text='Answer 2 (case sensitive):').grid(row=6, column=0, sticky='w')
        a2_var = tk.StringVar()
        ttk.Entry(frm, textvariable=a2_var, show='').grid(row=6, column=1, sticky='ew')

        def do_create():
            code = (code_var.get() or '').strip()
            conf = (confirm_var.get() or '').strip()
            if not code:
                messagebox.showwarning('Input', 'Enter a security code')
                return
            if code != conf:
                messagebox.showwarning('Input', 'Code and confirmation do not match')
                return
            qlist = []
            qlist.append({'q': q1_var.get() or '', 'a': a1_var.get() or ''})
            qlist.append({'q': q2_var.get() or '', 'a': a2_var.get() or ''})
            if not _set_new_code(code, qlist):
                messagebox.showerror('Error', 'Failed to save security data')
                return
            messagebox.showinfo('Saved', 'Security code created')
            try:
                self._close_all_child_toplevels()
            except Exception:
                try:
                    top.destroy()
                except Exception:
                    pass
            return True

        btns = ttk.Frame(frm)
        btns.grid(row=7, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text='Create', command=do_create).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Cancel', command=top.destroy).pack(side=tk.LEFT, padx=6)

        frm.columnconfigure(1, weight=1)
        self.wait_window(top)
        # reload and return True if now set
        sec2 = _load_security()
        return bool(sec2 and 'code_hash' in sec2)

    def _prompt_code_dialog(self):
        sec = _load_security()
        if not sec:
            return False
        top = tk.Toplevel(self)
        top.transient(self)
        top.title('Enter Security Code')
        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text='Security code:').grid(row=0, column=0, sticky='w')
        code_var = tk.StringVar()
        e = ttk.Entry(frm, textvariable=code_var, show='*')
        e.grid(row=0, column=1, sticky='ew')

        result = {'ok': False}

        def do_ok():
            if _verify_code(code_var.get()):
                result['ok'] = True
                top.destroy()
            else:
                messagebox.showerror('Invalid', 'Security code incorrect')

        def do_forgot():
            top.destroy()
            if self._forgot_flow():
                # allow immediate set of new code
                self.create_security_window()

        btns = ttk.Frame(frm)
        btns.grid(row=1, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text='OK', command=do_ok).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Forgot', command=do_forgot).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Cancel', command=top.destroy).pack(side=tk.LEFT, padx=6)

        frm.columnconfigure(1, weight=1)
        e.focus_set()
        self.wait_window(top)
        return result['ok']

    def _forgot_flow(self):
        sec = _load_security()
        if not sec or 'questions' not in sec:
            messagebox.showinfo('No Security', 'No security questions configured')
            return False
        top = tk.Toplevel(self)
        top.transient(self)
        top.title('Forgot Security Code')
        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        answers = []
        entries = []
        for i, qa in enumerate(sec.get('questions', [])[:4]):
            ttk.Label(frm, text=qa.get('q','')).grid(row=2*i, column=0, sticky='w')
            var = tk.StringVar()
            ttk.Entry(frm, textvariable=var, show='').grid(row=2*i, column=1, sticky='ew')
            entries.append((qa.get('a',''), var))

        def do_check():
            for correct, var in entries:
                if var.get() != correct:
                    messagebox.showerror('Incorrect', 'One or more answers are incorrect (case-sensitive)')
                    return
            messagebox.showinfo('Verified', 'Security answers verified — you may set a new security code')
            top.destroy()
            return True

        btns = ttk.Frame(frm)
        btns.grid(row=2*len(entries), column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text='Verify', command=do_check).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Cancel', command=top.destroy).pack(side=tk.LEFT, padx=6)
        frm.columnconfigure(1, weight=1)
        self.wait_window(top)
        # If window destroyed by do_check, we assume success (user will set code next)
        # Check whether security still has same code (we return True if window closed normally and user verified)
        return True

    def open_shift_history(self):
        """Open Shift History window. Allows starting/ending shifts and viewing a list.

        Shifts are stored in `shifts.csv` with fields: ShiftID,Operator,Start,End,Notes
        The window also computes a simple payments summary by summing `PaymentAmount` from
        `VISITS_FILE` for visit dates that fall between shift start.date() and end.date()
        (inclusive). This is an approximation when VISITS have no timestamps.
        """
        top = tk.Toplevel(self)
        self.maximize_window(top)
        top.title("Shift History")
        top.geometry('760x420')

        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        # controls: operator, notes, start
        ctrl = ttk.Frame(frm)
        ctrl.pack(fill=tk.X)
        ttk.Label(ctrl, text='Operator:').pack(side=tk.LEFT)
        # Single operator clinic: prefill operator name and make readonly (doctor can start directly)
        op_var = tk.StringVar(value='Dr.Fakhir')
        op_entry = ttk.Entry(ctrl, textvariable=op_var, width=20, state='readonly')
        op_entry.pack(side=tk.LEFT, padx=(6,12))
        ttk.Label(ctrl, text='Notes:').pack(side=tk.LEFT)
        # Prefill notes with today's date to record shift start date and keep readonly
        notes_var = tk.StringVar(value=datetime.today().strftime('%Y-%m-%d'))
        notes_entry = ttk.Entry(ctrl, textvariable=notes_var, width=36, state='readonly')
        notes_entry.pack(side=tk.LEFT, padx=(6,12))
        def do_start():
            # Operator and notes are prefilled. Use defaults if somehow empty so Start is instantaneous.
            op = (op_var.get().strip() or 'Dr.Fakhir')
            notes = (notes_var.get().strip() or datetime.today().strftime('%Y-%m-%d'))
            sid = str(uuid.uuid4())
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            first = not os.path.exists(SHIFTS_FILE)
            try:
                # compute current visit count as a marker so shift summaries include only visits added after this point
                try:
                    visit_count = 0
                    if os.path.exists(VISITS_FILE):
                        with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as vf:
                            vr = csv.DictReader(vf)
                            for _ in vr:
                                visit_count += 1
                except Exception:
                    visit_count = 0
                with open(SHIFTS_FILE, 'a', newline='', encoding='utf-8') as f:
                    fieldnames = ['ShiftID','Operator','Start','End','Notes','Marker','EndMarker','Clinic']
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    if first:
                        w.writeheader()
                    w.writerow({'ShiftID': sid, 'Operator': op, 'Start': now, 'End': '', 'Notes': notes, 'Marker': str(visit_count), 'EndMarker': '', 'Clinic': getattr(self, 'current_clinic', '')})
            except Exception as e:
                messagebox.showerror('Save','Failed to start shift: ' + str(e), parent=top)
                return
            op_var.set('')
            notes_var.set('')
            refresh()

        ttk.Button(ctrl, text='Start Shift', command=do_start).pack(side=tk.LEFT, padx=6)
        ttk.Button(ctrl, text='Refresh', command=lambda: refresh()).pack(side=tk.LEFT, padx=6)

        # treeview
        cols = ('ShiftID','Operator','Start','End','Duration','Visits','Patients','TotalReceived','Dues','Stockouts','Notes')
        tree = ttk.Treeview(frm, columns=cols, show='headings')
        for c in cols:
            tree.heading(c, text=c, anchor='w')
        tree.column('ShiftID', width=0, stretch=False)
        tree.column('Operator', width=120, anchor='w')
        tree.column('Start', width=140, anchor='w')
        tree.column('End', width=140, anchor='w')
        tree.column('Duration', width=100, anchor='w')
        tree.column('Visits', width=70, anchor='w')
        tree.column('Patients', width=70, anchor='w')
        tree.column('TotalReceived', width=110, anchor='w')
        tree.column('Dues', width=100, anchor='w')
        tree.column('Stockouts', width=90, anchor='w')
        tree.column('Notes', width=160, anchor='w')
        tree.pack(fill=tk.BOTH, expand=True, pady=(8,0))

        vs = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=vs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)

        def read_shifts():
            rows = []
            if not os.path.exists(SHIFTS_FILE):
                return rows
            try:
                        with open(SHIFTS_FILE, 'r', newline='', encoding='utf-8') as f:
                            rdr = csv.DictReader(f)
                            fnames = rdr.fieldnames or []
                            has_clinic_field = any((n or '').strip().lower() == 'clinic' for n in fnames)
                            for r in rdr:
                                if has_clinic_field:
                                    clinic_val = (r.get('Clinic') or '').strip()
                                    # include rows for the current clinic; also include blank Clinic values
                                    if clinic_val == getattr(self, 'current_clinic', '') or clinic_val == '':
                                        rows.append(r)
                                else:
                                    # legacy file with no Clinic column: treat as clinic-specific
                                    rows.append(r)
            except Exception:
                return []
            return rows

        def compute_shift_metrics(start_s, end_s, start_marker=None, end_marker=None):
            # Returns (visit_count, total_payments, unique_patients_count, total_dues)
            try:
                start_dt = datetime.strptime(start_s, '%Y-%m-%d %H:%M:%S') if start_s else None
            except Exception:
                start_dt = None
            try:
                end_dt = datetime.strptime(end_s, '%Y-%m-%d %H:%M:%S') if end_s else None
            except Exception:
                end_dt = None
            total = 0.0
            count = 0
            patients = set()
            dues_total = 0.0
            if not os.path.exists(VISITS_FILE):
                return count, total, 0, 0.0
            try:
                with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    for idx, r in enumerate(rdr):
                        # if a start_marker (visit-row-count at shift start) was recorded, skip earlier rows
                        try:
                            sm = None
                            em = None
                            if start_marker is not None and str(start_marker).strip() != '':
                                try:
                                    sm = int(start_marker)
                                except Exception:
                                    sm = None
                            if end_marker is not None and str(end_marker).strip() != '':
                                try:
                                    em = int(end_marker)
                                except Exception:
                                    em = None
                            # if start marker present skip rows before it
                            if sm is not None and idx < sm:
                                continue
                            # if end marker present stop at it (exclude rows >= em)
                            if em is not None and idx >= em:
                                continue
                        except Exception:
                            pass
                        d = (r.get('Date') or '').strip()
                        if not d:
                            continue
                        try:
                            vd = datetime.strptime(d, '%Y-%m-%d')
                        except Exception:
                            continue
                        # include by date between start.date and end.date
                        include = True
                        if start_dt and vd.date() < start_dt.date():
                            include = False
                        if end_dt and vd.date() > end_dt.date():
                            include = False
                        if not include:
                            continue
                        # count visit
                        count += 1
                        name = (r.get('Name') or '').strip()
                        title = (r.get('Title') or '').strip()
                        patients.add((title.lower(), name.lower()))
                        pay = (r.get('PaymentAmount') or '').strip()
                        try:
                            pv = float(pay) if pay != '' else 0.0
                        except Exception:
                            pv = 0.0
                        total += pv
                        # compute due for this visit
                        tf = (r.get('TotalFee') or '').strip()
                        try:
                            tfv = float(tf) if tf != '' else 0.0
                        except Exception:
                            tfv = 0.0
                        due_here = 0.0
                        if tfv > 0:
                            due_here = max(tfv - (pv or 0.0), 0.0)
                        dues_total += due_here
            except Exception:
                pass
            return count, total, len(patients), dues_total

        def refresh():
            for i in tree.get_children():
                tree.delete(i)
            shifts = read_shifts()
            # sort by Start desc
            try:
                shifts.sort(key=lambda r: datetime.strptime(r.get('Start','') or '1970-01-01 00:00:00','%Y-%m-%d %H:%M:%S'), reverse=True)
            except Exception:
                pass
            for s in shifts:
                sid = s.get('ShiftID','')
                op = s.get('Operator','')
                start = s.get('Start','')
                end = s.get('End','')
                notes = s.get('Notes','')
                # compute duration
                dur = ''
                if start and end:
                    try:
                        sd = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
                        ed = datetime.strptime(end, '%Y-%m-%d %H:%M:%S')
                        delta = ed - sd
                        mins = int(delta.total_seconds() // 60)
                        dur = f"{mins} min"
                    except Exception:
                        dur = ''
                elif start and not end:
                    try:
                        sd = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
                        delta = datetime.now() - sd
                        mins = int(delta.total_seconds() // 60)
                        dur = f"{mins} min (open)"
                    except Exception:
                        dur = ''
                marker = s.get('Marker','')
                end_marker = s.get('EndMarker','')
                visits, total, patients_count, dues_total = compute_shift_metrics(start, end, start_marker=marker, end_marker=end_marker)
                # compute stockouts / low stock from current inventory snapshot
                low_count = 0
                try:
                    for m in self.medicines:
                        try:
                            q = float((m.get('Quantity') or '').strip()) if (m.get('Quantity') or '').strip() != '' else 0.0
                        except Exception:
                            q = 0.0
                        try:
                            rl = float((m.get('ReorderLevel') or '').strip()) if (m.get('ReorderLevel') or '').strip() != '' else None
                        except Exception:
                            rl = None
                        if q <= 0:
                            low_count += 1
                        elif rl is not None and q < rl:
                            low_count += 1
                except Exception:
                    low_count = 0
                tree.insert('', tk.END, iid=sid, values=(sid, op, start, end, dur, str(visits), str(patients_count), f"{total:.2f}", f"{dues_total:.2f}", str(low_count), notes))

        def do_end():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('End','Select a shift to end', parent=top)
                return
            sid = sel[0]
            shifts = read_shifts()
            found = False
            for r in shifts:
                if r.get('ShiftID') == sid:
                    if r.get('End'):
                        messagebox.showinfo('End','Shift already ended', parent=top)
                        return
                    r['End'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    # record end marker as visit count at this moment
                    try:
                        end_count = 0
                        if os.path.exists(VISITS_FILE):
                            with open(VISITS_FILE, 'r', newline='', encoding='utf-8') as vf:
                                vr = csv.DictReader(vf)
                                for _ in vr:
                                    end_count += 1
                        r['EndMarker'] = str(end_count)
                    except Exception:
                        r['EndMarker'] = r.get('EndMarker','')
                    found = True
                    break
            if not found:
                messagebox.showerror('End','Shift not found', parent=top)
                return
            # rewrite file
            try:
                with open(SHIFTS_FILE, 'w', newline='', encoding='utf-8') as f:
                    fieldnames = ['ShiftID','Operator','Start','End','Notes','Marker','EndMarker','Clinic']
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    w.writeheader()
                    for r in shifts:
                        out = {k: r.get(k,'') for k in fieldnames}
                        w.writerow(out)
            except Exception as e:
                messagebox.showerror('Save','Failed to end shift: ' + str(e), parent=top)
                return
            refresh()

        def do_delete():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Delete','Select a shift to delete', parent=top)
                return
            if not messagebox.askyesno('Confirm','Delete selected shift?', parent=top):
                return
            sid = sel[0]
            shifts = [r for r in read_shifts() if r.get('ShiftID') != sid]
            try:
                with open(SHIFTS_FILE, 'w', newline='', encoding='utf-8') as f:
                    fieldnames = ['ShiftID','Operator','Start','End','Notes','Marker','EndMarker','Clinic']
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    w.writeheader()
                    for r in shifts:
                        out = {k: r.get(k,'') for k in fieldnames}
                        w.writerow(out)
            except Exception as e:
                messagebox.showerror('Delete','Failed to delete shift: ' + str(e), parent=top)
                return
            refresh()

        btns = ttk.Frame(frm, padding=6)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text='End Selected', command=do_end).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Delete', command=do_delete).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Close', command=top.destroy).pack(side=tk.RIGHT)

        refresh()

    def open_add_invoice(self):
        """Open Add Invoice dialog: supplier (dropdown), date, items (desc+price), total, status (Due/Done)."""
        top = tk.Toplevel(self)
        top.title('Add Invoice')
        try:
            top.geometry('700x480')
        except Exception:
            pass

        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        # Header: Supplier, Date, Status
        hdr = ttk.Frame(frm)
        hdr.pack(fill=tk.X, pady=(0,8))

        ttk.Label(hdr, text='Supplier:').grid(row=0, column=0, sticky='w', padx=6, pady=4)
        supplier_var = tk.StringVar()
        suppliers = [s.get('Name','') for s in self.suppliers]
        sup_cb = ttk.Combobox(hdr, textvariable=supplier_var, values=suppliers, width=36)
        sup_cb.grid(row=0, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(hdr, text='Date:').grid(row=0, column=2, sticky='w', padx=6, pady=4)
        date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        ttk.Entry(hdr, textvariable=date_var, width=18).grid(row=0, column=3, sticky='w', padx=6, pady=4)

        ttk.Label(hdr, text='Status:').grid(row=0, column=4, sticky='w', padx=6, pady=4)
        status_var = tk.StringVar(value='Due')
        status_cb = ttk.Combobox(hdr, textvariable=status_var, values=['Due','Done'], width=10, state='readonly')
        status_cb.grid(row=0, column=5, sticky='w', padx=6, pady=4)

        def import_jpg():
            if not OCR_AVAILABLE:
                messagebox.showerror('OCR Not Available', 'pytesseract or Tesseract is not installed.\n\nInstall Tesseract (https://github.com/tesseract-ocr/tesseract) and the Python package pytesseract.')
                return
            path = filedialog.askopenfilename(title='Select invoice image', filetypes=[('Images','*.png;*.jpg;*.jpeg;*.tif;*.tiff')])
            if not path:
                return
            try:
                img = Image.open(path)
                text = pytesseract.image_to_string(img)
            except Exception as e:
                messagebox.showerror('OCR Error', f'OCR failed: {e}')
                return

            lines = [l.strip() for l in text.splitlines() if l.strip()]
            fulltext = '\n'.join(lines)

            # Supplier detection: exact substring or fuzzy match against known suppliers
            detected_supplier = ''
            suppliers_list = [s.get('Name','') for s in self.suppliers if s.get('Name','')]
            if suppliers_list:
                ftlower = fulltext.lower()
                for sup in suppliers_list:
                    if sup and sup.lower() in ftlower:
                        detected_supplier = sup
                        break
                if not detected_supplier:
                    # try fuzzy match on first few lines
                    snippet = ' '.join(lines[:5])
                    close = difflib.get_close_matches(snippet, suppliers_list, n=1, cutoff=0.6)
                    if close:
                        detected_supplier = close[0]
                    else:
                        for ln in lines:
                            close = difflib.get_close_matches(ln, suppliers_list, n=1, cutoff=0.6)
                            if close:
                                detected_supplier = close[0]
                                break
            if detected_supplier:
                supplier_var.set(detected_supplier)

            # Date detection using common patterns
            detected_date = ''
            date_patterns = [r"(\d{4}-\d{2}-\d{2})", r"(\d{2}/\d{2}/\d{4})", r"(\d{2}-\d{2}-\d{4})", r"(\d{1,2} [A-Za-z]{3,9} \d{4})"]
            for pat in date_patterns:
                m = re.search(pat, fulltext)
                if m:
                    detected_date = m.group(1)
                    break
            if detected_date:
                date_var.set(detected_date)

            # Extract amounts and item lines heuristically
            amt_re = re.compile(r"(?<!\d)(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{1,2})?")
            items = []
            amounts_all = []
            for ln in lines:
                # remove common currency markers for matching
                ln_clean = ln.replace('Rs.', '').replace('Rs', '').replace('INR', '')
                am = amt_re.findall(ln_clean.replace(',', ''))
                if am:
                    try:
                        price = am[-1]
                        pv = float(price)
                    except Exception:
                        # skip line if amount parse fails
                        continue
                    # description: remove the price part and some keywords
                    desc = re.sub(re.escape(price), '', ln_clean, flags=re.IGNORECASE).strip()
                    desc = re.sub(r"\b(Qty|Qty:|Qty\.|Quantity|Total|Subtotal|Invoice|Amount)\b", '', desc, flags=re.IGNORECASE).strip(' :-')
                    if desc == '' or re.search(r'total', ln, re.I):
                        amounts_all.append(pv)
                        continue
                    items.append((desc, f"{pv:.2f}"))
                    amounts_all.append(pv)

            # Find explicit total if present
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

            # Populate items tree and total
            if items:
                for iid in items_tree.get_children():
                    items_tree.delete(iid)
                for d,p in items:
                    items_tree.insert('', tk.END, values=(d, p))
                update_total()
            if total_val is not None:
                total_var.set(f"{total_val:.2f}")

            # Status detection
            if re.search(r'paid|paid in full|payment received', fulltext, re.I):
                status_var.set('Done')
            elif re.search(r'due|balance|outstanding', fulltext, re.I):
                status_var.set('Due')

            messagebox.showinfo('OCR Import', 'OCR import attempted. Detected fields have been filled where possible. Please review and complete any missing data.')

        # Add Import JPG button to header
        try:
            ttk.Button(hdr, text='Import JPG', command=import_jpg).grid(row=0, column=6, sticky='w', padx=6, pady=4)
        except Exception:
            pass

        # Items area: entry row and tree
        items_frame = ttk.LabelFrame(frm, text='Items', padding=6)
        items_frame.pack(fill=tk.BOTH, expand=True)

        item_desc_var = tk.StringVar()
        item_price_var = tk.StringVar()
        top_row = ttk.Frame(items_frame)
        top_row.pack(fill=tk.X, pady=(0,6))
        ttk.Label(top_row, text='Description:').pack(side=tk.LEFT, padx=(0,6))
        ttk.Entry(top_row, textvariable=item_desc_var, width=40).pack(side=tk.LEFT, padx=(0,6))
        ttk.Label(top_row, text='Price:').pack(side=tk.LEFT, padx=(6,6))
        ttk.Entry(top_row, textvariable=item_price_var, width=12).pack(side=tk.LEFT, padx=(0,6))
        def add_item():
            d = item_desc_var.get().strip()
            p = item_price_var.get().strip()
            if not d:
                messagebox.showwarning('Input','Description required')
                return
            try:
                pv = float(p) if p != '' else 0.0
            except Exception:
                messagebox.showwarning('Input','Price must be a number')
                return
            items_tree.insert('', tk.END, values=(d, f"{pv:.2f}"))
            item_desc_var.set('')
            item_price_var.set('')
            update_total()
        def remove_item():
            sel = items_tree.selection()
            if not sel:
                return
            for s in sel:
                items_tree.delete(s)
            update_total()
        ttk.Button(top_row, text='Add Item', command=add_item).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(top_row, text='Remove', command=remove_item).pack(side=tk.LEFT, padx=(6,0))

        cols = ('Description','Price')
        items_tree = ttk.Treeview(items_frame, columns=cols, show='headings', height=8)
        for c in cols:
            items_tree.heading(c, text=c, anchor='w')
            items_tree.column(c, width=200 if c=='Description' else 80, anchor='w')
        items_tree.pack(fill=tk.BOTH, expand=True)

        total_var = tk.StringVar(value='0.00')
        def update_total():
            total = 0.0
            for iid in items_tree.get_children():
                try:
                    pv = float(items_tree.item(iid, 'values')[1])
                except Exception:
                    pv = 0.0
                total += pv
            total_var.set(f"{total:.2f}")

        bottom = ttk.Frame(frm, padding=6)
        bottom.pack(fill=tk.X)
        ttk.Label(bottom, text='Total:', font=('TkDefaultFont', 11, 'bold')).pack(side=tk.RIGHT, padx=(6,0))
        ttk.Label(bottom, textvariable=total_var, font=('TkDefaultFont', 11, 'bold')).pack(side=tk.RIGHT)

        def do_save():
            supplier = supplier_var.get().strip()
            date_s = date_var.get().strip()
            status = status_var.get().strip()
            items = []
            for iid in items_tree.get_children():
                vals = items_tree.item(iid, 'values')
                items.append({'desc': vals[0], 'price': vals[1]})
            if not supplier:
                if messagebox.askyesno('Confirm','No supplier selected. Continue?') is False:
                    return
            if not items:
                messagebox.showwarning('Input','Add at least one item')
                return
            invoice_id = str(uuid.uuid4())
            # persist to INVOICES_FILE as one-row per invoice
            fieldnames = ['InvoiceID','Supplier','Date','Items','Total','Status']
            try:
                # prepare items string as desc|price;;desc|price
                items_s = ';;'.join([f"{it['desc'].replace(';;',';')}|{it['price']}" for it in items])
                total = total_var.get()
                exists = os.path.exists(INVOICES_FILE)
                with open(INVOICES_FILE, 'a', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    if not exists:
                        w.writeheader()
                    w.writerow({'InvoiceID': invoice_id, 'Supplier': supplier, 'Date': date_s, 'Items': items_s, 'Total': total, 'Status': status})
                messagebox.showinfo('Saved','Invoice saved')
                try:
                    self._close_all_child_toplevels()
                except Exception:
                    try:
                        top.destroy()
                    except Exception:
                        pass
            except Exception as e:
                messagebox.showerror('Save Error', f'Failed to save invoice: {e}')

        btns = ttk.Frame(frm, padding=6)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text='Save Invoice', command=do_save).pack(side=tk.RIGHT, padx=6)
        ttk.Button(btns, text='Close', command=top.destroy).pack(side=tk.RIGHT)

    def open_view_invoices(self):
        """Open a window that lists saved invoices from `invoices.csv`."""
        top = tk.Toplevel(self)
        top.title('Invoices')
        top.geometry('760x420')

        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        cols = ('InvoiceID','Supplier','Date','Total','Status')
        tree = ttk.Treeview(frm, columns=cols, show='headings')
        for c in cols:
            tree.heading(c, text=c)
        tree.column('InvoiceID', width=220)
        tree.column('Supplier', width=180)
        tree.column('Date', width=100)
        tree.column('Total', width=80, anchor='e')
        tree.column('Status', width=80)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vs = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=vs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)

        def load_invoices():
            for i in tree.get_children():
                tree.delete(i)
            if not os.path.exists(INVOICES_FILE):
                return
            try:
                # Open invoices file and support both headered and header-less CSVs
                with open(INVOICES_FILE, 'r', newline='', encoding='utf-8') as f:
                    # peek to see if file is empty
                    first = f.readline()
                    if not first:
                        return
                    # reset
                    f.seek(0)
                    rdr = csv.DictReader(f)
                    fieldnames = [fn.strip() for fn in (rdr.fieldnames or [])]
                    # If header does not contain expected keys, treat file as header-less
                    if 'InvoiceID' not in fieldnames:
                        # read as simple rows and map columns by position
                        f.seek(0)
                        rows = [row for row in csv.reader(f) if any(cell.strip() for cell in row)]
                        for row in rows:
                            invoice_id = row[0] if len(row) > 0 else ''
                            supplier = row[1] if len(row) > 1 else ''
                            date = row[2] if len(row) > 2 else ''
                            total = row[4] if len(row) > 4 else (row[3] if len(row) > 3 else '')
                            status = row[5] if len(row) > 5 else ''
                            tree.insert('', tk.END, iid=invoice_id, values=(invoice_id, supplier, date, total, status))
                        # attempt to rewrite file with header so future reads work normally
                        try:
                            if rows:
                                with open(INVOICES_FILE, 'w', newline='', encoding='utf-8') as out:
                                    fnames = ['InvoiceID','Supplier','Date','Items','Total','Status']
                                    w = csv.writer(out)
                                    w.writerow(fnames)
                                    for row in rows:
                                        w.writerow(row)
                        except Exception:
                            # non-fatal: continue without rewriting
                            pass
                    else:
                        # Normal headered CSV
                        f.seek(0)
                        rdr = csv.DictReader(f)
                        for r in rdr:
                            iid = r.get('InvoiceID','')
                            tree.insert('', tk.END, iid=iid, values=(iid, r.get('Supplier',''), r.get('Date',''), r.get('Total',''), r.get('Status','')))
            except Exception as e:
                messagebox.showerror('Error', f'Failed to load invoices: {e}')

        def view_details():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Invoice', 'Select an invoice to view details')
                return
            iid = sel[0]
            try:
                with open(INVOICES_FILE, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    for r in rdr:
                        if r.get('InvoiceID','') == iid:
                            items_s = r.get('Items','')
                            items = []
                            if items_s:
                                for part in items_s.split(';;'):
                                    try:
                                        desc, price = part.split('|',1)
                                    except Exception:
                                        desc = part
                                        price = ''
                                    items.append({'desc': desc, 'price': price})
                            # show details in dialog
                            dlg = tk.Toplevel(top)
                            dlg.title(f'Invoice {iid}')
                            ttk.Label(dlg, text=f"Supplier: {r.get('Supplier','')}").pack(anchor='w', padx=8, pady=(8,0))
                            ttk.Label(dlg, text=f"Date: {r.get('Date','')}").pack(anchor='w', padx=8)
                            ttk.Label(dlg, text=f"Status: {r.get('Status','')}").pack(anchor='w', padx=8)
                            ttk.Label(dlg, text='Items:').pack(anchor='w', padx=8, pady=(6,0))
                            itf = ttk.Frame(dlg, padding=8)
                            itf.pack(fill=tk.BOTH, expand=True)
                            itree = ttk.Treeview(itf, columns=('Description','Price'), show='headings', height=8)
                            itree.heading('Description', text='Description')
                            itree.heading('Price', text='Price')
                            itree.column('Description', width=320)
                            itree.column('Price', width=80, anchor='e')
                            itree.pack(fill=tk.BOTH, expand=True)
                            for it in items:
                                itree.insert('', tk.END, values=(it.get('desc',''), it.get('price','')))
                            ttk.Button(dlg, text='Close', command=dlg.destroy).pack(pady=8)
                            return
                messagebox.showerror('Not found', 'Invoice not found in file')
            except Exception as e:
                messagebox.showerror('Error', f'Failed to read invoice: {e}')

        btns = ttk.Frame(top, padding=6)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text='View Details', command=view_details).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Close', command=top.destroy).pack(side=tk.RIGHT, padx=6)

        load_invoices()

    def open_order_list(self):
        """Open Order List showing medicines with low stock (Quantity < 4)."""
        # clear unread counter when the doctor opens the order list (they've seen notifications)
        try:
            meta = _load_order_meta()
            if meta.get('unread', 0):
                meta['unread'] = 0
                _save_order_meta(meta)
            self.order_unread = 0
            try:
                self._update_order_badge()
            except Exception:
                pass
        except Exception:
            pass
        top = tk.Toplevel(self)
        self.maximize_window(top)
        top.title("Order List")
        top.geometry("560x360")

        # remember order window and tree so other actions can refresh it
        try:
            self.order_top = top
        except Exception:
            self.order_top = None

        frm = ttk.Frame(top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)
        cols = ('Name', 'Supplier', 'Quantity', 'ReorderLevel', 'Order', 'Notes')
        tree = ttk.Treeview(frm, columns=cols, show='headings')
        for c in cols:
            tree.heading(c, text=c, anchor='w')
        tree.column('Name', width=180, anchor='w')
        tree.column('Supplier', width=140, anchor='w')
        tree.column('Quantity', width=70, anchor='w')
        tree.column('ReorderLevel', width=80, anchor='w')
        tree.column('Order', width=80, anchor='w')
        tree.column('Notes', width=200, anchor='w')
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        try:
            self.order_tree = tree
        except Exception:
            self.order_tree = None

        vs = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=vs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)

        # collect low-stock medicines and compute suggested order quantities
        low = []
        for m in self.medicines:
            qraw = (m.get('Quantity') or '').strip()
            try:
                qv = float(qraw) if qraw != '' else 0.0
            except Exception:
                qv = 0.0
            if qv <= 3:
                # determine desired level (use ReorderLevel if present else default 30)
                desired_raw = (m.get('ReorderLevel') or '').strip()
                try:
                    desired = int(float(desired_raw)) if desired_raw != '' else 30
                except Exception:
                    desired = 30
                # suggest ordering enough to reach desired level, at least 1
                try:
                    cur_int = int(qv)
                except Exception:
                    cur_int = int(float(qv)) if qv else 0
                suggested = max(desired - cur_int, 1)
                low.append((m, qv, suggested))

        # sort by quantity ascending
        low.sort(key=lambda t: t[1])

            # after computing current low list, mark any previously-notified items
            # as still low; also clear unread/notified when opening the list below

        if not low:
            lbl = ttk.Label(frm, text='All products have sufficient stock (>= 4).')
            lbl.pack(padx=12, pady=12)
            # no tree rows; reflect empty state
            try:
                self.order_tree = None
            except Exception:
                pass
        else:
            for m, qv, suggested in low:
                qty_display = (f"{qv:.0f}" if float(qv).is_integer() else f"{qv}")
                vals = (m.get('Name',''), m.get('Supplier',''), qty_display, m.get('ReorderLevel',''), str(suggested), m.get('Notes',''))
                mid = (m.get('MedicineID','') or '').strip()
                try:
                    if mid and mid not in tree.get_children():
                        tree.insert('', tk.END, iid=mid, values=vals)
                    else:
                        tree.insert('', tk.END, values=vals)
                except Exception:
                    try:
                        tree.insert('', tk.END, values=vals)
                    except Exception:
                        pass

        # footer with controls
        ftr = ttk.Frame(top, padding=6)
        ftr.pack(fill=tk.X)
        # keep count label for dynamic updates
        self.order_count_label = ttk.Label(ftr, text=f"Items to order: {len(low)}", foreground='red', font=('TkDefaultFont', 10, 'bold'))
        self.order_count_label.pack(side=tk.LEFT)

        # mark items as notified and clear unread now that doctor opened the list
        try:
            meta = _load_order_meta()
            # set notified to current low ids so they are not re-notified
            current_low_ids = [m.get('MedicineID','') for (m,_,_) in low]
            meta['notified'] = current_low_ids
            meta['unread'] = 0
            _save_order_meta(meta)
            self.order_unread = 0
            try:
                self._update_order_badge()
            except Exception:
                pass
        except Exception:
            pass

        def _edit_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Edit quantity', 'Please select an item to edit')
                return
            iid = sel[0]
            cur = tree.set(iid, 'Order')
            def _apply():
                val = ent.get().strip()
                if not val:
                    return
                try:
                    # keep integer values
                    ival = int(float(val))
                except Exception:
                    messagebox.showerror('Invalid', 'Please enter a numeric quantity')
                    return
                tree.set(iid, 'Order', str(ival))
                dlg.destroy()

            dlg = tk.Toplevel(top)
            dlg.title('Edit Order Quantity')
            ttk.Label(dlg, text='Order quantity:').pack(padx=8, pady=(8,0))
            ent = ttk.Entry(dlg)
            ent.insert(0, cur)
            ent.pack(padx=8, pady=8)
            btnf = ttk.Frame(dlg, padding=6)
            btnf.pack(fill=tk.X)
            ttk.Button(btnf, text='OK', command=_apply).pack(side=tk.LEFT, padx=6)
            ttk.Button(btnf, text='Cancel', command=dlg.destroy).pack(side=tk.RIGHT, padx=6)

        def _remove_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Remove', 'Please select item(s) to remove')
                return
            for iid in sel:
                tree.delete(iid)

        def _confirm_orders():
            rows = []
            for iid in tree.get_children():
                vals = tree.item(iid, 'values')
                # Name, Supplier, Quantity, ReorderLevel, Order, Notes
                try:
                    order_q = int(float(vals[4]))
                except Exception:
                    order_q = 0
                rows.append({'MedicineID': iid, 'Name': vals[0], 'Supplier': vals[1], 'CurrentQty': vals[2], 'OrderQty': order_q, 'Notes': vals[5], 'Date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            if not rows:
                messagebox.showinfo('No orders', 'No items to order')
                return
            # save to ORDER_FILE
            try:
                need_header = not os.path.exists(ORDER_FILE)
                with open(ORDER_FILE, 'a', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=['MedicineID','Name','Supplier','CurrentQty','OrderQty','Notes','Date'])
                    if need_header:
                        w.writeheader()
                    for r in rows:
                        w.writerow(r)
                    # increment unread counter so doctor sees notification on main toolbar
                    try:
                        meta = _load_order_meta()
                        meta['unread'] = int(meta.get('unread', 0) or 0) + len(rows)
                        _save_order_meta(meta)
                        self.order_unread = int(meta.get('unread', 0) or 0)
                        try:
                            self._update_order_badge()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    messagebox.showinfo('Saved', f'Order saved to {ORDER_FILE}')
                    try:
                        self._close_all_child_toplevels()
                    except Exception:
                        pass
                    top.destroy()
            except Exception as e:
                messagebox.showerror('Error', f'Failed to save order: {e}')

        def _export_csv():
            path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')])
            if not path:
                return
            try:
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(['MedicineID','Name','Supplier','CurrentQty','OrderQty','Notes'])
                    for iid in tree.get_children():
                        vals = tree.item(iid, 'values')
                        w.writerow([iid, vals[0], vals[1], vals[2], vals[4], vals[5]])
                messagebox.showinfo('Exported', f'Order exported to {path}')
            except Exception as e:
                messagebox.showerror('Error', f'Failed to export: {e}')

        btnf = ttk.Frame(ftr)
        btnf.pack(side=tk.RIGHT)
        ttk.Button(btnf, text='Edit Quantity', command=_edit_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btnf, text='Remove Selected', command=_remove_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btnf, text='Export CSV', command=_export_csv).pack(side=tk.LEFT, padx=4)
        ttk.Button(btnf, text='Confirm Order', command=_confirm_orders).pack(side=tk.LEFT, padx=4)
        def _on_close():
            try:
                self.order_top = None
            except Exception:
                pass
            try:
                self.order_tree = None
            except Exception:
                pass
            try:
                self.order_count_label = None
            except Exception:
                pass
            try:
                top.destroy()
            except Exception:
                pass

        ttk.Button(btnf, text='Close', command=_on_close).pack(side=tk.LEFT, padx=4)
        try:
            top.protocol('WM_DELETE_WINDOW', _on_close)
        except Exception:
            pass

    def open_inventory(self):
        """Open the Medicine Database (Inventory) window with CSV-backed CRUD."""
        top = tk.Toplevel(self)
        top.title("Medicine Database")
        top.geometry("720x420")

        frame = ttk.Frame(top, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)

        cols = ('Name','Supplier','Category','Quantity','Price','Reorder','Notes')
        tree = ttk.Treeview(frame, columns=cols, show='headings')
        for c in cols:
            tree.heading(c, text=c, anchor='w')
        tree.column('Name', width=180, anchor='w')
        tree.column('Supplier', width=140, anchor='w')
        tree.column('Category', width=120, anchor='w')
        tree.column('Quantity', width=80, anchor='w')
        tree.column('Price', width=80, anchor='w')
        tree.column('Reorder', width=80, anchor='w')
        tree.column('Notes', width=180, anchor='w')
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vs = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=vs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)

        # control buttons
        ctrl = ttk.Frame(top, padding=6)
        ctrl.pack(fill=tk.X)
        # build category list for filter (include 'All' and ensure 'Mother Tincture')
        def _build_cats():
            # combine categories from medicines and the persistent categories list
            meds_cats = {(m.get('Category') or '').strip() for m in self.medicines if (m.get('Category') or '').strip()}
            try:
                extra = set((self.categories or []))
            except Exception:
                extra = set()
            cats = sorted([c for c in (meds_cats | extra) if c])
            # default categories to ensure appear in combobox
            defaults = ['Mother Tincture', 'Drops', 'Syrup', 'Cream']
            for d in reversed(defaults):
                if d not in cats:
                    cats.insert(0, d)
            cats.insert(0, 'All')
            return cats

        category_var = tk.StringVar(value='All')

        def refresh_tree():
            for i in tree.get_children():
                tree.delete(i)
            # ensure every medicine has Category key
            sel_cat = (category_var.get() or '').strip()
            for m in self.medicines:
                if 'Category' not in m:
                    m['Category'] = ''
                if sel_cat and sel_cat != 'All' and (m.get('Category','') or '').strip() != sel_cat:
                    continue
                vals = (m.get('Name',''), m.get('Supplier',''), m.get('Category',''), m.get('Quantity',''), m.get('Price',''), m.get('ReorderLevel',''), m.get('Notes',''))
                mid = (m.get('MedicineID','') or '').strip()
                try:
                    if mid and mid not in tree.get_children():
                        tree.insert('', tk.END, iid=mid, values=vals)
                    else:
                        # empty or duplicate iid: insert without specifying iid to avoid TclError
                        tree.insert('', tk.END, values=vals)
                except Exception:
                    try:
                        tree.insert('', tk.END, values=vals)
                    except Exception:
                        pass

        # expose inventory refresh so other parts of the app can trigger UI updates
        try:
            self._inventory_refresh = refresh_tree
        except Exception:
            self._inventory_refresh = None

        # add category filter control to ctrl frame
        try:
            cats = _build_cats()
            ttk.Label(ctrl, text='Category:').pack(side=tk.LEFT, padx=(0,6))
            cat_cb = ttk.Combobox(ctrl, textvariable=category_var, values=cats, width=24, state='readonly')
            cat_cb.pack(side=tk.LEFT, padx=(0,6))
            def _on_cat_change(event=None):
                refresh_tree()
            cat_cb.bind('<<ComboboxSelected>>', _on_cat_change)
            ttk.Button(ctrl, text='Show All', command=lambda: (category_var.set('All'), refresh_tree())).pack(side=tk.LEFT, padx=(6,6))
        except Exception:
            pass

        # Inventory search controls: search across all clinics' inventory files
        try:
            search_var2 = tk.StringVar()
            ttk.Label(ctrl, text='Search Medicine:').pack(side=tk.LEFT, padx=(12,6))
            sv_entry = ttk.Entry(ctrl, textvariable=search_var2, width=15)
            sv_entry.pack(side=tk.LEFT, padx=(0,6))
            def inventory_search(event=None):
                q = (search_var2.get() or '').strip().lower()
                if not q:
                    refresh_tree()
                    return

                # build results list of (Name, AvailabilityString, Quantity, Price, Reorder, Notes)
                results = []
                for m in self.medicines:
                    name = (m.get('Name') or '').strip()
                    if not name or q not in name.lower():
                        continue
                    mid = (m.get('MedicineID') or '').strip()
                    avail_parts = []
                    # check each clinic inventory file for quantities
                    clinics = getattr(self, 'clinics', []) or []
                    for c in clinics:
                        try:
                            invf = INVENTORY_TEMPLATE.format(clinic=c)
                        except Exception:
                            invf = None
                        qty = ''
                        if invf and os.path.exists(invf):
                            try:
                                with open(invf, 'r', newline='', encoding='utf-8') as f:
                                    rdr = csv.DictReader(f)
                                    if not rdr.fieldnames:
                                        f.seek(0)
                                        for row in csv.reader(f):
                                            if not row:
                                                continue
                                            # inventory rows: MedicineID, Quantity, ReorderLevel
                                            if len(row) >= 1 and mid and row[0].strip() == mid:
                                                qty = row[1].strip() if len(row) > 1 else ''
                                                break
                                    else:
                                        for row in rdr:
                                            if mid and (row.get('MedicineID') or '').strip() == mid:
                                                qty = (row.get('Quantity') or '').strip()
                                                break
                            except Exception:
                                qty = ''
                        # append formatted part
                        try:
                            avail_parts.append(f"{c}:{qty if qty!='' else '0'}")
                        except Exception:
                            avail_parts.append(f"{c}:?")

                    avail_str = ', '.join(avail_parts) if avail_parts else 'No inventory files'
                    results.append((name, avail_str, m.get('Quantity',''), m.get('Price',''), m.get('ReorderLevel',''), m.get('Notes','')))

                # show results in a popup
                rtop = tk.Toplevel(top)
                rtop.title(f"Search results: {search_var2.get()}")
                rtop.geometry('720x320')
                rf = ttk.Frame(rtop, padding=6)
                rf.pack(fill=tk.BOTH, expand=True)
                cols2 = ('Name','Availability','Quantity','Price','Reorder','Notes')
                rtree = ttk.Treeview(rf, columns=cols2, show='headings')
                for c in cols2:
                    rtree.heading(c, text=c, anchor='w')
                rtree.column('Name', width=240, anchor='w')
                rtree.column('Availability', width=240, anchor='w')
                rtree.column('Quantity', width=80, anchor='w')
                rtree.column('Price', width=60, anchor='w')
                rtree.column('Reorder', width=60, anchor='w')
                rtree.column('Notes', width=200, anchor='w')
                rtree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                vs2 = ttk.Scrollbar(rf, orient=tk.VERTICAL, command=rtree.yview)
                rtree.configure(yscroll=vs2.set)
                vs2.pack(side=tk.RIGHT, fill=tk.Y)
                for row in results:
                    rtree.insert('', tk.END, values=row)

            def inventory_clear():
                search_var2.set('')
                refresh_tree()

            ttk.Button(ctrl, text='Search', command=inventory_search).pack(side=tk.LEFT, padx=(6,4))
            ttk.Button(ctrl, text='Clear', command=inventory_clear).pack(side=tk.LEFT, padx=(0,6))
            sv_entry.bind('<Return>', inventory_search)
        except Exception:
            pass

        def add_medicine():
            dlg = tk.Toplevel(top)
            # allow standard window decorations (minimize/maximize) and resizing
            dlg.resizable(True, True)
            dlg.title('Add Medicine')
            fields = {}
            # build category list (ensure 'Mother Tincture' exists)
            cats = sorted({(m.get('Category') or '').strip() for m in self.medicines if (m.get('Category') or '').strip()})
            # default categories to ensure appear in combobox
            defaults = ['Mother Tincture', 'Drops', 'Syrup', 'Cream']
            for d in reversed(defaults):
                if d not in cats:
                    cats.insert(0, d)
            labels = ['Name','Supplier','Category','Quantity','Price','ReorderLevel','Notes']
            for r,lab in enumerate(labels):
                ttk.Label(dlg, text=lab+':').grid(row=r, column=0, sticky='w', padx=6, pady=4)
                if lab == 'Notes':
                    txt = tk.Text(dlg, width=40, height=4)
                    txt.grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = txt
                elif lab == 'Supplier':
                    sv = tk.StringVar()
                    vals = [s.get('Name','') for s in self.suppliers]
                    cb = ttk.Combobox(dlg, textvariable=sv, values=vals, width=30)
                    cb.grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = sv
                elif lab == 'Category':
                    sv = tk.StringVar()
                    cb = ttk.Combobox(dlg, textvariable=sv, values=cats, width=30)
                    cb.grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = sv
                else:
                    sv = tk.StringVar()
                    ttk.Entry(dlg, textvariable=sv, width=30).grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = sv

            def do_add():
                name = fields['Name'].get().strip()
                if not name:
                    messagebox.showwarning('Input','Name required')
                    return
                mid = str(uuid.uuid4())
                entry = {
                    'MedicineID': mid,
                    'Name': name,
                    'Supplier': fields['Supplier'].get().strip(),
                    'Category': fields.get('Category').get().strip() if fields.get('Category') is not None else '',
                    'Quantity': fields['Quantity'].get().strip(),
                    'Price': fields['Price'].get().strip(),
                    'ReorderLevel': fields['ReorderLevel'].get().strip(),
                    'Notes': fields['Notes'].get('1.0', tk.END).strip() if isinstance(fields['Notes'], tk.Text) else fields['Notes'].get().strip(),
                }
                self.medicines.append(entry)
                # persist master and inventory
                try:
                    okm = self.save_medicines()
                except Exception:
                    okm = False
                try:
                    oki = self.save_inventory()
                except Exception:
                    oki = False
                if not okm:
                    messagebox.showerror('Save Error', 'Failed to save medicine master record')
                    return
                dlg.destroy()
                refresh_tree()

            ttk.Button(dlg, text='Save', command=do_add).grid(row=len(labels), column=0, columnspan=2, pady=8)

        def edit_medicine():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Edit','Select a medicine to edit')
                return
            mid = sel[0]
            # find entry
            ent = None
            for m in self.medicines:
                if m.get('MedicineID') == mid:
                    ent = m
                    break
            if ent is None:
                messagebox.showerror('Edit','Selected medicine not found')
                return

            dlg = tk.Toplevel(top)
            # allow minimize/maximize on edit dialog as well
            dlg.resizable(True, True)
            dlg.title('Edit Medicine')
            fields = {}
            # build category list (ensure 'Mother Tincture' exists)
            cats = sorted({(m.get('Category') or '').strip() for m in self.medicines if (m.get('Category') or '').strip()})
            if 'Mother Tincture' not in cats:
                cats.insert(0, 'Mother Tincture')
            labels = ['Name','Supplier','Category','Quantity','Price','ReorderLevel','Notes']
            for r,lab in enumerate(labels):
                ttk.Label(dlg, text=lab+':').grid(row=r, column=0, sticky='w', padx=6, pady=4)
                if lab == 'Notes':
                    txt = tk.Text(dlg, width=40, height=4)
                    txt.insert('1.0', ent.get('Notes',''))
                    txt.grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = txt
                elif lab == 'Supplier':
                    sv = tk.StringVar(value=ent.get('Supplier',''))
                    vals = [s.get('Name','') for s in self.suppliers]
                    cb = ttk.Combobox(dlg, textvariable=sv, values=vals, width=30)
                    cb.grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = sv
                elif lab == 'Category':
                    sv = tk.StringVar(value=ent.get('Category',''))
                    cb = ttk.Combobox(dlg, textvariable=sv, values=cats, width=30)
                    cb.grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = sv
                else:
                    sv = tk.StringVar(value=ent.get(lab,''))
                    ttk.Entry(dlg, textvariable=sv, width=30).grid(row=r, column=1, padx=6, pady=4)
                    fields[lab] = sv

            def do_save():
                ent['Name'] = fields['Name'].get().strip()
                ent['Supplier'] = fields['Supplier'].get().strip()
                # master fields
                ent['Name'] = fields['Name'].get().strip()
                ent['Supplier'] = fields['Supplier'].get().strip()
                ent['Price'] = fields['Price'].get().strip()
                ent['ReorderLevel'] = fields['ReorderLevel'].get().strip()
                ent['Notes'] = fields['Notes'].get('1.0', tk.END).strip() if isinstance(fields['Notes'], tk.Text) else fields['Notes'].get().strip()
                ent['Category'] = fields.get('Category').get().strip() if fields.get('Category') is not None else ent.get('Category','')
                # inventory qty is clinic-specific; update entry's Quantity field and persist both master and inventory
                ent['Quantity'] = fields['Quantity'].get().strip()
                ok_master = self.save_medicines()
                ok_inv = self.save_inventory()
                if not ok_master:
                    messagebox.showerror('Save Error','Failed to save master medicine record')
                    return
                if not ok_inv:
                    messagebox.showwarning('Save', 'Saved master record but failed to update inventory file')
                dlg.destroy()
                refresh_tree()

            ttk.Button(dlg, text='Save', command=do_save).grid(row=len(labels), column=0, columnspan=2, pady=8)

        def delete_medicine():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Delete','Select one or more medicines to delete')
                return
            # Confirm deletion of multiple items
            if not messagebox.askyesno('Confirm', f'Delete {len(sel)} selected medicine(s)?'):
                return
            sel_ids = set(sel)
            self.medicines = [m for m in self.medicines if (m.get('MedicineID') or '') not in sel_ids]
            ok_master = self.save_medicines()
            ok_inv = self.save_inventory()
            if not ok_master:
                messagebox.showerror('Delete','Failed to update master medicines file')
                return
            if not ok_inv:
                messagebox.showwarning('Delete','Master updated but failed to update inventory file')
            refresh_tree()

        def import_csv():
            path = filedialog.askopenfilename(title='Select medicines CSV to import', filetypes=[('CSV files','*.csv'),('All files','*.*')], initialdir=os.path.expanduser('~\\Desktop'))
            if not path:
                return
            try:
                with open(path, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    added = 0
                    updated = 0
                    for r in rdr:
                        # permissive import: ignore missing fields
                        name = (r.get('Name') or r.get('name') or '').strip()
                        if not name:
                            # skip rows without a name
                            continue
                        mid = (r.get('MedicineID') or '').strip() or str(uuid.uuid4())
                        # try to find existing by MedicineID
                        ent = None
                        for m in self.medicines:
                            if m.get('MedicineID') and m.get('MedicineID') == mid:
                                ent = m
                                break
                        # fallback: match by name+supplier (case-insensitive)
                        if ent is None:
                            sname = (r.get('Supplier') or '').strip().lower()
                            for m in self.medicines:
                                if (m.get('Name','').strip().lower() == name.lower()) and (m.get('Supplier','').strip().lower() == sname):
                                    ent = m
                                    break

                        if ent is None:
                            ent = {'MedicineID': mid}
                            self.medicines.append(ent)
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
                        # Quantity is optional; only set if present
                        if 'Quantity' in r:
                            ent['Quantity'] = (r.get('Quantity') or '').strip()

                okm = self.save_medicines()
                oki = self.save_inventory()
                try:
                    refresh_tree()
                except Exception:
                    pass
                messagebox.showinfo('Import Finished', f'Imported: {added} new, {updated} updated. Saved master: {okm}, inventory: {oki}')
            except Exception as e:
                messagebox.showerror('Import Error', f'Failed to import CSV:\n{e}')

        ttk.Button(ctrl, text='Add', command=add_medicine).pack(side=tk.LEFT, padx=6)
        ttk.Button(ctrl, text='Edit', command=edit_medicine).pack(side=tk.LEFT, padx=6)
        ttk.Button(ctrl, text='Delete', command=delete_medicine).pack(side=tk.LEFT, padx=6)
        # Select All convenience button
        try:
            ttk.Button(ctrl, text='Select All', command=lambda: tree.selection_set(tree.get_children())).pack(side=tk.LEFT, padx=6)
        except Exception:
            pass
        ttk.Button(ctrl, text='Close', command=top.destroy).pack(side=tk.RIGHT, padx=6)
        try:
            def _on_inv_close():
                try:
                    self._inventory_refresh = None
                except Exception:
                    pass
                try:
                    top.destroy()
                except Exception:
                    pass
            top.protocol('WM_DELETE_WINDOW', _on_inv_close)
        except Exception:
            pass

        # keyboard shortcut: Ctrl+A to select all items in the inventory tree
        try:
            def _select_all_event(event=None):
                try:
                    tree.selection_set(tree.get_children())
                except Exception:
                    pass
                return 'break'
            tree.bind('<Control-a>', _select_all_event)
            tree.bind('<Control-A>', _select_all_event)
        except Exception:
            pass

        refresh_tree()

    def open_stock_adjustment(self):
        """Open Stock Adjustment window.

        Supports two modes:
        - Delta: change quantity by +/-.
        - Set: set absolute quantity.

        If the resulting quantity would be negative, user must confirm.
        Each adjustment is saved to `stock_adjustments.csv` for audit.
        """
        top = tk.Toplevel(self)
        top.title("Stock Adjustment")
        top.geometry('820x420')

        main = ttk.Frame(top, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Medicines list on left
        mcols = ('Name','Supplier','Quantity')
        mtree = ttk.Treeview(left, columns=mcols, show='headings', height=18, style='StockAdj.Treeview')
        for c in mcols:
            mtree.heading(c, text=c, anchor='w')
        mtree.column('Name', width=240, anchor='w')
        mtree.column('Supplier', width=140, anchor='w')
        mtree.column('Quantity', width=80, anchor='w')
        mtree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        mscroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=mtree.yview)
        mtree.configure(yscroll=mscroll.set)
        mscroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Search bar for medicines (left side) — larger box
        search_frame = ttk.Frame(left)
        search_frame.pack(side=tk.TOP, fill=tk.X, pady=(0,6))
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
        search_entry.pack(side=tk.LEFT)

        # Treeview style specific to stock adjustment (local font: Arial 11 bold)
        try:
            style = ttk.Style(top)
        except Exception:
            style = ttk.Style()
        style.configure('StockAdj.Treeview', font=('Arial', 11, 'bold'))
        style.configure('StockAdj.Treeview.Heading', font=('Arial', 11, 'bold'))

        def do_search_meds():
            q = (search_var.get() or '').strip().lower()
            refresh_meds(q)
        ttk.Button(search_frame, text='Search', command=do_search_meds).pack(side=tk.LEFT, padx=(6,0))
        def do_clear_meds():
            search_var.set('')
            refresh_meds(None)
        ttk.Button(search_frame, text='Clear', command=do_clear_meds).pack(side=tk.LEFT, padx=(6,0))
        search_entry.bind('<Return>', lambda e: do_search_meds())

        # populate medicines (optionally filtered) and auto-fit columns
        def refresh_meds(query=None):
            for i in mtree.get_children():
                mtree.delete(i)
            # collect rows to display
            rows = []
            for m in self.medicines:
                name = (m.get('Name') or '').strip()
                lname = name.lower()
                supp = (m.get('Supplier') or '').strip()
                lsupp = supp.lower()
                mid = (m.get('MedicineID') or '').strip()
                qty = m.get('Quantity','')
                if query:
                    if query not in lname and query not in lsupp and query not in (mid.lower() if mid else ''):
                        continue
                rows.append((mid, (name, supp, qty)))

            # measure text widths using local font
            # avoid passing `master=` to Font (some Tk builds reject -master option)
            f = tkfont.Font(family='Arial', size=11, weight='bold')
            col_texts = { 'Name': ['Name'], 'Supplier': ['Supplier'], 'Quantity': ['Quantity'] }
            for mid, vals in rows:
                col_texts['Name'].append(vals[0])
                col_texts['Supplier'].append(vals[1])
                col_texts['Quantity'].append(str(vals[2]))
            padding = 18
            for c in mcols:
                try:
                    maxw = max((f.measure(str(t)) for t in col_texts[c])) + padding
                except Exception:
                    maxw = 100
                mtree.column(c, width=maxw, anchor='w')

            # insert rows with safe unique iids (preserve MedicineID as base)
            existing = set(mtree.get_children())
            dup_counts = {}
            for mid, vals in rows:
                vals = (vals[0], vals[1], vals[2])
                if mid:
                    if mid not in existing and dup_counts.get(mid, 0) == 0:
                        iid = mid
                        dup_counts[mid] = 1
                    else:
                        cnt = dup_counts.get(mid, 1)
                        iid = f"{mid}#{cnt}"
                        dup_counts[mid] = cnt + 1
                else:
                    iid = None
                if iid:
                    mtree.insert('', tk.END, iid=iid, values=vals)
                else:
                    mtree.insert('', tk.END, values=vals)

        # Right side controls + history
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(12,0))

        # Selected medicine info
        sel_name_var = tk.StringVar()
        sel_supplier_var = tk.StringVar()
        sel_qty_var = tk.StringVar()

        ttk.Label(right, text='Selected Product:', font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(right, textvariable=sel_name_var).grid(row=1, column=0, sticky='w')
        ttk.Label(right, textvariable=sel_supplier_var).grid(row=2, column=0, sticky='w')
        ttk.Label(right, text='Current Qty:').grid(row=3, column=0, sticky='w', pady=(6,0))
        ttk.Label(right, textvariable=sel_qty_var, font=('TkDefaultFont', 10, 'bold')).grid(row=4, column=0, sticky='w')

        # Operator / user
        operator_var = tk.StringVar()
        ttk.Label(right, text='Operator/User:').grid(row=5, column=0, sticky='w', pady=(8,0))
        ttk.Entry(right, textvariable=operator_var, width=18).grid(row=6, column=0, sticky='w')

        # Adjustment mode
        mode_var = tk.StringVar(value='delta')
        ttk.Radiobutton(right, text='Delta (+/-)', variable=mode_var, value='delta').grid(row=7, column=0, sticky='w', pady=(10,0))
        ttk.Radiobutton(right, text='Set absolute', variable=mode_var, value='set').grid(row=8, column=0, sticky='w')

        ttk.Label(right, text='Amount:').grid(row=9, column=0, sticky='w', pady=(8,0))
        amt_var = tk.StringVar()
        ttk.Entry(right, textvariable=amt_var, width=18).grid(row=10, column=0, sticky='w')

        ttk.Label(right, text='Reason (required):').grid(row=11, column=0, sticky='w', pady=(8,0))
        reason_txt = tk.Text(right, width=36, height=4)
        reason_txt.grid(row=12, column=0, pady=(4,0))

        force_neg_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text='Allow negative result without extra confirmation', variable=force_neg_var).grid(row=13, column=0, sticky='w', pady=(6,0))

        # History area
        hist_frame = ttk.LabelFrame(top, text='Adjustment History (selected product)', padding=6)
        hist_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8,6))
        hcols = ('Date','User','Change','Old','New','Reason')
        htree = ttk.Treeview(hist_frame, columns=hcols, show='headings', height=6)
        for c in hcols:
            htree.heading(c, text=c, anchor='w')
        htree.column('Date', width=110, anchor='w')
        htree.column('User', width=100, anchor='w')
        htree.column('Change', width=80, anchor='w')
        htree.column('Old', width=80, anchor='w')
        htree.column('New', width=80, anchor='w')
        htree.column('Reason', width=300, anchor='w')
        htree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hscroll = ttk.Scrollbar(hist_frame, orient=tk.VERTICAL, command=htree.yview)
        htree.configure(yscroll=hscroll.set)
        hscroll.pack(side=tk.RIGHT, fill=tk.Y)

        def load_history_for(mid):
            for i in htree.get_children():
                htree.delete(i)
            if not os.path.exists(STOCK_ADJ_FILE):
                return
            try:
                with open(STOCK_ADJ_FILE, 'r', newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    rows = [r for r in rdr if (r.get('MedicineID') or '') == mid]
                # sort by Date desc
                try:
                    rows.sort(key=lambda r: datetime.strptime(r.get('Date',''), '%Y-%m-%d %H:%M:%S'), reverse=True)
                except Exception:
                    pass
                for r in rows:
                    htree.insert('', tk.END, values=(r.get('Date',''), r.get('User',''), r.get('Change',''), r.get('OldQty',''), r.get('NewQty',''), r.get('Reason','')))
            except Exception:
                return

        # Apply adjustment
        def apply_adjustment():
            sel = mtree.selection()
            if not sel:
                messagebox.showwarning('Select', 'Select a product first')
                return
            mid = sel[0]
            base_mid = mid.split('#', 1)[0]
            # find medicine by base id
            med = None
            for m in self.medicines:
                if (m.get('MedicineID') or '') == base_mid:
                    med = m
                    break
            if med is None:
                messagebox.showerror('Error', 'Selected product not found')
                return
            old_raw = (med.get('Quantity') or '').strip()
            try:
                oldv = float(old_raw) if old_raw != '' else 0.0
            except Exception:
                oldv = 0.0

            mode = mode_var.get()
            amt_s = amt_var.get().strip()
            if amt_s == '':
                messagebox.showwarning('Input', 'Enter amount')
                return
            try:
                amt = float(amt_s)
            except Exception:
                messagebox.showwarning('Input', 'Amount must be a number')
                return

            if mode == 'delta':
                newv = oldv + amt
                change = amt
            else:
                newv = amt
                change = newv - oldv

            reason = reason_txt.get('1.0', tk.END).strip()
            if not reason:
                messagebox.showwarning('Validation', 'Please enter a reason for the adjustment')
                return

            # negative result handling
            if newv < 0 and not force_neg_var.get():
                ok = messagebox.askyesno('Confirm', f'Resulting quantity would be {newv}. Proceed and allow negative?')
                if not ok:
                    return

            # persist change
            adj_id = str(uuid.uuid4())
            when = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            user = operator_var.get().strip()
            # append to STOCK_ADJ_FILE (use base MedicineID)
            first_write = not os.path.exists(STOCK_ADJ_FILE)
            try:
                with open(STOCK_ADJ_FILE, 'a', newline='', encoding='utf-8') as f:
                    fieldnames = ['AdjustmentID','MedicineID','Name','Supplier','OldQty','Change','NewQty','Mode','Reason','Date','User']
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    if first_write:
                        w.writeheader()
                    w.writerow({'AdjustmentID': adj_id, 'MedicineID': base_mid, 'Name': med.get('Name',''), 'Supplier': med.get('Supplier',''), 'OldQty': f"{oldv:.2f}" if isinstance(oldv, float) else str(oldv), 'Change': f"{change:.2f}", 'NewQty': f"{newv:.2f}", 'Mode': mode, 'Reason': reason, 'Date': when, 'User': user})
            except Exception as e:
                messagebox.showerror('Save', f'Failed to save adjustment: {e}')
                return

            # update in-memory and save medicines
            # store as integer string if whole-number
            if abs(newv - round(newv)) < 1e-9:
                new_str = str(int(round(newv)))
            else:
                new_str = f"{newv:.2f}"
            med['Quantity'] = new_str
            ok = self.save_inventory()
            if not ok:
                messagebox.showerror('Save', 'Failed to update inventory file')
                return

            messagebox.showinfo('Saved', f'Adjustment applied. New qty: {new_str}')
            try:
                self._close_all_child_toplevels()
            except Exception:
                pass
            sel_qty_var.set(new_str)
            # refresh lists
            refresh_meds()
            load_history_for(base_mid)

        # selection binding
        def on_select(event=None):
            sel = mtree.selection()
            if not sel:
                sel_name_var.set('')
                sel_supplier_var.set('')
                sel_qty_var.set('')
                for i in htree.get_children():
                    htree.delete(i)
                return
            mid = sel[0]
            # support iids that may be suffixed to keep uniqueness (e.g., 'MID#1')
            base_mid = mid.split('#', 1)[0]
            med = next((m for m in self.medicines if (m.get('MedicineID') or '') == base_mid), None)
            if not med:
                return
            sel_name_var.set(med.get('Name',''))
            sel_supplier_var.set(med.get('Supplier',''))
            sel_qty_var.set(med.get('Quantity',''))
            load_history_for(mid)

        mtree.bind('<<TreeviewSelect>>', on_select)

        # bottom buttons
        btn_frame = ttk.Frame(right)
        btn_frame.grid(row=14, column=0, pady=(12,0), sticky='ew')
        ttk.Button(btn_frame, text='Apply', command=apply_adjustment).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text='Close', command=top.destroy).pack(side=tk.RIGHT, padx=6)

        refresh_meds()

    def pick_date(self, parent, var):
        """Open a simple calendar picker and set `var` to selected YYYY-MM-DD."""
        # determine initial date
        try:
            init = datetime.strptime(var.get(), '%Y-%m-%d')
        except Exception:
            init = datetime.today()

        cal_top = tk.Toplevel(parent)
        try:
            self.maximize_window(cal_top)
        except Exception:
            pass
        cal_top.transient(parent)
        cal_top.title('Select Date')

        yr = init.year
        mth = init.month

        header = ttk.Frame(cal_top)
        header.pack(padx=8, pady=6)

        month_label = tk.StringVar()

        def refresh_calendar():
            month_label.set(f"{calendar.month_name[mth]} {yr}")
            for w in cal_grid.winfo_children():
                w.destroy()
            # weekday headers
            days = ['Mo','Tu','We','Th','Fr','Sa','Su']
            for c, d in enumerate(days):
                ttk.Label(cal_grid, text=d, width=3, anchor='center').grid(row=0, column=c)
            mc = calendar.monthcalendar(yr, mth)
            for r, week in enumerate(mc, start=1):
                for c, day in enumerate(week):
                    if day == 0:
                        ttk.Label(cal_grid, text='', width=3).grid(row=r, column=c)
                    else:
                        def on_click(d=day):
                            sel = datetime(yr, mth, d).strftime('%Y-%m-%d')
                            var.set(sel)
                            cal_top.destroy()
                        b = ttk.Button(cal_grid, text=str(day), width=3, command=on_click)
                        b.grid(row=r, column=c, padx=1, pady=1)

        def prev_month():
            nonlocal yr, mth
            if mth == 1:
                mth = 12
                yr -= 1
            else:
                mth -= 1
            refresh_calendar()

        def next_month():
            nonlocal yr, mth
            if mth == 12:
                mth = 1
                yr += 1
            else:
                mth += 1
            refresh_calendar()

        ttk.Button(header, text='<', width=3, command=prev_month).pack(side=tk.LEFT)
        ttk.Label(header, textvariable=month_label, width=18, anchor='center').pack(side=tk.LEFT, padx=6)
        ttk.Button(header, text='>', width=3, command=next_month).pack(side=tk.LEFT)

        cal_grid = ttk.Frame(cal_top)
        cal_grid.pack(padx=8, pady=(0,8))

        refresh_calendar()
        cal_top.grab_set()


def main():
    app = HomeoPatientApp()
    app.mainloop()


if __name__ == "__main__":
    main()
