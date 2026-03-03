import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from xml.dom import minidom
import re
import os
import time

# =============================================
# KONFIGURASI SEMUA SUMBER
# =============================================
SOURCES = [
    # bansos.medanaktual.com
    {"url": "https://bansos.medanaktual.com/category/bansos/", "category": "Bansos"},
    {"url": "https://bansos.medanaktual.com/category/bantuan-pip/", "category": "Bantuan PIP"},
    {"url": "https://bansos.medanaktual.com/category/cek-bansos/", "category": "Cek Bansos"},
    # id.medanaktual.com
    {"url": "https://id.medanaktual.com/category/bpjs-kesehatan/", "category": "BPJS Kesehatan"},
    {"url": "https://id.medanaktual.com/category/bpjs-ketenagakerjaan/", "category": "BPJS Ketenagakerjaan"},
    {"url": "https://id.medanaktual.com/category/cpns/", "category": "CPNS"},
    {"url": "https://id.medanaktual.com/category/pppk/", "category": "PPPK"},
    {"url": "https://id.medanaktual.com/category/ekonomi/", "category": "Ekonomi"},
    {"url": "https://id.medanaktual.com/category/pendidikan/", "category": "Pendidikan"},
    # disway.id
    {"url": "https://disway.id/kategori/108/keuangan", "category": "Keuangan"},
    # ihram.co.id
    {"url": "https://ihram.co.id/olahraga", "category": "Olahraga"},
    {"url": "https://ihram.co.id/finance", "category": "Finance"},
    {"url": "https://ihram.co.id/teknologi", "category": "Teknologi"},
    # radarbogor.jawapos.com
    {"url": "https://radarbogor.jawapos.com/bansos", "category": "Bansos"},
]

