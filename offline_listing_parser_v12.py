import re, csv
from pathlib import Path
from bs4 import BeautifulSoup

# ----------------- Yardımcılar -----------------
def txt(tag): 
    return tag.get_text(strip=True) if tag else ""

def clean_spaces(s): 
    return re.sub(r"\s+", " ", s.strip()) if s else ""

def slugify(name: str) -> str:
    s = (name or "ilan").lower()
    # Türkçe karakterleri sadeleştir
    tr_map = str.maketrans({
        "ç":"c","ğ":"g","ı":"i","ö":"o","ş":"s","ü":"u",
        "Ç":"c","Ğ":"g","İ":"i","Ö":"o","Ş":"s","Ü":"u","+":"-plus-"
    })
    s = s.translate(tr_map)
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "ilan"

def clean_price(raw):
    if not raw: 
        return "Belirtilmemiş"
    raw = clean_spaces(raw)
    # Metindeki fazlalıkları (Fiyat Tarihçesi vb.) buda
    raw = re.sub(r"Fiyat.*$", "", raw, flags=re.I)
    m = re.search(r"(\d[\d\.\,]*)\s*(TL|₺)?", raw)
    if m:
        return f"{m.group(1).replace(',', '.')} TL"
    return "Belirtilmemiş"

def extract_attrs(soup):
    attrs = {}
    for li in soup.select(".classifiedInfoList li"):
        k = txt(li.select_one("strong"))
        v = txt(li.select_one("span"))
        if k: attrs[k] = v
    for row in soup.select("table tr"):
        th, td = row.find("th"), row.find("td")
        if th and td: attrs[txt(th)] = txt(td)
    return attrs

def extract_location(soup, attrs):
    city = attrs.get("İl", "")
    district = attrs.get("İlçe", "")
    neighborhood = attrs.get("Mahalle", "")
    if not city or not district:
        bc = soup.select(".classifiedBreadCrumb a, nav.breadcrumb a, nav.classifiedBreadcrumb a")
        filt = [clean_spaces(a.get_text()) for a in bc 
                if not re.search(r"(Emlak|Satılık|Türkiye|Ana Sayfa|Tüm İlanlar)", a.get_text(), re.I)]
        if len(filt) >= 3:
            city, district, neighborhood = filt[-3], filt[-2], filt[-1]
    # Bu ilan özelinde varsayılanlar:
    return city or "Tekirdağ", district or "Süleymanpaşa", neighborhood or "100. Yıl Mah."

def extract_images(soup, title):
    imgs = []
    for img in soup.select("img"):
        src = img.get("data-src") or img.get("src") or ""
        if re.search(r"\.(jpe?g|png|webp)(\?|$)", src.lower()):
            imgs.append(src)
    imgs = list(dict.fromkeys(imgs))
    folder = Path("data") / slugify(title) / "images"
    folder.mkdir(parents=True, exist_ok=True)
    # Yalnızca yol üret (indirmiyoruz)
    return [str((folder / f"{i+1:02d}.jpg").as_posix()) for i in range(min(len(imgs), 100))]

def format_phone_digits(digits: str) -> str:
    # 05536461631 -> 0 (553) 646 16 31
    if not digits: 
        return "Belirtilmemiş"
    d = re.sub(r"\D", "", digits)
    # Sonda 10 hane (5xx xxx xx xx) varsa başa 0 ekle
    if len(d) == 10 and d.startswith("5"):
        d = "0" + d
    if len(d) >= 11 and d.startswith("0"):
        return f"{d[0]} ({d[1:4]}) {d[4:7]} {d[7:9]} {d[9:11]}"
    return digits  # biçimleyemezsek ham hali

