import time
import os
from huggingface_hub import HfApi

api = HfApi()
space_id = 'hungba23213213/tempmail-bot'

# Single files to upload
single_files = [
    'main.py',
    'Dockerfile',
    'Procfile',
    'render.yaml',
    'requirements.txt',
    'README.md',
    '.gitignore',
]

# Directories to upload
folders = ['bot', 'services', 'utils']

print("=== Uploading single files ===")
for f in single_files:
    if not os.path.exists(f):
        print(f"  SKIP (not found): {f}")
        continue
    for attempt in range(5):
        try:
            api.upload_file(
                path_or_fileobj=f,
                path_in_repo=f,
                repo_id=space_id,
                repo_type='space',
                commit_message=f'Update {f}',
            )
            print(f"  OK: {f}")
            break
        except Exception as e:
            err = str(e)[:80]
            print(f"  Retry {attempt+1}/5 for {f}: {err}")
            time.sleep(3)
    else:
        print(f"  FAILED: {f}")

print("\n=== Uploading folders ===")
for folder in folders:
    if not os.path.isdir(folder):
        print(f"  SKIP (not found): {folder}/")
        continue
    for attempt in range(5):
        try:
            api.upload_folder(
                folder_path=folder,
                path_in_repo=folder,
                repo_id=space_id,
                repo_type='space',
                commit_message=f'Update {folder}/',
            )
            print(f"  OK: {folder}/")
            break
        except Exception as e:
            err = str(e)[:80]
            print(f"  Retry {attempt+1}/5 for {folder}/: {err}")
            time.sleep(5)
    else:
        print(f"  FAILED: {folder}/")

print("\n=== Done ===")
