#!/usr/bin/env python3
"""搜尋台南東區/北區買屋物件（591 + 信義房屋），發送到 Discord。"""

import json, os, subprocess, sys, time
from datetime import datetime, timezone, timedelta

import requests
from playwright.sync_api import sync_playwright

# === 設定 ===

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime("%Y-%m-%d")

PRICE_MIN = 500  # 萬
PRICE_MAX = 800  # 萬
REGION = "台南市"
DISTRICTS = ["東區", "北區"]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

# === 591 ===

def search_591() -> list[dict]:
    """用 591 API 搜尋買屋物件。"""
    print("\n🔍 591 買屋搜尋...")
    url = "https://bff-house.591.com.tw/v1/web/sale/list"
    params = {
        "type": 2, "category": 1,
        "regionid": 15,             # 台南市
        "section": "206,209",       # 東區,北區
        "price": "500_800",
        "shType": "list",
        "firstRow": 0,
    }
    results = []
    try:
        while True:
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=15)
            data = r.json().get("data", {})
            items = data.get("house_list", [])
            if not items:
                break
            for h in items:
                price = h.get("price", 0)
                if not (PRICE_MIN <= price <= PRICE_MAX):
                    continue
                results.append({
                    "title": h.get("title", ""),
                    "price": f"{price} 萬",
                    "unit_price": h.get("unit_price", ""),
                    "area": f"{h.get('area', '')} 坪",
                    "layout": h.get("room", ""),
                    "floor": h.get("floor", ""),
                    "address": f"{h.get('section_name', '')}{h.get('address', '')}",
                    "age": h.get("showhouseage", ""),
                    "source": "591",
                    "url": f"https://sale.591.com.tw/home/house/detail/2/{h['houseid']}.html",
                })
            params["firstRow"] += 30
            if params["firstRow"] >= int(data.get("total", 0)):
                break
            time.sleep(1)
    except Exception as e:
        print(f"   ❌ 591 失敗: {e}")
    print(f"   找到 {len(results)} 筆")
    return results

# === 信義房屋 ===

def search_sinyi() -> list[dict]:
    """用 Playwright 爬信義房屋買屋。"""
    print("\n🔍 信義房屋買屋搜尋...")
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(user_agent=UA, locale="zh-TW").new_page()

            api_data = []
            def handle_response(response):
                if "filterObject.php" in response.url:
                    try:
                        api_data.append(response.json())
                    except Exception:
                        pass

            page.on("response", handle_response)
            page.goto("https://www.sinyi.com.tw/buy/list/Tainan-city/East-district,North-district/price-500-800",
                      wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
            browser.close()

        for resp in api_data:
            for obj in resp.get("content", {}).get("object", []):
                zc = obj.get("zipCode", "")
                if zc not in ("701", "704"):
                    continue
                price = obj.get("totalPrice", 0)
                if not (PRICE_MIN <= price <= PRICE_MAX):
                    continue
                results.append({
                    "title": obj.get("name", ""),
                    "price": f"{price} 萬",
                    "unit_price": obj.get("uniPrice", ""),
                    "area": f"{obj.get('areaBuilding', '')} 坪",
                    "layout": obj.get("layout", ""),
                    "floor": f"{obj.get('floor', '')}F/{obj.get('totalfloor', '')}F",
                    "address": obj.get("address", ""),
                    "age": obj.get("age", ""),
                    "source": "信義",
                    "url": f"https://www.sinyi.com.tw/buy/house/{obj['houseNo']}",
                })
    except Exception as e:
        print(f"   ❌ 信義失敗: {e}")
    print(f"   找到 {len(results)} 筆")
    return results

# === Claude 摘要 ===

def claude_summarize(jobs: list[dict]) -> str:
    prompt = f"""你是買屋助手。以下是台南市東區/北區的買屋物件列表（JSON），預算 {PRICE_MIN}-{PRICE_MAX} 萬。
用 2-3 句話總結趨勢（價格分佈、坪數、屋齡、值得關注的物件）。只輸出摘要文字，不要 JSON。

{json.dumps(jobs[:20], ensure_ascii=False, indent=2)}"""
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
        send_discord(f"🏠 {TODAY} 台南買屋日報\n\n🔍 今日未找到 {PRICE_MIN}-{PRICE_MAX} 萬的物件。", webhook)
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
        lines = [f"🏠 {TODAY} 台南買屋日報（東區/北區）"]
        lines.append(f"🆕 {len(new_items)} 筆新物件（{old_n} 筆已推送過）" if prev else f"共 {len(new_items)} 筆")
        if summary:
            lines.append(f"\n💡 {summary}")
        lines.append("")
        for i, h in enumerate(new_items[:20], 1):
            lines.append(f"**{i}. {h['title']}**")
            lines.append(f"💰 {h['price']}（{h['unit_price']}）")
            lines.append(f"📐 {h['area']} {h['layout']} {h['floor']}")
            lines.append(f"📍 {h['address']}  🏗 {h['age']}")
            lines.append(f"🔗 <{h['url']}>  [{h['source']}]")
            lines.append("")
        if len(new_items) > 20:
            lines.append(f"...還有 {len(new_items) - 20} 筆，請查看完整報告。")
        msg = "\n".join(lines)
    elif deduped:
        msg = f"🏠 {TODAY} 台南買屋日報\n\n今日 {len(deduped)} 筆皆與前次相同，無新物件。"
    else:
        msg = f"🏠 {TODAY} 台南買屋日報\n\n🔍 今日未找到符合條件的物件。"

    print("\n📤 發送 Discord...")
    send_discord(msg, webhook)
    print("✅ 完成")


if __name__ == "__main__":
    main()
