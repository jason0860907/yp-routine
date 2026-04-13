#!/usr/bin/env python3
"""搜尋 104 人力銀行 AI 遠端職缺，篩選後發送到 Discord。"""

import json, os, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
from playwright.sync_api import sync_playwright

# === 設定 ===

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime("%Y-%m-%d")

SEARCH_QUERIES = [
    "AI 遠端 工程師",
    "LLM engineer remote",
    "機器學習 遠端 工程師",
    "GenAI 遠端 工程師",
]

RELEVANT_KEYWORDS = [
    "ai", "ml", "llm", "machine learning", "deep learning", "genai",
    "generative ai", "人工智慧", "機器學習", "深度學習", "資料科學",
    "data scientist", "data science", "nlp", "自然語言", "computer vision",
    "模型", "model", "neural", "pytorch", "tensorflow",
    "大型語言模型", "生成式", "prompt engineer",
]

EXCLUDE_KEYWORDS = [
    "行銷", "業務", "主播", "客服", "行政", "人資", "hr", "marketing",
    "sales", "admin", "助理", "會計", "財務", "法務",
    "設計師", "ui designer", "graphic", "美編", "小編", "社群",
    "產品經理", "project manager",
]

MIN_MONTHLY = 70000   # 月薪下限
MIN_YEARLY = 800000   # 年薪下限

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

# 104 搜尋頁 DOM 抓取
EXTRACT_JOBS_JS = """() => {
    const cards = document.querySelectorAll('div.job-list-container');
    const results = [], seen = new Set();
    for (const card of cards) {
        const el = card.querySelector('a.info-job__text');
        if (!el) continue;
        const m = (el.getAttribute('href') || '').match(/\\/job\\/([a-zA-Z0-9]+)/);
        if (!m || seen.has(m[1])) continue;
        seen.add(m[1]);
        const co = card.querySelector('a.info-company__text');
        const sa = card.querySelector('a[data-gtm-joblist^="職缺-薪資"]');
        results.push({
            title: el.getAttribute('title') || el.textContent.trim(),
            company: co ? co.textContent.trim() : '未知公司',
            salary: sa ? sa.textContent.trim() : '面議',
            url: 'https://www.104.com.tw/job/' + m[1],
        });
    }
    return results;
}"""

# === 爬蟲 ===

def scrape_104(page, query: str) -> list[dict] | None:
    print(f"\n🔍 搜尋: {query}")
    try:
        page.goto(f"https://www.104.com.tw/jobs/search/?keyword={quote(query)}&ro=1&jobsource=index_s",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("div.job-list-container", timeout=10000)
        jobs = page.evaluate(EXTRACT_JOBS_JS)
        print(f"   找到 {len(jobs)} 筆")
        return jobs
    except Exception as e:
        print(f"   ❌ 失敗: {e}")
        return None

# === 篩選 ===

def is_relevant(title: str) -> bool:
    t = title.lower()
    return (any(kw in t for kw in RELEVANT_KEYWORDS)
            and not any(kw in t for kw in EXCLUDE_KEYWORDS))


def filter_and_rank(all_jobs: list[dict]) -> list[dict]:
    seen, filtered = set(), []
    for job in all_jobs:
        if job["url"] not in seen and is_relevant(job["title"]):
            seen.add(job["url"])
            filtered.append(job)
    filtered.sort(key=lambda j: sum(kw in j["title"].lower() for kw in RELEVANT_KEYWORDS), reverse=True)
    return filtered[:15]


def fetch_job_details(jobs: list[dict]) -> list[dict]:
    """用 104 API 取得遠端資訊，並依薪資過濾。"""
    REMOTE_TYPES = {1: "全遠端", 2: "彈性遠端"}
    result = []
    for job in jobs:
        job_id = job["url"].split("/job/")[1]
        try:
            r = requests.get(f"https://www.104.com.tw/job/ajax/content/{job_id}",
                             headers={"User-Agent": UA, "Referer": f"https://www.104.com.tw/job/{job_id}"},
                             timeout=10)
            d = r.json().get("data", {}).get("jobDetail", {})

            rw = d.get("remoteWork")
            if rw and isinstance(rw, dict):
                rt = REMOTE_TYPES.get(rw.get("type"), "可遠端")
                desc = rw.get("description", "")
                job["remote"] = f"{rt}（{desc}）" if desc else rt
            else:
                job["remote"] = "未提供"

            smax, stype = d.get("salaryMax", 0), d.get("salaryType", 0)
            if stype == 50 and 0 < smax < MIN_MONTHLY:
                print(f"   ❌ 月薪上限 {smax:,}: {job['title'][:40]}")
                continue
            if stype == 60 and 0 < smax < MIN_YEARLY:
                print(f"   ❌ 年薪上限 {smax:,}: {job['title'][:40]}")
                continue
        except Exception:
            job["remote"] = "未知"

        result.append(job)
        time.sleep(0.5)
    return result

# === Claude 篩選 + 摘要 ===

def claude_filter_and_summarize(jobs: list[dict]) -> dict:
    prompt = f"""你是 AI 職缺篩選助手。以下是從 104 人力銀行爬到的職缺列表（JSON）。
每筆職缺都有 "remote" 欄位（全遠端 / 彈性遠端 / 未提供）。

請做兩件事：

## 1. 智慧篩選
只保留：AI/ML/LLM/資料科學/深度學習 相關的技術職位。
排除：行銷、業務、客服、行政、設計、PM、硬體工程、設備維護等非軟體職。
優先保留有遠端的職缺，「未提供」也可保留。如果無法確定，寧可保留。

## 2. 每日摘要
用 2-3 句話總結今天的職缺趨勢（領域分佈、薪資範圍、值得關注的機會）。

## 輸出
嚴格輸出 JSON，不要有其他文字：
{{"summary": "摘要", "jobs": [保留的職缺物件（原始格式不變）]}}

## 職缺列表
{json.dumps(jobs, ensure_ascii=False, indent=2)}"""

    try:
        r = subprocess.run(["claude", "-p", prompt, "--output-format", "json"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"   ⚠️ Claude 錯誤: {r.stderr[:200]}")
            return {"jobs": jobs, "summary": ""}

        outer = json.loads(r.stdout)
        text = outer.get("result", r.stdout)
        if isinstance(text, str):
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(text)
        else:
            parsed = text

        filtered = parsed.get("jobs", jobs)
        summary = parsed.get("summary", "")
        print(f"🤖 Claude: {len(jobs)} → {len(filtered)} 筆")
        if summary:
            print(f"📝 {summary[:80]}...")
        return {"jobs": filtered, "summary": summary}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
        print(f"   ⚠️ Claude 失敗（{e}），跳過")
        return {"jobs": jobs, "summary": ""}

# === Discord ===

def send_discord(text: str, webhook: str):
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    for chunk in chunks:
        r = requests.post(webhook, json={"content": chunk}, timeout=10)
        print(f"   Discord: {r.status_code}")
        time.sleep(1)

# === 存檔 / 去重 ===

def save_report(jobs: list[dict], report_dir: str):
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"{TODAY}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": TODAY, "count": len(jobs), "jobs": jobs}, f, ensure_ascii=False, indent=2)
    print(f"📁 存檔: {path}")


