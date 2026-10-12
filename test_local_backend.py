import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import local_backend


class LocalBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        local_backend.DATABASE = Path(cls.temp_dir.name) / "campusbite-test.sqlite3"
        local_backend.initialize_database()
        with local_backend.get_db() as connection:
            version = connection.execute(
                "SELECT value FROM app_meta WHERE key = 'shop_credentials_version'"
            ).fetchone()
            if version is None or version["value"] != "1":
                raise AssertionError(f"Shop credential migration missing from {local_backend.DATABASE}")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), local_backend.CampusBiteHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp_dir.cleanup()

    def request(self, path, method="GET", payload=None, token=None):
        headers = {"Host": f"127.0.0.1:{self.server.server_port}"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                body = error.read()
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = {"body": body.decode("utf-8", errors="replace")}
                return error.code, payload
            finally:
                error.close()

    def setUp(self):
        with local_backend.get_db() as connection:
            state = local_backend.seed_state()
            connection.execute("DELETE FROM users WHERE login_id = 'cb5001'")
            connection.execute("DELETE FROM sessions")
            connection.execute(
                "UPDATE app_state SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (json.dumps(state),),
            )
            local_backend.sync_relational_tables(connection, state)

    def test_health_and_visitor_privacy(self):
        status, health = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["database"], "sqlite")
        status, response = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(response["role"], "visitor")
        self.assertEqual(response["state"]["orders"], [])
        self.assertEqual(response["state"]["students"], [])
        self.assertEqual(len(response["state"]["menu"]), 47)
        self.assertEqual({item["foodType"] for item in response["state"]["menu"]}, {"Veg", "Non-Veg"})

    def test_database_file_is_not_served(self):
        for path in ("/data/campusbite.sqlite3", "/../data/campusbite.sqlite3"):
            status, _ = self.request(path)
            self.assertEqual(status, 404)
        request = urllib.request.Request(
            self.base_url + "/data/campusbite.sqlite3",
            headers={"Host": f"127.0.0.1:{self.server.server_port}"},
            method="HEAD",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(context.exception.code, 404)
        context.exception.close()

    def test_api_rejects_cross_origin_writes(self):
        request = urllib.request.Request(
            self.base_url + "/api/login",
            data=json.dumps({"loginId": "admin", "password": "CampusBite@123"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Host": f"127.0.0.1:{self.server.server_port}",
                "Origin": "https://malicious.example",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                self.fail(f"Expected cross-origin request to fail, got {response.status}")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 403)
            error.close()

    def test_login_order_price_and_student_privacy(self):
        status, invalid = self.request(
            "/api/login", "POST", {"loginId": "cb1024", "password": "wrong"}
        )
        self.assertEqual(status, 401)
        self.assertEqual(invalid["error"], "Invalid account ID or password.")

        status, login = self.request(
            "/api/login", "POST", {"loginId": "CB1024", "password": "1234"}
        )
        self.assertEqual(status, 200)
        token = login["access_token"]
        status, created = self.request(
            "/api/orders",
            "POST",
            {
                "studentId": "cb1024",
                "stallId": 1,
                "items": [{"id": 1, "name": "Forged name", "price": 1, "qty": 1}],
                "paymentMethod": "cash",
            },
            token,
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["order"]["items"][0]["name"], "Masala Dosa")
        self.assertEqual(created["order"]["total"], 65)

        status, private = self.request("/api/state", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(private["role"], "Student")
        self.assertEqual([order["id"] for order in private["state"]["orders"]], ["CB1001"])
        self.assertEqual([person["id"] for person in private["state"]["students"]], ["cb1024"])

        with local_backend.get_db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT amount FROM payments").fetchone()[0], 65)

    def test_admin_state_save_and_account_creation(self):
        status, login = self.request(
            "/api/login", "POST", {"loginId": "admin", "password": "CampusBite@123"}
        )
        self.assertEqual(status, 200)
        token = login["access_token"]
        status, state_result = self.request("/api/state", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(state_result["role"], "admin")

        status, user = self.request(
            "/api/users",
            "POST",
            {
                "loginId": "cb5001",
                "displayName": "Test Student",
                "role": "Student",
                "password": "test-password-123",
            },
            token,
        )
        self.assertEqual(status, 201)
        status, duplicate_manager = self.request(
            "/api/users",
            "POST",
            {
                "loginId": "newmanager",
                "displayName": "Duplicate Shop Manager",
                "role": "Stall manager",
                "stallId": 1,
                "password": "test-password-123",
            },
            token,
        )
        self.assertEqual(status, 409)
        self.assertIn("already has an active manager", duplicate_manager["error"])
        status, student_login = self.request(
            "/api/login", "POST", {"loginId": "cb5001", "password": "test-password-123"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(student_login["user"]["id"], "cb5001")

        state_result["state"]["announcements"].append({
            "id": 99,
            "title": "Database test",
            "message": "Persisted",
            "active": True,
            "createdAt": "2026-10-11T00:00:00Z",
        })
        status, saved = self.request(
            "/api/state", "PUT", {"state": state_result["state"]}, token
        )
        self.assertEqual(status, 200)
        self.assertTrue(saved["saved"])
        with local_backend.get_db() as connection:
            announcement = connection.execute(
                "SELECT title FROM announcements WHERE id = '99'"
            ).fetchone()
            self.assertEqual(announcement["title"], "Database test")
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM users WHERE login_id = 'cb5001'").fetchone()[0],
                1,
            )

    def test_shop_managers_only_receive_and_update_their_shop_orders(self):
        status, global_admin = self.request(
            "/api/login", "POST", {"loginId": "admin", "password": "CampusBite@123"}
        )
        self.assertEqual(status, 200)
        admin_token = global_admin["access_token"]
        status, old_shared_login = self.request(
            "/api/login", "POST", {"loginId": "newshop1", "password": "CampusShop@123"}
        )
        self.assertEqual(status, 401)
        status, admin_only = self.request(
            "/api/users/password",
            "POST",
            {"loginId": "newshop1", "password": "Not-Admin-123"},
            "invalid-student-token",
        )
        self.assertEqual(status, 401)
        first_password = "First-Shop-Private-84"
        second_password = "Second-Shop-Private-92"
        for login_id, password in (
            ("newshop1", first_password),
            ("newshop2", second_password),
        ):
            status, result = self.request(
                "/api/users/password",
                "POST",
                {"loginId": login_id, "password": password},
                admin_token,
            )
            self.assertEqual(status, 200, result)
        status, duplicate_password = self.request(
            "/api/users/password",
            "POST",
            {"loginId": "newshop2", "password": first_password},
            admin_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("different password", duplicate_password["error"])

        status, first_student = self.request(
            "/api/login", "POST", {"loginId": "cb1024", "password": "1234"}
        )
        self.assertEqual(status, 200)
        status, first_order = self.request(
            "/api/orders",
            "POST",
            {"studentId": "cb1024", "stallId": 1, "items": [{"id": 1, "qty": 1}], "paymentMethod": "cash"},
            first_student["access_token"],
        )
        self.assertEqual(status, 201)

        status, second_student = self.request(
            "/api/login", "POST", {"loginId": "cb2088", "password": "1234"}
        )
        self.assertEqual(status, 200)
        status, second_order = self.request(
            "/api/orders",
            "POST",
            {"studentId": "cb2088", "stallId": 2, "items": [{"id": 2, "qty": 1}], "paymentMethod": "cash"},
            second_student["access_token"],
        )
        self.assertEqual(status, 201)

        status, first_manager = self.request(
            "/api/login", "POST", {"loginId": "newshop1", "password": first_password}
        )
        self.assertEqual(status, 200)
        first_token = first_manager["access_token"]
        self.assertEqual(first_manager["user"]["stallId"], 1)
        status, first_state = self.request("/api/state", token=first_token)
        self.assertEqual(status, 200)
        self.assertEqual(first_state["role"], "Stall manager")
        self.assertEqual([stall["id"] for stall in first_state["state"]["stalls"]], [1])
        self.assertTrue(all(item["stallId"] == 1 for item in first_state["state"]["menu"]))
        self.assertEqual(
            [order["id"] for order in first_state["state"]["orders"]],
            [first_order["order"]["id"]],
        )

        status, second_manager = self.request(
            "/api/login", "POST", {"loginId": "newshop2", "password": second_password}
        )
        self.assertEqual(status, 200)
        second_token = second_manager["access_token"]
        status, forbidden = self.request(
            "/api/orders/status", "POST",
            {"orderId": second_order["order"]["id"], "status": "Preparing"},
            first_token,
        )
        self.assertEqual(status, 403)
        self.assertIn("assigned shop", forbidden["error"])

        status, updated = self.request(
            "/api/orders/status", "POST",
            {"orderId": first_order["order"]["id"], "status": "Ready"},
            first_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["order"]["status"], "Ready")
        status, second_state = self.request("/api/state", token=second_token)
        self.assertEqual(status, 200)
        self.assertEqual(
            [order["id"] for order in second_state["state"]["orders"]],
            [second_order["order"]["id"]],
        )
        status, denied_save = self.request(
            "/api/state", "PUT", {"state": second_state["state"]}, first_token
        )
        self.assertEqual(status, 401)

    def test_shop_passwords_are_private_unique_and_admin_managed(self):
        status, admin = self.request(
            "/api/login", "POST", {"loginId": "admin", "password": "CampusBite@123"}
        )
        self.assertEqual(status, 200)
        admin_token = admin["access_token"]
        passwords = {
            "newshop1": "Shop-One-Unique-Password",
            "newshop2": "Shop-Two-Unique-Password",
        }
        for login_id, password in passwords.items():
            status, result = self.request(
                "/api/users/password",
                "POST",
                {"loginId": login_id, "password": password},
                admin_token,
            )
            self.assertEqual(status, 200, result)

        status, duplicate = self.request(
            "/api/users/password",
            "POST",
            {"loginId": "newshop2", "password": passwords["newshop1"]},
            admin_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("different password", duplicate["error"])

        status, staff_duplicate = self.request(
            "/api/users",
            "POST",
            {
                "loginId": "shopstaff2",
                "displayName": "Shop Two Staff",
                "role": "Stall staff",
                "stallId": 2,
                "password": passwords["newshop1"],
            },
            admin_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("different password", staff_duplicate["error"])

        status, student = self.request(
            "/api/login", "POST", {"loginId": "cb1024", "password": "1234"}
        )
        self.assertEqual(status, 200)
        status, denied = self.request(
            "/api/users/password",
            "POST",
            {"loginId": "newshop1", "password": "Changed-By-Student"},
            student["access_token"],
        )
        self.assertEqual(status, 401)

        for login_id, password in passwords.items():
            status, login = self.request(
                "/api/login", "POST", {"loginId": login_id, "password": password}
            )
            self.assertEqual(status, 200)
            self.assertEqual(login["user"]["id"], login_id)
        status, wrong_shop_password = self.request(
            "/api/login",
            "POST",
            {"loginId": "newshop1", "password": passwords["newshop2"]},
        )
        self.assertEqual(status, 401)
        local_backend.initialize_database()
        status, login_after_restart = self.request(
            "/api/login",
            "POST",
            {"loginId": "newshop1", "password": passwords["newshop1"]},
        )
        self.assertEqual(status, 200, login_after_restart)
        status, admin_state = self.request("/api/state", token=admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(set(admin_state["shopPasswordsConfigured"]), {"newshop1", "newshop2"})
        self.assertNotIn("shopPasswordsConfigured", admin_state["state"])
        status, old_shared_password = self.request(
            "/api/login",
            "POST",
            {"loginId": "newshop3", "password": "CampusShop@123"},
        )
        self.assertEqual(status, 401)


    def test_legacy_stall_data_migrates_to_eight_shop_layout(self):
        legacy_database = Path(self.temp_dir.name) / "legacy.sqlite3"
        original_database = local_backend.DATABASE
        try:
            local_backend.DATABASE = legacy_database
            local_backend.initialize_database()
            with local_backend.get_db() as connection:
                state = local_backend.seed_state()
                state.pop("shopLayoutVersion", None)
                state["stalls"] = [
                    {"id": 1, "name": "New Canteen", "location": "KPRCAS", "status": "Open", "hours": "08:00–20:00"},
                    {"id": 2, "name": "Old Canteen", "location": "KPRCAS", "status": "Paused", "hours": "08:00–18:00"},
                ]
                state["orders"] = [{
                    "id": "CB1001", "studentId": "cb1024", "stallId": 2, "items": [],
                    "status": "Placed", "total": 10, "createdAt": "2026-10-11T00:00:00Z",
                }]
                connection.execute(
                    "UPDATE app_state SET payload = ? WHERE id = 1",
                    (json.dumps(state),),
                )
                local_backend.migrate_shop_layout(connection)
                migrated = local_backend.main_state(connection)
        finally:
            local_backend.DATABASE = original_database
        named_stalls = {stall["name"]: stall for stall in migrated["stalls"]}
        self.assertEqual(len([stall for stall in migrated["stalls"] if stall["id"] <= 8]), 8)
        self.assertEqual(named_stalls["Old Canteen Shop 1"]["status"], "Paused")
        self.assertEqual(migrated["orders"][0]["stallId"], 5)
        self.assertTrue(all(1 <= item["stallId"] <= 8 for item in migrated["menu"]))

    def test_food_catalog_upgrade_adds_realistic_foods_for_every_shop(self):
        with local_backend.get_db() as connection:
            state = local_backend.main_state(connection)
            state["menu"] = [item for item in state["menu"] if item["id"] != 138]
            edited_item = next(item for item in state["menu"] if item["id"] == 101)
            edited_item["name"] = "Owner's Pongal Recipe"
            edited_item["price"] = 72
            connection.execute(
                "UPDATE app_state SET payload = ? WHERE id = 1",
                (json.dumps(state),),
            )
            local_backend.migrate_food_catalog(connection)
            updated = local_backend.main_state(connection)

        items_by_shop = {
            stall_id: [item for item in updated["menu"] if item.get("stallId") == stall_id]
            for stall_id in range(1, 9)
        }
        self.assertEqual(len(updated["menu"]), 47)
        self.assertTrue(all(len(items) >= 4 for items in items_by_shop.values()))
        self.assertEqual(next(item for item in updated["menu"] if item["id"] == 101)["name"], "Owner's Pongal Recipe")
        self.assertEqual(next(item for item in updated["menu"] if item["id"] == 101)["price"], 72)
        self.assertEqual(next(item for item in updated["menu"] if item["id"] == 124)["name"], "Chocolate Milkshake")
        self.assertEqual(next(item for item in updated["menu"] if item["id"] == 101)["foodType"], "Veg")
        self.assertEqual(next(item for item in updated["menu"] if item["id"] == 110)["foodType"], "Non-Veg")
        self.assertEqual(next(item for item in updated["menu"] if item["id"] == 138)["name"], "Lemon Soda")
        self.assertTrue(all(item.get("foodType") in {"Veg", "Non-Veg"} for item in updated["menu"]))


if __name__ == "__main__":
    unittest.main()
