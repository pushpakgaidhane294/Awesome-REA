"""Visible nested-list links are checked, while actual code and literal text stay ignored."""
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_readme import plain_text
from validate import document_links, prose_only, validate_markdown


class RenderedLinks(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs).get('href'))


class MarkdownListLinksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / 'tests/fixtures/markdown_list_links.json').read_text())

    def test_visible_links_match_real_gfm_fixtures(self):
        self.assertEqual(self.fixture['mode'], 'gfm')
        self.assertIsNone(self.fixture['context'])
        self.assertTrue(self.fixture['cases'])
        for case in self.fixture['cases']:
            with self.subTest(case=case['id']):
                self.assertEqual(hashlib.sha256(case['html'].encode()).hexdigest(), case['html_sha256'])
                expected = [tuple(link) for link in case['expected_links']]
                self.assertEqual(Counter(RenderedLinks(case['html']).links), Counter(link[0] for link in expected))
                self.assertEqual(list(document_links(case['markdown'])), expected)

    def test_line_endings_and_original_prose_columns_are_preserved(self):
        for case in self.fixture['cases']:
            for ending, final_newline in [('\n', True), ('\r\n', True), ('\n', False)]:
                with self.subTest(case=case['id'], ending=ending, final_newline=final_newline):
                    text = case['markdown'].replace('\n', ending)
                    if not final_newline:
                        text = text.rstrip('\r\n')
                    masked = prose_only(text)
                    self.assertEqual(masked.count('\n'), text.count('\n'))
                    originals = text.splitlines(keepends=True)
                    for index, line in enumerate(masked.splitlines(keepends=True)):
                        if line.strip():
                            self.assertEqual(line, originals[index])
                    self.assertEqual(list(document_links(text)), [tuple(link) for link in case['expected_links']])

    def test_validator_reports_exact_missing_target_lines_without_code_errors(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'README.md'
            for case in self.fixture['cases']:
                with self.subTest(case=case['id']):
                    path.write_text(case['markdown'])
                    errors = []
                    validate_markdown(root, errors)
                    expected = [f'README.md:{line}: missing local link target: {destination}'
                                for destination, line in case['expected_links']]
                    self.assertEqual(errors, expected)

    def test_inline_code_delimiters_cannot_hide_links_in_other_blocks(self):
        cases = [
            ('- Parent\n  `unmatched\n    [Real](real.md)\n', [('real.md', 3)]),
            ('- Parent\n  `one\n    [Real](real.md)\n  ``two\n', [('real.md', 3)]),
            ('- Parent\n  \\`literal\n    [Real](real.md)\n  \\`literal\n', [('real.md', 3)]),
            ('- Parent\n  `unmatched\n\n  [Real](real.md) `later\n', [('real.md', 4)]),
            ('- `unmatched\n  # [Real](real.md)\n  `later\n', [('real.md', 2)]),
            ('- `unmatched\n- [Real](real.md) `later\n', [('real.md', 2)]),
            ('- Parent\n  ``code\n    [Code](hidden.md)\n  `` and [Real](real.md)\n', [('real.md', 4)]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(list(document_links(text)), expected)

    def test_preformatted_html_links_survive_and_do_not_swallow_later_prose(self):
        text = ('<pre>\nliteral text\n    [Code](hidden.md)\n'
                '    <a href="real.md#heading">Real</a><img src="image.svg">\n'
                '</pre>\n\n[After](after.md)\n')
        self.assertEqual(list(document_links(text)), [('after.md', 7), ('real.md#heading', 4), ('image.svg', 4)])
        unclosed_item = '- <pre>\n  literal text\n[After](after.md)\n'
        self.assertEqual(list(document_links(unclosed_item)), [('after.md', 3)])

    def test_current_literal_source_links_and_inline_code_stay_excluded(self):
        literal = plain_text('[literal](missing-literal.md#nope) and https://example.org')
        text = '- Parent\n    ' + literal + '\n    `[code](missing-code.md)` and [Real](missing-real.md)\n'
        self.assertEqual(list(document_links(text)), [('missing-real.md', 3)])
        self.assertIn(literal, prose_only(text))
        # A real code block needs four columns beyond this item's two-column prefix.
        code = '- Parent\n\n      [code](missing-code.md)\n    [Real](missing-real.md)\n'
        self.assertEqual(list(document_links(code)), [('missing-real.md', 4)])


if __name__ == '__main__':
    unittest.main()
