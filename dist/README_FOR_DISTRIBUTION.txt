Taj Homeo — EXE Distribution README

This README explains how to package and ship the built EXE so it runs on other Windows machines.

1) What to include (recommended portable ZIP)
- TajHomeoApp.exe  (from dist\TajHomeoApp.exe)
- Optional: Tesseract-OCR\  (if you use OCR features; include full folder with tesseract.exe)
- storage\  (optional initial CSVs you want to ship: medicines.csv, patients.csv, suppliers.csv, etc.)
- PORTABLE  (an empty file to force portable mode if you want the app to store CSVs next to the EXE)
- README_FOR_DISTRIBUTION.txt (this file)

Recommended ZIP layout:
- TajHomeoApp.exe
- Tesseract-OCR\tesseract.exe
- storage\medicines.csv
- storage\patients.csv
- PORTABLE
- README_FOR_DISTRIBUTION.txt

Note: To avoid accidentally sharing existing patient or clinic data, the portable ZIP produced by default for distribution does NOT include your current CSV data. The `dist\storage` folder will be empty in the shipped ZIP unless you explicitly copy CSV files into it before zipping.
If you want to pre-populate the app for a recipient (for demo/testing), copy only the intentionally-shared CSV files into `dist\storage` before creating the ZIP.

2) Portable vs per-user storage
- Portable mode: create an empty file named "PORTABLE" in the same folder as the EXE. When present the app stores/reads CSVs in the EXE folder (recommended for distributing a ready-to-run bundle).
- Per-user storage (default): app stores CSVs under %APPDATA%\TajHomeo. This is better for multi-user installs but requires recipients to know where data will be written.

3) Tesseract (OCR)
- The app expects Tesseract at: C:\Program Files\Tesseract-OCR\tesseract.exe by default.
- If you bundle Tesseract inside the ZIP, include the folder `Tesseract-OCR` and the app will try common locations. (If not detected, edit the EXE config or environment to point `pytesseract.pytesseract.tesseract_cmd` to the bundled path.)

4) Visual C++ Redistributable
- The built EXE may require the Microsoft Visual C++ redistributable (2015-2022). If a target machine does not have it, provide the installer or the user can download it from Microsoft.

5) Running on the target machine
- Unzip the bundle to a folder (e.g., C:\Users\Someone\TajHomeo).
- If you included `Tesseract-OCR`, ensure `Tesseract-OCR\tesseract.exe` exists.
- If you want portable storage, ensure `PORTABLE` file is present.
- Run `TajHomeoApp.exe` by double-clicking it.

6) Troubleshooting
- App doesn't start or shows an error:
  - Try running from PowerShell to see stdout/stderr: open PowerShell, cd to the EXE folder, then run:
    TajHomeoApp.exe
  - Check for missing VC++ Redistributable errors and install the MSVC runtime as needed.
  - If OCR features fail, confirm Tesseract is present and reachable by the path above.
- Data not present: if the app uses %APPDATA% and you expected portable files, create `PORTABLE` in the EXE folder.
- Permission errors: run from a user-writable folder (like Desktop or Documents) rather than Program Files.

7) Optional: Code signing
- Unsigned EXEs may trigger SmartScreen warnings. To avoid this when distributing to many users, sign the EXE with a code-signing certificate.

8) Packaging tips
- Zip the `dist` folder contents (not the parent folder) so the end user extracts the EXE next to any bundled folders.
- Test the ZIP on a clean VM (no Python, no Tesseract) before sending.

9) Logs
- If you need debugging information, collect the `run_log.txt` (if created) and any message box text / screenshots.

If you want, I can:
- Bundle `Tesseract-OCR` into the `dist` folder and produce a portable ZIP for you, or
- Produce a short one-page README (PDF) you can attach to an email, or
- Create an installer (MSI) that installs prerequisites automatically.

Tell me which option you prefer and I will proceed.
