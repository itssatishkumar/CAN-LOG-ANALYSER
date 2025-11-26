import os
import requests

# -----------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------
USERNAME = "YOUR_GITHUB_USERNAME"
REPO     = "YOUR_REPO_NAME"
BRANCH   = "main"   # or master

API_URL = f"https://api.github.com/repos/{USERNAME}/{REPO}/contents"
VERSION_URL = f"https://raw.githubusercontent.com/{USERNAME}/{REPO}/{BRANCH}/version.txt"
LOCAL_VERSION_FILE = "version.txt"
# -----------------------------------------------------


# -----------------------------------------------------
# VERSION CHECKING
# -----------------------------------------------------
def get_local_version():
    if not os.path.exists(LOCAL_VERSION_FILE):
        return "0.0.0"
    return open(LOCAL_VERSION_FILE).read().strip()

def get_remote_version():
    r = requests.get(VERSION_URL)
    return r.text.strip()

def is_update_available():
    return get_local_version() != get_remote_version()
# -----------------------------------------------------


# -----------------------------------------------------
# FILE & FOLDER SYNC
# -----------------------------------------------------
def sync_folder(git_path, local_path):
    """ Sync a folder from GitHub to local PC recursively. """

    url = f"{API_URL}/{git_path}?ref={BRANCH}"
    response = requests.get(url).json()

    # Error handler
    if isinstance(response, dict) and "message" in response:
        print("Error:", response["message"])
        return

    # Ensure local folder exists
    if not os.path.exists(local_path):
        os.makedirs(local_path)

    for item in response:
        name = item["name"]
        item_type = item["type"]
        git_item_path = item["path"]
        local_item_path = os.path.join(local_path, name)

        # If it is a file → download it
        if item_type == "file":
            download_file(item["download_url"], local_item_path)

        # If it is a folder → recursively sync it
        elif item_type == "dir":
            sync_folder(git_item_path, local_item_path)


def download_file(url, local_path):
    """ Download a single file from GitHub into local folder. """
    print(f"Downloading: {local_path}")
    data = requests.get(url).content

    with open(local_path, "wb") as f:
        f.write(data)
# -----------------------------------------------------


# -----------------------------------------------------
# MAIN UPDATE FLOW
# -----------------------------------------------------
def run_updater():
    local = get_local_version()
    remote = get_remote_version()

    print("Local version :", local)
    print("Git version   :", remote)

    if local == remote:
        print("\n✔ Your software is already up to date.")
        return

    choice = input("\nNew update available. Update now? (y/n): ").strip().lower()
    if choice != "y":
        print("❌ Update canceled.")
        return

    print("\n🔄 Updating files...\n")
    sync_folder("", ".")
    print("\n✅ Update completed successfully!")
# -----------------------------------------------------


if __name__ == "__main__":
    run_updater()
