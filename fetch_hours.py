#!/usr/bin/env python3
"""
fetch_hours.py
--------------
從兩個 Google Calendar iCal 端點抓取今日圖書館開館資訊，
輸出 data.json 供 index.html 讀取。
不需要任何 API Key，直接使用公開 iCal URL。
"""

import json
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar

TZ_TAIPEI = ZoneInfo("Asia/Taipei")

CALENDARS = {
    "jd": {
        "name": "交大校區",
        "ical_url": (
            "https://calendar.google.com/calendar/ical/"
            "c_e6a5ca6c818f1aaf7cea40e50d6691183805f3b3fd349f29af96ce53d3c6b9ed"
            "%40group.calendar.google.com/public/basic.ics"
        ),
        "calendar_url": (
            "https://calendar.google.com/calendar/embed"
            "?src=c_e6a5ca6c818f1aaf7cea40e50d6691183805f3b3fd349f29af96ce53d3c6b9ed"
            "%40group.calendar.google.com&ctz=Asia%2FTaipei"
        ),
    },
    "ym": {
        "name": "陽明校區",
        "ical_url": (
            "https://calendar.google.com/calendar/ical/"
            "c_6b25276d5eb0aef28ecfc4775650eb698a6364e565388f9e61c1d1704a7ef4e0"
            "%40group.calendar.google.com/public/basic.ics"
        ),
        "calendar_url": (
            "https://calendar.google.com/calendar/embed"
            "?src=c_6b25276d5eb0aef28ecfc4775650eb698a6364e565388f9e61c1d1704a7ef4e0"
            "%40group.calendar.google.com&ctz=Asia%2FTaipei"
        ),
    },
}


def fetch_ical(url: str) -> bytes | None:
    """下載 iCal 檔，失敗回傳 None。"""
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"  [ERROR] fetch failed: {e}", file=sys.stderr)
        return None


def to_taipei_date(dt_or_date) -> date:
    """把 datetime 或 date 統一轉成台北時區的 date。"""
    if isinstance(dt_or_date, datetime):
        return dt_or_date.astimezone(TZ_TAIPEI).date()
    return dt_or_date


def parse_summary(summary: str) -> dict:
    """
    從事件標題解析開館資訊。
    常見格式：
      "08:00-22:30"
      "休館" "閉館" "Closed"
      "兒童節補假休館"
      "09:00-17:00 校慶調整"
      "Adjusted Opening Hours 09:00-17:00"
    """
    s = summary.strip()

    if re.search(r'休館|閉館|closed', s, re.IGNORECASE):
        return {"closed": True, "hours": None, "note": s}

    m = re.search(r'(\d{1,2}:\d{2})\s*[-–~～]\s*(\d{1,2}:\d{2})', s)
    if m:
        hours = f"{m.group(1)}–{m.group(2)}"
        note = re.sub(r'\d{1,2}:\d{2}\s*[-–~～]\s*\d{1,2}:\d{2}', '', s).strip(' /｜|　-–')
        return {"closed": False, "hours": hours, "note": note if note else None}

    return {"closed": False, "hours": None, "note": s}


def get_today_events(ical_bytes: bytes, target: date) -> list[dict]:
    """解析 iCal，回傳 target 當天所有事件。"""
    try:
        cal = Calendar.from_ical(ical_bytes)
    except Exception as e:
        print(f"  [ERROR] parse ical: {e}", file=sys.stderr)
        return []

    results = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dtstart = component.get("DTSTART")
        dtend   = component.get("DTEND")
        summary = str(component.get("SUMMARY", "")).strip()

        if dtstart is None:
            continue

        start_val  = dtstart.dt
        end_val    = dtend.dt if dtend else None
        start_date = to_taipei_date(start_val)

        if end_val is not None:
            end_date = to_taipei_date(end_val)
            # iCal 全天事件 DTEND 是 exclusive（次日），需減一天
            if not isinstance(start_val, datetime):
                end_date -= timedelta(days=1)
        else:
            end_date = start_date

        if start_date <= target <= end_date:
            parsed = parse_summary(summary)
            parsed["raw"] = summary
            results.append(parsed)
            print(f"  ✓ 事件：{summary!r} → {parsed}")

    return results


def merge_events(events: list[dict]) -> dict:
    """閉館 > 有時段的開館 > 僅 note"""
    if not events:
        return {"closed": False, "hours": None, "note": "行事曆今日無登錄資料"}

    closed = [e for e in events if e["closed"]]
    if closed:
        return {"closed": True, "hours": None, "note": closed[0]["note"]}

    with_hours = [e for e in events if e["hours"]]
    if with_hours:
        e = with_hours[0]
        return {"closed": False, "hours": e["hours"], "note": e.get("note")}

    return {"closed": False, "hours": None, "note": events[0].get("note")}


def main():
    today  = datetime.now(TZ_TAIPEI).date()
    now_str = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    print(f"=== 抓取日期：{today}（台北時間）===")

    output = {
        "date": today.isoformat(),
        "updated_at": now_str,
        "campuses": {},
    }

    exit_code = 0
    for key, info in CALENDARS.items():
        print(f"\n[{info['name']}]")
        ical_bytes = fetch_ical(info["ical_url"])

        if ical_bytes is None:
            result = {"closed": False, "hours": None,
                      "note": "資料擷取失敗，請查閱官網", "fetch_error": True}
            exit_code = 1
        else:
            events = get_today_events(ical_bytes, today)
            result = merge_events(events)
            result["fetch_error"] = False
            print(f"  合併結果：{result}")

        result["name"]         = info["name"]
        result["calendar_url"] = info["calendar_url"]
        output["campuses"][key] = result

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ data.json 寫出完成")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
