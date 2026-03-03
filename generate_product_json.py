import requests
import json
import time
import os
import re
from slugify import slugify

# -----------------------------
# CONFIG
# -----------------------------

DEFAULT_STOCK = 9999
SOURCE_NAME = "deodap"
OUTPUT_DIR = "normalized_output"

# -----------------------------
# SEO META BUILDERS
# -----------------------------

def build_meta_title(name, category=None):
    if category:
        return f"{name} | Best {category} Online"
    return f"{name} | Buy Online"


def build_meta_description(name):
    return (
        f"Buy {name}. High quality product for daily use. "
        f"Best price with fast delivery. Order online today."
    )

# -----------------------------
# HTML CLEANER
# -----------------------------

def remove_after_keywords(html: str) -> str:
    pattern = re.compile(
        r'(?:<strong>|\\u003Cstrong\\u003E)\s*(keywords|dimension)\s*:?-?\s*(?:</strong>|\\u003C/strong\\u003E)[\s\S]*$',
        re.IGNORECASE
    )
    return re.sub(pattern, '', html).strip()

# -----------------------------
# FETCH PRODUCTS
# -----------------------------

def fetch_all_products(base_url):
    products = []
    page_num = 1

    while True:
        url = f"{base_url}?page={page_num}"
        r = requests.get(url, timeout=20)
        r.raise_for_status()

        batch = r.json().get("products", [])
        if not batch:
            break

        products.extend(batch)
        page_num += 1
        time.sleep(0.3)

    return products


def fetch_collection_info(base_url):
    collection_url = base_url.replace("/products.json", ".json")
    r = requests.get(collection_url, timeout=20)
    r.raise_for_status()
    return r.json()["collection"]

# -----------------------------
# PRICE LOGIC
# -----------------------------

def get_markup(cost):
    if cost <= 100:
        return 2.5
    elif cost <= 300:
        return 2.0
    elif cost <= 700:
        return 1.7
    else:
        return 1.5


def round_price(v):
    return int(round(v / 10) * 10 - 1)


def calculate_retail(wholesale, mrp=None):
    retail = round_price(wholesale * get_markup(wholesale))
    if retail <= wholesale:
        retail = int(wholesale) + 1
    if mrp and retail > mrp:
        retail = int(mrp)
    return retail

# -----------------------------
# NORMALIZE PRODUCT
# -----------------------------

def normalize_product(p, category_title, category_slug):
    if not p.get("variants"):
        return None

    tags = p.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    raw_html = p.get("body_html") or ""
    clean_html = remove_after_keywords(raw_html)

    first_variant = p["variants"][0]
    wholesale = float(first_variant["price"])
    mrp = float(first_variant["compare_at_price"]) if first_variant.get("compare_at_price") else None

    main_price = calculate_retail(wholesale, mrp)

    product = {
        "externalId": p["id"],
        "name": p["title"],
        "description": clean_html,
        "price": main_price,
        "comparePrice": mrp,
        "sku": first_variant.get("sku"),
        "stock": first_variant.get("inventory_quantity", DEFAULT_STOCK),
        "brand": p.get("vendor"),
        "slug": slugify(p.get("handle") or p["title"]),
        "source": SOURCE_NAME,
        "metaTitle": build_meta_title(p["title"], category_title),
        "metaDescription": build_meta_description(p["title"]),
        "tags": tags,
        "category": [category_title],
        "categoryName": [category_slug],
        "images": [i["src"] for i in p.get("images", [])],
        "weight": round((first_variant.get("grams") or 0) / 1000, 3),
        "isDigital": False,
        "trackInventory": True,
        "isFeatured": False,
        "variants": [],
        "attributes": {}
    }

    sizes, colors, materials = set(), set(), set()

    for v in p["variants"]:
        wholesale = float(v["price"])
        mrp = float(v["compare_at_price"]) if v.get("compare_at_price") else None

        price = calculate_retail(wholesale, mrp)

        variant = {
            "id": v["id"],
            "name": v["title"],
            "sku": v.get("sku"),
            "price": price,
            "comparePrice": mrp,
            "available": v.get("available", True),
            "stock": v.get("inventory_quantity", DEFAULT_STOCK),
            "size": v.get("option1"),
            "color": v.get("option2"),
            "material": v.get("option3")
        }

        if variant["size"]:
            sizes.add(variant["size"])
        if variant["color"]:
            colors.add(variant["color"])
        if variant["material"]:
            materials.add(variant["material"])

        product["variants"].append(variant)

    if sizes:
        product["attributes"]["size"] = list(sizes)
    if colors:
        product["attributes"]["color"] = list(colors)
    if materials:
        product["attributes"]["material"] = list(materials)

    return product

# -----------------------------
# MAIN
# -----------------------------

def main():

    # Create output folder
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Read collection URLs
    with open("collections.txt", "r") as f:
        collection_urls = [line.strip() for line in f if line.strip()]

    for base_url in collection_urls:
        print(f"\nProcessing: {base_url}")

        collection = fetch_collection_info(base_url)
        category_title = collection["title"]
        category_slug = collection["handle"]

        raw_products = fetch_all_products(base_url)
        print(f"Loaded {len(raw_products)} products")

        normalized = []

        for p in raw_products:
            product = normalize_product(p, category_title, category_slug)
            if product:
                normalized.append(product)

        safe_category = slugify(category_title)
        output_file = os.path.join(OUTPUT_DIR, f"{safe_category}_products.json")

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)

        print(f"✅ Saved {len(normalized)} products to {output_file}")

    print("\nAll collections processed successfully.")


if __name__ == "__main__":
    main()