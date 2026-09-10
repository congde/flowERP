from __future__ import annotations

import tempfile

from datetime import date, timedelta

from pathlib import Path

from flowerp import ERPService, ERPStore, InventoryService, LedgerService, MasterDataService, ReportService, SalesService

from flowerp.finance import FinanceService

from flowerp.cash_management import CashManagementService

from flowerp.channels import EcommerceChannelService

from flowerp.import_export import ImportExportService

from flowerp.identity import Principal, SYSTEM_PRINCIPAL

from flowerp.models import ApprovalRequired, Conflict, InsufficientStock, InvalidTransition, OrderLine, ValidationError

from flowerp.operations import BackupService

from flowerp.purchasing import PurchasingService

def _service() -> tuple[tempfile.TemporaryDirectory, ERPService]:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-")
    service = ERPService(ERPStore(Path(tmp.name) / "eval.db"))
    service.add_product("SKU-A", "验收商品", 1000, 2)
    return tmp, service

def stock_never_negative() -> str:
    tmp, service = _service()
    try:
        service.receive_stock("SKU-A", 5, "open")
        order = service.create_order("客户", [OrderLine("SKU-A", 6, 1000)], "SO-EVAL-NEG")
        try: service.reserve_order(order["id"])
        except InsufficientStock: pass
        else: raise AssertionError("库存不足仍然预占成功")
        stock = service.product("SKU-A")
        assert stock["available"] == 5 and stock["reserved"] == 0
        return "缺货请求被拒绝，库存未发生部分写入"
    finally: tmp.cleanup()

def receiving_is_idempotent() -> str:
    tmp, service = _service()
    try:
        first = service.receive_stock("SKU-A", 5, "receipt:001")
        second = service.receive_stock("SKU-A", 5, "receipt:001")
        assert first["on_hand"] == 5 and second["on_hand"] == 5 and second["idempotent_replay"]
        return "重复入库键只生效一次"
    finally: tmp.cleanup()

def inventory_export_is_stable() -> str:
    tmp, service = _service()
    try:
        service.add_product("EXPORT-B", "导出商品 B", 2000, 1000)
        service.add_product("EXPORT-A", "导出商品 A", 1000, 500)
        service.receive_stock("EXPORT-B", 2, "export-b")
        service.receive_stock("EXPORT-A", 3, "export-a")
        content = service.export_inventory()
        lines = (content[1:] if content.startswith("\ufeff") else content).splitlines()
        assert lines[0] == "sku,name,site,location,lot_id,on_hand,reserved,available"
        assert lines[1].startswith("EXPORT-A,") and lines[2].startswith("EXPORT-B,")
        assert lines[1].endswith(",3,0,3") and lines[2].endswith(",2,0,2")
        assert service.product("EXPORT-A")["available"] == 3
        assert service.product("EXPORT-B")["available"] == 2
        from flowerp.identity import IdentityService
        IdentityService(service.store).ensure_local_defaults()
        v2 = ImportExportService(service.store).export_csv(SYSTEM_PRINCIPAL, "inventory")
        v2_lines = (v2[1:] if v2.startswith("\ufeff") else v2).splitlines()
        assert any(line.startswith("EXPORT-A,") and line.endswith(",3,0,3") for line in v2_lines)
        return "库存导出字段固定、按 SKU 排序，且门面/导出/v2 账本的 available 是同一个数"
    finally:
        tmp.cleanup()

def cancellation_releases_reservation() -> str:
    tmp, service = _service()
    try:
        service.receive_stock("SKU-A", 5, "open")
        order = service.create_order("客户", [OrderLine("SKU-A", 3, 1000)], "SO-EVAL-CANCEL")
        service.reserve_order(order["id"]); service.cancel_order(order["id"])
        stock = service.product("SKU-A")
        assert stock["available"] == 5 and stock["reserved"] == 0
        return "取消 reserved 订单后完整释放预占"
    finally: tmp.cleanup()

def illegal_transition_is_blocked() -> str:
    tmp, service = _service()
    try:
        order = service.create_order("客户", [OrderLine("SKU-A", 1, 1000)], "SO-EVAL-STATE")
        try: service.ship_order(order["id"])
        except InvalidTransition: return "draft 订单不能跳过预占直接发货"
        raise AssertionError("非法状态迁移未被阻断")
    finally: tmp.cleanup()

