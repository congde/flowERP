import ast
from pathlib import Path
import tempfile
import unittest
from flowerp.server import App


class RepositoryBoundaryTests(unittest.TestCase):
    def test_business_application_has_no_workbench_imports_or_database(self):
        root = Path(__file__).resolve().parents[1]
        for path in (root / 'flowerp').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('workbench', 'agent')), str(path))
                elif isinstance(node, ast.Import):
                    self.assertFalse(any(n.name.startswith(('workbench', 'agent')) for n in node.names), str(path))
        with tempfile.TemporaryDirectory() as folder:
            app = App(folder)
            self.assertTrue((Path(folder) / 'flowerp.db').is_file())
            self.assertFalse((Path(folder) / 'workbench.db').exists())
            for endpoint in ('tasks', 'course/status', 'delivery/views', 'feedback', 'evolutions'):
                result = app.api.dispatch('GET', '/api/v1/' + endpoint, {}, {})
                self.assertEqual(410, result.status)
        html = (root / 'web/index.html').read_text(encoding='utf-8')
        self.assertNotIn('id="page-delivery"', html)
        self.assertNotIn('data-page="delivery"', html)
