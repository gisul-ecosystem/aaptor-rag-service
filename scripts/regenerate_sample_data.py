"""
Regenerate sample data for all SQL schemas with improved value generation.
Fixes:
- service/product names use domain-appropriate values
- boolean columns use True/False
- duration/minutes columns use realistic values
- game titles use game-like names
- menu categories use food categories
- is_available uses boolean
"""
import json, random, requests
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

RAG_URL = "http://103.99.38.144:7003"
ADMIN_KEY = "adm_7DO6mYfMDUvUayUCfx-jGlwUWnzH5PVXtnAwYEMTS9IhhCwg"
ROWS_PER_TABLE = 100

# ── Domain-aware value pools ──────────────────────────────────────────────────
STATUSES         = ["active", "inactive", "pending", "completed", "cancelled", "approved", "rejected", "processing"]
PAYMENT_STATUSES = ["paid", "unpaid", "overdue", "refunded", "partial", "pending"]
ORDER_STATUSES   = ["placed", "confirmed", "shipped", "delivered", "cancelled", "returned", "processing", "completed"]
PRIORITIES       = ["low", "medium", "high", "critical", "urgent"]
GENDERS          = ["male", "female", "other"]
BLOOD_GROUPS     = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
DEPARTMENTS      = ["Engineering", "Marketing", "Sales", "HR", "Finance", "Operations", "Legal", "IT", "Product", "Design", "Support", "Research"]
JOB_TITLES       = ["Manager", "Director", "Engineer", "Analyst", "Coordinator", "Specialist", "Lead", "Associate", "Consultant", "Developer", "Architect", "VP"]
PRODUCT_CATEGORIES = ["Electronics", "Clothing", "Food", "Books", "Sports", "Home", "Beauty", "Toys", "Automotive", "Health", "Garden", "Office"]
FOOD_CATEGORIES  = ["Appetizer", "Main Course", "Dessert", "Beverage", "Salad", "Soup", "Snack", "Breakfast", "Lunch", "Dinner", "Side Dish", "Special"]
SPECIALIZATIONS  = ["Cardiology", "Neurology", "Orthopedics", "Pediatrics", "Oncology", "Dermatology", "Psychiatry", "Radiology", "Surgery", "Internal Medicine"]
TRANSACTION_TYPES = ["debit", "credit", "transfer", "payment", "refund", "withdrawal", "deposit"]
ACCOUNT_TYPES    = ["savings", "checking", "investment", "loan", "credit", "business"]
COURSE_TYPES     = ["lecture", "lab", "seminar", "workshop", "online", "hybrid"]
GRADES           = ["A", "B", "C", "D", "F", "A+", "B+", "C+"]
LANGUAGES        = ["English", "Spanish", "French", "German", "Chinese", "Japanese", "Arabic", "Portuguese", "Russian", "Hindi"]
COUNTRIES_LIST   = ["USA", "UK", "Canada", "Australia", "Germany", "France", "India", "Japan", "Brazil", "China", "Italy", "Spain", "Mexico", "Netherlands", "Sweden"]
CITIES_LIST      = ["New York", "London", "Paris", "Tokyo", "Sydney", "Berlin", "Toronto", "Dubai", "Singapore", "Mumbai", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia"]
COMPANY_SUFFIXES = ["Inc", "LLC", "Corp", "Ltd", "Group", "Solutions", "Technologies", "Services", "Systems", "Enterprises"]

# Service/product names by domain
SERVICE_NAMES    = ["Hotel Booking", "Car Rental", "Tour Package", "Flight Booking", "Travel Insurance", "Airport Transfer", "Cruise Package", "Visa Service", "Travel Guide", "Accommodation"]
GAME_TITLES      = ["Dragon Quest", "Space Warriors", "City Builder", "Racing Pro", "Battle Arena", "Puzzle Master", "Adventure Land", "Sports Champion", "Strategy Wars", "Fantasy World"]
GAME_GENRES      = ["Action", "RPG", "Strategy", "Sports", "Puzzle", "Adventure", "Simulation", "Racing", "Fighting", "Horror"]
MENU_ITEMS       = ["Grilled Chicken", "Caesar Salad", "Beef Burger", "Pasta Carbonara", "Fish Tacos", "Veggie Pizza", "Chocolate Cake", "Lemonade", "Steak", "Sushi Roll"]
PROPERTY_TYPES   = ["apartment", "house", "condo", "villa", "studio", "townhouse", "penthouse", "cottage"]
VEHICLE_TYPES    = ["sedan", "SUV", "truck", "van", "motorcycle", "bus", "bicycle", "scooter"]
BLOOD_TYPES      = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
DIAGNOSIS_CODES  = ["ICD-001", "ICD-002", "ICD-003", "ICD-004", "ICD-005", "ICD-006", "ICD-007", "ICD-008"]
SKILL_LEVELS     = ["beginner", "intermediate", "advanced", "expert", "master"]
SUBSCRIPTION_TYPES = ["free", "basic", "premium", "enterprise", "trial"]
DELIVERY_STATUSES = ["pending", "picked_up", "in_transit", "delivered", "failed", "returned"]
BOOKING_STATUSES = ["confirmed", "pending", "cancelled", "completed", "no_show"]
PAYMENT_METHODS  = ["credit_card", "debit_card", "paypal", "bank_transfer", "cash", "crypto"]
RATING_VALUES    = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]