def purchase_requires_approval() -> str:
    tmp, service = _service()
    try:
        purchase = service.propose_purchase("SKU-A", 7, "低于补货点", "PR-EVAL-APPROVAL")
        try: service.receive_purchase(purchase["id"], "receipt:pr")
        except ApprovalRequired: pass
        else: raise AssertionError("未审批采购被入库")
        service.approve_purchase(purchase["id"], "reviewer")
        service.receive_purchase(purchase["id"], "receipt:pr")
        assert service.product("SKU-A")["on_hand"] == 7
        return "未审批被阻断，审批后可入库"
    finally: tmp.cleanup()

def purchase_request_preserves_reason() -> str:
    tmp, service = _service()
    try:
        purchase = service.propose_purchase("SKU-A", 7, "低于补货点", "PR-EVAL-PROPOSE")
        assert purchase["id"] == "PR-EVAL-PROPOSE"
        assert purchase["status"] == "proposed" and purchase["quantity"] == 7
        assert purchase["reason"] == "低于补货点"
        try:
            service.propose_purchase("SKU-A", 0, "无效数量", "PR-EVAL-INVALID")
        except ValueError:
            pass
        else:
            raise AssertionError("零数量采购申请未被拒绝")
        assert all(item["id"] != "PR-EVAL-INVALID" for item in service.list_purchases())
        try:
            service.propose_purchase("SKU-A", 2, "  ", "PR-EVAL-NO-REASON")
        except ValueError:
            pass
        else:
            raise AssertionError("空白采购原因未被拒绝")
        assert all(item["id"] != "PR-EVAL-NO-REASON" for item in service.list_purchases())
        return "采购申请保留 SKU、数量、原因和稳定身份，无效数量或空白原因没有部分写入"
    finally:
        tmp.cleanup()

def order_total_matches_lines() -> str:
    tmp, service = _service()
    try:
        order = service.create_order("客户", [OrderLine("SKU-A", 3, 1250)], "SO-EVAL-TOTAL")
        assert order["total_cents"] == sum(line["line_total_cents"] for line in order["lines"]) == 3750
        return "订单总额与明细计算一致"
    finally: tmp.cleanup()