FEED_TITLE = "Multi-Source RSS Feed"
FEED_DESCRIPTION = "RSS Feed gabungan dari berbagai sumber berita Indonesia"
FEED_LINK = "https://github.com/Kimjo12/bansos-rss"
OUTPUT_FILE = "feed.xml"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_page(url):
    """Ambil halaman HTML dari URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, verify=True, allow_redirects=True)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except Exception as e:
        print(f"  [ERROR] Gagal mengambil {url}: {e}")
        return None


def get_domain(url):
    """Ekstrak domain dari URL."""
    from urllib.parse import urlparse
    return urlparse(url).netloc


def parse_articles_generic(html, source_url, category):
    """Parse artikel dari HTML - generic untuk berbagai situs WordPress/CMS."""
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    seen_urls = set()
    domain = get_domain(source_url)

    # Strategi 1: Cari semua <a> dalam heading (h1-h4) - umum di WordPress
    links = []
    for tag in ["h1", "h2", "h3", "h4"]:
        for heading in soup.find_all(tag):
            for a in heading.find_all("a", href=True):
                links.append(a)

    # Strategi 2: Cari <a> dengan class yang umum di theme berita
    common_title_classes = [
        "post-title", "entry-title", "jeg_post_title", "article-title",
        "news-title", "card-title", "title", "post__title"
    ]
    for cls in common_title_classes:
        for a in soup.select(f"a.{cls}, .{cls} a"):
            if a not in links:
                links.append(a)

    # Strategi 3: Cari article tag
    for article in soup.find_all("article"):
        for a in article.find_all("a", href=True):
            title_text = a.get_text(strip=True)
            if len(title_text) > 20:  # Kemungkinan judul artikel
                if a not in links:
                    links.append(a)

    for link in links:
        url = link.get("href", "").strip()
        title = link.get_text(strip=True)

        if not url or not title:
            continue
        if len(title) < 15:  # Terlalu pendek untuk jadi judul
            continue
        if url in seen_urls:
            continue

        # Pastikan URL lengkap
        if url.startswith("/"):
            url = f"https://{domain}{url}"

        # Filter: hanya ambil yang dari domain yang sama
        if domain not in url:
            continue
        # Skip halaman kategori, tag, page
        skip_patterns = ["/category/", "/tag/", "/page/", "/kategori/", "/author/",
                         "#", "javascript:", "/search/"]
        if any(p in url for p in skip_patterns):
            continue
        # Skip jika URL sama dengan source
        if url.rstrip("/") == source_url.rstrip("/"):
            continue

        seen_urls.add(url)

        # Cari excerpt
        excerpt = ""
        parent = link.parent
        for _ in range(8):
            if parent is None:
                break
            parent = parent.parent
            if parent:
                p_tag = parent.find("p")
                if p_tag and len(p_tag.get_text(strip=True)) > 30:
                    excerpt = p_tag.get_text(strip=True)[:300]
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
                    src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
                    if src and "jeg-empty" not in src and "data:image" not in src and "placeholder" not in src:
                        if src.startswith("/"):
                            src = f"https://{domain}{src}"
                        image = src
                        break

        articles.append({
            "title": title,
            "url": url,
            "excerpt": excerpt,
            "image": image,
            "category": category,
            "source": domain,
        })

    return articles


def fetch_article_date(url):
    """Ambil tanggal publikasi dari halaman artikel."""
    html = fetch_page(url)
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Cari dari meta tag
    for meta_prop in ["article:published_time", "og:published_time", "datePublished"]:
        meta = soup.find("meta", {"property": meta_prop}) or soup.find("meta", {"name": meta_prop})
        if meta and meta.get("content"):
            return meta["content"]

    # Cari dari tag <time>
    time_tag = soup.find("time", {"datetime": True})
    if time_tag:
        return time_tag["datetime"]

    # Cari dari JSON-LD
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            import json
            data = json.loads(script.string)
            if isinstance(data, dict):
                if "datePublished" in data:
                    return data["datePublished"]
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "datePublished" in item:
                        return item["datePublished"]
        except Exception:
            pass

    return ""


def format_date_rfc822(date_str):
    """Konversi berbagai format tanggal ke RFC 822."""
    if not date_str:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    try:
        # ISO format
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except Exception:
        pass

    try:
        # Coba parse format umum lainnya
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"]:
            try:
                dt = datetime.strptime(date_str[:19], fmt)
                return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except Exception:
                continue
    except Exception:
        pass

    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


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
    github_user = os.environ.get("GITHUB_REPOSITORY_OWNER", "Kimjo12")
    repo_name = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] if os.environ.get("GITHUB_REPOSITORY") else "bansos-rss"
    feed_url = f"https://{github_user}.github.io/{repo_name}/feed.xml"

    atom_link = ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link")
    atom_link.set("href", feed_url)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    print(f"\n{'='*60}")
    print(f"Mengambil tanggal publikasi untuk {len(articles)} artikel...")
    print(f"{'='*60}")

    for i, article in enumerate(articles):
        print(f"  [{i+1}/{len(articles)}] [{article['source']}] {article['title'][:50]}...")

        # Ambil tanggal dari halaman artikel (setiap 5 artikel, delay sedikit)
        if i > 0 and i % 5 == 0:
            time.sleep(1)

        pub_date_raw = fetch_article_date(article["url"])
        pub_date = format_date_rfc822(pub_date_raw)

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article["title"]
        ET.SubElement(item, "link").text = article["url"]
        ET.SubElement(item, "guid").text = article["url"]
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, "category").text = article.get("category", "")
        ET.SubElement(item, "source").text = article.get("source", "")

        # Description
        description = article.get("excerpt", "")
        if description:
            ET.SubElement(item, "description").text = description

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
        pretty_xml = "\n".join(pretty_xml.split("\n")[1:])
        xml_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + pretty_xml
    except Exception:
        pass

    return xml_string


def main():
    print("=" * 60)
    print("Multi-Source RSS Feed Generator")
    print(f"Total sumber: {len(SOURCES)}")
    print("=" * 60)

    all_articles = []
    seen_urls = set()

    for idx, source in enumerate(SOURCES):
        url = source["url"]
        category = source["category"]
        domain = get_domain(url)

        print(f"\n[{idx+1}/{len(SOURCES)}] Scraping: {url}")
        print(f"  Kategori: {category} | Domain: {domain}")

        html = fetch_page(url)
        if not html:
            print(f"  [SKIP] Gagal mengambil halaman")
            continue

        articles = parse_articles_generic(html, url, category)

        new_count = 0
        for article in articles:
            if article["url"] not in seen_urls:
                seen_urls.add(article["url"])
                all_articles.append(article)
                new_count += 1

        print(f"  Ditemukan: {len(articles)} artikel, Baru: {new_count}")

        # Delay antar sumber untuk tidak terlalu agresif
        time.sleep(1)

    print(f"\n{'='*60}")
    print(f"Total artikel unik: {len(all_articles)}")
    print(f"{'='*60}")

    if not all_articles:
        print("\n[WARNING] Tidak ada artikel ditemukan!")
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
    print(f"[INFO] Sumber aktif: {len(set(a['source'] for a in all_articles))}")


if __name__ == "__main__":
    main()