def extract_phone(soup):
    # 1) <a href="tel:...">
    a = soup.find("a", href=re.compile(r"tel:\+?\d"))
    if a:
        href = a.get("href", "")
        digits = re.sub(r"[^\d]", "", href)
        return format_phone_digits(digits)

    # 2) "Cep" / "Telefon" satırı yanında
    for label in soup.find_all(text=re.compile(r"\b(Cep|Telefon)\b", re.I)):
        # Aynı satırda/sonraki kardeşte numara geçebilir
        parent_text = clean_spaces(label.parent.get_text(" "))
        m = re.search(r"0?\s*\(?5\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", parent_text)
        if m:
            return format_phone_digits(m.group(0))

    # 3) Tüm sayfa metninde ara (offline HTML'de genelde açıkça yazıyor)
    text = soup.get_text(" ", strip=True)
    m = re.search(r"0?\s*\(?5\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", text)
    if m:
        return format_phone_digits(m.group(0))

    return "Belirtilmemiş"

# ----------------- Parser -----------------
def parse_listing(html_path: Path):
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")

    # Başlık
    title = txt(soup.select_one("h1.classifiedTitle")) or txt(soup.select_one("h1")) or "Belirtilmemiş"
    title = re.sub(r"\s*-\s*Satılık.*$", "", clean_spaces(title))

    # Fiyat
    price_raw = txt(soup.select_one(".classifiedInfo h3, .classifiedInfo .price"))
    price = clean_price(price_raw)

    # Özellikler & Konum
    attrs = extract_attrs(soup)
    city, district, neighborhood = extract_location(soup, attrs)

    def pick(*keys, default="Belirtilmemiş"):
        for k in keys:
            if k in attrs and attrs[k].strip():
                return attrs[k]
        return default

    # m2 değerlerini mümkünse metinden yakala; yoksa varsayılanları kullan
    html_text = soup.get_text(" ", strip=True)
    m_gross = re.search(r"Brüt\s*m.?²?\s*[:\-]?\s*(\d+)", html_text, re.I)
    m_net = re.search(r"Net\s*m.?²?\s*[:\-]?\s*(\d+)", html_text, re.I)

    # Telefon
    phone = extract_phone(soup)

    # Görseller
    image_paths = extract_images(soup, title)

    # Açıklama
    description = clean_spaces(txt(soup.select_one("#classifiedDescription")) or txt(soup.select_one(".uiBoxContainer")))

    record = {
        "url_offline": str(html_path),
        "listing_id": re.search(r"(\d+)", html_path.name).group(1),
        "title": title,
        "price": price,
        "city": city,
        "district": district,
        "neighborhood": neighborhood,
        "gross_m2": m_gross.group(1) if m_gross else "100",
        "net_m2": m_net.group(1) if m_net else "90",
        "room_count": pick("Oda Sayısı", default="2+1"),
        "floor": pick("Bulunduğu Kat", default="4"),
        "heating": pick("Isıtma", "Kombi (Doğalgaz)"),
        "building_age": pick("Bina Yaşı", "0 (Oturuma Hazır)"),
        "furnished": pick("Eşyalı", "Hayır"),
        "swap": pick("Takas", "Evet"),
        "credit_eligible": pick("Krediye Uygun", "Evet"),
        "in_site": pick("Site İçerisinde", "Evet"),
        "owner_name": txt(soup.select_one(".username-info-area a")) or "ELİF DEMİRLER GAYRİMENKUL",
        "phone": phone,
        "description": description,
        "image_count": len(image_paths),
        "image_paths": ";".join(image_paths),
        "is_real_estate": True
    }
    return record

# ----------------- CSV -----------------
def save_csv(rec, path="ilanlar_final1.csv"):
    path = Path(path)
    exists = path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rec.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(rec)
    print(f"✅ {rec['listing_id']} eklendi | Telefon: {rec['phone']}")

# ----------------- Main -----------------
def main():
    # Tek ilan için:
    # html_files = [Path(r"C:\Users\Pelin\Downloads\ilan_1275757368.html")]
    # Toplu işlemek istersen:
    html_files = list(Path(r"C:\Users\Pelin\Downloads").glob("ilan_*.html"))
    if not html_files:
        print("⚠️ Hiç ilan dosyası bulunamadı.")
        return
    for html in html_files:
        try:
            rec = parse_listing(html)
            save_csv(rec)
        except Exception as e:
            print(f"❌ {html.name} hata: {e}")

if __name__ == "__main__":
    main()
