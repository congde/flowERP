import argparse, getpass, json, tempfile
from pathlib import Path
from . import EcommerceDemo, ERPService, ERPStore
from .config import load_settings
from .identity import IdentityService
from .mock_data import load_mock_data, verify_mock_data
from .operations import BackupService, HealthService, RuntimeCoordinator
from .server import serve
from .http_bind import ServerBindError, report_bind_error

def main():
    parser=argparse.ArgumentParser(description="FlowERP 客户项目管理")
    sub=parser.add_subparsers(dest="command",required=True)
    demo_cmd = sub.add_parser("demo", help="客户项目：跑通一条 FlowERP 演示账本")
    demo_cmd.add_argument("--runtime-dir")
    mock_cmd = sub.add_parser("mock-data", help="客户项目：生成幂等的完整 ERP 验收账套")
    mock_cmd.add_argument("--runtime-dir", default=".runtime")
    verify_mock_cmd = sub.add_parser("verify-mock-data", help="客户项目：验证完整 ERP 验收账套")
    verify_mock_cmd.add_argument("--runtime-dir", default=".runtime")
    serve_cmd = sub.add_parser("serve", help="客户项目：启动 FlowERP（默认 :8000）")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8000)
    serve_cmd.add_argument("--runtime-dir", help="覆盖本机 services.json 中保存的数据目录")
    init_cmd = sub.add_parser("init", help="初始化组织和管理员")
    init_cmd.add_argument("--runtime-dir", default=".runtime")
    init_cmd.add_argument("--organization", default="FlowERP")
    init_cmd.add_argument("--username", default="admin")
    backup_cmd = sub.add_parser("backup", help="创建一致性数据库备份")
    backup_cmd.add_argument("--runtime-dir", default=".runtime")
    backup_cmd.add_argument("--output-dir", default=".runtime/backups")
    backup_cmd.add_argument("--label", default="manual")
    verify_cmd = sub.add_parser("verify-backup", help="验证备份可恢复")
    verify_cmd.add_argument("--runtime-dir", default=".runtime")
    verify_cmd.add_argument("--path", required=True)
    check_cmd = sub.add_parser("doctor", help="检查服务就绪状态")
    check_cmd.add_argument("--runtime-dir", default=".runtime")
    status_cmd = sub.add_parser("runtime-status", help="查看运行协调状态")
    status_cmd.add_argument("--runtime-dir", default=".runtime")
    maintenance_cmd = sub.add_parser("maintenance", help="启用或关闭业务写入维护模式")
    maintenance_cmd.add_argument("mode", choices=("on", "off"))
    maintenance_cmd.add_argument("--runtime-dir", default=".runtime")
    maintenance_cmd.add_argument("--reason", default="")
    maintenance_cmd.add_argument("--actor", default="cli-operator")
    args=parser.parse_args()
    if args.command == "serve":
            try:
                serve(args.host, args.port, args.runtime_dir)
            except ServerBindError as error:
                return report_bind_error(error)
            return 0
    if args.command in {"mock-data", "verify-mock-data"}:
            runtime = Path(args.runtime_dir); store = ERPStore(runtime / "flowerp.db")
            result = load_mock_data(store) if args.command == "mock-data" else verify_mock_data(store)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            complete = result["verification"]["complete"] if args.command == "mock-data" else result["complete"]
            return 0 if complete else 1
    if args.command == "init":
            runtime = Path(args.runtime_dir); store = ERPStore(runtime / "flowerp.db")
            identity = IdentityService(store); identity.ensure_local_defaults()
            first = getpass.getpass("管理员密码（至少 10 位）: "); second = getpass.getpass("再次输入密码: ")
            if first != second: parser.error("两次输入的密码不一致")
            print(json.dumps(identity.bootstrap(args.organization, args.username, first), ensure_ascii=False, indent=2)); return 0
    if args.command == "backup":
            runtime = Path(args.runtime_dir); service = BackupService(ERPStore(runtime / "flowerp.db"), args.output_dir)
            print(json.dumps(service.create(args.label), ensure_ascii=False, indent=2)); return 0
    if args.command == "verify-backup":
            runtime = Path(args.runtime_dir); service = BackupService(ERPStore(runtime / "flowerp.db"), Path(args.path).parent)
            result = service.verify(args.path); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["ok"] else 1
    if args.command == "doctor":
            settings = load_settings(args.runtime_dir); runtime = settings.runtime_dir
            ok, result = HealthService(ERPStore(runtime / "flowerp.db", settings.database_busy_timeout_ms), runtime,
                                               settings.minimum_free_disk_mb, settings.backup_max_age_hours,
                                               settings.require_recent_backup).ready()
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if ok else 1
    if args.command == "runtime-status":
            runtime = Path(args.runtime_dir); store = ERPStore(runtime / "flowerp.db")
            print(json.dumps({"runtime": RuntimeCoordinator(store).status(), "leases": store.rows(
                "SELECT lease_name,owner_id,fencing_token,heartbeat_at,expires_at,expires_at>CURRENT_TIMESTAMP AS active "
                "FROM instance_leases ORDER BY lease_name")}, ensure_ascii=False, indent=2)); return 0
    if args.command == "maintenance":
            runtime = Path(args.runtime_dir); result = RuntimeCoordinator(ERPStore(runtime / "flowerp.db")).set_maintenance(
                args.mode == "on", args.reason, args.actor,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    if args.command == 'demo':
        with tempfile.TemporaryDirectory(prefix='flowerp-demo-') as temporary:
            service=ERPService(ERPStore(Path(args.runtime_dir or temporary)/'flowerp.db'))
            scenario=EcommerceDemo(service);scenario.reset()
            while not scenario.state()['is_complete']:scenario.advance()
            print(json.dumps({'scenario':scenario.state(),'inventory':service.inventory()},ensure_ascii=False))
        return 0
    return 1

if __name__ == '__main__':
    raise SystemExit(main())
