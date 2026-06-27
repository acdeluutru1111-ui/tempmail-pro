import requests, json

TOKEN = '8919838655:AAFGu_IevkdJ1uc-BrEX0okK0_QBZw0T4kA'
WH_URL = 'https://hungba23213213-tempmail-bot.hf.space/webhook/' + TOKEN

# Set webhook directly via Telegram API
r = requests.post(
    'https://api.telegram.org/bot' + TOKEN + '/setWebhook',
    json={'url': WH_URL, 'allowed_updates': ['message', 'callback_query']},
    timeout=15
)
print('setWebhook:', r.json())

# Check webhook info
r2 = requests.get('https://api.telegram.org/bot' + TOKEN + '/getWebhookInfo', timeout=15)
info = r2.json()['result']
print('URL:', info['url'])
print('Pending updates:', info['pending_update_count'])
print('Last error:', info.get('last_error_message', 'none'))
print('Has custom cert:', info.get('has_custom_certificate', False))
