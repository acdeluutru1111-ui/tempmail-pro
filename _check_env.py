from huggingface_hub import HfApi
api = HfApi()
space_id = 'hungba23213213/tempmail-bot'

try:
    # Try to get space secrets/env vars
    # Note: this requires write access
    import requests
    token = api.token
    headers = {"Authorization": f"Bearer {token}"}
    
    # Get space info including env vars
    resp = requests.get(
        f"https://huggingface.co/api/spaces/{space_id}",
        headers=headers,
        timeout=15,
    )
    data = resp.json()
    
    # Check for env vars
    env_vars = data.get('cardData', {}).get('env', [])
    print(f"Card data env: {env_vars}")
    
    # Check runtime
    runtime = data.get('runtime', {})
    print(f"Stage: {runtime.get('stage')}")
    print(f"Hardware: {runtime.get('hardware')}")
    
    # Check SDK
    print(f"SDK: {data.get('sdk')}")
    
except Exception as e:
    print(f"Error: {e}")
