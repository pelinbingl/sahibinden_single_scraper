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
    txt = soup.get_text(" ", strip=True)
    patterns = {
        "Brüt m²": r"Brüt\s*m²[:\s]*([\d\.]+)",
        "Net m²": r"Net\s*m²[:\s]*([\d\.]+)",
        "Oda Sayısı": r"Oda\s*Sayısı[:\s]*([\d\+\-]+)",
        "Bulunduğu Kat": r"Kat[:\s]*([\w\d]+)",
        "Isıtma": r"Isıtma[:\s]*([\w\s]+)",
        "Bina Yaşı": r"Bina\s*Yaşı[:\s]*([\d]+)",
    }
    for key, pat in patterns.items():
        if key not in attrs:
            m = re.search(pat, txt)
            if m:
                attrs[key] = m.group(1)
    return attrs

def parse_offline_listing(html_path: str):
    html_path = Path(html_path).resolve()
    saved_dir = html_path.parent / (html_path.stem + "_files")
    soup = read_html(html_path)
    state = extract_json_state(soup)
    classified = state.get("classifiedDetail") or state.get("classified") or {}

    title = classified.get("title") or safe_text(soup.select_one("h1")) or "ilan"
    city = (classified.get("city") or {}).get("name", "")
    district = (classified.get("town") or {}).get("name", "")
    neighborhood = (classified.get("quarter") or {}).get("name", "")
    price = classified.get("price", {}).get("valueFormatted", "")
    description = classified.get("description") or safe_text(soup.select_one("#classifiedDescription"))
    owner_name = (classified.get("user") or {}).get("name", "")
    phone = (classified.get("user") or {}).get("phoneNumber", "")

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
        "price": price,
        "city": city,
        "district": district,
        "neighborhood": neighborhood,
        "gross_m2": attrs.get("Brüt m²", ""),
        "net_m2": attrs.get("Net m²", ""),
        "room_count": attrs.get("Oda Sayısı", ""),
        "floor": attrs.get("Bulunduğu Kat", ""),
        "heating": attrs.get("Isıtma", ""),
        "building_age": attrs.get("Bina Yaşı", ""),
        "furnished": attrs.get("Eşyalı", ""),
        "swap": attrs.get("Takas", ""),
        "credit_eligible": attrs.get("Krediye Uygun", ""),
        "in_site": attrs.get("Site İçerisinde", ""),
        "owner_name": owner_name,
        "phone": phone,
        "description": description,
        "image_count": len(image_paths),
        "image_paths": ";".join(image_paths),
        "is_real_estate": True
    }

    csv_path = base_dir / "listing.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=record.keys())
        writer.writeheader()
        writer.writerow(record)

    with open(base_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(record, f, indent=4, ensure_ascii=False)

    print(f"✅ '{title}' kaydedildi → {base_dir}")
    print(f"📸 {len(image_paths)} görsel kaydedildi.")
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
    print(f"🧾 Kayıt eklendi: {out_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    parser.add_argument("--out", required=False, default="data/offline_all_listings.csv")
    args = parser.parse_args()

    record = parse_offline_listing(args.html)
    if args.out:
        save_to_master_csv(record, args.out)
