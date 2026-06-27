import time, os
from huggingface_hub import HfApi

api = HfApi()
space_id = 'hungba23213213/tempmail-bot'

# Read current Dockerfile and add a comment to force rebuild
with open('Dockerfile', 'r') as f:
    content = f.read()

new_content = content.rstrip() + '\n# rebuild trigger ' + str(int(time.time())) + '\n'
with open('_Dockerfile_tmp', 'w') as f:
    f.write(new_content)

# Upload modified Dockerfile to trigger rebuild
api.upload_file(
    path_or_fileobj='_Dockerfile_tmp',
    path_in_repo='Dockerfile',
    repo_id=space_id,
    repo_type='space',
    commit_message='Force rebuild to inject secrets',
)
print('Rebuild triggered!')

# Wait for rebuild
print('Waiting 120s for Docker rebuild...')
time.sleep(120)

# Check
info = api.space_info(space_id)
sha = info.runtime.raw.get('sha', 'N/A')
stage = info.runtime.stage
print(f'Stage: {stage}')
print(f'SHA: {sha}')

# Cleanup
os.remove('_Dockerfile_tmp')
print('Done!')