def load_previous_urls(report_dir: str) -> set[str]:
    if not os.path.isdir(report_dir):
        return set()
    files = sorted(f for f in os.listdir(report_dir) if f.endswith(".json") and f != f"{TODAY}.json")
    if not files:
        return set()
    try:
        with open(os.path.join(report_dir, files[-1]), encoding="utf-8") as f:
            return {j["url"] for j in json.load(f).get("jobs", [])}
    except Exception:
        return set()

# === 主程式 ===

def main():
    webhook = os.environ.get("DISCORD_WEBHOOK", "")
    if not webhook:
        print("❌ DISCORD_WEBHOOK 未設定"); sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    report_dir = os.path.join(script_dir, "reports")

    # 1. 爬蟲
    all_jobs, errors = [], 0
    with sync_playwright() as p:
        page = p.chromium.launch(headless=True).new_context(user_agent=UA, locale="zh-TW").new_page()
        for query in SEARCH_QUERIES:
            jobs = scrape_104(page, query)
            if jobs is None: errors += 1
            else: all_jobs.extend(jobs)
            time.sleep(2)
        page.context.browser.close()

    if errors == len(SEARCH_QUERIES):
        send_discord(f"⚠️ {TODAY} 職缺日報\n\n❌ 所有搜尋皆失敗，請手動檢查 104。", webhook)
        sys.exit(1)

    # 2. 關鍵字粗篩 → API 詳情 + 薪資過濾 → Claude 精篩
    rough = filter_and_rank(all_jobs)
    print(f"\n📊 {len(all_jobs)} 筆 → 粗篩 {len(rough)} 筆")

    print("\n🏠 查詢詳情...")
    rough = fetch_job_details(rough)
    for j in rough:
        print(f"   {j['remote']:<20} {j['title'][:50]}")

    result = claude_filter_and_summarize(rough)
    filtered, summary = result["jobs"], result["summary"]
    print(f"📋 最終 {len(filtered)} 筆")

    # 3. 存檔 + 去重
    save_report(filtered, report_dir)
    prev = load_previous_urls(report_dir)
    new_jobs = [j for j in filtered if j["url"] not in prev]
    old_n = len(filtered) - len(new_jobs)

    # 4. Discord
    if new_jobs:
        lines = [f"📋 {TODAY} AI 遠端職缺日報（104）"]
        lines.append(f"🆕 {len(new_jobs)} 筆新職缺（{old_n} 筆已推送過）" if prev else f"共 {len(new_jobs)} 筆")
        if summary:
            lines.append(f"\n💡 {summary}")
        lines.append("")
        for i, j in enumerate(new_jobs, 1):
            lines.append(f"**{i}. {j['title']}**")
            lines.append(f"🏢 {j['company']}")
            lines.append(f"💰 {j['salary']}")
            lines.append(f"🏠 {j.get('remote', '未知')}")
            lines.append(f"🔗 <{j['url']}>")
            lines.append("")
        msg = "\n".join(lines)
    elif filtered:
        msg = f"📋 {TODAY} AI 遠端職缺日報（104）\n\n今日 {len(filtered)} 筆皆與前次相同，無新職缺。"
    else:
        msg = f"📋 {TODAY} AI 遠端職缺日報（104）\n\n🔍 今日未找到符合條件的職缺。"

    print("\n📤 發送 Discord...")
    send_discord(msg, webhook)
    print("✅ 完成")


if __name__ == "__main__":
    main()
