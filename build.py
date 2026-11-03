#!/usr/bin/env python3
"""posts/ の Markdown から、日記サイトを _site/ に作る。

- posts/YYYY-MM-DD.md が 1日分の日記になる(ファイル名の日付が公開日)
- 作るページ: トップ(直近の日記)、日別、月別アーカイブ
- 見た目は template.html で決める
"""
import html
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import markdown

# ---- 設定 ------------------------------------------------------------
SITE_TITLE = "diary"   # サイトの名前
SITE_DESCRIPTION = ""  # サイトの説明(SNSなどにURLを貼ったときに出る。空なら出さない)
SITE_URL = "https://tomnyancat.github.io/diary/"  # 公開されるURL(OGPに必要)
AUTHOR = "TOM"   # 書いた人の名前
AUTHOR_URL = ""        # プロフィールのURL(Instagramなど)。空なら名前だけ表示
INDEX_DAYS = 10        # トップページに本文ごと並べる日数
# ---------------------------------------------------------------------

POSTS_DIR = Path("posts")
OUT_DIR = Path("_site")
TEMPLATE = Path("template.html")

WEEKDAYS = "月火水木金土日"
FILENAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
# 「Instagram: URL」だけの行を、短いリンクにする
INSTAGRAM_RE = re.compile(r"^Instagram\s*:\s*(https?://\S+)\s*$", re.MULTILINE)


def plain_text(fragment):
    text = re.sub(r"<br\s*/?>", " ", fragment)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


@dataclass
class Day:
    date: date
    body: str  # 変換済みのHTML

    @property
    def slug(self):
        return self.date.isoformat()

    @property
    def title(self):
        """最初の見出し(書名)。SNSに貼ったときのタイトルに使う"""
        m = re.search(r"<h3>(.*?)</h3>", self.body, re.DOTALL)
        return plain_text(m.group(1)) if m else ""

    @property
    def summary(self):
        """最初の本文の段落(100文字まで)。リンクだけの段落は飛ばす"""
        for m in re.finditer(r"<p>(.*?)</p>", self.body, re.DOTALL):
            if re.fullmatch(r"<a [^>]*>[^<]*</a>", m.group(1).strip()):
                continue
            text = plain_text(m.group(1))
            return text if len(text) <= 100 else text[:100] + "…"
        return ""


def instagram_link(match):
    # ?utm_source=... などの追跡用パラメータは落とす
    parts = urlsplit(match.group(1))
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return f"[Instagramの投稿を見る]({url})"


def shift_headings(text):
    # 本文の ## はページ内では h3 にする(h2 は日付に使う)
    return re.sub(
        r"<(/?)h([1-5])>",
        lambda m: f"<{m.group(1)}h{int(m.group(2)) + 1}>",
        text,
    )


def load_days():
    md = markdown.Markdown(extensions=["nl2br"])  # 改行はそのまま改行にする
    days = []
    for path in sorted(POSTS_DIR.glob("*.md")):
        m = FILENAME_RE.match(path.name)
        if not m:
            print(f"skip (ファイル名が YYYY-MM-DD.md ではない): {path.name}")
            continue
        try:
            d = date(*map(int, m.groups()))
        except ValueError:
            print(f"skip (存在しない日付): {path.name}")
            continue
        text = INSTAGRAM_RE.sub(instagram_link, path.read_text(encoding="utf-8"))
        body = shift_headings(md.convert(text))
        md.reset()
        days.append(Day(d, body))
    days.sort(key=lambda day: day.date, reverse=True)  # 新しい順
    return days


def jp_date(d):
    return f"{d.year}年{d.month}月{d.day}日({WEEKDAYS[d.weekday()]})"


def render_article(day, link=True):
    heading = jp_date(day.date)
    if link:
        heading = f'<a href="{day.slug}.html">{heading}</a>'
    return f"<article>\n<h2>{heading}</h2>\n{day.body}\n</article>"


