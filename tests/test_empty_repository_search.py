"""Run the offline app-VM contract for same-query repository discovery."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EmptyRepositorySearchTests(unittest.TestCase):
    def test_same_query_transition_and_empty_state_boundaries(self):
        result = subprocess.run(['node', str(ROOT / 'tests/empty_repository_search_ui.cjs')],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Curated empty-result repository transition passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
