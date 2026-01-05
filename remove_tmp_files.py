import os
files = [r"c:\Users\RASHID\Music\Taj Homeo\tmp_check_tesseract_cmd.py", r"c:\Users\RASHID\Music\Taj Homeo\tmp_import_app.py"]
for f in files:
    try:
        if os.path.exists(f):
            os.remove(f)
            print('removed', f)
        else:
            print('not found', f)
    except Exception as e:
        print('error removing', f, e)
