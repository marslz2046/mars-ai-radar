#!/usr/bin/env python3
"""Generate static AI radar data from public sources.

This MVP intentionally avoids login-only sources, cookies, API keys, and
private inboxes. It writes data/news.json and data/source-status.json.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import html
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = timezone(timedelta(hours=8))
USER_AGENT = "MarsAIRadar/0.1 (+https://github.com/)"

AI_KEYWORDS = [
    "AI",
    "Agent",
    "Claude",
    "OpenAI",
    "Anthropic",
    "GPT",
    "LLM",
    "大模型",
    "模型",
    "智能体",
    "生成",
    "推理",
    "多模态",
    "机器人",
    "自动化",
    "编程",
    "Token",
]


@dataclass
class RawItem:
    source_id: str
    source: str
    type: str
    title: str
    summary: str
    url: str
    published_at: datetime
    tags: list[str]
    priority: int = 0
    ai_relevance: str = "strong"
    backfill: bool = False


def fetch_text(url: str, timeout: int = 25) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def strip_tags(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def iso_local(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")


def parse_geekpark_state(page: str) -> dict[str, Any] | None:
    marker = "window.__INITIAL_STATE__="
    start = page.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = page.find(";(function()", start)
    if end == -1:
        return None
    payload = page[start:end]
    return json.loads(payload)


def fetch_geekpark(now: datetime) -> list[RawItem]:
    url = "https://www.geekpark.net/column/304"
    state = parse_geekpark_state(fetch_text(url))
    if not state:
        raise ValueError("GeekPark structured state not found")
    posts = state.get("column", {}).get("column", {}).get("posts", [])
    out: list[RawItem] = []
    for post in posts:
        title = clean_text(post.get("title"))
        if not title:
            continue
        published = datetime.fromtimestamp(int(post["published_timestamp"]), TZ)
        tags = [clean_text(tag) for tag in post.get("tags", []) if clean_text(tag)]
        out.append(
            RawItem(
                source_id="geekpark",
                source="极客公园",
                type="media",
                title=title,
                summary=clean_text(post.get("abstract")),
                url=f"https://www.geekpark.net/news/{post['id']}",
                published_at=published,
                tags=tags[:4] or ["AI新浪潮观察"],
            )
        )
    return out


def fetch_xiaohu(now: datetime) -> list[RawItem]:
    page = fetch_text("https://daily.xiaohu.ai/")
    out: list[RawItem] = []

    latest_date = None
    latest_link = "https://daily.xiaohu.ai/"
    latest_match = re.search(r'<a class="latest-card" href="([^"]+)">([\s\S]*?)</a>\s*</section>', page)
    if latest_match:
        latest_link = urljoin("https://daily.xiaohu.ai/", latest_match.group(1))
        block = latest_match.group(2)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", block)
        if date_match:
            latest_date = datetime.fromisoformat(date_match.group(1)).replace(hour=10, tzinfo=TZ)
        headline_match = re.search(r'<div class="latest-headline">([\s\S]*?)</div>', block)
        summary_match = re.search(r'<div class="latest-summary">([\s\S]*?)</div>', block)
        if headline_match:
            title = strip_tags(headline_match.group(1))
            if has_cjk(title):
                out.append(
                    RawItem(
                        source_id="xiaohu",
                        source="小互 AI 日报",
                        type="daily",
                        title=title,
                        summary=strip_tags(summary_match.group(1)) if summary_match else "小互 AI 日报最新一期头条。",
                        url=latest_link,
                        published_at=latest_date or now.replace(hour=10, minute=0, second=0, microsecond=0),
                        tags=["日报", "头条"],
                    )
                )
    for point in re.findall(r'<li class="latest-point">([\s\S]*?)</li>', block):
            title_match = re.search(r'<span class="latest-point-title">([\s\S]*?)</span>', point)
            score_match = re.search(r'<span class="latest-point-score[^"]*">(\d+)</span>', point)
            if title_match:
                title = strip_tags(title_match.group(1))
                if not has_cjk(title):
                    continue
                score = int(score_match.group(1)) if score_match else 8
                out.append(
                    RawItem(
                        source_id="xiaohu",
                        source="小互 AI 日报",
                        type="daily",
                        title=title,
                        summary="小互 AI 日报本期高分条目。",
                        url=latest_link,
                        published_at=latest_date or now.replace(hour=10, minute=0, second=0, microsecond=0),
                        tags=["日报", f"站内分 {score}"],
                    )
                )

    archive_issue_links: list[tuple[str, datetime]] = []
    for card in re.findall(r'<a class="archive-card" href="([^"]+)">([\s\S]*?)</a>', page):
        href, block = card
        title_match = re.search(r'<div class="archive-headline">([\s\S]*?)</div>', block)
        date_match = re.search(r'href="(\d{4}-\d{2}-\d{2})/', f'href="{href}"')
        if not title_match or not date_match:
            continue
        dt = datetime.fromisoformat(date_match.group(1)).replace(hour=10, tzinfo=TZ)
        archive_issue_links.append((urljoin("https://daily.xiaohu.ai/", href), dt))
        title = strip_tags(title_match.group(1))
        if not has_cjk(title) or any(item.title == title for item in out):
            continue
        out.append(
            RawItem(
                source_id="xiaohu",
                source="小互 AI 日报",
                type="daily",
                title=title,
                summary="小互 AI 日报历史归档条目。",
                url=urljoin("https://daily.xiaohu.ai/", href),
                published_at=dt,
                tags=["日报", "归档"],
            )
        )
    existing_titles = {item.title for item in out}
    issue_links: list[tuple[str, datetime]] = []
    if latest_date and latest_link:
        issue_links.append((latest_link, latest_date))
    issue_links.extend(archive_issue_links)
    seen_issues: set[str] = set()
    for issue_url, issue_date in issue_links[:7]:
        if issue_url in seen_issues:
            continue
        seen_issues.add(issue_url)
        try:
            for item in parse_xiaohu_issue(issue_url, issue_date):
                if item.title not in existing_titles:
                    out.append(item)
                    existing_titles.add(item.title)
        except Exception:
            # The homepage still provides a usable fallback; source-status will
            # capture hard failures at the fetcher level.
            pass
    return out


def parse_xiaohu_issue(issue_url: str, published: datetime, limit: int = 18) -> list[RawItem]:
    page = fetch_text(issue_url)
    out: list[RawItem] = []
    for card in re.findall(r'<div class="point-card">([\s\S]*?)</div>\s*</div>', page):
        link_match = re.search(r'<a href="([^"]+)"[^>]*>([\s\S]*?)</a>', card)
        summary_match = re.search(r'<div class="point-summary">([\s\S]*?)</div>', card)
        score_match = re.search(r"score-(\d+)", card)
        if not link_match:
            continue
        title = strip_tags(link_match.group(2))
        if not title or not has_cjk(title):
            continue
        score = int(score_match.group(1)) if score_match else 8
        out.append(
            RawItem(
                source_id="xiaohu",
                source="小互 AI 日报",
                type="daily",
                title=title,
                summary=strip_tags(summary_match.group(1)) if summary_match else "小互 AI 日报精选条目。",
                url=html.unescape(link_match.group(1)),
                published_at=published,
                tags=["日报", f"站内分 {score}"],
            )
        )

    for item in re.findall(r'<div class="longtail-item">([\s\S]*?)</div>', page):
        link_match = re.search(r'<a href="([^"]+)"[^>]*>([\s\S]*?)</a>', item)
        score_match = re.search(r'score-pill[^"]*">(\d+)</span>', item)
        if not link_match:
            continue
        title = strip_tags(link_match.group(2))
        if not has_cjk(title):
            continue
        score = int(score_match.group(1)) if score_match else 0
        if score < 4 and not any(k.lower() in title.lower() for k in AI_KEYWORDS):
            continue
        out.append(
            RawItem(
                source_id="xiaohu",
                source="小互 AI 日报",
                type="daily",
                title=title,
                summary="小互 AI 日报长尾候选，经站内分和 AI 关键词过滤后保留。",
                url=html.unescape(link_match.group(1)),
                published_at=published,
                tags=["日报", f"站内分 {score}", "长尾"],
            )
        )
        if len(out) >= limit:
            break
    return out[:limit]


def waytoagi_candidates(now: datetime, days: int = 14) -> list[tuple[datetime, str, str]]:
    out: list[tuple[datetime, str, str]] = []
    for offset in range(days):
        dt = (now - timedelta(days=offset)).astimezone(TZ)
        slug = dt.strftime("%Y%m%d")
        url = f"https://www.waytoagi.com/zh/blog/news-{slug}"
        try:
            page = fetch_text(url, timeout=12)
        except HTTPError:
            continue
        except URLError:
            continue
        title_match = re.search(r"<title>([^<]+)</title>", page)
        title = clean_text(title_match.group(1)) if title_match else f"知识库精选-{dt:%Y年%-m月%-d日}"
        if "WayToAGI" in title or "知识库精选" in title:
            out.append((dt.replace(hour=10, minute=0, second=0, microsecond=0), title, url))
    return out


def fetch_waytoagi(now: datetime) -> list[RawItem]:
    out: list[RawItem] = []
    for dt, title, url in waytoagi_candidates(now):
        out.append(
            RawItem(
                source_id="waytoagi",
                source="WaytoAGI",
                type="daily",
                title=title.replace("-WayToAGI", ""),
                summary="WaytoAGI 公开知识库精选页。若近期日期路由异常，该来源会在源状态中显示。",
                url=url,
                published_at=dt,
                tags=["知识库精选"],
            )
        )
    return out


def score_item(item: RawItem, now: datetime) -> int:
    age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600)
    freshness = max(0, 35 - int(age_hours / 4))
    relevance = 30 if any(k.lower() in item.title.lower() for k in AI_KEYWORDS) else 22
    source_quality = {"xiaohu": 18, "geekpark": 18, "waytoagi": 16}.get(item.source_id, 12)
    novelty = 12
    if "归档" in item.tags:
        novelty -= 2
    return max(45, min(98, freshness + relevance + source_quality + novelty))


def dedupe(items: list[RawItem]) -> list[RawItem]:
    seen: set[str] = set()
    out: list[RawItem] = []
    for item in sorted(items, key=lambda x: (x.published_at, x.priority), reverse=True):
        key = re.sub(r"\W+", "", item.title.lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def source_record(source_id: str, name: str, items: list[RawItem], mode: str) -> dict[str, Any]:
    if items:
        latest = max(item.published_at for item in items)
        return {
            "id": source_id,
            "name": name,
            "mode": mode,
            "cadence": "公开页面",
            "status": "ok",
            "last_accessible": latest.date().isoformat(),
            "home_url": items[0].url,
        }
    return {
        "id": source_id,
        "name": name,
        "mode": mode,
        "cadence": "公开页面",
        "status": "warn",
        "last_accessible": None,
        "home_url": None,
    }


def main() -> int:
    now = datetime.now(TZ)
    source_errors: dict[str, str] = {}
    by_source: dict[str, list[RawItem]] = {}

    fetchers = {
        "geekpark": ("极客公园", "AI 栏目", fetch_geekpark),
        "xiaohu": ("小互 AI 日报", "日报页", fetch_xiaohu),
        "waytoagi": ("WaytoAGI", "知识库精选页", fetch_waytoagi),
    }
    all_items: list[RawItem] = []
    for source_id, (_, _, fetcher) in fetchers.items():
        try:
            items = fetcher(now)
        except Exception as exc:  # noqa: BLE001 - status file should expose failures
            source_errors[source_id] = str(exc)
            items = []
        for item in items:
            item.priority = score_item(item, now)
        by_source[source_id] = items
        all_items.extend(items)

    all_items = dedupe(all_items)
    sources = [
        source_record(source_id, name, by_source.get(source_id, []), mode)
        for source_id, (name, mode, _) in fetchers.items()
    ]
    sources.extend(
        [
            {
                "id": "huangshu",
                "name": "AI产品黄叔",
                "mode": "X/公众号待接入",
                "cadence": "需稳定公开 feed",
                "status": "paused",
                "last_accessible": None,
                "home_url": "https://x.com/PMbackttfuture",
            },
            {
                "id": "khazix",
                "name": "数字生命卡兹克",
                "mode": "X/GitHub 待接入",
                "cadence": "需稳定公开 feed",
                "status": "paused",
                "last_accessible": None,
                "home_url": "https://x.com/Khazix0918",
            },
        ]
    )
    for source in sources:
        if source["id"] in source_errors:
            source["status"] = "failed"
            source["error"] = source_errors[source["id"]]

    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "generated_at": iso_local(now),
        "generated_rfc2822": format_datetime(now),
        "sources": sources,
        "items": [
            {
                **asdict(item),
                "published_at": iso_local(item.published_at),
            }
            for item in all_items
        ],
    }
    (DATA_DIR / "news.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    status = {
        "generated_at": iso_local(now),
        "ok": not source_errors,
        "failed_sites": source_errors,
        "source_counts": {source_id: len(items) for source_id, items in by_source.items()},
        "sources": sources,
    }
    (DATA_DIR / "source-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(all_items)} items to {DATA_DIR / 'news.json'}")
    return 0 if not source_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
