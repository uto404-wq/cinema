"""ジョルダン映画から3館の上映スケジュールを取得して data.json を作る。

GitHub Actions から毎日実行される。取得に失敗した館は前回のデータを残す。
"""
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data.json"
JST = dt.timezone(dt.timedelta(hours=9))

THEATERS = {
    "t": {"name": "TOHOシネマズなんば", "short": "TOHOなんば",
          "url": "https://www.tohotheater.jp/",
          "src": "https://movie.jorudan.co.jp/theater/1001828/schedule/"},
    "p": {"name": "なんばパークスシネマ", "short": "パークス",
          "url": "https://www.parkscinema.com/",
          "src": "https://movie.jorudan.co.jp/theater/1001853/schedule/"},
    "s": {"name": "イオンシネマ シアタス心斎橋", "short": "シアタス",
          "url": "https://www.aeoncinema.com/cinema/shinsaibashi/",
          "src": "https://movie.jorudan.co.jp/theater/1002064/schedule/"},
}

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
TIME_RE = re.compile(r"\b([0-2]?\d:[0-5]\d)\b")
HEADERS = {"User-Agent": "Mozilla/5.0 (personal cinema schedule viewer)"}


def to_date(month: int, day: int, today: dt.date) -> str:
    year = today.year
    if month < today.month - 6:      # 12月に翌年1月分を取得した場合
        year += 1
    elif month > today.month + 6:    # 1月に前年12月分が残っている場合
        year -= 1
    return dt.date(year, month, day).isoformat()


def title_for(table) -> str:
    """表の直前にある見出し（h2/h3/h4）を作品名とみなす。"""
    h = table.find_previous(["h2", "h3", "h4"])
    if h is None:
        return ""
    title = h.get_text(" ", strip=True)
    if h.name != "h2":
        parent = h.find_previous("h2")
        if parent:
            p = parent.get_text(" ", strip=True)
            if p and p not in title and len(title) <= 12:   # 「字幕版」等だけの小見出し
                title = f"{p} {title}"
    return re.sub(r"\s+", " ", title)


def parse(html: str, today: dt.date) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    for table in soup.find_all("table"):
        head = table.find("tr")
        if head is None:
            continue
        dates = []
        for c in head.find_all(["th", "td"]):
            m = DATE_RE.search(c.get_text())
            dates.append(to_date(int(m[1]), int(m[2]), today) if m else None)
        if not any(dates):
            continue
        title = title_for(table)
        if not title:
            continue
        for row in table.find_all("tr")[1:]:
            for d, cell in zip(dates, row.find_all(["td", "th"])):
                if not d:
                    continue
                times = [t.zfill(5) for t in TIME_RE.findall(cell.get_text(" "))]
                if times:
                    shows.append({"title": title, "date": d, "times": sorted(set(times))})
    return shows


def main() -> int:
    today = dt.datetime.now(JST).date()
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    old_shows = old.get("shows", [])

    all_shows, failed = [], []
    for key, th in THEATERS.items():
        try:
            r = requests.get(th["src"], headers=HEADERS, timeout=30)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            shows = parse(r.text, today)
            if not shows:
                raise ValueError("上映データが0件")
            for s in shows:
                s["th"] = key
            all_shows += shows
            print(f"[OK] {th['name']}: {len(shows)}件")
        except Exception as e:  # noqa: BLE001
            failed.append(key)
            keep = [s for s in old_shows if s.get("th") == key]
            all_shows += keep
            print(f"[NG] {th['name']}: {e}（前回データ{len(keep)}件を維持）", file=sys.stderr)
        time.sleep(2)

    if len(failed) == len(THEATERS):
        print("全館の取得に失敗しました。data.json は更新しません。", file=sys.stderr)
        return 1

    # 昨日以前の上映は削除
    all_shows = [s for s in all_shows if s["date"] >= today.isoformat()]
    all_shows.sort(key=lambda s: (s["th"], s["date"], s["title"]))
    data = {
        "updated": dt.datetime.now(JST).isoformat(timespec="minutes"),
        "failed": failed,
        "theaters": THEATERS,
        "shows": all_shows,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"data.json: {len(all_shows)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
