"""Tests for the plugin manifests and layout. Run: python3 -m unittest discover tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build  # noqa: E402


class PluginTest(unittest.TestCase):
    def test_manifests_agree_with_plugin_json(self):
        self.assertEqual(build.stale_manifests(), [], "edit the root plugin.json, then run python3 build.py")

    def test_skill_is_where_every_agent_looks(self):
        skill = build.check()
        self.assertEqual(os.path.relpath(skill, build.ROOT), os.path.join("skills", build.load("plugin.json")["name"]))
        self.assertTrue(os.path.isfile(os.path.join(skill, "scripts", "match_names.py")))

    def test_marketplaces_list_this_plugin(self):
        name = build.load("plugin.json")["name"]
        for path in build.MARKETPLACES:
            with self.subTest(path=path):
                self.assertEqual([p["name"] for p in build.load(path)["plugins"]], [name])

    def test_manifests_carry_a_version(self):
        # Without one, installs that pin a version never see an update.
        for path in ("plugin.json",) + build.PLUGIN_MANIFESTS:
            with self.subTest(path=path):
                self.assertRegex(build.load(path).get("version", ""), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
