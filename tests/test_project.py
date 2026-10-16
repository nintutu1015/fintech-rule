import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project', ROOT / 'tools/project.py')
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)


class ProjectChecks(unittest.TestCase):
    def setUp(self):
        self.settings, self.sources = project.project_inputs(ROOT)
        self.text = project.render(ROOT)
        self.expectations = project.load_json(ROOT / 'tests/expectations.json')

    def test_public_project_needs_no_private_credentials(self):
        warnings = project.check(ROOT)
        self.assertEqual(len(warnings), 3)

    def test_group_cycle_is_rejected(self):
        changed = self.text.replace('Proxy = select,ALL_Filter,', 'Proxy = select,AI,')
        with self.assertRaisesRegex(ValueError, 'cycle'):
            project.validate(changed, self.settings, self.sources)

    def test_unknown_policy_is_rejected(self):
        changed = self.text.replace('FINAL,Proxy', 'DOMAIN,example.invalid,MissingGroup\nFINAL,Proxy')
        with self.assertRaisesRegex(ValueError, 'Unknown or missing policy'):
            project.validate(changed, self.settings, self.sources)

    def test_new_missing_policy_is_not_hidden_by_legacy_allowance(self):
        changed = self.text.replace('FINAL,Proxy', 'IP-CIDR,203.0.113.0/24,no-resolve\nFINAL,Proxy')
        with self.assertRaisesRegex(ValueError, 'Unknown or missing policy'):
            project.validate(changed, self.settings, self.sources)

    def test_conflicting_local_condition_is_rejected(self):
        changed = self.text.replace('FINAL,Proxy', 'DOMAIN-SUFFIX,bybit.biz,US\nFINAL,Proxy')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            project.validate(changed, self.settings, self.sources)

    def test_paypal_generic_rule_shadowing_is_detected(self):
        sources = copy.deepcopy(self.sources)
        item = next(x for x in sources['remote_rules'] if x['tag'] == 'Paypal')
        sources['remote_rules'].remove(item)
        sources['remote_rules'].append(item)
        with self.assertRaisesRegex(ValueError, 'priority regression'):
            project.check_expectations(project.parse_sections(self.text), sources, self.expectations)

    def test_local_node_option_cannot_disappear_from_ai(self):
        changed = self.text.replace('AI = select,Proxy,Auto,Fallback,LOCAL_NODE,', 'AI = select,Proxy,Auto,Fallback,')
        with self.assertRaisesRegex(ValueError, 'menu regression'):
            project.check_expectations(project.parse_sections(changed), self.sources, self.expectations)

    def test_credential_in_public_file_is_rejected_without_echoing_value(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = 'fixture-private-value'
            (root / 'bad.conf').write_text('https://example.invalid/?to' + 'ken=' + value)
            with self.assertRaisesRegex(ValueError, 'Potential credential') as error:
                project.scan_public(root)
            self.assertNotIn(value, str(error.exception))

    def test_force_tracked_private_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / '.local').mkdir()
            (root / '.local/private.json').write_text('{}')
            subprocess.run(['git', 'add', '-f', '.local/private.json'], cwd=root, check=True)
            with self.assertRaisesRegex(ValueError, 'private/generated path is tracked'):
                project.scan_public(root)

    def test_private_build_is_ignored_and_owner_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'project'
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(*project.IGNORED))
            (root / '.local').mkdir()
            private = {
                'schema_version': 1,
                'local_proxies': ['MyLocal = http,127.0.0.1,3128'],
                'remote_proxies': ['MESL = https://example.invalid/subscription'],
                'mitm_private': {},
            }
            (root / '.local/private.json').write_text(json.dumps(private))
            output = project.build(root)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertIn('MyLocal', output.read_text())
            self.assertNotIn('{{LOCAL_', output.read_text())
            with self.assertRaises(ValueError):
                project.build(root, output=root / 'public.lcf')
            self.assertFalse((root / 'public.lcf').exists())

    def test_public_source_cannot_read_private_path(self):
        with self.assertRaisesRegex(ValueError, 'private/generated'):
            project.source_path(ROOT, '.local/private.json')


if __name__ == '__main__':
    unittest.main()
