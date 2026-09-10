"""L04 teaching probe. Load candidate code; retain evidence in a fresh directory.

This is an independent check, not a product exporter or a human acceptance.
Optional candidate file entry: function(store, target: pathlib.Path) -> None.
"""
from __future__ import annotations

import argparse
import builtins
import csv
import importlib
import inspect
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch


HEADERS = ['sku', 'name', 'site', 'location', 'lot_id', 'on_hand', 'reserved', 'available']


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def snapshot(store):
    with store.connect() as connection:
        return list(connection.iterdump())


def prepare(directory, scenario):
    from flowerp import ERPStore
    from flowerp.identity import IdentityService, SYSTEM_PRINCIPAL as principal
    from flowerp.master_data import MasterDataService
    from flowerp.inventory import InventoryService

    store = ERPStore(directory / 'practice.db')
    IdentityService(store).ensure_local_defaults()
    master, inventory = MasterDataService(store), InventoryService(store)
    expected = []
    if scenario == 'empty':
        return store, expected
    name = '螺丝,镀锌"加强"\n第二行' if scenario == 'special' else '螺丝'
    product = master.create_product(principal, 'P001', name, tracking='lot')
    # IDs come from the candidate's real lot API; they are not the printed lot numbers.
    lots = [inventory.create_lot(principal, product['id'], number)['id']
            for number in ('LOT01', 'LOT02')]
    entries = [('WEST', 'B01', lots[1], 12, 4), ('EAST', 'A01', lots[0], 8, 3)]
    if scenario == 'ordering':
        high, low = sorted(lots, reverse=True)
        entries = [('WEST', 'B01', high, 12, 4), ('EAST', 'A02', low, 9, 2),
                   ('EAST', 'A01', high, 8, 3), ('EAST', 'A01', low, 6, 1)]
    sites, locations = {}, {}
    for index, (site, location, lot, on_hand, reserved) in enumerate(entries):
        if site not in sites:
            sites[site] = master.create_site(principal, site, site)['id']
        if (site, location) not in locations:
            locations[site, location] = master.create_location(principal, sites[site], location, location)['id']
        location_id = locations[site, location]
        inventory.receive(principal, product['id'], location_id, on_hand, f'l04-{index}', lot_id=lot)
        inventory.reserve(principal, product['id'], location_id, reserved, 'l04-probe', str(index), lot_id=lot)
        expected.append(['P001', name, site, location, lot, str(on_hand), str(reserved), str(on_hand-reserved)])
    expected.sort(key=lambda row: (row[0], row[2], row[3], row[4]))
    return store, expected


def parsed(content):
    return list(csv.reader(io.StringIO(content.removeprefix('\ufeff'), newline='')))