def generate_value(col_name: str, col_type: str, row_idx: int, table_name: str = "",
                   parent_ids: dict = None) -> any:
    name = col_name.lower().strip()
    ctype = col_type.upper().split("(")[0].strip()
    parent_ids = parent_ids or {}

    # ── Primary key ──────────────────────────────────────────────────────────
    pk_patterns = [
        f"{table_name.lower()}_id", f"{table_name.lower()}id", "id",
        "aid", "bid", "cid", "did", "eid", "fid", "gid", "oid", "pid", "rid", "sid", "tid", "uid",
        "stuid", "empid", "custid", "prodid",
    ]
    if name in pk_patterns:
        return row_idx + 1

    # ── Foreign key ───────────────────────────────────────────────────────────
    if name.endswith("_id") and name not in pk_patterns:
        ref = name[:-3]
        for candidate in [ref + "s", ref, ref + "es"]:
            if candidate in parent_ids and parent_ids[candidate]:
                return random.choice(parent_ids[candidate])
        return (row_idx % 20) + 1

    # ── Boolean fields ────────────────────────────────────────────────────────
    if ctype in ("BOOLEAN", "BOOL") or name.startswith("is_") or name.startswith("has_"):
        return row_idx % 2 == 0

    # ── Name fields — context-aware ───────────────────────────────────────────
    if name in ("first_name", "fname", "given_name"):
        return fake.first_name()
    if name in ("last_name", "lname", "surname", "family_name"):
        return fake.last_name()
    if name in ("full_name", "customer_name", "employee_name", "user_name",
                "patient_name", "student_name", "teacher_name", "doctor_name",
                "author_name", "player_name", "driver_name", "agent_name"):
        return fake.name()
    if name == "name" and table_name.lower() in ("customers", "users", "employees",
                                                   "patients", "students", "teachers",
                                                   "doctors", "drivers", "agents",
                                                   "authors", "players", "members"):
        return fake.name()
    if name == "name" and table_name.lower() in ("services", "service"):
        return SERVICE_NAMES[row_idx % len(SERVICE_NAMES)]
    if name == "name" and table_name.lower() in ("games", "game"):
        return GAME_TITLES[row_idx % len(GAME_TITLES)]
    if name == "name" and table_name.lower() in ("menu_items", "menu", "dishes", "food_items"):
        return MENU_ITEMS[row_idx % len(MENU_ITEMS)]
    if name == "name" and table_name.lower() in ("products", "product", "items", "item"):
        return f"Product {row_idx + 1}"
    if name == "name" and table_name.lower() in ("departments", "department"):
        return DEPARTMENTS[row_idx % len(DEPARTMENTS)]
    if name == "name" and table_name.lower() in ("categories", "category"):
        return PRODUCT_CATEGORIES[row_idx % len(PRODUCT_CATEGORIES)]
    if name == "name":
        return f"{table_name.replace('_', ' ').title()} {row_idx + 1}"

    # ── Title fields ──────────────────────────────────────────────────────────
    if name == "title" and table_name.lower() in ("games", "game"):
        return GAME_TITLES[row_idx % len(GAME_TITLES)]
    if name == "title" and table_name.lower() in ("films", "film", "movies", "movie"):
        return f"Film {row_idx + 1}"
    if name == "title" and table_name.lower() in ("books", "book"):
        return f"Book Title {row_idx + 1}"
    if name == "title" and ctype in ("VARCHAR", "TEXT"):
        return f"{table_name.replace('_', ' ').title()} {row_idx + 1}"

    # ── Company ───────────────────────────────────────────────────────────────
    if "company" in name or "organization" in name or "employer" in name:
        return f"{fake.last_name()} {random.choice(COMPANY_SUFFIXES)}"
    if "username" in name or "login" in name or "user_name" in name:
        return fake.user_name() + str(row_idx)

    # ── Contact ───────────────────────────────────────────────────────────────
    if "email" in name:
        return f"user{row_idx + 1}@{fake.domain_name()}"
    if "phone" in name or "mobile" in name or "fax" in name:
        return f"+1-555-{1000 + row_idx:04d}"
    if "website" in name or "url" in name:
        return f"https://www.{fake.domain_name()}"

    # ── Location ──────────────────────────────────────────────────────────────
    if name in ("address", "street", "street_address", "address1", "address2"):
        return fake.street_address()
    if "district" in name or "neighborhood" in name:
        return f"District {(row_idx % 10) + 1}"
    if name in ("city", "town", "municipality"):
        return CITIES_LIST[row_idx % len(CITIES_LIST)]
    if name in ("country", "nation", "country_name"):
        return COUNTRIES_LIST[row_idx % len(COUNTRIES_LIST)]
    if name in ("state", "province", "region"):
        return fake.state()
    if "zip" in name or "postal" in name:
        return f"{10001 + row_idx}"
    if "latitude" in name or name == "lat":
        return round(random.uniform(-90, 90), 6)
    if "longitude" in name or name in ("lng", "lon"):
        return round(random.uniform(-180, 180), 6)
    if "origin" in name or "source" in name:
        return f"Origin {(row_idx % 20) + 1}"
    if "destination" in name:
        return f"Destination {(row_idx % 20) + 1}"

    # ── Category fields — domain-aware ────────────────────────────────────────
    if name == "category" and table_name.lower() in ("menu_items", "menu", "dishes", "food_items", "recipes"):
        return FOOD_CATEGORIES[row_idx % len(FOOD_CATEGORIES)]
    if name == "category" and table_name.lower() in ("services", "service"):
        return SERVICE_NAMES[row_idx % len(SERVICE_NAMES)]
    if "category" in name and "id" not in name:
        return PRODUCT_CATEGORIES[row_idx % len(PRODUCT_CATEGORIES)]

    # ── Genre ─────────────────────────────────────────────────────────────────
    if "genre" in name:
        return GAME_GENRES[row_idx % len(GAME_GENRES)]

    # ── Status / type fields ──────────────────────────────────────────────────
    if name in ("status", "current_status"):
        if table_name.lower() in ("orders", "order"):
            return ORDER_STATUSES[row_idx % len(ORDER_STATUSES)]
        if table_name.lower() in ("payments", "payment"):
            return PAYMENT_STATUSES[row_idx % len(PAYMENT_STATUSES)]
        if table_name.lower() in ("bookings", "booking", "reservations"):
            return BOOKING_STATUSES[row_idx % len(BOOKING_STATUSES)]
        if table_name.lower() in ("deliveries", "delivery", "shipments", "shipment"):
            return DELIVERY_STATUSES[row_idx % len(DELIVERY_STATUSES)]
        return STATUSES[row_idx % len(STATUSES)]
    if "payment_status" in name:
        return PAYMENT_STATUSES[row_idx % len(PAYMENT_STATUSES)]
    if "order_status" in name:
        return ORDER_STATUSES[row_idx % len(ORDER_STATUSES)]
    if "booking_status" in name or "reservation_status" in name:
        return BOOKING_STATUSES[row_idx % len(BOOKING_STATUSES)]
    if "delivery_status" in name or "shipment_status" in name:
        return DELIVERY_STATUSES[row_idx % len(DELIVERY_STATUSES)]
    if "priority" in name:
        return PRIORITIES[row_idx % len(PRIORITIES)]
    if "gender" in name or "sex" in name:
        return GENDERS[row_idx % len(GENDERS)]
    if "blood" in name:
        return BLOOD_GROUPS[row_idx % len(BLOOD_GROUPS)]
    if "department" in name or "dept" in name:
        return DEPARTMENTS[row_idx % len(DEPARTMENTS)]
    if "job_title" in name or "position" in name or "role" in name:
        return JOB_TITLES[row_idx % len(JOB_TITLES)]
    if name == "title" and ctype in ("VARCHAR", "TEXT"):
        return JOB_TITLES[row_idx % len(JOB_TITLES)]
    if "account_type" in name:
        return ACCOUNT_TYPES[row_idx % len(ACCOUNT_TYPES)]
    if "transaction_type" in name or "type" in name and "transaction" in table_name.lower():
        return TRANSACTION_TYPES[row_idx % len(TRANSACTION_TYPES)]
    if "type" in name and ctype in ("VARCHAR", "TEXT", "CHAR"):
        if "vehicle" in name or "vehicle" in table_name.lower():
            return VEHICLE_TYPES[row_idx % len(VEHICLE_TYPES)]
        if "property" in name or "property" in table_name.lower():
            return PROPERTY_TYPES[row_idx % len(PROPERTY_TYPES)]
        return STATUSES[row_idx % len(STATUSES)]
    if "specialization" in name or "specialty" in name:
        return SPECIALIZATIONS[row_idx % len(SPECIALIZATIONS)]
    if "language" in name and "id" not in name:
        return LANGUAGES[row_idx % len(LANGUAGES)]
    if "grade" in name and ctype in ("VARCHAR", "TEXT", "CHAR"):
        return GRADES[row_idx % len(GRADES)]
    if "course_type" in name or "class_type" in name:
        return COURSE_TYPES[row_idx % len(COURSE_TYPES)]
    if "skill_level" in name or "level_name" in name:
        return SKILL_LEVELS[row_idx % len(SKILL_LEVELS)]
    if "subscription" in name and "id" not in name:
        return SUBSCRIPTION_TYPES[row_idx % len(SUBSCRIPTION_TYPES)]
    if "payment_method" in name:
        return PAYMENT_METHODS[row_idx % len(PAYMENT_METHODS)]

    # ── Numeric fields ────────────────────────────────────────────────────────
    if "grade_level" in name or "grade_year" in name or "year_level" in name:
        return (row_idx % 12) + 1
    if "age" in name:
        return 18 + (row_idx * 3 % 62)
    if "salary" in name or "wage" in name or "income" in name:
        return round(30000 + (row_idx * 2500) + random.uniform(0, 2000), 2)
    if "price" in name or "unit_price" in name or "price_per" in name:
        return round(5 + (row_idx % 50) * 12.5 + random.uniform(0, 10), 2)
    if "amount" in name or "total" in name or "balance" in name or "revenue" in name:
        return round(100 + (row_idx * 47.3) + random.uniform(0, 500), 2)
    if "cost" in name or "fee" in name or "charge" in name:
        return round(10 + (row_idx * 15.7) + random.uniform(0, 100), 2)
    if "discount" in name or "tax" in name:
        return round(random.uniform(0, 30), 2)
    if "rating" in name or "score" in name:
        return round(1 + (row_idx % 5) * 0.8 + random.uniform(0, 0.9), 1)
    if "rank" in name:
        return (row_idx % 100) + 1
    if "quantity" in name or "qty" in name or "stock" in name:
        return (row_idx * 7 % 200) + 1
    if "duration" in name or "minutes" in name or "hours" in name:
        return (row_idx % 12 + 1) * 30  # 30, 60, 90, ... 360
    if "count" in name or "num_" in name or "number_of" in name:
        return (row_idx * 3 % 50) + 1
    if "year" in name:
        return 2018 + (row_idx % 7)
    if "month" in name:
        return (row_idx % 12) + 1
    if "day" in name:
        return (row_idx % 28) + 1
    if "percentage" in name or "percent" in name:
        return round(random.uniform(0, 100), 2)
    if "weight" in name:
        return round(0.5 + (row_idx % 100) * 0.3, 2)
    if "height" in name:
        return round(150 + (row_idx % 50) * 0.5, 1)
    if "level" in name and ctype in ("INT", "INTEGER", "SMALLINT", "BIGINT"):
        return (row_idx % 100) + 1
    if "total_score" in name or "high_score" in name:
        return round(100 + row_idx * 50.5 + random.uniform(0, 100), 2)

    # ── Date / time ───────────────────────────────────────────────────────────
    if ctype in ("DATE", "DATETIME", "TIMESTAMP") or "date" in name or "_at" in name:
        base = datetime(2022, 1, 1)
        delta = timedelta(days=row_idx * 3 + random.randint(0, 10))
        return (base + delta).strftime("%Y-%m-%d")
    if "time" in name and "id" not in name:
        base = datetime(2022, 1, 1)
        delta = timedelta(days=row_idx * 3 + random.randint(0, 10))
        return (base + delta).strftime("%Y-%m-%d")

    # ── Text / description ────────────────────────────────────────────────────
    if "description" in name or "notes" in name or "comment" in name or "remarks" in name:
        return f"Description for {table_name} {row_idx + 1}"
    if "code" in name:
        return f"{table_name[:3].upper()}{row_idx + 1:04d}"
    if "reference" in name or "ref_" in name:
        return f"REF-{row_idx + 1:06d}"
    if "tag" in name or "label" in name:
        return f"tag_{row_idx % 10}"
    if "color" in name or "colour" in name:
        return random.choice(["red", "blue", "green", "black", "white", "yellow"])
    if "size" in name:
        return random.choice(["XS", "S", "M", "L", "XL", "XXL"])
    if "bio" in name or "about" in name or "summary" in name:
        return f"Bio {row_idx + 1}"

    # ── Type-based fallback ───────────────────────────────────────────────────
    if ctype in ("INT", "INTEGER", "SMALLINT", "BIGINT", "TINYINT"):
        return row_idx + 1
    if ctype in ("FLOAT", "REAL", "DOUBLE", "DECIMAL", "NUMERIC"):
        return round(random.uniform(1, 1000), 2)
    if ctype in ("VARCHAR", "TEXT", "CHAR", "NVARCHAR", "NTEXT"):
        return f"{col_name.replace('_', ' ').title()} {row_idx + 1}"
    if ctype in ("DATE", "DATETIME", "TIMESTAMP"):
        base = datetime(2022, 1, 1)
        return (base + timedelta(days=row_idx * 3)).strftime("%Y-%m-%d")
    if ctype in ("BOOLEAN", "BOOL"):
        return row_idx % 2 == 0

    return f"{col_name}_{row_idx + 1}"


