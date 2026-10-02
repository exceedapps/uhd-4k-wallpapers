# Backup copy — do NOT run from here

`build_catalog.py` here is a versioned BACKUP of the script that lives in the MONARQ Android
project (`<Android project>/tools/build_catalog.py`). It is run only from there: its paths are
relative to the Android project root (content/catalog, content/manifest.json,
app/src/main/assets/manifest.json).

After any change to the script, copy it here and commit:
    cp tools/build_catalog.py content/tools/build_catalog.py
