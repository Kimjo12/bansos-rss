import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from xml.dom import minidom
import re
import os

SITE_URL = "https://bansos.medanaktual.com/"
FEED_TITLE = "Bansos MedanAktual RSS Feed"
FEED_DESCRIPTION = "RSS Feed untuk bansos.medanaktual.com - Informasi Bantuan Sosial Terkini"
FEED_LINK = "https://bansos.medanaktual.com/"
OUTPUT_FILE = "feed.xml"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Halaman yang akan di-scrape (tambahkan lebih banyak jika perlu)
PAGES_TO_SCRAPE = [
    SITE_URL,
    f"{SITE_URL}page/2/",
    f"{SITE_URL}page/3/",
]


def fetch_page(url):
    """Ambil halaman HTML dari URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, verify=True)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"[ERROR] Gagal mengambil {url}: {e}")
        return None


def parse_articles(html):
    """Parse artikel dari HTML halaman utama."""
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    seen_urls = set()

    # Cari semua link artikel dari heading h2/h3 dengan class post-title
    # JNews theme biasanya pakai class "jeg_post_title"
    selectors = [
        "h3.jeg_post_title a",
        "h2.jeg_post_title a",
        "h3 a[href*='bansos.medanaktual.com']",
        "h2 a[href*='bansos.medanaktual.com']",
        ".jeg_postblock a.jeg_post_title",
    ]

    links = []
    for selector in selectors:
        links.extend(soup.select(selector))

    for link in links:
        url = link.get("href", "").strip()
        title = link.get_text(strip=True)

        if not url or not title:
            continue
        if url in seen_urls:
            continue
        if "/category/" in url or "/tag/" in url or "/page/" in url:
            continue
        if url == SITE_URL:
            continue
        if "bansos.medanaktual.com" not in url:
            continue

        seen_urls.add(url)

        # Cari excerpt - naik ke parent untuk cari <p>
        excerpt = ""
        parent = link.parent
        for _ in range(8):
            if parent is None:
                break
            parent = parent.parent
            if parent:
                p_tag = parent.find("p")
                if p_tag and len(p_tag.get_text(strip=True)) > 30:
                    excerpt = p_tag.get_text(strip=True)
                    break

        # Cari gambar
        image = ""
        img_parent = link.parent
        for _ in range(6):
            if img_parent is None:
                break
            img_parent = img_parent.parent
            if img_parent:
                img = img_parent.find("img")
                if img:
                    src = img.get("data-src") or img.get("src") or ""
                    if src and "jeg-empty" not in src and "data:image" not in src:
                        image = src
                        break

        articles.append({
            "title": title,
            "url": url,
            "excerpt": excerpt,
            "image": image,
        })

    return articles


def fetch_article_content(url):
    """Ambil konten lengkap dari halaman artikel individual."""
    html = fetch_page(url)
    if not html:
        return "", ""

    soup = BeautifulSoup(html, "html.parser")

    # Cari tanggal publikasi
    pub_date = ""
    # Cari dari meta tag
    meta_date = soup.find("meta", {"property": "article:published_time"})
    if meta_date:
        pub_date = meta_date.get("content", "")

    if not pub_date:
        time_tag = soup.find("time", {"datetime": True})
        if time_tag:
            pub_date = time_tag.get("datetime", "")

    # Cari konten artikel
    content = ""
    content_div = (
        soup.select_one("div.entry-content")
        or soup.select_one("div.content-inner")
        or soup.select_one("div.post-content")
        or soup.select_one("article .entry-content")
    )

    if content_div:
        # Hapus elemen yang tidak perlu
        for tag in content_div.select(
            ".jeg_share_button, .jnews_related, .jeg_ad, "
            ".jp-relatedposts, .sharedaddy, script, style, "
            ".jeg_post_tags, .jeg_authorbox, .jnews_comment, "
            ".jeg_next_prev, ins, .adsbygoogle, .jeg_breadcrumbs, "
            "iframe[src*='facebook'], .fb-comments"
        ):
            tag.decompose()

        # Ambil teks bersih
        paragraphs = content_div.find_all(["p", "h2", "h3", "h4", "ul", "ol", "table"])
        content_parts = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text and len(text) > 5:
                if p.name in ["h2", "h3", "h4"]:
                    content_parts.append(f"<{p.name}>{text}</{p.name}>")
                elif p.name in ["ul", "ol"]:
                    content_parts.append(str(p))
                elif p.name == "table":
                    content_parts.append(str(p))
                else:
                    content_parts.append(f"<p>{text}</p>")

        content = "\n".join(content_parts)

    return content, pub_date


def generate_rss(articles):
    """Generate file feed.xml dari daftar artikel."""
    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")
    rss.set("xmlns:media", "http://search.yahoo.com/mrss/")

    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "link").text = FEED_LINK
    ET.SubElement(channel, "language").text = "id"
    ET.SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )

    # Atom self link
    github_user = os.environ.get("GITHUB_REPOSITORY_OWNER", "USERNAME")
    repo_name = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] if os.environ.get("GITHUB_REPOSITORY") else "bansos-rss"
    feed_url = f"https://{github_user}.github.io/{repo_name}/feed.xml"

    atom_link = ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link")
    atom_link.set("href", feed_url)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    print(f"\n[INFO] Memproses {len(articles)} artikel...")

    for i, article in enumerate(articles):
        print(f"  [{i+1}/{len(articles)}] {article['title'][:60]}...")

        # Ambil konten lengkap
        content, pub_date = fetch_article_content(article["url"])

        if not pub_date:
            pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        else:
            # Convert ISO date ke RFC 822
            try:
                dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except Exception:
                pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article["title"]
        ET.SubElement(item, "link").text = article["url"]
        ET.SubElement(item, "guid").text = article["url"]
        ET.SubElement(item, "pubDate").text = pub_date

        # Description (excerpt)
        description = article.get("excerpt", "")
        if not description and content:
            # Ambil 200 karakter pertama dari konten
            soup = BeautifulSoup(content, "html.parser")
            description = soup.get_text(strip=True)[:300] + "..."
        ET.SubElement(item, "description").text = description

        # Full content
        if content:
            content_encoded = ET.SubElement(
                item, "{http://purl.org/rss/1.0/modules/content/}encoded"
            )
            content_encoded.text = content

        # Media/image
        if article.get("image"):
            media_content = ET.SubElement(
                item, "{http://search.yahoo.com/mrss/}content"
            )
            media_content.set("url", article["image"])
            media_content.set("medium", "image")

    # Pretty print XML
    xml_string = ET.tostring(rss, encoding="unicode", xml_declaration=False)
    xml_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_string

    try:
        dom = minidom.parseString(xml_string)
        pretty_xml = dom.toprettyxml(indent="  ", encoding=None)
        # Remove extra xml declaration from minidom
        pretty_xml = "\n".join(pretty_xml.split("\n")[1:])
        xml_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + pretty_xml
    except Exception:
        pass

    return xml_string


def main():
    print("=" * 60)
    print("Bansos MedanAktual RSS Feed Generator")
    print("=" * 60)

    all_articles = []
    seen_urls = set()

    for page_url in PAGES_TO_SCRAPE:
        print(f"\n[INFO] Scraping: {page_url}")
        html = fetch_page(page_url)
        if not html:
            continue

        articles = parse_articles(html)
        for article in articles:
            if article["url"] not in seen_urls:
                seen_urls.add(article["url"])
                all_articles.append(article)

        print(f"  Ditemukan {len(articles)} artikel (total unik: {len(all_articles)})")

    if not all_articles:
        print("\n[WARNING] Tidak ada artikel ditemukan!")
        # Buat feed kosong
        rss_content = '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        rss_content += f"<title>{FEED_TITLE}</title>"
        rss_content += f"<link>{FEED_LINK}</link>"
        rss_content += f"<description>{FEED_DESCRIPTION}</description>"
        rss_content += "</channel></rss>"
    else:
        rss_content = generate_rss(all_articles)

    # Simpan file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(rss_content)

    print(f"\n[SUCCESS] Feed berhasil disimpan ke {OUTPUT_FILE}")
    print(f"[INFO] Total artikel: {len(all_articles)}")


if __name__ == "__main__":
    main()