def ecommerce_channel_order_is_idempotent_and_guarded() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-channel-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        master = MasterDataService(store); inventory = InventoryService(store); channels = EcommerceChannelService(store)
        product = master.create_product(SYSTEM_PRINCIPAL, "EVAL-EC", "渠道验收商品", 12900, 6000)
        customer = master.create_customer(SYSTEM_PRINCIPAL, "EVAL-PLATFORM", "平台结算客户", credit_limit_cents=100000)
        shop = channels.create_shop(SYSTEM_PRINCIPAL, "mock", "EVAL-SHOP", "验收沙箱店", customer["id"], "SITE-MAIN", "eval-shop")
        channels.map_listing(SYSTEM_PRINCIPAL, shop["id"], "item-1", "sku-1", "验收商品",
                             [{"product_id": product["id"], "quantity": 1, "revenue_share_basis_points": 10000}])
        payload = {"external_order_id": "EC-ORDER-1", "external_status": "paid", "order_time": "2026-08-14T10:00:00+08:00",
                   "currency": "CNY", "goods_cents": 12900, "total_cents": 12900, "recipient": "验收员",
                   "phone": "13800138000", "province": "上海市", "city": "上海市", "street": "验证路 1 号",
                   "lines": [{"external_line_id": "1", "external_product_id": "item-1", "external_sku_id": "sku-1",
                              "quantity": 1, "unit_price_cents": 12900, "total_cents": 12900}]}
        first = channels.ingest_orders(SYSTEM_PRINCIPAL, shop["id"], [payload])
        replay = channels.ingest_orders(SYSTEM_PRINCIPAL, shop["id"], [payload])
        assert first["items"][0]["id"] == replay["items"][0]["id"] and replay["replay_count"] == 1
        inventory.receive(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK", 1, "eval-channel-stock", unit_cost_cents=6000)
        imported = channels.review_and_import(SYSTEM_PRINCIPAL, first["items"][0]["id"])
        assert imported["status"] == "imported"
        shortage = dict(payload); shortage["external_order_id"] = "EC-ORDER-2"; shortage["lines"] = [dict(payload["lines"][0], external_line_id="2", quantity=2, total_cents=25800)]; shortage["goods_cents"] = 25800; shortage["total_cents"] = 25800
        second = channels.ingest_orders(SYSTEM_PRINCIPAL, shop["id"], [shortage])["items"][0]
        try: channels.review_and_import(SYSTEM_PRINCIPAL, second["id"])
        except Conflict: pass
        else: raise AssertionError("渠道订单缺货仍完成预占")
        balance = inventory.balance(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK")
        assert balance["reserved"] == 1 and balance["available"] == 0
        return "渠道订单重放幂等，审单生成销售单并原子预占，缺货订单保留异常且未超卖"
    finally:
        tmp.cleanup()

def channel_callback_lease_is_exclusive_and_bounded() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-callback-lease-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        master = MasterDataService(store); channels = EcommerceChannelService(store)
        product = master.create_product(SYSTEM_PRINCIPAL, "EVAL-CALLBACK", "回传验收商品", 1000, 500)
        customer = master.create_customer(
            SYSTEM_PRINCIPAL, "EVAL-CALLBACK-PLATFORM", "回传平台客户", credit_limit_cents=100000,
        )
        shop = channels.create_shop(
            SYSTEM_PRINCIPAL, "mock", "EVAL-CALLBACK-SHOP", "回传验收店",
            customer["id"], "SITE-MAIN", "eval-callback-shop",
        )
        channels.map_listing(
            SYSTEM_PRINCIPAL, shop["id"], "item-callback", "sku-callback", "回传验收商品",
            [{"product_id": product["id"], "quantity": 1, "revenue_share_basis_points": 10000}],
        )
        payload = {
            "external_order_id": "EVAL-CALLBACK-ORDER-1", "external_status": "paid",
            "order_time": "2026-08-31T10:00:00+08:00", "currency": "CNY",
            "goods_cents": 1000, "total_cents": 1000, "recipient": "验收员",
            "phone": "13800138000", "province": "上海市", "city": "上海市", "street": "回传路 1 号",
            "lines": [{"external_line_id": "1", "external_product_id": "item-callback",
                       "external_sku_id": "sku-callback", "quantity": 1,
                       "unit_price_cents": 1000, "total_cents": 1000}],
        }
        order = channels.ingest_orders(SYSTEM_PRINCIPAL, shop["id"], [payload])["items"][0]
        channels.cancel_order(SYSTEM_PRINCIPAL, order["id"], "验收取消")
        claimed = channels.claim_callbacks(SYSTEM_PRINCIPAL, "eval-worker-a", limit=1, lease_seconds=60)
        assert len(claimed) == 1 and claimed[0]["status"] == "processing"
        assert claimed[0]["attempts"] == 1 and claimed[0]["processing_owner"] == "eval-worker-a"
        assert channels.claim_callbacks(SYSTEM_PRINCIPAL, "eval-worker-b", limit=1) == []
        try:
            channels.complete_callback(SYSTEM_PRINCIPAL, claimed[0]["id"], True, worker_id="eval-worker-b")
        except Conflict:
            pass
        else:
            raise AssertionError("非租约持有者确认了渠道回传")
        failed = channels.complete_callback(
            SYSTEM_PRINCIPAL, claimed[0]["id"], False, "platform throttled", "eval-worker-a",
        )
        assert failed["status"] == "failed" and failed["last_error"] == "platform throttled"
        assert failed["available_at"] > failed["created_at"]
        assert channels.claim_callbacks(SYSTEM_PRINCIPAL, "eval-worker-b", limit=1) == []
        return "渠道回传仅允许一个具名 Worker 持有租约；越权确认被阻断，失败保留证据并进入有界退避"
    finally:
        tmp.cleanup()

def production_schema_invariants() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-v2-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        assert store.scalar("SELECT MAX(version) FROM schema_migrations") >= 16
        assert store.scalar("SELECT COUNT(*) FROM permissions") >= 20
        assert store.integrity_check()["ok"]
        return "生产 Schema、权限字典、外键与数据库完整性检查通过"
    finally:
        tmp.cleanup()

def multi_location_transfer_conserves_stock() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-transfer-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        master = MasterDataService(store); inventory = InventoryService(store)
        product = master.create_product(SYSTEM_PRINCIPAL, "EVAL-X", "调拨验收商品", 1000, 500)
        target = master.create_location(SYSTEM_PRINCIPAL, "SITE-MAIN", "EVAL-BIN", "验收库位")
        inventory.receive(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK", 10, "eval-opening")
        inventory.transfer(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK", target["id"], 4, "eval-transfer")
        balances = inventory.list_balances(SYSTEM_PRINCIPAL, product_id=product["id"])
        assert sum(row["on_hand"] for row in balances) == 10
        assert sorted(row["on_hand"] for row in balances) == [4, 6]
        return "跨库位调拨前后库存总量守恒，来源与目标账一致"
    finally:
        tmp.cleanup()

def stale_stock_count_is_blocked() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-count-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        master = MasterDataService(store); inventory = InventoryService(store)
        product = master.create_product(SYSTEM_PRINCIPAL, "EVAL-C", "盘点验收商品", 1000, 500)
        inventory.receive(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK", 5, "count-opening")
        count = inventory.create_count(SYSTEM_PRINCIPAL, "LOC-MAIN-STOCK", "2026-08-13",
                                       [{"product_id": product["id"], "counted_quantity": 4}], "验收")
        inventory.receive(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK", 1, "count-change")
        try:
            inventory.post_count(SYSTEM_PRINCIPAL, count["id"])
        except Conflict:
            return "盘点快照后发生库存变化，过账被可靠阻断"
        raise AssertionError("过期盘点快照仍然成功过账")
    finally:
        tmp.cleanup()

def sales_credit_and_atomic_reservation() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-sales-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        master = MasterDataService(store); inventory = InventoryService(store); sales = SalesService(store)
        product = master.create_product(SYSTEM_PRINCIPAL, "EVAL-S", "销售验收商品", 1000, 500)
        customer = master.create_customer(SYSTEM_PRINCIPAL, "EVAL-CUS", "验收客户", credit_limit_cents=100000)
        inventory.receive(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK", 2, "sales-opening")
        order = sales.create_order(SYSTEM_PRINCIPAL, customer["id"], [{"product_id": product["id"], "quantity": 3}])
        sales.confirm(SYSTEM_PRINCIPAL, order["id"])
        try:
            sales.reserve(SYSTEM_PRINCIPAL, order["id"])
        except InsufficientStock:
            balance = inventory.balance(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK")
            assert balance["reserved"] == 0 and balance["available"] == 2
            return "正式销售订单缺货时整单回滚，没有部分预占"
        raise AssertionError("正式销售订单超卖未被阻断")
    finally:
        tmp.cleanup()

def backup_is_restorable() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-backup-")
    try:
        root = Path(tmp.name); store = ERPStore(root / "eval.db")
        backup = BackupService(store, root / "backups")
        created = backup.create("eval")
        verification = backup.verify(created["backup"])
        assert verification["ok"] and verification["integrity"]["schema_version"] >= 2
        return "在线备份校验和、解压与 SQLite 完整性复验全部通过"
    finally:
        tmp.cleanup()

def purchase_invoice_three_way_match() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-3way-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        buyer = Principal("eval-buyer", "ORG-DEFAULT", "buyer", "制单人", SYSTEM_PRINCIPAL.permissions)
        approver = Principal("eval-approver", "ORG-DEFAULT", "approver", "审批人", SYSTEM_PRINCIPAL.permissions)
        master = MasterDataService(store); purchasing = PurchasingService(store); finance = FinanceService(store)
        product = master.create_product(SYSTEM_PRINCIPAL, "EVAL-3W", "三单匹配商品", 10000, 6000)
        supplier = master.create_supplier(SYSTEM_PRINCIPAL, "EVAL-SUP", "验收供应商")
        purchase = purchasing.create_order(buyer, supplier["id"], "SITE-MAIN",
                                           [{"product_id": product["id"], "quantity": 3, "unit_price_cents": 6000}])
        purchasing.submit(buyer, purchase["id"]); purchasing.approve(approver, purchase["id"])
        line_id = purchasing.order(SYSTEM_PRINCIPAL, purchase["id"])["lines"][0]["id"]
        receipt = purchasing.create_receipt(SYSTEM_PRINCIPAL, purchase["id"], "LOC-MAIN-STOCK",
                                             [{"purchase_line_id": line_id, "accepted_quantity": 2}])
        purchasing.post_receipt(SYSTEM_PRINCIPAL, receipt["id"], "eval-3way")
        try:
            finance.create_invoice_from_purchase(
                SYSTEM_PRINCIPAL, purchase["id"], supplier_invoice_number="BAD-001",
                supplier_lines=[{"source_line_id": line_id, "quantity": 3, "unit_price_cents": 6000}],
            )
        except Conflict:
            pass
        else:
            raise AssertionError("供应商发票超过已收数量仍通过匹配")
        invoice = finance.create_invoice_from_purchase(
            SYSTEM_PRINCIPAL, purchase["id"], supplier_invoice_number="OK-001",
            supplier_lines=[{"source_line_id": line_id, "quantity": 2, "unit_price_cents": 6000}],
        )
        assert invoice["match_status"] == "matched" and invoice["lines"][0]["quantity"] == 2
        return "采购订单、已过账收货与供应商发票的数量和单价匹配通过，超收发票被阻断"
    finally:
        tmp.cleanup()

def payable_aging_tracks_open_supplier_exposure() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-ap-aging-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        buyer = Principal("eval-ap-buyer", "ORG-DEFAULT", "buyer", "采购制单", SYSTEM_PRINCIPAL.permissions)
        approver = Principal("eval-ap-approver", "ORG-DEFAULT", "approver", "采购审批", SYSTEM_PRINCIPAL.permissions)
        master = MasterDataService(store); purchasing = PurchasingService(store)
        finance = FinanceService(store); reports = ReportService(store)
        product = master.create_product(SYSTEM_PRINCIPAL, "EVAL-AP", "应付账龄验收商品", 10_000, 6_000)
        supplier = master.create_supplier(SYSTEM_PRINCIPAL, "EVAL-AP-SUP", "应付账龄验收供应商")

        def payable(due_offset: int, reference: str) -> dict:
            order = purchasing.create_order(
                buyer, supplier["id"], "SITE-MAIN",
                [{"product_id": product["id"], "quantity": 2, "unit_price_cents": 6_000}],
            )
            purchasing.submit(buyer, order["id"]); purchasing.approve(approver, order["id"])
            line_id = purchasing.order(SYSTEM_PRINCIPAL, order["id"])["lines"][0]["id"]
            receipt = purchasing.create_receipt(
                SYSTEM_PRINCIPAL, order["id"], "LOC-MAIN-STOCK",
                [{"purchase_line_id": line_id, "accepted_quantity": 2}],
            )
            purchasing.post_receipt(SYSTEM_PRINCIPAL, receipt["id"], f"eval-ap-{reference}")
            due = date.today() + timedelta(days=due_offset)
            return finance.create_invoice_from_purchase(
                SYSTEM_PRINCIPAL, order["id"],
                invoice_date=(due - timedelta(days=30)).isoformat(), due_date=due.isoformat(),
                supplier_invoice_number=reference,
            )

        current = payable(5, "EVAL-AP-CURRENT")
        overdue = payable(-20, "EVAL-AP-OVERDUE")
        allocated = overdue["total_cents"] // 2
        finance.record_payment(
            SYSTEM_PRINCIPAL, "disbursement", "supplier", supplier["id"], allocated,
            allocations=[{"invoice_id": overdue["id"], "amount_cents": allocated}],
        )
        aging = reports.ap_aging(SYSTEM_PRINCIPAL, date.today().isoformat())
        assert aging["buckets"]["current"] == current["total_cents"], aging
        assert aging["buckets"]["1_30"] == overdue["total_cents"] - allocated, aging
        assert aging["overdue_cents"] == reports.dashboard(SYSTEM_PRINCIPAL)["overdue_payable_cents"]
        try:
            reports.ap_aging(SYSTEM_PRINCIPAL, "2026-02-30")
        except ValidationError:
            pass
        else:
            raise AssertionError("无效应付账龄日期未被拒绝")
        return "应付账龄按到期日分桶，部分付款只保留未结余额，并与驾驶舱逾期应付一致"
    finally:
        tmp.cleanup()

def double_entry_fifo_and_subledger_reconciliation() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-ledger-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        master = MasterDataService(store); inventory = InventoryService(store)
        sales = SalesService(store); finance = FinanceService(store); ledger = LedgerService(store)
        product = master.create_product(SYSTEM_PRINCIPAL, "EVAL-GL", "总账验收商品", 12000, 5000)
        customer = master.create_customer(SYSTEM_PRINCIPAL, "EVAL-GL-C", "总账验收客户", credit_limit_cents=200000)
        inventory.receive(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK", 2, "eval-gl-a", unit_cost_cents=5000)
        inventory.receive(SYSTEM_PRINCIPAL, product["id"], "LOC-MAIN-STOCK", 2, "eval-gl-b", unit_cost_cents=7000)
        order = sales.create_order(SYSTEM_PRINCIPAL, customer["id"], [{"product_id": product["id"], "quantity": 3}])
        sales.confirm(SYSTEM_PRINCIPAL, order["id"]); sales.reserve(SYSTEM_PRINCIPAL, order["id"])
        shipment = sales.create_shipment(SYSTEM_PRINCIPAL, order["id"])
        sales.post_shipment(SYSTEM_PRINCIPAL, shipment["id"], "eval-gl-ship")
        move = store.row("SELECT total_cost_cents FROM stock_moves WHERE reference_id=?", (shipment["id"],))
        assert move and move["total_cost_cents"] == 17000, move
        invoice = finance.create_invoice_from_sales(SYSTEM_PRINCIPAL, order["id"])
        finance.record_payment(
            SYSTEM_PRINCIPAL, "receipt", "customer", customer["id"], invoice["total_cents"],
            external_reference="EVAL-GL-PAY",
            allocations=[{"invoice_id": invoice["id"], "amount_cents": invoice["total_cents"]}],
        )
        trial = ledger.trial_balance(SYSTEM_PRINCIPAL)
        reconciliation = ledger.reconcile_subledgers(SYSTEM_PRINCIPAL)
        assert trial["balanced"] and trial["debit_cents"] == trial["credit_cents"], trial
        assert reconciliation["ok"], reconciliation
        assert store.scalar("SELECT COUNT(*) FROM stock_moves WHERE valuation_status='pending'") == 0
        return "FIFO 销售成本、复式凭证、收款核销及库存/应收子账总账自动对账全部通过"
    finally:
        tmp.cleanup()

def bank_statement_control_and_reconciliation() -> str:
    tmp = tempfile.TemporaryDirectory(prefix="flowerp-eval-bank-")
    try:
        store = ERPStore(Path(tmp.name) / "eval.db")
        from flowerp.identity import IdentityService
        IdentityService(store).ensure_local_defaults()
        master = MasterDataService(store); finance = FinanceService(store); cash = CashManagementService(store)
        customer = master.create_customer(SYSTEM_PRINCIPAL, "EVAL-BANK-C", "银行对账验收客户")
        account = cash.create_account(SYSTEM_PRINCIPAL, "EVAL-BANK", "验收基本户", "验收银行", "1002")
        payment = finance.record_payment(
            SYSTEM_PRINCIPAL, "receipt", "customer", customer["id"], 25_800, "2026-08-14",
            external_reference="EVAL-BANK-TX", bank_account_id=account["id"],
        )
        try:
            cash.import_statement(
                SYSTEM_PRINCIPAL, account["id"], "BAD-BALANCE", "2026-08-01", "2026-08-31", 0, 1,
                [{"external_transaction_id": "BAD", "transaction_date": "2026-08-14",
                  "signed_amount_cents": 25_800}],
            )
        except Exception:
            pass
        else:
            raise AssertionError("不平银行对账单仍被导入")
        statement = cash.import_statement(
            SYSTEM_PRINCIPAL, account["id"], "EVAL-202608", "2026-08-01", "2026-08-31", 0, 25_800,
            [{"external_transaction_id": "EVAL-LINE-1", "transaction_date": "2026-08-14",
              "signed_amount_cents": 25_800, "reference": "EVAL-BANK-TX"}],
        )
        matched = cash.auto_match(SYSTEM_PRINCIPAL, statement["id"])
        assert matched["unmatched_count"] == 0 and matched["lines"][0]["payment_id"] == payment["id"]
        reconciled = cash.reconcile(SYSTEM_PRINCIPAL, statement["id"])
        assert reconciled["status"] == "reconciled"
        return "不平对账单被阻断，银行流水自动匹配收付款后与银行存款总账余额一致"
    finally:
        tmp.cleanup()
