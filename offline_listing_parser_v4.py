import os, re, json, shutil, argparse, csv
import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path
from slugify import slugify

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
    parts = [p.strip() for p in h2_text.split("/") if p.strip()]
    city = parts[0] if len(parts) > 0 else ""
    district = parts[1] if len(parts) > 1 else ""
    neighborhood = parts[2] if len(parts) > 2 else ""
    return city, district, neighborhood

def extract_json_state(soup: BeautifulSoup):
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

def copy_images(saved_dir: Path, dest_images: Path, title: str) -> list:
    dest_images.mkdir(parents=True, exist_ok=True)
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    paths, idx = [], 1
    for p in saved_dir.rglob("*"):
        if p.suffix.lower() in exts:
            new_name = f"{slugify(title)[:50]}_{idx:02}{p.suffix.lower()}"
            dst = dest_images / new_name
            try:
                shutil.copy2(p, dst)
                paths.append(str(dst.as_posix()))
                idx += 1
            except: continue
    uniq = []
    seen = set()
    for path in paths:
        if path not in seen:
            uniq.append(path)
            seen.add(path)
    return uniq

def parse_offline_listing(html_path: str, output_csv: str):
    html_path = Path(html_path).resolve()
    saved_dir = html_path.parent / (html_path.stem + "_files")
    soup = read_html(html_path)
    state = extract_json_state(soup)
    classified = state.get("classifiedDetail") or state.get("classified") or {}

    title = classified.get("title") or safe_text(soup.select_one("h1"))
    price = classified.get("price", {}).get("valueFormatted") or ""
    if not price:
        price = clean_price(safe_text(soup.select_one(".classifiedDetailPrice")))

    city = (classified.get("city") or {}).get("name", "")
    district = (classified.get("town") or {}).get("name", "")
    neighborhood = (classified.get("quarter") or {}).get("name", "")
    if not city:
        c, d, n = parse_location_from_h2(safe_text(soup.select_one(".classifiedInfo h2")))
        city, district, neighborhood = city or c, district or d, neighborhood or n

    description = classified.get("description") or safe_text(soup.select_one("#classifiedDescription"))
    owner_name = (classified.get("user") or {}).get("name", "") or safe_text(soup.select_one(".userInfo .username"))
    phone = (classified.get("user") or {}).get("phoneNumber", "")

    attributes = {}
    for tr in soup.select(".classifiedInfoList tr"):
        tds = tr.find_all("td")
        if len(tds) == 2:
            key, val = safe_text(tds[0]), safe_text(tds[1])
            attributes[key] = val

    image_paths = []
    if saved_dir.exists():
        image_paths = copy_images(saved_dir, Path("data/images"), title)

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
        "image_count": len(image_paths),
        "image_paths": ";".join(image_paths),
        "is_real_estate": True
    }

    Path("data").mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=record.keys())
        writer.writeheader()
        writer.writerow(record)

    print(f"✅ CSV oluşturuldu: {output_csv}")
    print(f"📸 {len(image_paths)} görsel kaydedildi.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    parser.add_argument("--out", default="data/offline_single_listing_clean1.csv")
    args = parser.parse_args()
    parse_offline_listing(args.html, args.out)
