# app.py
import os
import re
import csv
import requests
import asyncio
from pathlib import Path
from flask import Flask, request, render_template_string, jsonify
from bs4 import BeautifulSoup

# Optional: pyppeteer only used for fallback rendering
try:
    from pyppeteer import launch
    PUPPETEER_AVAILABLE = True
except Exception:
    PUPPETEER_AVAILABLE = False

app = Flask(__name__)

# ---------- Helpers ----------
def txt(tag):
    return tag.get_text(strip=True) if tag else ""

def clean_spaces(s):
    return re.sub(r"\s+", " ", s.strip()) if s else ""

def slugify(name: str) -> str:
    s = (name or "ilan").lower()
    tr_map = str.maketrans({
        "ç":"c","ğ":"g","ı":"i","ö":"o","ş":"s","ü":"u",
        "Ç":"c","Ğ":"g","İ":"i","Ö":"o","Ş":"s","Ü":"u","+":"-plus-"
    })
    s = s.translate(tr_map)
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "ilan"

# Browser-like headers to reduce 403
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def format_phone_digits(digits: str) -> str:
    if not digits:
        return "Belirtilmemiş"
    d = re.sub(r"\D", "", digits)
    if len(d) == 10 and d.startswith("5"):
        d = "0" + d
    if len(d) >= 11 and d.startswith("0"):
        return f"{d[0]} ({d[1:4]}) {d[4:7]} {d[7:9]} {d[9:11]}"
    return digits

# ---------- Fetchers ----------
def fetch_via_requests(url, timeout=15):
    """Try to get page via requests with browser-like headers."""
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)

async def _pyppeteer_fetch(url, timeout=30000):
    """Async fetch using pyppeteer to render JS pages."""
    browser = await launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
    page = await browser.newPage()
    await page.setUserAgent(DEFAULT_HEADERS["User-Agent"])
    await page.setExtraHTTPHeaders({"Accept-Language": DEFAULT_HEADERS["Accept-Language"]})
    await page.goto(url, {'timeout': timeout, 'waitUntil': 'networkidle2'})
    content = await page.content()
    await browser.close()
    return content

def fetch_via_pyppeteer(url):
    """Run pyppeteer in a fresh loop to avoid 'no current event loop' errors."""
    if not PUPPETEER_AVAILABLE:
        return False, "pyppeteer not installed"
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        html = loop.run_until_complete(_pyppeteer_fetch(url))
        loop.close()
        return True, html
    except Exception as e:
        return False, str(e)

# ---------- Image downloader ----------
def download_images_from_soup(soup, title):
    folder = Path("data") / slugify(title) / "images"
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    imgs = []
    for img in soup.select("img"):
        src = img.get("data-src") or img.get("src") or ""
        if src and re.search(r"\.(jpe?g|png|webp)(\?|$)", src.lower()):
            imgs.append(src)
    imgs = list(dict.fromkeys(imgs))
    for i, src in enumerate(imgs[:100], start=1):
        try:
            if not src.startswith("http"):
                # try to make absolute if possible (skip otherwise)
                continue
            r = requests.get(src, headers=DEFAULT_HEADERS, timeout=15)
            if r.status_code == 200:
                ext = ".jpg" if ".jpg" in src.lower() or ".jpeg" in src.lower() else ".png"
                path = folder / f"{i:02d}{ext}"
                path.write_bytes(r.content)
                saved.append(str(path.as_posix()))
        except Exception:
            continue
    return saved

