"""
Regression tests for src.web.app's environment create/update routes.

Both routes previously read optional "name"/"thesis" JSON fields via
`payload.get("name", <default>)` and then unconditionally called
`.strip()` on the result. That pattern only applies the default when the
key is *missing* - a request body with an explicit `"name": null` (a
perfectly valid JSON payload a client could send) returned `None` from
`.get()` and crashed with `AttributeError: 'NoneType' object has no
attribute 'strip'`, turning into an unhandled 500. Fixed via the new
`_clean_str` helper; these tests cover the null, blank, and valid-value
cases for both the create and update routes.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.web import app as app_module


class TestEnvironmentPayloadHandling(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.tmpdir.name) / "environments.json"
        self.patcher = patch.object(app_module, "ENVIRONMENTS_PATH", self.env_path)
        self.patcher.start()
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.patcher.stop()
        self.tmpdir.cleanup()

    def test_create_environment_with_explicit_null_name_and_thesis(self):
        resp = self.client.post(
            "/api/environments", json={"name": None, "thesis": None, "tickers": "AAPL"}
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(body["name"], "Untitled Thesis")
        self.assertEqual(body["thesis"], "")

    def test_create_environment_with_blank_name_falls_back_to_default(self):
        resp = self.client.post("/api/environments", json={"name": "   ", "tickers": "AAPL"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["name"], "Untitled Thesis")

    def test_create_environment_preserves_valid_name_and_thesis(self):
        resp = self.client.post(
            "/api/environments", json={"name": " MSFT thesis ", "thesis": " growth story "}
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(body["name"], "MSFT thesis")
        self.assertEqual(body["thesis"], "growth story")

    def test_update_environment_with_explicit_null_name_keeps_existing_value(self):
        create = self.client.post(
            "/api/environments", json={"name": "Original Name", "thesis": "Original thesis"}
        )
        env_id = create.get_json()["id"]

        resp = self.client.put(f"/api/environments/{env_id}", json={"name": None, "thesis": None})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["name"], "Original Name")
        self.assertEqual(body["thesis"], "Original thesis")


if __name__ == "__main__":
    unittest.main()
