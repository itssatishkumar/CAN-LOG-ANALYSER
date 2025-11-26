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


# -------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------

def get_text_file_content(url):
    """Fetch plain text file from GitHub (version.txt)."""
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.text.strip()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


def download_file(url, target_path, parent=None):
    """Download a file with GUI progress bar."""
    try:
        r = requests.get(url, stream=True, timeout=20)
        r.raise_for_status()

        total = int(r.headers.get("content-length", 0))

        progress = QProgressDialog(
            f"Downloading {os.path.basename(target_path)}...",
            "Cancel",
            0,
            total if total > 0 else 0,
            parent
        )
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setWindowTitle("Updating…")
        progress.setMinimumDuration(200)
        progress.show()

        downloaded = 0
        chunk_size = 8192

        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        progress.setValue(downloaded)

                    QApplication.processEvents()
                    if progress.wasCanceled():
                        progress.close()
                        return False

        progress.close()
        return True

    except Exception as e:
        print(f"Download failed for {url}: {e}")
        return False


def is_running_as_exe():
    """Detect if the program is running as a compiled EXE."""
    _, ext = os.path.splitext(sys.argv[0])
    return ext.lower() == ".exe"


# -------------------------------------------------------
# RECURSIVE GITHUB FOLDER SYNC
# -------------------------------------------------------

def sync_github_folder(api_url, local_path, progress):
    """Recursively download folders & files from GitHub using API."""
    try:
        r = requests.get(api_url, timeout=20)
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        QMessageBox.warning(None, "Update Failed", f"Error fetching GitHub folder:\n{e}")
        return False

    if not os.path.exists(local_path):
        os.makedirs(local_path, exist_ok=True)

    for item in items:
        name = item["name"]
        item_type = item["type"]
        download_url = item.get("download_url")
        next_api_url = item["url"]
        local_item_path = os.path.join(local_path, name)

        # Skip unwanted cache directories
        if name == "__pycache__":
            continue

        if item_type == "file":
            progress.setLabelText(f"Downloading: {name}")
            QApplication.processEvents()

            if not download_file(download_url, local_item_path, parent=None):
                return False

        elif item_type == "dir":
            # Recursively download the directory
            if not sync_github_folder(next_api_url, local_item_path, progress):
                return False

    return True


# -------------------------------------------------------
# MAIN UPDATE FUNCTION
# -------------------------------------------------------

def check_for_update(local_version, app):
    parent = app.activeWindow() if app else None

    # 1. Check version from GitHub
    online_version = get_text_file_content(RAW_VERSION_URL)
    if not online_version:
        QMessageBox.warning(parent, "Update Error", "Could not read version.txt from GitHub.")
        return

    if online_version == local_version:
        print("Already up to date")
        return

    # 2. Ask user
    reply = QMessageBox.question(
        parent,
        "Update Available",
        f"A new version ({online_version}) is available.\n\nDo you want to update?",
        QMessageBox.Yes | QMessageBox.No
    )
    if reply != QMessageBox.Yes:
        return

    target_folder = os.path.dirname(os.path.abspath(sys.argv[0]))

    # 3. If running as EXE
    if is_running_as_exe():
        exe_url_file = f"https://raw.githubusercontent.com/{REPO_USER}/{REPO_NAME}/{BRANCH}/appversion.txt"
        exe_download_url = get_text_file_content(exe_url_file)

        if not exe_download_url:
            QMessageBox.warning(parent, "Update Failed", "Could not fetch EXE URL.")
            return

        new_exe_path = os.path.join(target_folder, "UPDATED_APP.exe")
        updater_path = os.path.join(target_folder, "updater.exe")

        if not download_file(exe_download_url, new_exe_path, parent):
            QMessageBox.warning(parent, "Update Failed", "Failed to download EXE.")
            return

        subprocess.Popen([updater_path, sys.argv[0], new_exe_path], shell=True)
        sys.exit(0)

    # 4. Python script mode → Full folder sync
    progress = QProgressDialog("Updating...", "Cancel", 0, 0, parent)
    progress.setWindowTitle("Updating…")
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setMinimumDuration(200)
    progress.show()

    if not sync_github_folder(API_ROOT_URL, target_folder, progress):
        QMessageBox.warning(parent, "Update Failed", "Some files could not be updated.")
        return

    # 5. Save new version
    with open(os.path.join(target_folder, "version.txt"), "w") as vf:
        vf.write(online_version)

    progress.close()

    QMessageBox.information(parent, "Update Complete", "Update installed.\nPlease restart application.")
    sys.exit(0)


# -------------------------------------------------------
# RUN DIRECTLY
# -------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Change this to your actual local version
    check_for_update(local_version="1.0.0", app=app)
