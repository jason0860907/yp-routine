#!/usr/bin/env python3
"""台股財報追蹤：月營收 + 季報，有新公告就推 Discord。"""

import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta

import requests

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime("%Y-%m-%d")

# 追蹤清單（代號, 名稱）
WATCHLIST = [
    ("3661", "世芯-KY"),
]

FINMIND = "https://api.finmindtrade.com/api/v4/data"

# === FinMind ===

def fetch(dataset: str, stock_id: str, start_date: str) -> list[dict]:
    r = requests.get(FINMIND, params={
        "dataset": dataset, "data_id": stock_id, "start_date": start_date,
    }, timeout=15)
    d = r.json()
    return d.get("data", []) if d.get("msg") == "success" else []


def latest_revenue(stock_id: str) -> dict | None:
    rows = fetch("TaiwanStockMonthRevenue", stock_id, "2024-01-01")
    return max(rows, key=lambda x: x["date"]) if rows else None


def revenue_yoy(stock_id: str, year: int, month: int) -> dict | None:
    """回傳 {current, prev_year, yoy_pct}（prev_year 為去年同月）"""
    rows = fetch("TaiwanStockMonthRevenue", stock_id, f"{year-1}-01-01")
    cur = next((r for r in rows if r["revenue_year"] == year and r["revenue_month"] == month), None)
    prev = next((r for r in rows if r["revenue_year"] == year - 1 and r["revenue_month"] == month), None)
    if not cur:
        return None
    result = {"current": cur["revenue"], "prev_year": prev["revenue"] if prev else None}
    if prev and prev["revenue"]:
        result["yoy_pct"] = (cur["revenue"] - prev["revenue"]) / prev["revenue"] * 100
    return result


def latest_earnings(stock_id: str) -> dict | None:
    """最新一季的關鍵財務數字。"""
    rows = fetch("TaiwanStockFinancialStatements", stock_id, "2024-01-01")
    if not rows:
        return None
    latest_date = max(r["date"] for r in rows)
    items = [r for r in rows if r["date"] == latest_date]
    wanted = {
        "Revenue": "營收",
        "GrossProfit": "毛利",
        "OperatingIncome": "營業利益",
        "IncomeAfterTaxes": "稅後淨利",
        "EPS": "EPS",
    }
    out = {"date": latest_date, "metrics": {}}
    for item in items:
        if item["type"] in wanted:
            out["metrics"][wanted[item["type"]]] = item["value"]
    return out if out["metrics"] else None


# === Claude 摘要 ===

def claude_summarize(name: str, event_type: str, payload: dict) -> str:
    prompt = f"""你是台股財報助手。以下是 {name} 的 {event_type} 資料（JSON）。
用 1-2 句繁體中文總結重點（成長/衰退、YoY/QoQ、值得關注之處）。只輸出摘要，不要 JSON。

{json.dumps(payload, ensure_ascii=False, indent=2)}"""
    try:
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


# === Discord / State ===

def send_discord(text: str, webhook: str):
    r = requests.post(webhook, json={"content": text}, timeout=10)
    print(f"   Discord: {r.status_code}")


def load_state(state_path: str) -> dict:
    if not os.path.isfile(state_path):
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state_path: str, state: dict):
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fmt_money(n: int | float) -> str:
    """1234567890 → 12.35 億 / 1234567 → 123.46 萬"""
    if abs(n) >= 1e8:
        return f"{n/1e8:.2f} 億"
    if abs(n) >= 1e4:
        return f"{n/1e4:.2f} 萬"
    return f"{n:.0f}"


def pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


# === 主程式 ===

def main():
    webhook = os.environ.get("DISCORD_WEBHOOK_FINANCE", "")
    if not webhook:
        print("❌ DISCORD_WEBHOOK_FINANCE 未設定"); sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    state_path = os.path.join(script_dir, "reports", "state.json")
    state = load_state(state_path)

    new_events = []  # (discord_message, state_key, state_value)

    for stock_id, name in WATCHLIST:
        print(f"\n📊 檢查 {stock_id} {name}")
        stock_state = state.setdefault(stock_id, {})

        # --- 月營收 ---
        rev = latest_revenue(stock_id)
        if rev:
            rev_key = f"{rev['revenue_year']}-{rev['revenue_month']:02d}"
            last_rev = stock_state.get("last_revenue")
            print(f"   月營收 最新: {rev_key}（已推送: {last_rev}）")
            if rev_key != last_rev:
                yoy = revenue_yoy(stock_id, rev["revenue_year"], rev["revenue_month"])
                payload = {"month": rev_key, **yoy} if yoy else {"month": rev_key, "current": rev["revenue"]}
                summary = claude_summarize(name, "月營收", payload)

                lines = [f"📈 **{name} ({stock_id}) · {rev['revenue_year']}/{rev['revenue_month']:02d} 月營收**"]
                lines.append(f"💰 營收：{fmt_money(rev['revenue'])}")
                if yoy and yoy.get("prev_year"):
                    lines.append(f"📊 YoY：{pct(yoy.get('yoy_pct'))}（去年同期 {fmt_money(yoy['prev_year'])}）")
                if summary:
                    lines.append(f"\n💡 {summary}")
                new_events.append(("\n".join(lines), (stock_id, "last_revenue", rev_key)))

        # --- 季報 ---
        earn = latest_earnings(stock_id)
        if earn:
            earn_key = earn["date"]
            last_earn = stock_state.get("last_earnings")
            print(f"   季報 最新: {earn_key}（已推送: {last_earn}）")
            if earn_key != last_earn:
                summary = claude_summarize(name, "季報", earn)

                lines = [f"📑 **{name} ({stock_id}) · {earn_key} 季報**"]
                for k, v in earn["metrics"].items():
                    lines.append(f"• {k}：{fmt_money(v) if k != 'EPS' else f'{v:.2f} 元'}")
                if summary:
                    lines.append(f"\n💡 {summary}")
                new_events.append(("\n".join(lines), (stock_id, "last_earnings", earn_key)))

    if not new_events:
        print("\n✅ 沒有新公告")
        return

    print(f"\n📤 {len(new_events)} 則新公告，發送 Discord...")
    for msg, (sid, key, val) in new_events:
        send_discord(msg, webhook)
        state[sid][key] = val

    save_state(state_path, state)
    print(f"💾 狀態已存: {state_path}")
    print("✅ 完成")


if __name__ == "__main__":
    main()
