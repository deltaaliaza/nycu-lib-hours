# 陽明交通大學圖書館 今日開館狀態

部署在 GitHub Pages 的圖書館開館時間看板，每日自動從 Google Calendar iCal 更新。

## 專案結構

```
nycu-lib-hours/
├── index.html              # 前端頁面（純靜態，讀取 data.json）
├── data.json               # 由 GitHub Actions 自動產生的開館資料
├── fetch_hours.py          # 抓取 iCal 並產生 data.json 的 Python 腳本
└── .github/
    └── workflows/
        └── update-hours.yml  # 定時執行排程
```

## 資料來源

- **交大校區**：Google Calendar iCal 公開網址
- **陽明校區**：Google Calendar iCal 公開網址
- 不需要 API Key，直接使用行事曆的 iCal 公開連結

## 更新排程

GitHub Actions 在台北時間以下時間自動執行：
- 00:01（午夜）
- 06:01（早上）
- 12:01（中午）
- 18:01（下午）

## 部署步驟

### 1. 建立 GitHub Repository

```bash
git init
git add .
git commit -m "init: library hours card"
git remote add origin https://github.com/你的帳號/nycu-lib-hours.git
git push -u origin main
```

### 2. 開啟 GitHub Pages

1. 進入 Repository → **Settings** → **Pages**
2. Source 選擇 **Deploy from a branch**
3. Branch 選 **main**，目錄選 **/ (root)**
4. 儲存後約 1 分鐘即可透過 `https://你的帳號.github.io/nycu-lib-hours/` 存取

### 3. 開啟 GitHub Actions 權限

1. 進入 Repository → **Settings** → **Actions** → **General**
2. 在 **Workflow permissions** 選擇 **Read and write permissions**
3. 儲存

### 4. 手動觸發第一次更新

1. 進入 Repository → **Actions** → **Update Library Hours**
2. 點 **Run workflow** 手動執行一次，確認 data.json 正確產生

## 本地測試

```bash
pip install requests icalendar python-dateutil pytz
python fetch_hours.py
cat data.json
```

## data.json 格式

```json
{
  "date": "2026-03-24",
  "updated_at": "2026-03-24T06:01:00+08:00",
  "campuses": {
    "jd": {
      "name": "交大校區",
      "closed": false,
      "hours": "08:00–22:30",
      "note": null,
      "fetch_error": false,
      "calendar_url": "https://..."
    },
    "ym": {
      "name": "陽明校區",
      "closed": true,
      "hours": null,
      "note": "兒童節補假休館",
      "fetch_error": false,
      "calendar_url": "https://..."
    }
  }
}
```
