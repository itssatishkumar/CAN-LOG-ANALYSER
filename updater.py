import os
import sys
import requests
import subprocess
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PySide6.QtCore import Qt

# -------------------------------------------------------
# GITHUB REPO CONFIG
# -------------------------------------------------------
REPO_USER = "itssatishkumar"
REPO_NAME = "CAN-LOG-ANALYSER"
BRANCH = "main"

RAW_VERSION_URL = f"https://raw.githubusercontent.com/{REPO_USER}/{REPO_NAME}/{BRANCH}/version.txt"
API_ROOT_URL = f"https://api.github.com/repos/{REPO_USER}/{REPO_NAME}/contents"
DEFAULT_LOCAL_VERSION = "1.0.0"


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
# LOCAL VERSION
# -------------------------------------------------------
def read_local_version(default=DEFAULT_LOCAL_VERSION):
    version_path = os.path.join(os.path.dirname(sys.argv[0]), "version.txt")
    try:
        with open(version_path, "r") as f:
            version = f.read().strip()
            print("LOCAL VERSION:", version)
            return version or default
    except Exception:
        print("Using default version:", default)
        return default


# -------------------------------------------------------
# FETCH FROM GITHUB
# -------------------------------------------------------
def get_text_file_content(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print("Fetching:", url, "| Status:", r.status_code)

        if r.status_code == 200:
            return r.text.strip()
        else:
            print("GitHub error:", r.text)
            return None
    except Exception as e:
        print("Error fetching:", e)
        return None


# -------------------------------------------------------
# DOWNLOAD FILE
# -------------------------------------------------------
def download_file(url, target_path, parent=None):
    if not url:
        print("Skipping file (no URL):", target_path)
        return True

    try:
        print("Downloading:", url)

        r = requests.get(url, headers=HEADERS, stream=True, timeout=20)
        r.raise_for_status()

        total = int(r.headers.get("content-length", 0))

        progress = QProgressDialog(
            f"Downloading {os.path.basename(target_path)}...",
            "Cancel", 0, total if total > 0 else 0, parent
        )
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setWindowTitle("Updating...")
        progress.show()

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
                        print("Download cancelled")
                        return False

        progress.close()
        return True

    except Exception as e:
        print("Download failed:", e)
        return False


# -------------------------------------------------------
# EXE DETECTION
# -------------------------------------------------------
def is_running_as_exe():
    return getattr(sys, 'frozen', False)


# -------------------------------------------------------
# SYNC GITHUB FOLDER
# -------------------------------------------------------
def sync_github_folder(api_url, local_path, progress):
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=20)
        print("Fetching folder:", api_url, "| Status:", r.status_code)

        if r.status_code != 200:
            print("GitHub API error:", r.text)
            return False

        items = r.json()

    except Exception as e:
        QMessageBox.warning(None, "Update Failed", f"Error:\n{e}")
        return False

    os.makedirs(local_path, exist_ok=True)

    for item in items:
        name = item["name"]
        item_type = item["type"]

        if name == "__pycache__":
            continue

        local_item_path = os.path.join(local_path, name)

        print("Processing:", name, "| Type:", item_type)

        if item_type == "file":
            download_url = item.get("download_url")

            progress.setLabelText(f"Downloading: {name}")
            QApplication.processEvents()

            if not download_file(download_url, local_item_path):
                return False

        elif item_type == "dir":
            if not sync_github_folder(item["url"], local_item_path, progress):
                return False

    return True


# -------------------------------------------------------
# UPDATE FUNCTION (FIXED DIALOG)
# -------------------------------------------------------
def check_for_update(local_version, app, force=False):

    online_version = get_text_file_content(RAW_VERSION_URL)
    print("ONLINE VERSION:", online_version)

    if not online_version:
        QMessageBox.warning(None, "Update Error", "Failed to fetch version.")
        return

    if online_version == local_version and not force:
        print("Already up to date")
        return

    print("Showing update dialog...")

    msg = QMessageBox()
    msg.setIcon(QMessageBox.Question)
    msg.setWindowTitle("Update Available")
    msg.setText(f"New version ({online_version}) available.\n\nUpdate now?")
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setWindowModality(Qt.ApplicationModal)

    reply = msg.exec()

    if reply != QMessageBox.Yes:
        print("User cancelled update")
        return

    target_folder = os.path.dirname(os.path.abspath(sys.argv[0]))

    # ---------------- EXE MODE ----------------
    if is_running_as_exe():
        print("Running in EXE mode")

        exe_url_file = f"https://raw.githubusercontent.com/{REPO_USER}/{REPO_NAME}/{BRANCH}/appversion.txt"
        exe_download_url = get_text_file_content(exe_url_file)

        if not exe_download_url:
            QMessageBox.warning(None, "Update Failed", "No EXE URL.")
            return

        new_exe_path = os.path.join(target_folder, "UPDATED_APP.exe")
        updater_path = os.path.join(target_folder, "updater.exe")

        if not download_file(exe_download_url, new_exe_path):
            return

        subprocess.Popen([updater_path, sys.argv[0], new_exe_path], shell=True)
        sys.exit(0)

    # ---------------- PYTHON MODE ----------------
    print("Running in PYTHON mode")

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
# RUN (FIXED EVENT LOOP)
# -------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    check_for_update(read_local_version(), app)
    sys.exit(app.exec())
