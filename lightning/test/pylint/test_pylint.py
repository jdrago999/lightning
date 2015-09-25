"Generic docstring A"
from __future__ import absolute_import
from bs4 import BeautifulSoup

import logging
import os
import re
import subprocess
import unittest


class TestPyLint(unittest.TestCase):
    """Ensure that our pylint score stays above a certain level.
        Asserts: pylint score is above min_score
    """

    min_score = 7  # out of 10

    # Set path of pylint output.
    project_path = os.path.normpath(
        os.path.dirname(__file__) + '../../../..'
    )
    lint_path = os.path.join(
        project_path, 'pylint',
    )
    lint_file = None

    def setUp(self):
        """Run pylint and write output to lightning/pylint/index.html"""
        raise unittest.SkipTest("this doesn't work across all dev environments") 

        # Make sure our directory exists.
        try:
            os.chdir(self.lint_path)
        except:
            os.makedirs(self.lint_path)
        # Run the pylint command.
        cmd = 'pylint --rcfile=.pylintrc -f html lightning > pylint/index.html'
        pylint_proc = subprocess.Popen(
            cmd,
            cwd=self.project_path,
            stderr=subprocess.STDOUT,
            shell=True
        )
        # Write our process output.
        self.lint_file = open(self.lint_path + '/index.html', 'w+')
        while True:
            line = pylint_proc.communicate()[0]
            if not line:
                break
            self.lint_file.write(line)

    def test_ensure_lint(self):
        """Asserts that our pylint score is above a certain level."""
        self.assertTrue(os.path.exists(self.lint_path + '/index.html'))
        soup = BeautifulSoup(self.lint_file)
        self.lint_file.close()
        self.ensure_overall_lint(soup)

    def ensure_overall_lint(self, soup):
        """Parses score from pylint output and checks against min_score"""
        total_container = soup('h2', text='Global evaluation')[0]
        logging.info(total_container.parent.text)
        logging.info('Full Report: ' + self.lint_path + '/index.html')
        score = re.search('at ([0-9\.])+\/10', total_container.parent.text)
        score = score.group(0)[3:-3]
        score = float(score)
        self.assertGreaterEqual(score, self.min_score)

    def tearDown(self):
        """Switch our working dir back to the project."""
        # Reset our working dir or nosetests freaks out.
        os.chdir(self.project_path)
