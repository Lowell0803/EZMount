# EZMount

[![Made with Python](readme/made-with-python.svg)](https://forthebadge.com)

<p align="center">
  <img src="./readme/logo.png" alt="EZMount Logo" width="400"/>
</p>

EZMount is a small GUI utility (Tk/Ttk) that helps manage rclone mounts and simple startup automation. It provides a compact way to mount/unmount cloud remotes, track active mounts, and create startup entries that will re-create mounts on login.

---

## Instructions

Before running EZMount, do the following:

1. **Generate an `rclone` config (`rclone.conf`) first** using `rclone config` (encryption for remotes is recommended).
2. Ensure **`rclone`** and **`nircmd`** (Windows only, optional but recommended for hidden startup execution) are installed and available on your system `PATH`.
   - On Windows, `nircmd.exe` is used to run rclone in a hidden window when creating `.cmd` startup files. If not available, EZMount will fall back to a `start /min` command which still works but shows a short window.
3. Place your `rclone.conf` somewhere accessible and point EZMount to it when the app asks.

---

## How to run

- **If you downloaded the prebuilt EXE (recommended for most users)**

  - Just download the EXE from the release page and run it. No Python install required.

- **If running from source**

  - Requires Python 3.8+ (3.10+ recommended) and the dependencies in the project (e.g. `sv-ttk`, `darkdetect`). Example quick start:
    ```bash
    python -m venv venv
    venv\Scripts\activate      # Windows
    pip install -U pip
    pip install sv-ttk darkdetect
    python main.py
    ```
  - Point the app at your `rclone.conf` when prompted.

- **If you want to build a single EXE yourself** (Windows example with PyInstaller):
  ```bash
  pip install pyinstaller
  pyinstaller --onefile --windowed --icon=app.ico --name EZMount main.py
  ```
