#!/usr/bin/env python3
"""
fetch_hours.py
--------------
從 calendars.json 中的 Google Calendar 整合網址抓取今日圖書館開館資訊，
輸出 data.json 供 index.html 讀取。
不需要任何 API Key，直接使用公開 iCal URL。
"""

import json
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote

import requests
from icalendar import Calendar

TZ_TAIPEI = ZoneInfo("Asia/Taipei")

BASE_DIR = Path(__file__).resolve().parent


def load_calendars() -> dict:
    """只讀取設定；從完整 embed URL 自動取得所有 src。"""
    config = json.loads((BASE_DIR / "calendars.json").read_text(encoding="utf-8"))
    if set(config) != {"jd", "ym"}:
        raise ValueError("calendars.json 必須包含 jd、ym 兩校區")
    for key, info in config.items():
        url = urlsplit(info["calendar_url"])
        if url.scheme != "https" or url.netloc != "calendar.google.com" or url.path != "/calendar/embed":
            raise ValueError(f"{key}: 請提供 Google Calendar 完整嵌入網址")
        ids = list(dict.fromkeys(parse_qs(url.query).get("src", [])))
        if not ids or any(not cid.strip() for cid in ids):
            raise ValueError(f"{key}: 行事曆網址沒有有效 src")
        info["ical_urls"] = [
            "https://calendar.google.com/calendar/ical/" + quote(cid, safe="") + "/public/basic.ics"
            for cid in ids
        ]
    return config


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
        if dt_or_date.tzinfo is None:
            dt_or_date = dt_or_date.replace(tzinfo=TZ_TAIPEI)
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
        raise ValueError("無法解析 iCal") from e

    if cal.name != "VCALENDAR":
        raise ValueError("回應不是 VCALENDAR")
    results = []
    for component in cal.walk():
        if component.name != "VEVENT" or str(component.get("STATUS", "")).upper() == "CANCELLED":
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
            elif isinstance(end_val, datetime):
                # 時間事件的 DTEND 也是排除式，避免午夜結束算到隔日。
                end_date = to_taipei_date(end_val - timedelta(microseconds=1))
        else:
            end_date = start_date

        if start_date <= target <= end_date:
            parsed = parse_summary(summary)
            parsed["raw"] = summary
            results.append(parsed)
            print(f"  ✓ 事件：{summary!r} → {parsed}")

    return results


def merge_events(events: list[dict]) -> dict:
    """
    合併當天多筆事件，優先順序：
      1. 有明確時段的事件（最優先）
      2. 閉館事件
      3. 僅有 note 的事件

    當天若同時有說明文字（如「圖週中考試延長開館」）和時間（如「08:00-22:30」），
    以時間為準，並將所有說明文字合併為 note 一起顯示。
    避免說明文字中偶爾出現「休館」二字造成誤判。
    """
    if not events:
        return {"closed": False, "hours": None, "note": "行事曆今日無登錄資料"}

    # 1. 優先取有明確時段的事件
    with_hours = [e for e in events if e["hours"]]
    if with_hours:
        e = with_hours[0]
        # 收集其他說明性 note 合併顯示
        extra_notes = [
            x["note"] for x in events
            if x.get("note") and not x["hours"] and not x["closed"]
        ]
        combined = "\u3001".join(filter(None, [e.get("note")] + extra_notes))
        return {
            "closed": False,
            "hours": e["hours"],
            "note": combined if combined else None,
        }

    # 2. 閉館事件
    closed = [e for e in events if e["closed"]]
    if closed:
        extra_notes = [
            x["note"] for x in events
            if x.get("note") and not x["closed"]
        ]
        combined = "\u3001".join(filter(None, [closed[0]["note"]] + extra_notes))
        return {"closed": True, "hours": None, "note": combined if combined else None}

    # 3. 僅有 note
    notes = [e["note"] for e in events if e.get("note")]
    return {"closed": False, "hours": None, "note": "\u3001".join(notes) if notes else None}


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
    for key, info in load_calendars().items():
        print(f"\n[{info['name']}]")
        events = []
        failed = 0
        for url in info["ical_urls"]:
            try:
                ical_bytes = fetch_ical(url)
                if ical_bytes is None:
                    raise ValueError("下載失敗")
                events.extend(get_today_events(ical_bytes, today))
            except Exception as e:
                failed += 1
                print(f"  [ERROR] {url}: {e}", file=sys.stderr)

        # 保留原來的開館判斷規則；所有來源的原始標題也一併呈現。
        unique = {event["raw"]: event for event in events if event["raw"]}
        events = list(unique.values())
        result = merge_events(events)
        result["events"] = [event["raw"] for event in events]
        result["fetch_error"] = failed > 0
        if failed:
            result["closed"] = False
            result["hours"] = None
            result["note"] = f"{failed} 個行事曆擷取失敗，以下事件可能不完整，請查閱行事曆。"
            exit_code = 1
        print(f"  合併結果：{result}")

        result["name"]         = info["name"]
        result["calendar_url"] = info["calendar_url"]
        output["campuses"][key] = result

    with (BASE_DIR / "data.json").open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ data.json 寫出完成")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