def _topological_sort(tables: dict, relationships: list) -> list:
    referenced = set()
    for rel in relationships:
        referenced.add(rel.get("to_table", ""))
    order = [t for t in tables if t in referenced] + [t for t in tables if t not in referenced]
    seen = set()
    result = []
    for t in order:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def generate_sample_data(schema: dict, rows_per_table: int = ROWS_PER_TABLE) -> dict:
    tables = schema["tables"]
    relationships = schema.get("relationships", [])
    table_order = _topological_sort(tables, relationships)
    generated_ids = {}
    sample_data = {}

    for tname in table_order:
        if tname not in tables:
            continue
        tdef = tables[tname]
        columns = tdef.get("columns", [])
        rows = []
        for row_idx in range(rows_per_table):
            row = {}
            for col in columns:
                col_name = col.get("name", "")
                col_type = col.get("type", "TEXT")
                if not col_name:
                    continue
                val = generate_value(col_name, col_type, row_idx, tname, generated_ids)
                row[col_name] = val
            rows.append(row)
        sample_data[tname] = rows

        # Track PKs for FK resolution
        pk_col = f"{tname}_id"
        first_col = columns[0].get("name", "") if columns else ""
        pk_ids = [r.get(pk_col) or r.get("id") or r.get(first_col) for r in rows]
        pk_ids = [v for v in pk_ids if isinstance(v, int)]
        if pk_ids:
            generated_ids[tname] = pk_ids
            generated_ids[tname + "s"] = pk_ids
            generated_ids[tname + "es"] = pk_ids

    return sample_data


