from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from flowerp.server import App, make_handler, _structured_log


class HTTPAPITests(unittest.TestCase):
    def test_stale_cookie_is_expired_without_authentication_bypass(self):
        from dataclasses import replace
        self.app.api.settings = replace(self.app.api.settings, auth_required=True)
        status, _, headers = self.request('GET', '/api/v1/auth/me', headers={'Cookie': 'flowerp_session=expired'})
        self.assertEqual(401, status)
        self.assertIn('Max-Age=0', headers['set-cookie'])
        self.assertEqual(401, self.request('GET', '/api/v1/auth/me')[0])


    def test_broken_log_stream_does_not_abort_request_processing(self) -> None:
        with patch("builtins.print", side_effect=BrokenPipeError):
            _structured_log({"event": "http_request"})

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(self.tmp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self, method: str, path: str, body: dict | None = None,
                headers: dict | None = None) -> tuple[int, object, dict]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        merged = {"Accept": "application/json", **(headers or {})}
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            merged["Content-Type"] = "application/json"
        conn.request(method, path, payload, merged)
        response = conn.getresponse()
        raw = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        conn.close()
        if "application/json" in response_headers.get("content-type", ""):
            return response.status, json.loads(raw.decode("utf-8")), response_headers
        return response.status, raw.decode("utf-8"), response_headers

    def test_static_application_has_security_headers(self) -> None:
        status, body, headers = self.request("GET", "/")
        self.assertEqual(200, status)
        self.assertIn("FlowERP", body)
        self.assertEqual("DENY", headers["x-frame-options"])
        self.assertIn("default-src 'self'", headers["content-security-policy"])
        self.assertEqual("nosniff", headers["x-content-type-options"])

    def test_application_shell_exposes_accessible_product_navigation(self) -> None:
        status, body, _ = self.request("GET", "/")
        self.assertEqual(200, status)
        self.assertIn('class="skip-link"', body)
        self.assertIn('id="global-search-button"', body)
        self.assertIn('id="command-backdrop"', body)
        self.assertIn('aria-labelledby="drawer-title"', body)
        self.assertIn('href="./styles.css?v=25"', body)
        self.assertIn('id="channel-orders-table"', body)
        self.assertIn('id="offline-form"', body)
        self.assertIn('id="returns-table"', body)
        self.assertIn('id="receipts-table"', body)
        self.assertIn('id="counts-table"', body)
        self.assertIn('for="inventory-keyword"', body)
        self.assertIn('id="inventory-keyword" type="search"', body)
        self.assertIn('id="inventory-clear" type="button"', body)
        self.assertIn('id="inventory-filter-status" role="status"', body)
        self.assertIn('仅筛选当前 API 已加载余额', body)
        self.assertIn('id="payments-table"', body)
        self.assertIn('id="bank-account-summary"', body)
        self.assertIn('id="bank-statements-table"', body)
        self.assertIn('id="periods-table"', body)
        self.assertIn('id="serials-table"', body)
        self.assertIn('id="pricing-table"', body)
        self.assertIn('id="reconciliations-table"', body)
        self.assertIn('id="alerts-table"', body)
        self.assertIn('id="import-result"', body)
        css_status, css, _ = self.request("GET", "/static/styles.css")
        self.assertEqual(200, css_status)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("focus-visible", css)
        relative_css_status, relative_css, _ = self.request("GET", "/styles.css")
        self.assertEqual(200, relative_css_status)
        self.assertEqual(css, relative_css)
        script_status, script, _ = self.request("GET", "/app.js")
        self.assertEqual(200, script_status)
        self.assertIn('location.protocol === "file:"', script)
        self.assertIn('/api/v1/sales/returns?limit=500', script)
        self.assertIn('/api/v1/purchases/receipts?limit=500', script)
        self.assertIn('/api/v1/finance/periods/reopen', script)
        self.assertIn('/api/v1/reports/ap-aging', script)
        self.assertIn('应收 / 应付账龄', body)
        self.assertIn('toast("系统初始化完成，已进入客户项目 FlowERP")', script)
        self.assertIn('toast("系统已初始化，已为您进入客户项目 FlowERP")', script)
        self.assertIn("客户项目", body)
        self.assertIn("http://127.0.0.1:8001", body)
        self.assertIn('>查看应收票</button>', script)
        self.assertIn('/api/v1/dashboard/trends?months=12', script)
        self.assertIn('id="dashboard-trend-chart"', body)
        self.assertRegex(body, r'src="\./app\.js\?v=\d+"')
        self.assertNotIn('prompt(', script)
        self.assertIn('x.processing_owner||"—"', script)
        self.assertIn('x.lease_expires_at', script)

    def test_static_path_traversal_is_blocked(self) -> None:
        status, _, _ = self.request("GET", "/static/../AGENTS.md")
        self.assertEqual(404, status)

    def test_health_and_setup_endpoints(self) -> None:
        status, body, headers = self.request("GET", "/api/v1/health/ready")
        self.assertEqual(200, status)
        self.assertEqual("ready", body["status"])
        self.assertIn("x-request-id", headers)
        status, body, _ = self.request("GET", "/api/v1/setup/status")
        self.assertEqual(200, status)
        self.assertFalse(body["initialized"])

    def test_channel_callback_api_enforces_named_lease_owner(self) -> None:
        principal = self.app.api._principal({})[0]
        product = self.app.api.master.create_product(principal, "HTTP-CALLBACK", "回传测试商品", 1000, 500)
        customer = self.app.api.master.create_customer(
            principal, "HTTP-PLATFORM", "平台结算客户", credit_limit_cents=100000,
        )
        shop = self.app.api.channels.create_shop(
            principal, "mock", "HTTP-SHOP", "API 沙箱店", customer["id"], "SITE-MAIN", "http-shop",
        )
        self.app.api.channels.map_listing(
            principal, shop["id"], "item-http", "sku-http", "API 商品",
            [{"product_id": product["id"], "quantity": 1, "revenue_share_basis_points": 10000}],
        )
        payload = {
            "external_order_id": "HTTP-ORDER-1", "external_status": "paid",
            "order_time": "2026-08-31T10:00:00+08:00", "currency": "CNY",
            "goods_cents": 1000, "total_cents": 1000, "recipient": "测试员",
            "phone": "13800138000", "province": "上海市", "city": "上海市", "street": "API 路 1 号",
            "lines": [{"external_line_id": "1", "external_product_id": "item-http",
                       "external_sku_id": "sku-http", "quantity": 1,
                       "unit_price_cents": 1000, "total_cents": 1000}],
        }
        order = self.app.api.channels.ingest_orders(principal, shop["id"], [payload])["items"][0]
        self.app.api.channels.cancel_order(principal, order["id"], "API 验证取消")

        claimed = self.app.api.dispatch(
            "POST", "/api/v1/channels/callbacks/claim", {},
            {"worker_id": "http-worker-a", "limit": 1, "lease_seconds": 60}, "127.0.0.1",
        )
        self.assertEqual(200, claimed.status)
        task = claimed.body["items"][0]
        wrong_owner = self.app.api.dispatch(
            "POST", f"/api/v1/channels/callbacks/{task['id']}/complete", {},
            {"success": True, "worker_id": "http-worker-b"}, "127.0.0.1",
        )
        self.assertEqual(409, wrong_owner.status)
        completed = self.app.api.dispatch(
            "POST", f"/api/v1/channels/callbacks/{task['id']}/complete", {},
            {"success": True, "worker_id": "http-worker-a"}, "127.0.0.1",
        )
        self.assertEqual(200, completed.status)
        self.assertEqual("succeeded", completed.body["status"])

    def test_bootstrap_login_and_authenticated_me(self) -> None:
        status, _, _ = self.request("POST", "/api/v1/setup/bootstrap", {
            "organization_name": "HTTP 测试组织",
            "username": "admin",
            "password": "Correct-Horse-2026",
        })
        self.assertEqual(201, status)
        status, body, headers = self.request("POST", "/api/v1/auth/login", {
            "organization": "DEFAULT",
            "username": "admin",
            "password": "Correct-Horse-2026",
        })
        self.assertEqual(200, status)
        self.assertIn("HttpOnly", headers["set-cookie"])
        token = body["token"]
        status, me, _ = self.request("GET", "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(200, status)
        self.assertEqual("admin", me["username"])
        self.assertIn("users.manage", me["permissions"])

    def test_write_requires_json_content_type(self) -> None:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        conn.request("POST", "/api/v1/products", "not-json", {"Content-Type": "text/plain"})
        response = conn.getresponse(); response.read(); conn.close()
        self.assertEqual(400, response.status)

    def test_idempotency_replays_same_api_request(self) -> None:
        body = {"sku": "HTTP-1", "name": "HTTP 商品", "sales_price_cents": 1000}
        headers = {"Idempotency-Key": "http-product-1"}
        first_status, first, first_headers = self.request("POST", "/api/v1/products", body, headers)
        second_status, second, second_headers = self.request("POST", "/api/v1/products", body, headers)
        self.assertEqual(201, first_status)
        self.assertEqual(201, second_status)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual("false", first_headers["idempotent-replay"])
        self.assertEqual("true", second_headers["idempotent-replay"])

    def test_idempotency_key_cannot_be_reused_for_different_payload(self) -> None:
        headers = {"Idempotency-Key": "same-key"}
        self.request("POST", "/api/v1/products", {"sku": "HTTP-A", "name": "A"}, headers)
        status, body, _ = self.request("POST", "/api/v1/products", {"sku": "HTTP-B", "name": "B"}, headers)
        self.assertEqual(409, status)
        self.assertEqual("conflict", body["error"]["code"])







if __name__ == "__main__":
    unittest.main()
