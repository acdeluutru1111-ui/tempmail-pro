from huggingface_hub import HfApi
import os

api = HfApi()
space_id = 'hungba23213213/tempmail-bot'

# Check HF Space files and their sizes
print("=== HF Space files ===")
try:
    files = list(api.list_repo_tree(space_id, repo_type='space', recursive=True))
    for f in files:
        sz = getattr(f, 'size', '?')
        print(f"  {f.path}  ({sz})")
except Exception as e:
    print(f"Error listing: {e}")

# Download app.py from HF to compare
print("\n=== Comparing app.py ===")
try:
    from huggingface_hub import hf_hub_download
    p = hf_hub_download(space_id, 'app.py', repo_type='space', local_dir='_hf_check')
    hf_size = os.path.getsize(p)
    local_size = os.path.getsize('app.py')
    print(f"  HF app.py: {hf_size} bytes")
    print(f"  Local app.py: {local_size} bytes")
    print(f"  Same? {hf_size == local_size}")
    
    # Check for debug endpoint in HF version
    with open(p, 'r') as f:
        content = f.read()
    has_debug = '/debug' in content
    has_tg_timeout = 'TG_TIMEOUT = 10' in content
    print(f"  Has /debug endpoint: {has_debug}")
    print(f"  Has TG_TIMEOUT=10: {has_tg_timeout}")
except Exception as e:
    print(f"Error: {e}")
