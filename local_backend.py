#!/usr/bin/env python3
"""Local-only CampusBite web server backed by SQLite."""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import posixpath
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("CAMPUSBITE_DATABASE", ROOT / "data" / "campusbite.sqlite3"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("CAMPUSBITE_PORT", "8765"))
SESSION_SECONDS = 60 * 60 * 12
MAX_BODY = 8 * 1024 * 1024
PBKDF2_ROUNDS = 310_000
DB_LOCK = threading.RLock()
SHOP_NAMES = {
    1: "New Canteen Shop 1",
    2: "New Canteen Shop 2",
    3: "New Canteen Shop 3",
    4: "New Canteen Shop 4",
    5: "Old Canteen Shop 1",
    6: "Old Canteen Shop 2",
    7: "Old Canteen Shop 3",
    8: "Old Canteen Shop 4",
}
SHOP_ACCOUNTS = {
    stall_id: f"{'new' if stall_id <= 4 else 'old'}shop{stall_id if stall_id <= 4 else stall_id - 4}"
    for stall_id in SHOP_NAMES
}


def seed_state() -> dict:
    menu_rows = [
        (1, "Masala Dosa", "South Indian", 65, "🥞", "Crispy dosa with potato masala and chutneys.", "hero-food-dosa.jpg", ""),
        (2, "Paneer Wrap", "Quick Bites", 90, "🌯", "Spiced paneer, crunchy vegetables and mint sauce.", "hero-food-wrap.jpg", "Student favourite"),
        (3, "Veg Fried Rice", "Meals", 110, "🍚", "Wok-tossed rice with vegetables and herbs.", "hero-food-rice.jpg", ""),
        (4, "Chicken Rice Bowl", "Meals", 145, "🍗", "Comforting rice bowl with savoury chicken.", "hero-food-rice.jpg", ""),
        (5, "Samosa Pair", "Quick Bites", 35, "🥟", "Golden, flaky samosas with tangy chutney.", "", "Combo deal"),
        (6, "Cold Coffee", "Drinks", 55, "🥤", "Chilled coffee for your study break.", "", ""),
        (7, "Fresh Lime Soda", "Drinks", 40, "🍋", "Refreshing lime with a fizzy finish.", "", ""),
        (8, "Idli & Sambar", "South Indian", 50, "🍘", "Soft idlis served with sambar and chutney.", "", ""),
        (9, "Brownie", "Desserts", 60, "🍫", "Rich chocolate brownie, baked fresh.", "", "Fresh today"),
        (101, "Ghee Pongal", "South Indian", 65, "🍚", "Soft rice and lentils finished with ghee, pepper and cashews.", "https://images.unsplash.com/photo-1601050690117-94f5f6fa8bd7?auto=format&fit=crop&w=900&q=80", "", 1),
        (102, "Poori Masala", "South Indian", 70, "🫓", "Two puffed pooris served with warm potato masala.", "https://images.unsplash.com/photo-1565557623262-b51c2513a641?auto=format&fit=crop&w=900&q=80", "", 1),
        (103, "Filter Coffee", "Drinks", 25, "☕", "Fresh South Indian filter coffee with frothy milk.", "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?auto=format&fit=crop&w=900&q=80", "", 1),
        (104, "Grilled Veg Sandwich", "Quick Bites", 65, "🥪", "Toasted bread layered with vegetables, cheese and green chutney.", "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=900&q=80", "", 2),
        (105, "Crispy Veg Puff", "Quick Bites", 25, "🥐", "Flaky bakery pastry filled with mildly spiced vegetables.", "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=900&q=80", "", 2),
        (106, "Masala French Fries", "Quick Bites", 55, "🍟", "Golden fries tossed with a light house masala seasoning.", "https://images.unsplash.com/photo-1573080496219-bb080dd4f877?auto=format&fit=crop&w=900&q=80", "", 2),
        (107, "Veg Hakka Noodles", "Meals", 100, "🍜", "Wok-tossed noodles with cabbage, carrot and spring onion.", "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?auto=format&fit=crop&w=900&q=80", "", 3),
        (108, "Gobi Manchurian", "Quick Bites", 90, "🥦", "Crisp cauliflower bites coated in a tangy Indo-Chinese sauce.", "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=900&q=80", "", 3),
        (109, "Schezwan Fried Rice", "Meals", 120, "🍛", "Spicy wok-fried rice with vegetables and house Schezwan sauce.", "https://images.unsplash.com/photo-1603133872878-684f208fb84b?auto=format&fit=crop&w=900&q=80", "", 3),
        (110, "Chicken Biryani", "Meals", 160, "🍗", "Aromatic basmati rice cooked with spiced chicken and herbs.", "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=900&q=80", "", 4),
        (111, "Chicken 65", "Quick Bites", 130, "🍗", "Crisp, chilli-seasoned chicken bites finished with curry leaves.", "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=900&q=80", "", 4),
        (112, "Egg Kothu Parotta", "Meals", 110, "🍳", "Chopped parotta tossed on the griddle with egg, onion and salna.", "https://images.unsplash.com/photo-1565557623262-b51c2513a641?auto=format&fit=crop&w=900&q=80", "", 4),
        (113, "Parotta with Salna", "South Indian", 60, "🫓", "Two flaky layered parottas served with warm, spiced salna.", "https://images.unsplash.com/photo-1565557623262-b51c2513a641?auto=format&fit=crop&w=900&q=80", "", 5),
        (114, "Egg Dosa", "South Indian", 75, "🍳", "Crisp dosa topped with egg, onion and a pinch of pepper.", "https://images.unsplash.com/photo-1668236543090-82eba5ee5976?auto=format&fit=crop&w=900&q=80", "", 5),
        (115, "Lemon Rice", "Meals", 55, "🍋", "Fluffy rice tempered with lemon, mustard seeds and peanuts.", "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=900&q=80", "", 5),
        (116, "Mango Lassi", "Drinks", 60, "🥭", "Chilled yoghurt blended with ripe mango.", "https://images.unsplash.com/photo-1550583724-b2692b85b150?auto=format&fit=crop&w=900&q=80", "", 6),
        (117, "Rose Milk", "Drinks", 40, "🥛", "Cold milk lightly flavoured with rose syrup.", "https://images.unsplash.com/photo-1550583724-b2692b85b150?auto=format&fit=crop&w=900&q=80", "", 6),
        (118, "Mint Lemon Cooler", "Drinks", 45, "🍋", "Fresh lime and mint served chilled for a refreshing break.", "https://images.unsplash.com/photo-1513558161293-cdaf765edfd7?auto=format&fit=crop&w=900&q=80", "", 6),
        (119, "Curd Rice", "Meals", 55, "🍚", "Cooling yoghurt rice finished with mustard, ginger and curry leaves.", "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=900&q=80", "", 7),
        (120, "South Indian Veg Meals", "Meals", 120, "🍛", "Rice with seasonal vegetable sides, sambar, rasam and curd.", "https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=900&q=80", "", 7),
        (121, "Chapati with Kurma", "Meals", 75, "🫓", "Two soft chapatis with creamy mixed-vegetable kurma.", "https://images.unsplash.com/photo-1565557623262-b51c2513a641?auto=format&fit=crop&w=900&q=80", "", 7),
        (122, "Paneer Kathi Roll", "Quick Bites", 95, "🌯", "Spiced paneer and crunchy vegetables wrapped in a soft flatbread.", "https://images.unsplash.com/photo-1626700051175-6818013e1d4f?auto=format&fit=crop&w=900&q=80", "", 8),
        (123, "Crispy Corn", "Quick Bites", 80, "🌽", "Crunchy sweet corn tossed with pepper, herbs and a little lime.", "https://images.unsplash.com/photo-1551754655-cd27e38d2076?auto=format&fit=crop&w=900&q=80", "", 8),
        (124, "Chocolate Milkshake", "Drinks", 70, "🥤", "Cold, creamy chocolate milkshake made for a quick campus break.", "https://images.unsplash.com/photo-1572490122747-3968b75cc699?auto=format&fit=crop&w=900&q=80", "", 8),
        (125, "Jam Bun", "Bakery", 25, "🍞", "Soft, freshly stocked bun filled with sweet jam.", "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=900&q=80", "", 2),
        (126, "Bun Butter Jam", "Bakery", 35, "🍞", "Soft bun spread with butter and sweet jam, made to order.", "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=900&q=80", "", 2),
        (127, "Palkova Bun", "Bakery", 40, "🍞", "Bakery bun filled with creamy, sweet palkova.", "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=900&q=80", "", 2),
        (128, "Egg Puff", "Bakery", 30, "🥐", "Flaky baked pastry filled with seasoned boiled egg.", "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=900&q=80", "", 2),
        (129, "Chicken Kothu Parotta", "Meals", 140, "🍗", "Chopped parotta tossed with chicken, egg, onion and salna.", "https://images.unsplash.com/photo-1565557623262-b51c2513a641?auto=format&fit=crop&w=900&q=80", "", 4),
        (130, "Chicken Hakka Noodles", "Meals", 140, "🍜", "Wok-tossed noodles with chicken, vegetables and spring onion.", "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?auto=format&fit=crop&w=900&q=80", "", 3),
        (131, "Egg Fried Rice", "Meals", 110, "🍳", "Wok-fried rice with egg, vegetables and spring onion.", "https://images.unsplash.com/photo-1603133872878-684f208fb84b?auto=format&fit=crop&w=900&q=80", "", 3),
        (132, "Fresh Orange Juice", "Fresh Juices", 60, "🍊", "Freshly squeezed oranges, prepared to order with no added syrup.", "https://images.unsplash.com/photo-1600271886742-f049cd451bba?auto=format&fit=crop&w=900&q=80", "", 6),
        (133, "Fresh Sweet Lime Juice", "Fresh Juices", 55, "🍋", "Fresh sweet lime juice squeezed to order.", "https://images.unsplash.com/photo-1513558161293-cdaf765edfd7?auto=format&fit=crop&w=900&q=80", "", 6),
        (134, "Fresh Watermelon Juice", "Fresh Juices", 50, "🍉", "Chilled watermelon juice made fresh for a light campus refreshment.", "https://images.unsplash.com/photo-1525385133512-2f3bdd039054?auto=format&fit=crop&w=900&q=80", "", 6),
        (135, "Fresh Pineapple Juice", "Fresh Juices", 60, "🍍", "Fresh pineapple juice blended and served chilled.", "https://images.unsplash.com/photo-1546173159-315724a31696?auto=format&fit=crop&w=900&q=80", "", 6),
        (136, "Fresh Sugarcane Juice", "Fresh Juices", 50, "🥤", "Freshly pressed sugarcane juice served chilled with lime.", "https://images.unsplash.com/photo-1513558161293-cdaf765edfd7?auto=format&fit=crop&w=900&q=80", "", 6),
        (137, "Chilled Cola", "Cool Drinks", 40, "🥤", "Chilled bottled cola served cold.", "https://images.unsplash.com/photo-1581636625402-29b2a704ef13?auto=format&fit=crop&w=900&q=80", "", 6),
        (138, "Lemon Soda", "Cool Drinks", 40, "🍋", "Cold sparkling lemon soda, available sweet or salted.", "https://images.unsplash.com/photo-1513558161293-cdaf765edfd7?auto=format&fit=crop&w=900&q=80", "", 6),
    ]
    non_veg_ids = {4, 110, 111, 112, 114, 128, 129, 130, 131}
    menu = [
        {
            "id": row[0],
            "name": row[1],
            "cat": row[2],
            "price": row[3],
            "emoji": row[4],
            "desc": row[5],
            "image": row[6],
            "offer": row[7],
            "available": True,
            "stallId": row[8] if len(row) > 8 else (row[0] - 1) % 8 + 1,
            "foodType": "Non-Veg" if row[0] in non_veg_ids else "Veg",
        }
        for row in menu_rows
    ]
    return {
        "menu": menu,
        "orders": [],
        "points": {"cb1024": 12, "cb2088": 0},
        "students": [
            {"id": "cb1024", "name": "Aarav Menon", "role": "Student", "status": "Active", "joined": "2025-08-12"},
            {"id": "cb2088", "name": "Diya Sharma", "role": "Student", "status": "Active", "joined": "2025-09-03"},
            {"id": "cb3041", "name": "Kabir Rao", "role": "Student", "status": "Active", "joined": "2025-10-19"},
            {"id": "staff01", "name": "Meera Nair", "role": "Stall manager", "status": "Active", "joined": "2025-07-01"},
        ],
        "stalls": [
            {
                "id": stall_id,
                "name": name,
                "location": "New Canteen" if stall_id <= 4 else "Old Canteen",
                "manager": SHOP_ACCOUNTS[stall_id],
                "hours": "08:00–20:00" if stall_id <= 4 else "08:00–18:00",
                "status": "Open",
                "shopGroup": "New Canteen" if stall_id <= 4 else "Old Canteen",
            }
            for stall_id, name in SHOP_NAMES.items()
        ],
        "campusPlaces": [
            {"id": "block-a", "name": "A Block", "kind": "Academic block", "query": "KPR College of Arts Science and Research A Block"},
            {"id": "block-b", "name": "B Block", "kind": "Academic block", "query": "KPR College of Arts Science and Research B Block"},
            {"id": "block-c", "name": "C Block", "kind": "Academic block", "query": "KPR College of Arts Science and Research C Block"},
            {"id": "new-canteen", "name": "New Canteen", "kind": "Food & pickup", "query": "KPR College of Arts Science and Research New Canteen"},
            {"id": "old-canteen", "name": "Old Canteen", "kind": "Food & pickup", "query": "KPR College of Arts Science and Research Old Canteen"},
        ],
        "announcements": [
            {"id": 1, "title": "Welcome to CampusBite", "message": "Order ahead and collect from your favourite campus stall.", "active": True, "createdAt": "2026-10-11T00:00:00.000Z"}
        ],
        "activity": [{"action": "Local SQLite database initialized", "actor": "CampusBite system", "at": "2026-10-11T00:00:00.000Z"}],
        "settings": {"upiId": "campusbite@upi", "payeeName": "CampusBite"},
        "nextOrder": 1001,
        "nextMenu": 10,
        "nextStall": 9,
        "nextPerson": 5,
        "shopLayoutVersion": 1,
    }


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt, PBKDF2_ROUNDS)
    return actual_salt, digest


