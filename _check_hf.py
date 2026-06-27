from huggingface_hub import HfApi
api = HfApi()
try:
    files = list(api.list_repo_tree('hungba23213213/tempmail-bot', repo_type='space'))
    for f in files:
        sz = getattr(f, 'size', '?')
        print(f"  {f.path}  ({sz})")
except Exception as e:
    print(f"Error: {e}")
