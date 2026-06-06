# CellWatch AI - Offline Deployment Guide

## Problem
You need to deploy CellWatch AI to a laptop **without internet access**.

## Solution: Copy Entire Virtual Environment

Since your Python version (3.13) is very new and some packages don't have pre-built wheels yet, the **easiest offline method** is to copy the entire working environment.

---

## Prerequisites

### On Source Laptop (Current Machine)
- ✅ Python 3.13 installed
- ✅ Working `.venv` with all packages installed
- ✅ Project running successfully

### On Target Laptop (New Machine)
- ⚠️ **Must have Python 3.13.x installed** (same version)
- ⚠️ Must be Windows 64-bit (same OS)
- ⚠️ Download Python 3.13 installer beforehand if needed

---

## Step-by-Step Instructions

### Step 1: Prepare Files on Source Laptop

Copy these folders/files to USB drive:

```
📁 MovenetTutorial/
├── 📁 monitor_app/           ✅ All your code
├── 📁 .venv/                 ✅ Complete virtual environment (~2GB)
├── 📁 recordings/            ⚠️ Optional (only if you need history)
├── 📄 incidents.db           ⚠️ Optional (only if you need data)
├── 📄 requirements.txt       ✅ For reference
├── 📄 README.md              ✅ Documentation
└── 📄 installed_packages.txt ✅ Backup list of packages
```

**What to EXCLUDE:**
- ❌ `__pycache__/` folders
- ❌ `.pyc` files
- ❌ `.git/` (if you have it)

### Step 2: On Target Laptop

#### A. Install Python 3.13
1. Run the Python installer you downloaded
2. ✅ **Check "Add Python to PATH"**
3. Verify: `python --version` should show `3.13.x`

#### B. Copy Project Folder
1. Copy entire `MovenetTutorial/` folder from USB to laptop
2. Recommended location: `C:\Users\YourName\Projects\MovenetTutorial`

#### C. Activate and Test
```bash
cd C:\Users\YourName\Projects\MovenetTutorial
.venv\Scripts\activate
python monitor_app/main.py
```

---

## Troubleshooting

### ❌ Error: "Python version mismatch"
**Solution:** Install the exact same Python version (3.13.x) on target laptop

### ❌ Error: "Module not found"
**Solution:** The `.venv` might have broken paths. Try:
```bash
# Recreate venv using the backup list
python -m venv .venv_new
.venv_new\Scripts\activate
pip install -r installed_packages.txt
```

### ❌ Error: "CUDA/GPU not found"
**Solution:** This is normal if target laptop has different GPU. The app will fall back to CPU mode automatically.

---

## Alternative: Minimal Package Download (If You Have Limited Internet)

If you can get **brief internet access** on the target laptop:

```bash
# On target laptop with internet
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

This downloads ~2GB but ensures compatibility.

---

## File Size Reference

- **Project Code**: ~5 MB
- **Virtual Environment**: ~2 GB
- **Custom YOLO Model**: 6 MB
- **Total**: ~2.1 GB (fits on 4GB USB)

---

## Security Note

⚠️ If `incidents.db` contains sensitive data, consider:
- Encrypting the USB drive
- Deleting recordings before transfer
- Creating a fresh database on target laptop

---

## Quick Checklist

- [ ] Python 3.13 installer downloaded
- [ ] Project folder copied to USB
- [ ] `.venv` folder included
- [ ] `best.pt` model file present
- [ ] Target laptop has Python 3.13 installed
- [ ] Project runs: `python monitor_app/main.py`

---

## Need Help?

If the `.venv` copy doesn't work, you have two options:
1. **Get brief internet** on target laptop to run `pip install -r requirements.txt`
2. **Downgrade to Python 3.11** on both laptops (better package availability)
