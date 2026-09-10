"""Independent ERP server entry point."""
import argparse
from .server import serve


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] != 'serve':
        from .admin import main as manage
        return manage()
    parser = argparse.ArgumentParser(description='FlowERP 客户系统')
    parser.add_argument('command', choices=['serve'])
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--runtime-dir', default='.runtime')
    args = parser.parse_args()
    serve(args.host, args.port, args.runtime_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
