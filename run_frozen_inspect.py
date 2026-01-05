import sys
# simulate frozen environment
setattr(sys, 'frozen', True)
setattr(sys, '_MEIPASS', '')
from homeo_patient_app import HomeoPatientApp
import tkinter as tk
from tkinter import ttk

# create app (will open window briefly)
app = HomeoPatientApp()
# find toolbar container: search for frames with many buttons
labels = []
def walk(widget):
    for w in widget.winfo_children():
        # check for ttk.Button or tk.Button
        try:
            if isinstance(w, ttk.Button) or isinstance(w, tk.Button):
                try:
                    labels.append(w.cget('text'))
                except Exception:
                    pass
        except Exception:
            pass
        walk(w)

walk(app)

print('TOOLBAR_BUTTON_LABELS:')
for l in labels:
    print(l)

# destroy app
app.destroy()
