import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from conftest import ROOT


DOCS = ROOT / "docs"
GALLERY_INDEX = DOCS / "gallery" / "index.html"
MARKDOWN_LINK = re.compile(r"\]\(<?([^\s)>]+)>?|^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?", re.M)


class HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(value for key, value in attrs if key in {"href", "src"} and value)


def page_links(page):
    contents = page.read_text(encoding="utf-8")
    html = HTMLLinks()
    html.feed(contents)
    if page.suffix == ".md":
        html.urls.extend(match[1] or match[2] for match in MARKDOWN_LINK.finditer(contents))
    return html.urls


def test_pages_links_stay_inside_docs():
    pages = sorted(path for path in DOCS.rglob("*") if path.is_file() and path.suffix in {".md", ".html"})
    broken = []
    for page in pages:
        # Generated reports have a paired summary and are inspected separately.
        if (
            page.parent == GALLERY_INDEX.parent
            and page.suffix == ".html"
            and page.with_suffix(".summary.json").is_file()
        ):
            continue
        for url in page_links(page):
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (page.parent / unquote(parsed.path)).resolve()
            if not target.is_relative_to(DOCS):
                broken.append(f"{page.relative_to(ROOT)} → {url}")
    assert not broken, "\n".join(broken)


def test_gallery_walkthrough_links_use_jekyll_urls():
    links = {url for url in page_links(GALLERY_INDEX) if url.startswith("../walkthroughs/")}
    assert links
    for url in links:
        assert url.endswith(".html"), url
        assert (GALLERY_INDEX.parent / url).with_suffix(".md").is_file(), url
