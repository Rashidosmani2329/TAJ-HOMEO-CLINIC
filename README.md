# TAJ-HOMEO-CLINIC

Simple homeopathy clinic management app (Kivy + Python).

Quick start

- Create a virtualenv and activate it.
- Install dependencies:

```bash
python -m pip install -r requirements.txt
```

- Run the app:

```bash
python homeo_kivy_app.py
```

CI

This repository includes a basic GitHub Actions workflow at `.github/workflows/ci.yml` that installs dependencies and runs a syntax check and tests if present.

License

Add your license here.
# Homeo Doctor — Patient Registry (Python)

Simple Tkinter app for a homeopathic doctor to add patient details.

Features:
- Form fields: Title (dropdown: `MR`, `MRS`), Name, Age, Address
- Saves entries to `patients.csv` in the same folder
- Shows saved patients in a list view

Requirements:
- Python 3 (3.7+ recommended)
- Tkinter (usually bundled with standard Python installations)

Run (PowerShell):
```
cd "c:\Users\RASHID\Music\Taj Homeo"
python .\homeo_patient_app.py
```

The app will create `patients.csv` on first save. Use the UI to add and view patients.
