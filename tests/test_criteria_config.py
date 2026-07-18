"""
Unit tests for the config-loading and validation helpers in
src/screener/criteria.py: load_criteria_from_config, validate_criteria,
and the unknown-criterion / bad-value branches of build_criteria_functions.

These were previously untested (0% coverage on load_criteria_from_config
and validate_criteria per `pytest --cov`).
"""

import unittest
import tempfile
import os
from pathlib import Path

from src.screener.criteria import (
    load_criteria_from_config,
    validate_criteria,
    build_criteria_functions,
)


class TestLoadCriteriaFromConfig(unittest.TestCase):
    """Test YAML config loading."""

    def test_missing_config_file_returns_empty_dict(self):
        """A nonexistent config path should warn and return {} rather than raise."""
        result = load_criteria_from_config('/nonexistent/path/config.yaml')
        self.assertEqual(result, {})

    def test_valid_config_returns_criteria_section(self):
        """A well-formed config file should surface screener.criteria."""
        content = (
            "screener:\n"
            "  criteria:\n"
            "    pe_max: 25\n"
            "    market_cap_min: 1000000000\n"
        )
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(content)
            path = f.name
        try:
            result = load_criteria_from_config(path)
            self.assertEqual(result, {'pe_max': 25, 'market_cap_min': 1000000000})
        finally:
            os.unlink(path)

    def test_config_missing_screener_section_returns_empty_dict(self):
        """A YAML file with no 'screener' key should return {} rather than KeyError."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write("other_section:\n  foo: bar\n")
            path = f.name
        try:
            result = load_criteria_from_config(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_malformed_yaml_returns_empty_dict(self):
        """Invalid YAML should be caught and logged, not raise, per the except Exception."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write("screener: [unclosed\n  criteria: {\n")
            path = f.name
        try:
            result = load_criteria_from_config(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_default_path_used_when_none_given(self):
        """Passing None should resolve to the repo's config/config.yaml (may or may not exist)."""
        # Just confirm it doesn't raise and returns a dict either way.
        result = load_criteria_from_config(None)
        self.assertIsInstance(result, dict)


class TestValidateCriteria(unittest.TestCase):
    """Test criteria key validation."""

    def test_valid_keys_pass(self):
        config = {'pe_max': 25, 'market_cap_min': 1000000000, 'positive_earnings': True}
        self.assertTrue(validate_criteria(config))

    def test_empty_config_is_valid(self):
        self.assertTrue(validate_criteria({}))

    def test_unknown_key_fails(self):
        config = {'pe_max': 25, 'made_up_criterion': 5}
        self.assertFalse(validate_criteria(config))

    def test_all_documented_keys_individually_valid(self):
        for key in (
            'market_cap_min', 'pe_max', 'current_ratio_min', 'debt_to_equity_max',
            'revenue_growth_min', 'positive_earnings', 'roe_min',
        ):
            with self.subTest(key=key):
                self.assertTrue(validate_criteria({key: 1}))


class TestBuildCriteriaFunctionsEdgeCases(unittest.TestCase):
    """Cover the unknown-key branch, which the happy-path test in
    test_screener.py doesn't exercise."""

    def test_unknown_criterion_is_skipped_not_raised(self):
        functions = build_criteria_functions({'not_a_real_criterion': 5})
        self.assertEqual(functions, [])

    def test_mix_of_valid_and_unknown_keeps_valid_only(self):
        functions = build_criteria_functions({'pe_max': 25, 'bogus_key': 1})
        names = [name for name, _ in functions]
        self.assertEqual(names, ['pe_max'])


if __name__ == '__main__':
    unittest.main()
