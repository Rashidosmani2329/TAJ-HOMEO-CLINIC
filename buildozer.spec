title = TajHomeo
[app]
title = Taj Homeo
package.name = tajhomeo
package.domain = org.tajhomeo

# Source include extensions
source.include_exts = py,kv,png,jpg,svg,csv

# Requirements: pin Kivy to a stable release; include pillow. Omit pytesseract by default
# NOTE: pytesseract requires the Tesseract native binary which is NOT provided by default on Android.
requirements = python3,kivy==2.1.0,pillow

orientation = portrait

# Android settings
android.api = 33
android.minapi = 21
android.archs = armeabi-v7a,arm64-v8a

# Permissions your app needs
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,INTERNET

# Use a recent NDK (buildozer/p4a will download the matching NDK)
android.ndk = 25b

# Prevent auto-rotation if you prefer fixed portrait
orientation = portrait

[buildozer]
log_level = 2
warn_on_root = 1

[android]
# (int) Android API to use
api = 33

# (str) Android entrypoint
entrypoint = org.kivy.android.PythonActivity

# (str) Android app theme, using default
# android.theme = '@style/MyTheme'

