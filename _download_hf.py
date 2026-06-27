from huggingface_hub import hf_hub_download
import shutil

# Download the app.py from HF Space
path = hf_hub_download(
    'hungba23213213/tempmail-bot', 
    'app.py', 
    repo_type='space',
    local_dir='_hf_current'
)
print(f"Downloaded to: {path}")
