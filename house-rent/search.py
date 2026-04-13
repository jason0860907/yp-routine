#!/usr/bin/env python3
"""搜尋台南東區/北區租屋物件（591 + 信義房屋），發送到 Discord。"""

import json, os, re, subprocess, sys, time
from datetime import datetime, timezone, timedelta

import requests
from playwright.sync_api import sync_playwright

# === 設定 ===

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime("%Y-%m-%d")

RENT_MAX = 20000  # 月租上限（2人合租每人10000以內）
REGION = "台南市"
DISTRICTS = ["東區", "北區"]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

# === 591 ===

def search_591() -> list[dict]:
    """用 591 API 搜尋租屋物件（可養寵物 + 可開火）。"""
    print("\n🔍 591 租屋搜尋...")
    url = "https://bff-house.591.com.tw/v3/web/rent/list"
    params = {
        "regionid": 15,              # 台南市
        "sectionid": "206,209",      # 東區,北區
        "other": "pet,cook",         # 可養寵物,可開火
        "firstRow": 0,
    }
    results = []
    try:
        while True:
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=15)
            data = r.json().get("data", {})
            items = data.get("items", [])
            if not items:
                break
            for h in items:
                price_str = h.get("price", "0")
                price = int(price_str.replace(",", "")) if isinstance(price_str, str) else int(price_str)
                if price > RENT_MAX:
                    continue
                tags = h.get("tags", [])
                results.append({
                    "title": h.get("title", ""),
                    "price": f"{price:,} 元/月",
                    "area": h.get("area_name", ""),
                    "layout": h.get("layoutStr", ""),
                    "floor": h.get("floor_name", ""),
                    "address": h.get("address", ""),
                    "kind": h.get("kind_name", ""),
                    "tags": ", ".join(tags) if tags else "",
                    "source": "591",
                    "url": f"https://rent.591.com.tw/{h['id']}",
                })
            params["firstRow"] += 30
            total = int(data.get("total", 0))
            if params["firstRow"] >= total:
                break
            time.sleep(1)
    except Exception as e:
        print(f"   ❌ 591 失敗: {e}")
    print(f"   找到 {len(results)} 筆")
    return results

# === 信義房屋 ===

def search_sinyi() -> list[dict]:
    """用 Playwright 爬信義房屋租屋。"""
    print("\n🔍 信義房屋租屋搜尋...")
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(user_agent=UA, locale="zh-TW").new_page()

            for district, slug in [("東區", "East-district"), ("北區", "North-district")]:
                page.goto(f"https://www.sinyi.com.tw/rent/list/Tainan-city/{slug}/index.html",
                          wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)

                items = page.evaluate("""() => {
                    const results = [];
                    document.querySelectorAll('.search_result_item').forEach(el => {
                        const link = el.querySelector('a[href*="houseno"]');
                        const priceEl = el.querySelector('.price_new .num');
                        const line2 = el.querySelector('.detail_line2');
                        const line3 = el.querySelector('.detail_line3');
                        const imgEl = el.querySelector('img');
                        if (!link || !priceEl) return;

                        const houseNo = (link.getAttribute('href') || '').split('/').pop();
                        const title = imgEl ? imgEl.getAttribute('alt').replace(/ - \\w+$/, '') : '';

                        results.push({
                            title: title,
                            price: parseInt(priceEl.textContent.replace(/,/g, '')) || 0,
                            detail: line2 ? line2.textContent.trim() : '',
                            address: line3 ? line3.textContent.trim() : '',
                            houseNo: houseNo,
                        });
                    });
                    return results;
                }""")

                for h in items:
                    if h["price"] > RENT_MAX or h["price"] == 0:
                        continue
                    # 只保留東區/北區的物件
                    if not any(d in h["address"] for d in DISTRICTS):
                        continue
                    results.append({
                        "title": h["title"],
                        "price": f"{h['price']:,} 元/月",
                        "area": "",
                        "layout": h["detail"],
                        "floor": "",
                        "address": h["address"],
                        "kind": "",
                        "tags": "",
                        "source": "信義",
                        "url": f"https://www.sinyi.com.tw/rent/houseno/{h['houseNo']}",
                    })
                time.sleep(1)

            browser.close()
    except Exception as e:
        print(f"   ❌ 信義失敗: {e}")
    print(f"   找到 {len(results)} 筆")
    return results

