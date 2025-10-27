# offline_listing_parser.py
import os, re, json, shutil, argparse
import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path
from slugify import slugify

# ---- Yardımcılar ----
def read_html(html_path: Path) -> BeautifulSoup:
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        return BeautifulSoup(f.read(), "html.parser")

def safe_text(el):
    return el.get_text(" ", strip=True) if el else ""

def clean_price(txt: str) -> str:
    if not txt:
        return ""
    m = re.search(r"(\d[\d\.\s,]*\d)\s*TL", txt, flags=re.I)
    return (m.group(1).replace(" ", "").replace(",", ".") + " TL") if m else txt.strip()

def extract_listing_id_from_filename(html_path: Path) -> str:
    m = re.search(r"-(\d+)", html_path.name)
    return m.group(1) if m else ""

def parse_location_from_h2(h2_text: str):
    # Örn: "Tekirdağ / Süleymanpaşa / 100. Yıl Mh."
    parts = [p.strip() for p in h2_text.split("/") if p.strip()]
    city = parts[0] if len(parts) > 0 else ""
    district = parts[1] if len(parts) > 1 else ""
    neighborhood = parts[2] if len(parts) > 2 else ""
    return city, district, neighborhood

def extract_json_state(soup: BeautifulSoup):
    # Bazı sayfalarda inline JS içinde JSON bulunur
    for script in soup.find_all("script"):
        txt = script.string or script.get_text()
        if not txt:
            continue
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", txt, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return {}

def copy_images_from_saved_folder(saved_files_dir: Path, dest_images_dir: Path, title: str) -> list:
    """
    Chrome'un kaydettiği klasördeki görsel dosyalarını tespit edip /data/images altına kopyalar.
    """
    dest_images_dir.mkdir(parents=True, exist_ok=True)
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    copied = []
    idx = 1
    for p in saved_files_dir.rglob("*"):
        if p.suffix.lower() in image_exts and p.is_file():
            new_name = f"{slugify(title)[:60]}_{idx:02}{p.suffix.lower()}"
            dst = dest_images_dir / new_name
            try:
                shutil.copy2(p, dst)
                copied.append(str(dst.as_posix()))
                idx += 1
            except Exception:
                continue
    # yinelenen küçük ikonlar/placeholder’lar olabilir; benzersizlik için set+liste
    uniq = []
    seen = set()
    for path in copied:
        if path not in seen:
            uniq.append(path)
            seen.add(path)
    return uniq

# ---- Ana işlev ----
def parse_offline_listing(html_path: str, output_csv: str):
    html_path = Path(html_path).resolve()
    saved_dir_guess = html_path.parent / (html_path.stem + "_files")  # Chrome'un yan klasörü
    soup = read_html(html_path)

    # JSON varsa al (en güvenilir)
    state = extract_json_state(soup)
    classified = state.get("classifiedDetail") or state.get("classified") or {}

    # Başlık
    title = classified.get("title") or safe_text(soup.select_one("h1"))

    # Fiyat
    price = classified.get("price", {}).get("valueFormatted") or ""
    if not price:
        price = clean_price(safe_text(soup.select_one(".classifiedDetailPrice")))

    # Konum
    city = (classified.get("city") or {}).get("name", "")
    district = (classified.get("town") or {}).get("name", "")
    neighborhood = (classified.get("quarter") or {}).get("name", "")
    if not city:
        city_h2 = safe_text(soup.select_one(".classifiedInfo h2"))
        c, d, n = parse_location_from_h2(city_h2)
        city = city or c
        district = district or d
        neighborhood = neighborhood or n

    # Açıklama
    description = classified.get("description") or safe_text(soup.select_one("#classifiedDescription"))

    # İlan sahibi ve telefon (telefon offline sayfada genelde yok; JSON varsa gelir)
    owner_name = (classified.get("user") or {}).get("name", "") or safe_text(soup.select_one(".userInfo .username"))
    phone = (classified.get("user") or {}).get("phoneNumber", "")

    # Özellikler (tablo)
    attributes = {}
    for tr in soup.select(".classifiedInfoList tr"):
        tds = tr.find_all("td")
        if len(tds) == 2:
            key = safe_text(tds[0])
            val = safe_text(tds[1])
            attributes[key] = val

    # Sık kullanılan sütun eşleştirmeleri
    record = {
        "url_offline": html_path.as_posix(),
        "listing_id": extract_listing_id_from_filename(html_path),
        "title": title,
        "price": price,
        "city": city,
        "district": district,
        "neighborhood": neighborhood,
        "gross_m2": attributes.get("Brüt m²", ""),
        "net_m2": attributes.get("Net m²", ""),
        "room_count": attributes.get("Oda Sayısı", ""),
        "floor": attributes.get("Bulunduğu Kat", ""),
        "heating": attributes.get("Isıtma", ""),
        "building_age": attributes.get("Bina Yaşı", ""),
        "furnished": attributes.get("Eşyalı", ""),
        "swap": attributes.get("Takas", ""),
        "credit_eligible": attributes.get("Krediye Uygun", ""),
        "in_site": attributes.get("Site İçerisinde", ""),
        "owner_name": owner_name,
        "phone": phone,
        "description": description,
    }

    # Görselleri kopyala (offline klasörden)
    dest_images_dir = Path("data/images")
    image_paths = []
    if saved_dir_guess.exists():
        image_paths = copy_images_from_saved_folder(saved_dir_guess, dest_images_dir, title)
    record["image_count"] = len(image_paths)
    record["image_paths"] = ";".join(image_paths)
    record["is_real_estate"] = True

    # CSV yaz
    Path("data").mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([record])
    if os.path.exists(output_csv):
        old = pd.read_csv(output_csv)
        df = pd.concat([old, df], ignore_index=True, sort=False)
    df.to_csv(output_csv, index=False, encoding="utf-8")
    print(f"✅ Kaydedildi: {output_csv}")
    print(f"📸 Görsel sayısı: {len(image_paths)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, help="Chrome'dan 'Web sayfası, tamamı' olarak kaydedilmiş ilan HTML dosyası")
    parser.add_argument("--out", default="data/offline_single_listing.csv", help="Çıkış CSV yolu")
    args = parser.parse_args()
    parse_offline_listing(args.html, args.out)
