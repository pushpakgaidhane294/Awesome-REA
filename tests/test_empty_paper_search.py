"""Check homepage discovery hands queries to the existing paper directory."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EmptyPaperSearchTests(unittest.TestCase):
    def check_group(self, group):
        result = subprocess.run(['node', str(ROOT / 'tests/empty_paper_search_ui.cjs'), group],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Empty-result paper handoff passed: ' + group, result.stdout)

    def test_localized_link_and_real_degpt_handoff(self):
        self.check_group('localized')

    def test_literal_and_bounded_destination_query_contract(self):
        self.check_group('query')

    def test_empty_state_availability_reset_and_repository_behavior(self):
        self.check_group('boundaries')


if __name__ == '__main__':
    unittest.main()
