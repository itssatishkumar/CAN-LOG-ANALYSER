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
DEFAULT_LOCAL_VERSION = "1.0.0"

DEBUG = False  # 🔥 SET TRUE ONLY FOR DEBUGGING


# -------------------------------------------------------
# LOG HELPER
# -------------------------------------------------------
def log(msg):
    if DEBUG:
        print(msg)


# -------------------------------------------------------
# LOAD TOKEN
# -------------------------------------------------------
def load_token():
    token_file = "GITHUB_TOKEN.txt"
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            return f.read().strip()
    return None


GITHUB_TOKEN = load_token()
HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}


# -------------------------------------------------------
# SAFE REQUEST (RETRY LOGIC)
# -------------------------------------------------------
def safe_request(url, stream=False, timeout=15, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, stream=stream, timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception as e:
            log(f"Retry {i+1} failed: {e}")
            time.sleep(2)
    return None


# -------------------------------------------------------
# LOCAL VERSION
# -------------------------------------------------------
def read_local_version(default=DEFAULT_LOCAL_VERSION):
    version_path = os.path.join(os.path.dirname(sys.argv[0]), "version.txt")
    try:
        with open(version_path, "r") as f:
            return f.read().strip() or default
    except Exception:
        return default


# -------------------------------------------------------
# FETCH TEXT
# -------------------------------------------------------
def get_text_file_content(url):
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

    total = int(r.headers.get("content-length", 0))
    downloaded = 0

    with open(target_path, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)

                if total > 0:
                    progress.setValue(downloaded)

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
def sync_github_folder(api_url, local_path, progress):
    r = safe_request(api_url)
    if not r:
        QMessageBox.warning(None, "Update Failed", "Network error.")
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
            if not sync_github_folder(item["url"], local_item_path, progress):
                return False

    return True


# -------------------------------------------------------
# MAIN UPDATE FUNCTION
# -------------------------------------------------------
def check_for_update(local_version, app, force=False):

    online_version = get_text_file_content(RAW_VERSION_URL)

    if not online_version:
        QMessageBox.warning(None, "Update Error", "Failed to fetch version.")
        return

    if online_version == local_version and not force:
        return

    # ---------------- DIALOG ----------------
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Question)
    msg.setWindowTitle("Update Available")
    msg.setText(f"New version ({online_version}) available.\n\nUpdate now?")
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

    if msg.exec() != QMessageBox.Yes:
        return

    target_folder = os.path.dirname(os.path.abspath(sys.argv[0]))

    # ---------------- EXE MODE ----------------
    if is_running_as_exe():
        exe_url_file = f"https://raw.githubusercontent.com/{REPO_USER}/{REPO_NAME}/{BRANCH}/appversion.txt"
        exe_download_url = get_text_file_content(exe_url_file)

        if not exe_download_url:
            QMessageBox.warning(None, "Update Failed", "No EXE URL.")
            return

        new_exe_path = os.path.join(target_folder, "UPDATED_APP.exe")
        updater_path = os.path.join(target_folder, "updater.exe")

        progress = QProgressDialog("Downloading update...", "Cancel", 0, 100)
        progress.setWindowModality(Qt.ApplicationModal)
        progress.show()

        if not download_file(exe_download_url, new_exe_path, progress):
            return

        subprocess.Popen([updater_path, sys.argv[0], new_exe_path], shell=True)
        sys.exit(0)

    # ---------------- PYTHON MODE ----------------
    progress = QProgressDialog("Updating...", "Cancel", 0, 0)
    progress.setWindowTitle("Updating...")
    progress.setWindowModality(Qt.ApplicationModal)
    progress.show()

    if not sync_github_folder(API_ROOT_URL, target_folder, progress):
        QMessageBox.warning(None, "Update Failed", "Update incomplete.")
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
