import os
import sys
import requests
import subprocess
import time
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PySide6.QtCore import Qt

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
REPO_USER = "itssatishkumar"
REPO_NAME = "CAN-LOG-ANALYSER"
BRANCH = "main"

RAW_VERSION_URL = f"https://raw.githubusercontent.com/{REPO_USER}/{REPO_NAME}/{BRANCH}/version.txt"
API_ROOT_URL = f"https://api.github.com/repos/{REPO_USER}/{REPO_NAME}/contents"

# 🔥 PUT YOUR TOKEN HERE (READ-ONLY)
GITHUB_TOKEN = "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"
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

DEFAULT_LOCAL_VERSION = "1.0.0"


# -------------------------------------------------------
# SAFE REQUEST (RETRY)
# -------------------------------------------------------
def safe_request(url, stream=False, timeout=15, retries=3):
    for _ in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, stream=stream, timeout=timeout)
            if r.status_code == 200:
                return r
        except:
            time.sleep(2)
    return None


# -------------------------------------------------------
# LOCAL VERSION
# -------------------------------------------------------
def read_local_version(default=DEFAULT_LOCAL_VERSION):
    try:
        with open(os.path.join(os.path.dirname(sys.argv[0]), "version.txt"), "r") as f:
            return f.read().strip() or default
    except:
        return default


# -------------------------------------------------------
# FETCH TEXT
# -------------------------------------------------------
def get_text(url):
    r = safe_request(url)
    if r:
        return r.text.strip()
    return None


# -------------------------------------------------------
# DOWNLOAD FILE
# -------------------------------------------------------
def download_file(url, target_path, progress):
    if not url:
        return True

    r = safe_request(url, stream=True)
    if not r:
        return False

    with open(target_path, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
                QApplication.processEvents()
                if progress.wasCanceled():
                    return False

    return True


# -------------------------------------------------------
# EXE DETECTION
# -------------------------------------------------------
def is_running_as_exe():
    return getattr(sys, 'frozen', False)


# -------------------------------------------------------
# SYNC GITHUB
# -------------------------------------------------------
def sync_folder(api_url, local_path, progress):
    r = safe_request(api_url)
    if not r:
        return False

    items = r.json()
    os.makedirs(local_path, exist_ok=True)

    for item in items:
        name = item["name"]

        if name == "__pycache__":
            continue

        local_item_path = os.path.join(local_path, name)

        progress.setLabelText(f"Updating: {name}")
        QApplication.processEvents()

        if item["type"] == "file":
            if not download_file(item.get("download_url"), local_item_path, progress):
                return False

        elif item["type"] == "dir":
            if not sync_folder(item["url"], local_item_path, progress):
                return False

    return True


# -------------------------------------------------------
# MAIN UPDATE FUNCTION
# -------------------------------------------------------
def check_for_update(local_version, app):

    online_version = get_text(RAW_VERSION_URL)

    if not online_version:
        return

    # ✅ NO UPDATE
    if online_version == local_version:
        print("Already up to date")
        return

    # 🔥 ASK USER
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Question)
    msg.setWindowTitle("Update Available")
    msg.setText(f"New version ({online_version}) available.\n\nUpdate now?")
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

    if msg.exec() != QMessageBox.Yes:
        return

    print("Updating...")

    target_folder = os.path.dirname(os.path.abspath(sys.argv[0]))

    # ---------------- EXE MODE ----------------
    if is_running_as_exe():
        exe_url_file = f"https://raw.githubusercontent.com/{REPO_USER}/{REPO_NAME}/{BRANCH}/appversion.txt"
        exe_download_url = get_text(exe_url_file)

        if not exe_download_url:
            QMessageBox.warning(None, "Update Failed", "No EXE URL.")
            return

        new_exe_path = os.path.join(target_folder, "UPDATED_APP.exe")
        updater_path = os.path.join(target_folder, "updater.exe")

        progress = QProgressDialog("Downloading update...", "Cancel", 0, 0)
        progress.setWindowModality(Qt.ApplicationModal)
        progress.show()

        if not download_file(exe_download_url, new_exe_path, progress):
            QMessageBox.warning(None, "Update Failed", "Download failed.")
            return

        subprocess.Popen([updater_path, sys.argv[0], new_exe_path], shell=True)
        sys.exit(0)

    # ---------------- PYTHON MODE ----------------
    progress = QProgressDialog("Updating...", "Cancel", 0, 0)
    progress.setWindowModality(Qt.ApplicationModal)
    progress.show()

    if not sync_folder(API_ROOT_URL, target_folder, progress):
        QMessageBox.warning(None, "Update Failed", "Update failed.")
        return

    # Save version
    with open(os.path.join(target_folder, "version.txt"), "w") as f:
        f.write(online_version)

    progress.close()

    QMessageBox.information(None, "Success", "Update complete. Restart app.")
    sys.exit(0)


# -------------------------------------------------------
# RUN
# -------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    check_for_update(read_local_version(), app)
    sys.exit(app.exec())