def content_check(directory, scenario):
    from flowerp.identity import SYSTEM_PRINCIPAL
    from flowerp.import_export import ImportExportService

    store, expected = prepare(directory, scenario)
    before = snapshot(store)
    (directory / 'before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
    (directory / 'expected.json').write_text(json.dumps([HEADERS] + expected, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        content = ImportExportService(store).export_csv(SYSTEM_PRINCIPAL, 'inventory')
        # Evidence capture only: this write does not test the product's file publication.
        (directory / 'actual.csv').write_bytes(content.encode('utf-8'))
        require(parsed(content) == [HEADERS] + expected, 'CSV 与 expected.json 不一致：检查字段、明细、数量、排序和字符还原')
    finally:
        after = snapshot(store)
        (directory / 'after.json').write_text(json.dumps(after, ensure_ascii=False, indent=2), encoding='utf-8')
        require(before == after, '导出改变了数据库内容')


def file_check(directory, entry):
    store, expected = prepare(directory, 'normal')
    module_name, function_name = entry.split(':', 1)
    function = getattr(importlib.import_module(module_name), function_name)
    source = Path(inspect.getfile(function)).resolve()
    require(source.is_relative_to(Path.cwd()), '文件入口必须来自本次候选')
    (directory / 'entry.txt').write_text(f'{entry}\n{source}\n', encoding='utf-8')
    normal = directory / 'normal.csv'
    before = snapshot(store)
    function(store, normal)
    require(normal.is_file(), '文件入口没有生成正常 CSV')
    require(parsed(normal.read_text(encoding='utf-8')) == [HEADERS] + expected, '文件入口的正常 CSV 不符合合同')
    require(before == snapshot(store), '正常文件导出改变了数据库')
    old_bytes = normal.read_bytes()
    failures = []

    for existed in (True, False):
        attempt = directory / ('with-old' if existed else 'without-old')
        attempt.mkdir()
        target = attempt / 'inventory.csv'
        if existed:
            target.write_bytes(old_bytes)
        captured = {'triggered': False, 'error': None, 'writes': []}

        class FailingFile:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.wrapped.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

            def write(self, data):
                if not data:
                    return self.wrapped.write(data)
                self.wrapped.write(data[:max(1, len(data)//2)])
                self.wrapped.flush()
                captured['triggered'] = True
                raise OSError('L04_INJECTED_PARTIAL_WRITE')

            def writelines(self, lines):
                for line in lines:
                    self.write(line)

        def intercept(original):
            def open_file(file, mode='r', *args, **kwargs):
                opened = original(file, mode, *args, **kwargs)
                if isinstance(file, (str, bytes, Path)):
                    path = Path(file.decode() if isinstance(file, bytes) else file).resolve()
                    if path.is_relative_to(attempt) and any(flag in mode for flag in 'wax+'):
                        captured['writes'].append(str(path))
                        return FailingFile(opened)
                return opened
            return open_file

        prior = snapshot(store)
        (attempt / 'before.json').write_text(json.dumps(prior, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            with patch('builtins.open', intercept(builtins.open)), patch('io.open', intercept(io.open)):
                function(store, target)
        except Exception as error:
            captured['error'] = f'{type(error).__name__}: {error}'
        after = snapshot(store)
        (attempt / 'after.json').write_text(json.dumps(after, ensure_ascii=False, indent=2), encoding='utf-8')
        captured['database_unchanged'] = prior == after
        captured['target_preserved'] = target.is_file() and target.read_bytes() == old_bytes if existed else not target.exists()
        (attempt / 'evidence.json').write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding='utf-8')
        for passed, reason in (
            (captured['triggered'], '未触发中途写入异常；必须针对实际写入 API 调整注入点，不能判通过'),
            (captured['error'] is not None, '写入失败未向调用者报告异常'),
            (captured['database_unchanged'], '失败写出改变了数据库'),
            (captured['target_preserved'], '旧目标被破坏或留下目标半成品'),
        ):
            if not passed:
                failures.append(f'{attempt.name}: {reason}')
    require(not failures, '; '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True, help='B 的实际候选目录')
    parser.add_argument('--output', type=Path, required=True, help='尚不存在的证据目录')
    parser.add_argument('--case', choices=['content', 'normal', 'empty', 'special', 'ordering', 'file-failure', 'all'], required=True)
    parser.add_argument('--file-entry', help='候选模块:函数；签名为 function(store, target_path)')
    args = parser.parse_args()
    root, output = args.workspace.resolve(), args.output.resolve()
    if not (root / 'flowerp' / '__init__.py').is_file():
        parser.error('候选缺少 flowerp 包；先核对目录和课程起点')
    if output.exists():
        parser.error('证据目录已存在；请换一个新目录，保留上次失败记录')
    import os
    os.chdir(root)
    sys.path.insert(0, str(root))
    output.mkdir(parents=True)
    results = []
    cases = ['normal', 'empty', 'special', 'ordering'] if args.case in {'content', 'all'} else [args.case]
    if args.case == 'all':
        cases.append('file-failure')
    for scenario in cases:
        directory = output / scenario
        directory.mkdir()
        try:
            if scenario == 'file-failure':
                if not args.file_entry:
                    results.append({'case': scenario, 'status': 'blocked', 'reason': '未指定候选实际文件入口；尚未验证旧文件保护'})
                    continue
                file_check(directory, args.file_entry)
            else:
                content_check(directory, scenario)
            results.append({'case': scenario, 'status': 'pass'})
        except Exception as error:
            results.append({'case': scenario, 'status': 'fail', 'reason': f'{type(error).__name__}: {error}'})
    report = {'workspace': str(root), 'scope': '独立教学检查，不代表任务状态或具名验收', 'results': results}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (output / 'report.json').write_text(text, encoding='utf-8')
    print(text)
    return 1 if any(r['status'] == 'fail' for r in results) else 2 if any(r['status'] == 'blocked' for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