def fetch_all_schemas() -> list:
    """Fetch all schemas using the /list endpoint with pagination."""
    print("Fetching all schemas via list endpoint...")
    try:
        all_schemas = []
        limit = 500
        skip = 0
        while True:
            resp = requests.get(
                f"{RAG_URL}/api/v1/sql-schemas/list",
                params={
                    "limit": limit,
                    "skip": skip,
                    "fields": "schema_id,domain,tables,relationships,difficulty_levels,sql_categories,source,sample_data",
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            schemas = data.get("schemas", [])
            total = data.get("total", 0)
            print(f"  page skip={skip} returned {len(schemas)} schemas")

            if not schemas:
                break

            for schema in schemas:
                # Some legacy entries may not have a proper schema definition.
                if not schema.get("tables"):
                    continue
                all_schemas.append(schema)

            skip += limit
            if skip >= total:
                break

        print(f"Fetched {len(all_schemas)} full schemas (total available: {total})")
        return all_schemas
    except Exception as e:
        print(f"Failed to fetch schemas: {e}")
        return []


def upload_schemas(schemas: list) -> None:
    batch_size = 10
    for i in range(0, len(schemas), batch_size):
        batch = schemas[i:i + batch_size]
        resp = requests.post(
            f"{RAG_URL}/api/v1/import-sql-schemas",
            json={"schemas": batch},
            headers={"X-Admin-Api-Key": ADMIN_KEY},
            timeout=60
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"  Batch {i//batch_size + 1}: updated={result['updated']}, errors={len(result.get('errors', []))}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--schema-id", help="Process only this schema_id")
    parser.add_argument("--rows", type=int, default=ROWS_PER_TABLE)
    args = parser.parse_args()

    rows = args.rows
    print(f"Target: {rows} rows per table")

    schemas = fetch_all_schemas()
    if args.schema_id:
        schemas = [s for s in schemas if s.get("schema_id") == args.schema_id]
        if not schemas:
            print(f"Schema '{args.schema_id}' not found")
            exit()

    print(f"Processing {len(schemas)} schemas...")
    updated_schemas = []

    for i, schema in enumerate(schemas):
        sid = schema.get("schema_id", "unknown")
        try:
            new_sample_data = generate_sample_data(schema, rows_per_table=rows)
            total_rows = sum(len(v) for v in new_sample_data.values())

            if args.dry_run:
                print(f"  [{i+1}/{len(schemas)}] {sid}: {total_rows} rows (DRY RUN)")
                first_table = list(new_sample_data.keys())[0]
                print(f"    {first_table}[0]: {new_sample_data[first_table][0]}")
            else:
                print(f"  [{i+1}/{len(schemas)}] {sid}: {total_rows} rows")

            updated_schemas.append({
                "schema_id": sid,
                "sample_data": new_sample_data,
                **{k: v for k, v in schema.items()
                   if k not in ("sample_data", "_id", "schema_id", "created_at", "updated_at")}
            })
        except Exception as e:
            print(f"  [{i+1}/{len(schemas)}] ERROR {sid}: {e}")
            import traceback; traceback.print_exc()

    if not args.dry_run and updated_schemas:
        print(f"\nUploading {len(updated_schemas)} schemas...")
        upload_schemas(updated_schemas)
        print("Done!")
    elif args.dry_run:
        print(f"\nDry run complete. {len(updated_schemas)} schemas would be updated.")
