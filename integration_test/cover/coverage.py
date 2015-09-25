from __future__ import absolute_import
import unittest
from bs4 import BeautifulSoup
import os


class TestCoverage(unittest.TestCase):
    """ Ensure that our test coverage remains at a certain level. """
    min_overall_coverage = 80
    min_individual_coverage = 40

    def test_ensure_coverage(self):
        # Make sure coverage files exist.
        coverage_path = os.path.join(
            os.path.dirname(__file__), '../../htmlcov/index.html',
        )
        self.assertTrue(os.path.exists(coverage_path), coverage_path+' missing')
        html = open(coverage_path)
        soup = BeautifulSoup(html.read())
        html.close()
        self.ensure_individual_coverage(soup)
        self.ensure_overall_coverage(soup)

    def ensure_overall_coverage(self, soup):
        total_container = soup.findAll('tr', {'class': 'total'})[0]
        total_coverage = total_container('td', {'class': 'right'})[0].text[:-1]
        total_coverage = int(total_coverage)
        self.assertGreaterEqual(total_coverage, self.min_overall_coverage)

    def ensure_individual_coverage(self, soup):
        test_cases = soup.findAll('tr', {'class': 'file'})
        for tc in test_cases:
            coverage = tc('td', {'class': 'right'})[0].text[:-1]
            coverage = int(coverage)
            self.assertGreaterEqual(coverage, self.min_individual_coverage)