# ---------- Parser ----------
def parse_html_to_record(html_path_or_url, html_text, offline_path=None):
    soup = BeautifulSoup(html_text, "html.parser")
    title = txt(soup.select_one("h1.classifiedTitle")) or txt(soup.select_one("h1")) or "Belirtilmemiş"
    title = re.sub(r"\s*-\s*Satılık.*$", "", clean_spaces(title))

    # Find phone
    phone = "Belirtilmemiş"
    a = soup.find("a", href=re.compile(r"tel:\+?\d"))
    if a:
        digits = re.sub(r"[^\d]", "", a.get("href", ""))
        phone = format_phone_digits(digits)
    else:
        text = soup.get_text(" ", strip=True)
        m = re.search(r"0?\s*\(?5\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", text)
        if m:
            phone = format_phone_digits(m.group(0))

    # m2 extraction
    page_text = soup.get_text(" ", strip=True)
    m_gross = re.search(r"Brüt\s*m.?²?\s*[:\-]?\s*(\d+)", page_text, re.I)
    m_net = re.search(r"Net\s*m.?²?\s*[:\-]?\s*(\d+)", page_text, re.I)

    images = download_images_from_soup(soup, title)
    description = clean_spaces(txt(soup.select_one("#classifiedDescription")) or "")
    # owner
    owner = txt(soup.select_one(".username-info-area a")) or "Belirtilmemiş"

    record = {
        "url_offline": offline_path or html_path_or_url,
        "listing_id": re.search(r"(\d+)", str(html_path_or_url)).group(1) if re.search(r"(\d+)", str(html_path_or_url)) else "",
        "title": title,
        "price": clean_spaces(txt(soup.select_one(".classifiedInfo h3")) or ""),
        "city": "Belirtilmemiş",
        "district": "Belirtilmemiş",
        "neighborhood": "Belirtilmemiş",
        "gross_m2": m_gross.group(1) if m_gross else "",
        "net_m2": m_net.group(1) if m_net else "",
        "room_count": txt(soup.select_one("li:contains('Oda')")) or "",
        "floor": txt(soup.select_one("li:contains('Bulunduğu Kat')")) or "",
        "heating": txt(soup.select_one("li:contains('Isıtma')")) or "",
        "building_age": txt(soup.select_one("li:contains('Bina Yaşı')")) or "",
        "furnished": txt(soup.select_one("li:contains('Eşyalı')")) or "",
        "swap": txt(soup.select_one("li:contains('Takas')")) or "",
        "credit_eligible": txt(soup.select_one("li:contains('Kredi')")) or "",
        "in_site": txt(soup.select_one("li:contains('Site İçerisinde')")) or "",
        "owner_name": owner,
        "phone": phone,
        "description": description,
        "image_count": len(images),
        "image_paths": ";".join(images),
        "is_real_estate": True
    }
    return record

# ---------- CSV saver ----------
def save_csv(rec, path="ilanlar_output.csv"):
    path = Path(path)
    exists = path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rec.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(rec)

# ---------- Flask routes ----------
INDEX_HTML = """
<!doctype html>
<title>İlan Parse</title>
<h2>İlan URL yapıştır — (GET param ?url=... veya form ile POST)</h2>
<form method="post" action="/parse">
  <input type="text" name="url" size="80" placeholder="https://www.sahibinden.com/ilan/..." required>
  <button type="submit">Parse Et</button>
</form>
<p>Ya da doğrudan: <a href="/parse?url=https://www.sahibinden.com/ilan/...">/parse?url=...</a></p>
"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)

@app.route("/parse", methods=["GET", "POST"])
def parse_route():
    url = request.values.get("url")
    if not url:
        return jsonify({"error": "url param yok. ?url=... veya form ile gönderin."}), 400

    # 1) try requests
    status, result = fetch_via_requests(url)
    if status == 200 and result:
        html = result
        record = parse_html_to_record(url, html, offline_path=url)
        save_csv(record)
        return jsonify({"result": "ok_requests", "record": record})

    # 2) if requests returned 403 or other code, try pyppeteer
    if status is None or (status and status >= 400):
        if PUPPETEER_AVAILABLE:
            ok, content_or_err = fetch_via_pyppeteer(url)
            if ok:
                html = content_or_err
                record = parse_html_to_record(url, html, offline_path=url)
                save_csv(record)
                return jsonify({"result": "ok_pyppeteer", "record": record})
            else:
                return jsonify({"error": "pyppeteer-hata", "details": content_or_err}), 502
        else:
            return jsonify({"error": "requests_failed_and_pyppeteer_not_available", "requests_status": status, "requests_result": result}), 502

    # fallback
    return jsonify({"error": "Bilinmeyen hata", "status": status, "details": str(result)}), 500

if __name__ == "__main__":
    # Optional: set PYPPETEER_HOME to avoid download issues
    # os.environ["PYPPETEER_HOME"] = str(Path(".venv").resolve())
    app.run(debug=True)