def password_used_by_shop_account(
    connection: sqlite3.Connection, password: str, exclude_login_id: str | None = None
) -> str | None:
    query = "SELECT login_id, salt, password_hash FROM users WHERE role IN ('Stall staff', 'Stall manager')"
    parameters: tuple[str, ...] = ()
    if exclude_login_id is not None:
        query += " AND login_id != ?"
        parameters = (exclude_login_id,)
    for account in connection.execute(query, parameters):
        _, candidate = hash_password(password, account["salt"])
        if hmac.compare_digest(candidate, account["password_hash"]):
            return account["login_id"]
    return None


@contextmanager
def get_db():
    connection = sqlite3.connect(DATABASE, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, get_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                login_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'Student', 'Stall staff', 'Stall manager')),
                stall_id INTEGER,
                status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Suspended')),
                salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                login_id TEXT NOT NULL REFERENCES users(login_id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stalls (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campus_places (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS menu_items (
                id INTEGER PRIMARY KEY,
                stall_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL CHECK (price > 0),
                available INTEGER NOT NULL CHECK (available IN (0, 1)),
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                stall_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                total REAL NOT NULL CHECK (total >= 0),
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS orders_student_created_idx ON orders(student_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS orders_stall_created_idx ON orders(stall_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                menu_item_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                unit_price REAL NOT NULL CHECK (unit_price > 0),
                quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 50)
            );
            CREATE INDEX IF NOT EXISTS order_items_order_idx ON order_items(order_id);
            CREATE TABLE IF NOT EXISTS announcements (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payments (
                order_id TEXT PRIMARY KEY,
                method TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount >= 0),
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "stall_id" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN stall_id INTEGER")
        if "shop_password_ready" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN shop_password_ready INTEGER NOT NULL DEFAULT 0")
        admin_password = os.environ.get("CAMPUSBITE_ADMIN_PASSWORD", "CampusBite@123")
        defaults = [
            ("admin", "CampusBite Administrator", "admin", admin_password),
            ("cb1024", "Aarav Menon", "Student", "1234"),
            ("cb2088", "Diya Sharma", "Student", "1234"),
            ("cb3041", "Kabir Rao", "Student", "1234"),
            ("staff01", "Meera Nair", "Stall manager", "1234"),
        ]
        for login_id, name, role, password in defaults:
            row = connection.execute("SELECT login_id FROM users WHERE login_id = ?", (login_id,)).fetchone()
            if row is None:
                salt, digest = hash_password(password)
                connection.execute(
                    "INSERT INTO users (login_id, display_name, role, salt, password_hash) VALUES (?, ?, ?, ?, ?)",
                    (login_id, name, role, salt, digest),
                )
        connection.execute(
            "INSERT OR IGNORE INTO app_state (id, payload) VALUES (1, ?)",
            (json.dumps(seed_state(), ensure_ascii=False, separators=(",", ":")),),
        )
        migrate_shop_layout(connection)
        migrate_food_catalog(connection)
        state = main_state(connection)
        for stall_id, login_id in SHOP_ACCOUNTS.items():
            display_name = f"{SHOP_NAMES[stall_id]} Manager"
            row = connection.execute("SELECT login_id FROM users WHERE login_id = ?", (login_id,)).fetchone()
            if row is None:
                salt, digest = hash_password(secrets.token_urlsafe(32))
                connection.execute(
                    """INSERT INTO users
                       (login_id, display_name, role, stall_id, salt, password_hash)
                       VALUES (?, ?, 'Stall manager', ?, ?, ?)""",
                    (login_id, display_name, stall_id, salt, digest),
                )
            else:
                connection.execute(
                    "UPDATE users SET role = 'Stall manager', stall_id = ? WHERE login_id = ?",
                    (stall_id, login_id),
                )
            person = next((item for item in state["students"] if item.get("id") == login_id), None)
            if person is None:
                person = {
                    "id": login_id, "name": display_name, "role": "Stall manager",
                    "status": "Active", "joined": time.strftime("%Y-%m-%d"),
                }
                state["students"].append(person)
            person["stallId"] = stall_id
            person["role"] = "Stall manager"
        credential_version = connection.execute(
            "SELECT value FROM app_meta WHERE key = 'shop_credentials_version'"
        ).fetchone()
        if credential_version is None or int(credential_version["value"]) < 1:
            for login_id in SHOP_ACCOUNTS.values():
                salt, digest = hash_password(secrets.token_urlsafe(32))
                connection.execute(
                    "UPDATE users SET salt = ?, password_hash = ?, shop_password_ready = 0 WHERE login_id = ?",
                    (salt, digest, login_id),
                )
                connection.execute("DELETE FROM sessions WHERE login_id = ?", (login_id,))
            connection.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('shop_credentials_version', '1')"
            )
        connection.execute(
            "UPDATE app_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
        )
        sync_relational_tables(connection, state)


def migrate_shop_layout(connection: sqlite3.Connection) -> None:
    state = main_state(connection)
    if int(state.get("shopLayoutVersion", 0)) >= 1:
        return
    existing = {int(stall["id"]): stall for stall in state.get("stalls", [])}
    stalls = []
    for stall_id, name in SHOP_NAMES.items():
        legacy_id = 1 if stall_id == 1 else 2 if stall_id == 5 else None
        previous = existing.get(stall_id, {})
        if legacy_id is not None and existing.get(legacy_id, {}).get("name") in {"New Canteen", "Old Canteen"}:
            previous = existing[legacy_id]
        elif previous.get("name") != name:
            previous = {}
        group = "New Canteen" if stall_id <= 4 else "Old Canteen"
        stalls.append({
            **previous,
            "id": stall_id,
            "name": name,
            "location": group,
            "manager": SHOP_ACCOUNTS[stall_id],
            "hours": previous.get("hours", "08:00–20:00" if stall_id <= 4 else "08:00–18:00"),
            "status": previous.get("status", "Open"),
            "shopGroup": group,
        })
    stalls.extend(stall for stall_id, stall in existing.items() if stall_id not in SHOP_NAMES)
    for order in state.get("orders", []):
        if int(order.get("stallId", 1)) == 2:
            order["stallId"] = 5
    state["stalls"] = stalls
    for index, item in enumerate(state.get("menu", [])):
        item["stallId"] = index % len(SHOP_NAMES) + 1
    state["nextStall"] = max(int(state.get("nextStall", 1)), max(stall["id"] for stall in stalls) + 1)
    state["shopLayoutVersion"] = 1
    connection.execute(
        "UPDATE app_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
        (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
    )
    sync_relational_tables(connection, state)


def migrate_food_catalog(connection: sqlite3.Connection) -> None:
    state = main_state(connection)
    existing_ids = {int(item["id"]) for item in state.get("menu", [])}
    catalog = {int(item["id"]): item for item in seed_state()["menu"]}
    new_items = [
        item for item_id, item in catalog.items()
        if item_id >= 125 and item_id not in existing_ids
    ]
    changed = bool(new_items)
    for item in state.get("menu", []):
        catalog_item = catalog.get(int(item["id"]))
        if catalog_item and not item.get("foodType"):
            item["foodType"] = catalog_item["foodType"]
            changed = True
    if not changed:
        return
    state.setdefault("menu", []).extend(new_items)
    state["foodCatalogVersion"] = 2
    connection.execute(
        "UPDATE app_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
        (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
    )
    sync_relational_tables(connection, state)


def sync_relational_tables(connection: sqlite3.Connection, state: dict) -> None:
    connection.execute("DELETE FROM order_items")
    connection.execute("DELETE FROM payments")
    connection.execute("DELETE FROM orders")
    connection.execute("DELETE FROM menu_items")
    connection.execute("DELETE FROM stalls")
    connection.execute("DELETE FROM campus_places")
    connection.execute("DELETE FROM announcements")
    connection.execute("DELETE FROM activity_log")

    for stall in state.get("stalls", []):
        connection.execute(
            "INSERT INTO stalls (id, name, status, payload) VALUES (?, ?, ?, ?)",
            (int(stall["id"]), str(stall["name"]), str(stall["status"]), json.dumps(stall, ensure_ascii=False)),
        )
    for place in state.get("campusPlaces", []):
        connection.execute(
            "INSERT INTO campus_places (id, name, kind, payload) VALUES (?, ?, ?, ?)",
            (str(place["id"]), str(place["name"]), str(place["kind"]), json.dumps(place, ensure_ascii=False)),
        )
    for item in state.get("menu", []):
        connection.execute(
            """INSERT INTO menu_items
               (id, stall_id, name, category, price, available, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                int(item["id"]), int(item.get("stallId", 1)), str(item["name"]),
                str(item["cat"]), float(item["price"]), int(item.get("available") is not False),
                json.dumps(item, ensure_ascii=False),
            ),
        )
    for order in state.get("orders", []):
        order_id = str(order["id"])
        created_at = str(order.get("createdAt", ""))
        connection.execute(
            """INSERT INTO orders (id, student_id, stall_id, status, total, created_at, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id, str(order.get("studentId", "")), int(order.get("stallId", 1)),
                str(order.get("status", "Placed")), float(order.get("total", 0)),
                created_at, json.dumps(order, ensure_ascii=False),
            ),
        )
        for item in order.get("items", []):
            connection.execute(
                """INSERT INTO order_items
                   (order_id, menu_item_id, item_name, unit_price, quantity)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    order_id, int(item["id"]), str(item["name"]),
                    float(item["price"]), int(item["qty"]),
                ),
            )
        payment_status = str(order.get("paymentStatus", "pending")).lower()
        if "refund" in payment_status:
            payment_status = "refund_recorded"
        elif "verif" in payment_status or payment_status == "paid":
            payment_status = "verified"
        elif "fail" in payment_status:
            payment_status = "failed"
        else:
            payment_status = "pending"
        method = str(order.get("paymentMethod", "cash")).lower()
        if method not in {"upi", "card", "cash", "credits"}:
            method = "cash"
        connection.execute(
            "INSERT INTO payments (order_id, method, amount, status) VALUES (?, ?, ?, ?)",
            (order_id, method, max(0, float(order.get("total", 0))), payment_status),
        )
    for index, announcement in enumerate(state.get("announcements", []), start=1):
        connection.execute(
            """INSERT INTO announcements (id, title, active, created_at, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (
                str(announcement["id"]), str(announcement["title"]),
                int(bool(announcement.get("active"))), str(announcement.get("createdAt", "")),
                json.dumps(announcement, ensure_ascii=False),
            ),
        )
    for index, entry in enumerate(state.get("activity", []), start=1):
        connection.execute(
            """INSERT INTO activity_log (id, action, actor, created_at, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (
                index, str(entry.get("action", "")), str(entry.get("actor", "")),
                str(entry.get("at", "")), json.dumps(entry, ensure_ascii=False),
            ),
        )


def main_state(connection: sqlite3.Connection) -> dict:
    row = connection.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("CampusBite SQLite state row is missing.")
    return json.loads(row["payload"])


def public_state(state: dict, user: sqlite3.Row | None) -> dict:
    result = copy.deepcopy(state)
    if user is None or user["role"] != "admin":
        result.pop("shopPasswordsConfigured", None)
    result["orders"] = []
    result["activity"] = []
    result["payments"] = []
    result["points"] = {}
    if user is None:
        result["students"] = []
    elif user["stall_id"] is not None and user["role"] in {"Stall staff", "Stall manager"}:
        stall_id = int(user["stall_id"])
        result["menu"] = [item for item in result.get("menu", []) if int(item.get("stallId", 1)) == stall_id]
        result["stalls"] = [stall for stall in result.get("stalls", []) if int(stall["id"]) == stall_id]
        result["orders"] = [order for order in state.get("orders", []) if int(order.get("stallId", 1)) == stall_id]
        result["students"] = []
    elif user["role"] != "admin":
        login_id = user["login_id"]
        result["students"] = [person for person in result.get("students", []) if person["id"].lower() == login_id]
        result["orders"] = [order for order in state.get("orders", []) if str(order.get("studentId", "")).lower() == login_id]
        result["points"] = {login_id: state.get("points", {}).get(login_id, 0)}
        result["activity"] = []
    return result


def safe_error(message: str, status: int = 400) -> tuple[int, dict]:
    return status, {"error": message}


class CampusBiteHandler(SimpleHTTPRequestHandler):
    server_version = "CampusBiteLocal/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format_string: str, *args) -> None:
        sys.stdout.write(f"{self.log_date_time_string()} {self.address_string()} {format_string % args}\n")

    @staticmethod
    def _is_private_file_path(path: str) -> bool:
        normalized = posixpath.normpath(unquote(path))
        return normalized.startswith("/data/") or normalized == "/data" or normalized.startswith("/.git/")

    def _json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError("Request body must be between 1 byte and 8 MB.")
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object.")
        return body

    def _session_user(self, connection: sqlite3.Connection) -> sqlite3.Row | None:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return None
        token = authorization[7:].strip()
        if len(token) < 40 or len(token) > 200:
            return None
        token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
        row = connection.execute(
            """SELECT users.* FROM sessions
               JOIN users ON users.login_id = sessions.login_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.status = 'Active'""",
            (token_hash, int(time.time())),
        ).fetchone()
        return row

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if self._is_private_file_path(path):
            self.send_error(404)
            return
        if path == "/api/health":
            self._json(200, {"ok": True, "database": "sqlite", "scope": "local-only"})
            return
        if path == "/api/state":
            with DB_LOCK, get_db() as connection:
                user = self._session_user(connection)
                state = main_state(connection)
                if user is not None and user["role"] == "admin":
                    configured_passwords = [
                        row["login_id"] for row in connection.execute(
                            """SELECT login_id FROM users
                               WHERE role IN ('Stall staff', 'Stall manager')
                                 AND stall_id IS NOT NULL AND shop_password_ready = 1
                               ORDER BY login_id"""
                        )
                    ]
                    self._json(200, {
                        "state": state, "role": "admin", "loginId": user["login_id"],
                        "shopPasswordsConfigured": configured_passwords,
                    })
                else:
                    self._json(200, {
                        "state": public_state(state, user),
                        "role": user["role"] if user else "visitor",
                        "loginId": user["login_id"] if user else None,
                        "stallId": int(user["stall_id"]) if user and user["stall_id"] is not None else None,
                    })
            return
        return super().do_GET()

    def do_HEAD(self) -> None:
        if self._is_private_file_path(urlsplit(self.path).path):
            self.send_error(404)
            return
        return super().do_HEAD()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if not self._same_origin_api_request():
            self._json(403, {"error": "Cross-origin requests are not allowed."})
            return
        try:
            data = self._read_json()
            if path == "/api/login":
                self._login(data)
            elif path == "/api/orders":
                self._create_order(data)
            elif path == "/api/orders/status":
                self._update_order_status(data)
            elif path == "/api/logout":
                self._logout()
            elif path == "/api/state":
                self._save_state(data)
            elif path == "/api/users":
                self._create_user(data)
            elif path == "/api/users/password":
                self._set_shop_password(data)
            else:
                self._json(404, {"error": "API endpoint not found."})
        except ValueError as error:
            self._json(400, {"error": str(error)})
        except (sqlite3.Error, RuntimeError) as error:
            print(f"CampusBite database request failed: {error}", file=sys.stderr)
            self._json(500, {"error": "The local database could not complete that request."})

    def _login(self, data: dict) -> None:
        login_id = data.get("loginId")
        password = data.get("password")
        if not isinstance(login_id, str) or not isinstance(password, str):
            self._json(400, {"error": "Enter your account ID and password."})
            return
        login_id = login_id.strip().lower()
        if not (2 <= len(login_id) <= 80) or len(password) > 128:
            self._json(400, {"error": "Enter your account ID and password."})
            return
        with DB_LOCK, get_db() as connection:
            user = connection.execute("SELECT * FROM users WHERE login_id = ?", (login_id,)).fetchone()
            if user is None:
                # Keep invalid-user and invalid-password responses indistinguishable.
                hash_password(password, b"CampusBiteLocal!")
                self._json(401, {"error": "Invalid account ID or password."})
                return
            _, candidate = hash_password(password, user["salt"])
            if user["status"] != "Active" or not hmac.compare_digest(candidate, user["password_hash"]):
                self._json(401, {"error": "Invalid account ID or password."})
                return
            token = secrets.token_urlsafe(48)
            expires_at = int(time.time()) + SESSION_SECONDS
            connection.execute(
                "INSERT INTO sessions (token_hash, login_id, expires_at) VALUES (?, ?, ?)",
                (hashlib.sha256(token.encode("ascii")).hexdigest(), login_id, expires_at),
            )
        self._json(200, {
            "access_token": token,
            "expires_at": expires_at,
            "user": {
                "id": user["login_id"], "name": user["display_name"], "role": user["role"],
                "stallId": int(user["stall_id"]) if user["stall_id"] is not None else None,
            },
        })

    def _create_order(self, data: dict) -> None:
        with DB_LOCK, get_db() as connection:
            user = self._session_user(connection)
            if user is None or user["role"] != "Student":
                self._json(401, {"error": "Sign in with an active student account to place an order."})
                return
            student_id = data.get("studentId")
            if not isinstance(student_id, str) or student_id.strip().lower() != user["login_id"]:
                self._json(403, {"error": "Orders can only be placed for the signed-in student."})
                return
            try:
                stall_id = int(data["stallId"])
                items = data["items"]
                method = data["paymentMethod"]
            except (KeyError, TypeError, ValueError):
                self._json(400, {"error": "The order is missing required details."})
                return
            if not isinstance(method, str) or method not in {"upi", "card", "cash", "credits"}:
                self._json(400, {"error": "Unsupported payment method."})
                return
            if not isinstance(items, list) or not 1 <= len(items) <= 30:
                self._json(400, {"error": "An order must contain between 1 and 30 items."})
                return
            state = main_state(connection)
            stall = next((item for item in state["stalls"] if item["id"] == stall_id), None)
            if not stall or stall["status"] != "Open":
                self._json(400, {"error": "The selected stall is not open."})
                return
            total = 0
            checked_items = []
            for requested in items:
                if not isinstance(requested, dict):
                    self._json(400, {"error": "Order items have an invalid format."})
                    return
                try:
                    item_id = int(requested["id"])
                    quantity = int(requested["qty"])
                except (KeyError, TypeError, ValueError):
                    self._json(400, {"error": "Each order item needs an ID and quantity."})
                    return
                menu_item = next((item for item in state["menu"] if item["id"] == item_id), None)
                if not menu_item or menu_item.get("available") is False or menu_item.get("stallId", stall_id) != stall_id:
                    self._json(400, {"error": "A selected menu item is unavailable at this stall."})
                    return
                if not 1 <= quantity <= 50:
                    self._json(400, {"error": "Item quantities must be between 1 and 50."})
                    return
                total += int(menu_item["price"]) * quantity
                checked_items.append({
                    "id": menu_item["id"], "name": menu_item["name"],
                    "price": menu_item["price"], "qty": quantity,
                })

            order_subtotal = total
            student_id = user["login_id"]
            points = max(0, int(state.get("points", {}).get(student_id, 0)))
            savings = min(order_subtotal, (min(points, (order_subtotal // 10) * 100) // 100) * 10)
            points_redeemed = (savings // 10) * 100
            total = order_subtotal - savings
            if points_redeemed:
                state.setdefault("points", {})[student_id] = points - points_redeemed
            order_id = f"CB{int(state['nextOrder'])}"
            state["nextOrder"] = int(state["nextOrder"]) + 1
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            order = {
                "id": order_id, "studentId": user["login_id"], "stallId": stall_id,
                "items": checked_items, "subtotal": order_subtotal, "bonusDiscount": savings,
                "bonusPointsRedeemed": points_redeemed, "total": total, "paymentMethod": method,
                "paymentStatus": "Pending on pickup" if method == "cash" else "Pending verification",
                "status": "Placed", "createdAt": now, "bonusAwarded": False,
            }
            state["orders"].append(order)
            state["activity"].insert(0, {"action": f"New order {order_id} placed", "actor": user["login_id"], "at": now})
            state["activity"] = state["activity"][:150]
            connection.execute(
                "UPDATE app_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
            )
            sync_relational_tables(connection, state)
        self._json(201, {"order": order, "points": state.get("points", {}).get(user["login_id"], 0)})

    def _update_order_status(self, data: dict) -> None:
        order_id = data.get("orderId")
        status = data.get("status")
        if not isinstance(order_id, str) or status not in {
            "Preparing", "Ready", "Ready for pickup", "Completed", "Cancelled",
        }:
            self._json(400, {"error": "Choose a valid order and status."})
            return
        with DB_LOCK, get_db() as connection:
            user = self._session_user(connection)
            if user is None or user["role"] == "Student":
                self._json(401, {"error": "An active staff session is required."})
                return
            state = main_state(connection)
            order = next((item for item in state.get("orders", []) if item["id"] == order_id), None)
            if order is None:
                self._json(404, {"error": "That order could not be found."})
                return
            if user["role"] != "admin" and (
                user["stall_id"] is None or int(user["stall_id"]) != int(order.get("stallId", 1))
            ):
                self._json(403, {"error": "You can only update orders for your assigned shop."})
                return
            order["status"] = status
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if status == "Completed" and not order.get("bonusAwarded"):
                student_id = str(order.get("studentId", "")).lower()
                if student_id:
                    earned = max(0, int(float(order.get("total", 0)) // 10))
                    state.setdefault("points", {})[student_id] = int(state.get("points", {}).get(student_id, 0)) + earned
                    order["bonusAwarded"] = True
                    order["bonusPointsEarned"] = earned
                else:
                    order["bonusAwarded"] = True
            state.setdefault("activity", []).insert(
                0, {"action": f"Updated {order_id} status to {status}", "actor": user["login_id"], "at": now}
            )
            state["activity"] = state["activity"][:150]
            connection.execute(
                "UPDATE app_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
            )
            sync_relational_tables(connection, state)
        self._json(200, {"order": order})

    def _save_state(self, data: dict) -> None:
        token_user = None
        with DB_LOCK, get_db() as connection:
            token_user = self._session_user(connection)
            if token_user is None or token_user["role"] != "admin":
                self._json(401, {"error": "An active admin session is required."})
                return
            state = data.get("state")
            if not isinstance(state, dict):
                self._json(400, {"error": "Database state is missing."})
                return
            state.pop("shopPasswordsConfigured", None)
            required = ("menu", "orders", "points", "students", "stalls", "campusPlaces", "announcements", "activity")
            if any(not isinstance(state.get(key), (list, dict)) for key in required):
                self._json(400, {"error": "Database state has an invalid shape."})
                return
            encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > MAX_BODY:
                self._json(413, {"error": "Database update exceeds the local request limit."})
                return
            connection.execute(
                "UPDATE app_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (encoded,),
            )
            sync_relational_tables(connection, state)
            for person in state["students"]:
                if not isinstance(person, dict):
                    continue
                login_id = str(person.get("id", "")).strip().lower()
                role = person.get("role")
                status = person.get("status")
                if role not in {"Student", "Stall staff", "Stall manager", "Admin"} or status not in {"Active", "Suspended"}:
                    continue
                db_role = "admin" if role == "Admin" else role
                stall_id = person.get("stallId") if role in {"Stall staff", "Stall manager"} else None
                if stall_id is not None and not any(
                    int(stall["id"]) == int(stall_id) for stall in state["stalls"]
                ):
                    continue
                connection.execute(
                    "UPDATE users SET display_name = ?, role = ?, status = ?, stall_id = ? WHERE login_id = ?",
                    (str(person.get("name", login_id))[:100], db_role, status, stall_id, login_id),
                )
        self._json(200, {"saved": True})

    def _create_user(self, data: dict) -> None:
        with DB_LOCK, get_db() as connection:
            user = self._session_user(connection)
            if user is None or user["role"] != "admin":
                self._json(401, {"error": "An active admin session is required."})
                return
            login_id = data.get("loginId")
            name = data.get("displayName")
            role = data.get("role")
            password = data.get("password")
            if not all(isinstance(value, str) for value in (login_id, name, role, password)):
                self._json(400, {"error": "Account ID, name, role, and password are required."})
                return
            login_id = login_id.strip().lower()
            if not (2 <= len(login_id) <= 80) or len(password) < 8 or len(password) > 128:
                self._json(400, {"error": "Use an account ID of 2–80 characters and a password of 8–128 characters."})
                return
            if role not in {"Student", "Stall staff", "Stall manager", "Admin"}:
                self._json(400, {"error": "Choose a supported account role."})
                return
            stall_id = data.get("stallId")
            if role in {"Stall staff", "Stall manager"}:
                try:
                    stall_id = int(stall_id)
                except (TypeError, ValueError):
                    self._json(400, {"error": "Choose the shop this staff account belongs to."})
                    return
                state = main_state(connection)
                if not any(int(stall["id"]) == stall_id for stall in state.get("stalls", [])):
                    self._json(400, {"error": "The selected shop does not exist."})
                    return
                if role == "Stall manager" and connection.execute(
                    "SELECT 1 FROM users WHERE stall_id = ? AND role = 'Stall manager' AND status = 'Active'",
                    (stall_id,),
                ).fetchone():
                    self._json(409, {"error": "That stall already has an active manager account. Assign another shop or create a staff account."})
                    return
            else:
                stall_id = None
            if role in {"Stall staff", "Stall manager"} and password_used_by_shop_account(connection, password):
                self._json(400, {"error": "Every stall account must have a different password."})
                return
            salt, digest = hash_password(password)
            db_role = "admin" if role == "Admin" else role
            try:
                connection.execute(
                    """INSERT INTO users
                       (login_id, display_name, role, stall_id, salt, password_hash)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (login_id, name.strip()[:100], db_role, stall_id, salt, digest),
                )
            except sqlite3.IntegrityError:
                self._json(409, {"error": "That account ID already exists."})
                return
            state = main_state(connection)
            state["students"].append({
                "id": login_id, "name": name.strip()[:100], "role": role,
                "status": "Active", "joined": time.strftime("%Y-%m-%d"),
                **({"stallId": stall_id} if stall_id is not None else {}),
            })
            connection.execute(
                "UPDATE app_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
            )
            sync_relational_tables(connection, state)
        self._json(201, {"created": True, "loginId": login_id})

    def _set_shop_password(self, data: dict) -> None:
        login_id = data.get("loginId")
        password = data.get("password")
        if not isinstance(login_id, str) or not isinstance(password, str):
            self._json(400, {"error": "Shop account ID and new password are required."})
            return
        login_id = login_id.strip().lower()
        if not 8 <= len(password) <= 128:
            self._json(400, {"error": "Use a unique password of 8–128 characters."})
            return
        with DB_LOCK, get_db() as connection:
            actor = self._session_user(connection)
            if actor is None or actor["role"] != "admin":
                self._json(401, {"error": "An active global admin session is required to set shop passwords."})
                return
            account = connection.execute(
                "SELECT login_id, role, stall_id FROM users WHERE login_id = ?",
                (login_id,),
            ).fetchone()
            if account is None or account["role"] not in {"Stall staff", "Stall manager"} or account["stall_id"] is None:
                self._json(404, {"error": "That shop staff account could not be found."})
                return
            if password_used_by_shop_account(connection, password, login_id):
                self._json(400, {"error": "Every stall must have a different password. Choose one not used by another shop account."})
                return
            salt, digest = hash_password(password)
            connection.execute(
                "UPDATE users SET salt = ?, password_hash = ?, shop_password_ready = 1 WHERE login_id = ?",
                (salt, digest, login_id),
            )
            connection.execute("DELETE FROM sessions WHERE login_id = ?", (login_id,))
        self._json(200, {"updated": True, "loginId": login_id})

    def _logout(self) -> None:
        authorization = self.headers.get("Authorization", "")
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        if token:
            token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
            with DB_LOCK, get_db() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        self._json(200, {"signedOut": True})

    def _same_origin_api_request(self) -> bool:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host", "").lower() not in {
            expected_host,
            f"localhost:{self.server.server_port}",
        }:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }:
            return False
        return self.headers.get("Sec-Fetch-Site", "same-origin") in {"same-origin", "none"}

    def do_PUT(self) -> None:
        if not self._same_origin_api_request():
            self._json(403, {"error": "Cross-origin requests are not allowed."})
            return
        if urlsplit(self.path).path != "/api/state":
            self._json(404, {"error": "API endpoint not found."})
            return
        try:
            self._save_state(self._read_json())
        except ValueError as error:
            self._json(400, {"error": str(error)})
        except sqlite3.Error as error:
            print(f"CampusBite database update failed: {error}", file=sys.stderr)
            self._json(500, {"error": "The local database could not save this update."})


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local CampusBite site and SQLite database.")
    parser.add_argument("--port", type=int, default=PORT, help="Local server port (default: 8765)")
    args = parser.parse_args()
    initialize_database()
    server = ThreadingHTTPServer((HOST, args.port), CampusBiteHandler)
    print(f"CampusBite local site: http://{HOST}:{args.port}/index.html")
    print(f"SQLite database: {DATABASE}")
    print("Local demo accounts: admin / CampusBite@123; students cb1024, cb2088, cb3041 / 1234")
    if "CAMPUSBITE_ADMIN_PASSWORD" not in os.environ:
        print("WARNING: using the demo admin password. Set CAMPUSBITE_ADMIN_PASSWORD before first startup.")
    print("This server listens only on this computer. Do not expose it to the internet.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping CampusBite local server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