def render_pager(newer, older):
    def link(day, label, rel):
        if day is None:
            return "<span></span>"
        return f'<a href="{day.slug}.html" rel="{rel}">{label}</a>'

    return (
        '<nav class="pager">\n'
        + link(older, f"← {older.date.month}月{older.date.day}日" if older else "", "prev")
        + "\n"
        + link(newer, f"{newer.date.month}月{newer.date.day}日 →" if newer else "", "next")
        + "\n</nav>"
    )


def render_archive(months):
    if not months:
        return ""
    items = "\n".join(
        f'<li><a href="{key}.html">{key[:4]}年{int(key[5:])}月</a>({len(days)})</li>'
        for key, days in months.items()
    )
    return f'<nav class="archive">\n<h2>アーカイブ</h2>\n<ul>\n{items}\n</ul>\n</nav>'


def render_meta(title, description, filename):
    is_index = filename == "index.html"
    url = ""
    if SITE_URL:
        url = SITE_URL.rstrip("/") + "/" + ("" if is_index else filename)
    tags = [
        ("name", "author", AUTHOR),
        ("name", "description", description),
        ("property", "og:type", "website" if is_index else "article"),
        ("property", "og:site_name", SITE_TITLE),
        ("property", "og:title", title),
        ("property", "og:description", description),
        ("property", "og:url", url),
        ("property", "og:locale", "ja_JP"),
        ("name", "twitter:card", "summary"),
    ]
    # 値が空のタグは出さない
    return "\n".join(
        f'<meta {attr}="{key}" content="{html.escape(value)}">'
        for attr, key, value in tags
        if value
    )


def write_page(filename, title, content, archive, og_title=None, description=None):
    page_title = SITE_TITLE if title is None else f"{title} - {SITE_TITLE}"
    if description is None:
        description = SITE_DESCRIPTION
    author = html.escape(AUTHOR)
    if AUTHOR_URL:
        author = f'<a href="{html.escape(AUTHOR_URL)}">{author}</a>'
    values = {
        "page_title": html.escape(page_title),
        "site_title": html.escape(SITE_TITLE),
        "meta": render_meta(og_title or page_title, description, filename),
        "content": content,
        "archive": archive,
        "author_html": author,
    }
    # 1回の置換で済ませる(本文中に {{...}} があっても影響しない)
    page = re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: values.get(m.group(1), m.group(0)),
        TEMPLATE.read_text(encoding="utf-8"),
    )
    (OUT_DIR / filename).write_text(page, encoding="utf-8")


def main():
    days = load_days()

    # 月ごとにまとめる(新しい月が先)
    months = {}
    for day in days:
        months.setdefault(day.slug[:7], []).append(day)
    archive = render_archive(months)

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir()

    # トップページ
    if days:
        content = "\n".join(render_article(d) for d in days[:INDEX_DAYS])
    else:
        content = "<p>まだ日記がありません。</p>"
    write_page("index.html", None, content, archive)

    # 日別ページ(days は新しい順なので、i-1 が翌日側、i+1 が前日側)
    for i, day in enumerate(days):
        newer = days[i - 1] if i > 0 else None
        older = days[i + 1] if i + 1 < len(days) else None
        content = render_article(day, link=False) + "\n" + render_pager(newer, older)
        write_page(
            f"{day.slug}.html",
            jp_date(day.date),
            content,
            archive,
            og_title=day.title or jp_date(day.date),
            description=day.summary,
        )

    # 月別ページ
    for key, month_days in months.items():
        content = (
            f"<h2>{key[:4]}年{int(key[5:])}月</h2>\n"
            + "\n".join(render_article(d) for d in month_days)
        )
        write_page(f"{key}.html", f"{key[:4]}年{int(key[5:])}月", content, archive)

    print(f"{len(days)}日分 → {len(months)}か月、{OUT_DIR}/ に出力しました")


if __name__ == "__main__":
    main()
