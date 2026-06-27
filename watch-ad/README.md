# Watch Ad - Telegram Web App

Monetag rewarded interstitial page for Telegram Mini App.

## Deploy to GitHub Pages

```bash
# 1. Tạo repo mới trên GitHub (ví dụ: watch-ad-page)

# 2. Clone repo
git clone https://github.com/YOUR_USERNAME/watch-ad-page.git
cd watch-ad-page

# 3. Copy file index.html vào đây
copy ..\index.html .

# 4. Push
git add .
git commit -m "Add watch-ad page"
git push origin main

# 5. Vào GitHub repo → Settings → Pages → Source: Deploy from branch → main → / (root)
# 6. URL sẽ là: https://YOUR_USERNAME.github.io/watch-ad-page/
```

## Deploy to Surge.sh (nhanh nhất)

```bash
# 1. Cài surge
npm install -g surge

# 2. Deploy
cd watch-ad
surge . watch-ad-tempmail.surge.sh

# 3. Done! URL: https://watch-ad-tempmail.surge.sh
```

## Cập nhật URL trong main.py

Sau khi có URL, cập nhật trong `main.py`:

```python
# Dòng ~38, thay đổi WEBHOOK_URL hoặc hardcode:
AD_WEB_URL = "https://YOUR_USERNAME.github.io/watch-ad-page"
```
