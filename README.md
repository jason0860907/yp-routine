# yp-routine

個人自動化任務集合。

## 任務列表

| 任務 | 說明 | 排程 |
|------|------|------|
| [job/](job/) | 搜尋 104 AI 遠端職缺，發送到 Discord | 每天 12:03 |
| [house-buy/](house-buy/) | 搜尋 591 台南東區/北區買屋（500–800 萬），發送到 Discord | 每天 12:10 |
| [house-rent/](house-rent/) | 搜尋 591 台南東區/北區租屋（可寵/可開火，≤20,000/月），發送到 Discord | 每天 12:15 |
| [stock-earnings/](stock-earnings/) | 追蹤台股自選清單的月營收與季報，新公告推送 Discord | 每天 09:05 |

## 環境需求

```bash
pip install playwright requests
playwright install chromium --with-deps
```
