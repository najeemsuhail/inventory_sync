import os
import json
import asyncio
from playwright.async_api import async_playwright

# -----------------------------
# CONFIG
# -----------------------------

INPUT_DIR = "normalized_output"
OUTPUT_SQL_FILE = "inventory_full_sync.sql"
CONCURRENT_REQUESTS = 10

WUKUSY_EMAIL = "suhail.najeem@gmail.com" # os.getenv("WUKUSY_EMAIL")
WUKUSY_PASSWORD = "Wukusy@3083" # os.getenv("WUKUSY_PASSWORD")


# -----------------------------
# LOAD SKUS
# -----------------------------

def load_all_skus():
    sku_set = set()

    for file in os.listdir(INPUT_DIR):
        if file.endswith(".json"):
            path = os.path.join(INPUT_DIR, file)

            with open(path, "r", encoding="utf-8") as f:
                products = json.load(f)

                for p in products:
                    if p.get("sku"):
                        sku_set.add(p["sku"])

    return list(sku_set)

# -----------------------------
# CHECK SKU INSIDE BROWSER
# -----------------------------

async def check_sku(page, sku):
    try:
        result = await page.evaluate(
            """async (sku) => {
                const response = await fetch(`/dropshiper/searchApi?q=${sku}`, {
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });
                const text = await response.text();
                return text.includes("search-result-item");
            }""",
            sku
        )
        return sku, result
    except:
        return sku, False

# -----------------------------
# PROCESS SKUS IN BATCHES
# -----------------------------

async def process_skus(page, sku_list):
    activate = []
    deactivate = []

    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

    async def bounded_check(sku):
        async with semaphore:
            return await check_sku(page, sku)

    tasks = [bounded_check(sku) for sku in sku_list]

    for coro in asyncio.as_completed(tasks):
        sku, exists = await coro
        if exists:
            activate.append(sku)
        else:
            deactivate.append(sku)

    return activate, deactivate

# -----------------------------
# GENERATE SQL
# -----------------------------

def generate_sql(activate, deactivate):
    with open(OUTPUT_SQL_FILE, "w", encoding="utf-8") as f:

        f.write("-- FULL INVENTORY SYNC\n\n")

        if activate:
            f.write("-- ACTIVATE AVAILABLE SKUS\n")
            f.write('UPDATE "Product"\n')
            f.write('SET "isActive" = true\n')
            f.write('WHERE sku IN (\n')

            for i, sku in enumerate(activate):
                comma = "," if i < len(activate) - 1 else ""
                f.write(f"'{sku}'{comma}\n")

            f.write(");\n\n")

        if deactivate:
            f.write("-- DEACTIVATE MISSING SKUS\n")
            f.write('UPDATE "Product"\n')
            f.write('SET "isActive" = false\n')
            f.write('WHERE sku IN (\n')

            for i, sku in enumerate(deactivate):
                comma = "," if i < len(deactivate) - 1 else ""
                f.write(f"'{sku}'{comma}\n")

            f.write(");\n")

    print(f"✅ SQL file generated: {OUTPUT_SQL_FILE}")

# -----------------------------
# MAIN
# -----------------------------

async def main():

    if not os.path.exists(INPUT_DIR):
        print("❌ normalized_output folder not found.")
        return

    sku_list = load_all_skus()

    if not sku_list:
        print("❌ No SKUs found.")
        return

    print(f"Checking {len(sku_list)} SKUs...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Login
        print("🔐 Logging into Wukusy...")
        await page.goto("https://wukusy.app/login")
        await page.fill('input[type="email"]', WUKUSY_EMAIL)
        await page.fill('input[type="password"]', WUKUSY_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        print("✅ Logged in")

        # Move to search page once
        await page.goto("https://wukusy.app/dropshiper/find")
        await page.wait_for_load_state("networkidle")

        activate, deactivate = await process_skus(page, sku_list)

        await browser.close()

    print(f"Available: {len(activate)}")
    print(f"Not Found: {len(deactivate)}")

    generate_sql(activate, deactivate)

    print("🎯 Full sync SQL ready.")

# -----------------------------

if __name__ == "__main__":
    asyncio.run(main())