# === Claude 摘要 ===

def claude_summarize(items: list[dict]) -> str:
    prompt = f"""你是租屋助手。以下是台南市東區/北區的租屋物件列表（JSON）。
條件：可養寵物、可開火、每人每月 10,000 元以內。
用 2-3 句話總結（價格分佈、房型分佈、值得關注的物件）。只輸出摘要文字。

{json.dumps(items[:20], ensure_ascii=False, indent=2)}"""
    try:
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""

# === Discord / 存檔 / 去重 ===

def send_discord(text: str, webhook: str):
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur); cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur: chunks.append(cur)
    for chunk in chunks:
        r = requests.post(webhook, json={"content": chunk}, timeout=10)
        print(f"   Discord: {r.status_code}")
        time.sleep(1)


def save_report(items: list[dict], report_dir: str):
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"{TODAY}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": TODAY, "count": len(items), "items": items}, f, ensure_ascii=False, indent=2)
    print(f"📁 存檔: {path}")


def load_previous_urls(report_dir: str) -> set[str]:
    if not os.path.isdir(report_dir):
        return set()
    files = sorted(f for f in os.listdir(report_dir) if f.endswith(".json") and f != f"{TODAY}.json")
    if not files:
        return set()
    try:
        with open(os.path.join(report_dir, files[-1]), encoding="utf-8") as f:
            return {i["url"] for i in json.load(f).get("items", [])}
    except Exception:
        return set()

# === 主程式 ===

def main():
    webhook = os.environ.get("DISCORD_WEBHOOK_HOUSE", "")
    if not webhook:
        print("❌ DISCORD_WEBHOOK_HOUSE 未設定"); sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    report_dir = os.path.join(script_dir, "reports")

    # 1. 搜尋
    all_items = search_591() + search_sinyi()

    # 去重
    seen, deduped = set(), []
    for item in all_items:
        if item["url"] not in seen:
            seen.add(item["url"])
            deduped.append(item)
    print(f"\n📊 共 {len(deduped)} 筆（去重後）")

    if not deduped:
        send_discord(f"🏡 {TODAY} 台南租屋日報\n\n🔍 今日未找到符合條件的物件（可寵、可開火、≤{RENT_MAX:,}/月）。", webhook)
        return

    # 2. Claude 摘要
    summary = claude_summarize(deduped)
    if summary:
        print(f"📝 {summary[:80]}...")

    # 3. 存檔 + 去重
    save_report(deduped, report_dir)
    prev = load_previous_urls(report_dir)
    new_items = [i for i in deduped if i["url"] not in prev]
    old_n = len(deduped) - len(new_items)

    # 4. Discord
    if new_items:
        lines = [f"🏡 {TODAY} 台南租屋日報（東區/北區）"]
        lines.append(f"🆕 {len(new_items)} 筆新物件（{old_n} 筆已推送過）" if prev else f"共 {len(new_items)} 筆")
        lines.append("🐾 可養寵物  🍳 可開火")
        if summary:
            lines.append(f"\n💡 {summary}")
        lines.append("")
        for i, h in enumerate(new_items[:20], 1):
            lines.append(f"**{i}. {h['title']}**")
            lines.append(f"💰 {h['price']}")
            detail_parts = [x for x in [h['area'], h['layout'], h['kind']] if x]
            if detail_parts:
                lines.append(f"📐 {' / '.join(detail_parts)}")
            lines.append(f"📍 {h['address']}")
            if h["tags"]:
                lines.append(f"🏷 {h['tags']}")
            lines.append(f"🔗 <{h['url']}>  [{h['source']}]")
            lines.append("")
        if len(new_items) > 20:
            lines.append(f"...還有 {len(new_items) - 20} 筆，請查看完整報告。")
        msg = "\n".join(lines)
    elif deduped:
        msg = f"🏡 {TODAY} 台南租屋日報\n\n今日 {len(deduped)} 筆皆與前次相同，無新物件。"
    else:
        msg = f"🏡 {TODAY} 台南租屋日報\n\n🔍 今日未找到符合條件的物件。"

    print("\n📤 發送 Discord...")
    send_discord(msg, webhook)
    print("✅ 完成")


if __name__ == "__main__":
    main()
