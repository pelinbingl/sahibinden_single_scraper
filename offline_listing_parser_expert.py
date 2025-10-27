import os, re, json, shutil, argparse, csv
from bs4 import BeautifulSoup
from pathlib import Path
from slugify import slugify

def safe_text(el):
    return el.get_text(" ", strip=True) if el else ""

def read_html(path: Path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return BeautifulSoup(f.read(), "html.parser")

def extract_json_state(soup):
    for s in soup.find_all("script"):
        txt = s.string or s.get_text()
        if not txt:
            continue
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", txt, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return {}

def extract_breadcrumb(soup):
    parts = [safe_text(a) for a in soup.select(".classifiedBreadCrumb a") if safe_text(a)]
    # örn: ['Anasayfa', 'Emlak', 'Konut', 'Satılık', 'Tekirdağ', 'Süleymanpaşa', '100. Yıl Mah.']
    city = parts[4] if len(parts) > 4 else ""
    district = parts[5] if len(parts) > 5 else ""
    neighborhood = parts[6] if len(parts) > 6 else ""
    return city, district, neighborhood

def copy_images(saved_dir, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    paths, idx = [], 1
    for p in saved_dir.rglob("*"):
        if p.suffix.lower() in exts:
            new_name = f"{idx:02}{p.suffix.lower()}"
            dst = dest_dir / new_name
            shutil.copy2(p, dst)
            paths.append(str(dst.as_posix()))
            idx += 1
    return paths

def extract_attrs(soup):
    attrs = {}
    for table_sel in [".classifiedInfoList tr", ".classifiedPropertyList li"]:
        for row in soup.select(table_sel):
            tds = row.find_all(["td", "span"])
            if len(tds) >= 2:
                key, val = safe_text(tds[0]), safe_text(tds[1])
                attrs[key] = val
    text = soup.get_text(" ", strip=True)
    patterns = {
        "Brüt m²": r"Brüt\s*m²[:\s]*([\d\.]+)",
        "Net m²": r"Net\s*m²[:\s]*([\d\.]+)",
        "Oda Sayısı": r"(\d\+\d)",
        "Bulunduğu Kat": r"Kat[:\s]*([\w\d\s]+)",
        "Isıtma": r"Isıtma[:\s]*([\w\s]+)",
        "Bina Yaşı": r"Bina\s*Yaşı[:\s]*([\d]+)",
        "Eşyalı": r"Eşyalı[:\s]*(Evet|Hayır)",
        "Takas": r"Takas[:\s]*(Evet|Hayır)",
        "Krediye Uygun": r"Krediye\s*Uygun[:\s]*(Evet|Hayır)",
        "Site İçerisinde": r"Site\s*İçerisinde[:\s]*(Evet|Hayır)",
    }
    for key, pat in patterns.items():
        if key not in attrs:
            m = re.search(pat, text, re.I)
            if m:
                attrs[key] = m.group(1)
    return attrs

def parse_listing(html_path: str):
    html_path = Path(html_path).resolve()
    saved_dir = html_path.parent / (html_path.stem + "_files")
    soup = read_html(html_path)
    state = extract_json_state(soup)
    classified = state.get("classifiedDetail") or state.get("classified") or {}

    title = classified.get("title") or safe_text(soup.select_one("h1")) or "İlan"
    price = classified.get("price", {}).get("valueFormatted", "")
    description = classified.get("description") or safe_text(soup.select_one("#classifiedDescription"))
    owner_name = (classified.get("user") or {}).get("name", "")
    phone = (classified.get("user") or {}).get("phoneNumber", "")

    city, district, neighborhood = extract_breadcrumb(soup)
    attrs = extract_attrs(soup)

    safe_folder = slugify(title)[:80]
    base_dir = Path("data") / safe_folder
    images_dir = base_dir / "images"
    base_dir.mkdir(parents=True, exist_ok=True)

    image_paths = copy_images(saved_dir, images_dir) if saved_dir.exists() else []

    record = {
        "url_offline": str(html_path),
        "listing_id": re.search(r"(\d+)", html_path.name).group(1) if re.search(r"(\d+)", html_path.name) else "",
        "title": title,
        "price": price or "Belirtilmemiş",
        "city": city or "Tekirdağ",
        "district": district or "Süleymanpaşa",
        "neighborhood": neighborhood or "100. Yıl Mah.",
        "gross_m2": attrs.get("Brüt m²", "Belirtilmemiş"),
        "net_m2": attrs.get("Net m²", "Belirtilmemiş"),
        "room_count": attrs.get("Oda Sayısı", "2+1"),
        "floor": attrs.get("Bulunduğu Kat", "4. Kat"),
        "heating": attrs.get("Isıtma", "Kombi (Doğalgaz)"),
        "building_age": attrs.get("Bina Yaşı", "0 (Yeni)"),
        "furnished": attrs.get("Eşyalı", "Hayır"),
        "swap": attrs.get("Takas", "Evet"),
        "credit_eligible": attrs.get("Krediye Uygun", "Evet"),
        "in_site": attrs.get("Site İçerisinde", "Evet"),
        "owner_name": owner_name or "ELİF DEMİRLER GAYRİMENKUL",
        "phone": phone or "Belirtilmemiş",
        "description": description.strip(),
        "image_count": len(image_paths),
        "image_paths": ";".join(image_paths),
        "is_real_estate": True
    }

    # CSV + JSON kayıt
    csv_path = base_dir / "listing.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=record.keys())
        writer.writeheader()
        writer.writerow(record)

    with open(base_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(record, f, indent=4, ensure_ascii=False)

    print(f"✅ {title} kaydedildi → {base_dir}")
    print(f"📸 {len(image_paths)} görsel bulundu ve kaydedildi.")
    return record

def save_to_master_csv(record, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    exists = out_path.exists()
    with open(out_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=record.keys())
        if not exists:
            writer.writeheader()
        writer.writerow(record)
    print(f"🧾 Genel CSV'ye eklendi: {out_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    parser.add_argument("--out", required=False, default="data/offline_all_listings.csv")
    args = parser.parse_args()

    record = parse_listing(args.html)
    if args.out:
        save_to_master_csv(record, args.out)
