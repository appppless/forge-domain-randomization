import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization.ui_models import (
    is_object_candidate_path,
    object_candidate_score,
    prune_nested_candidates,
)


class TestUIBuilderHelpers(unittest.TestCase):
    def test_prune_nested_candidates_keeps_parent_once(self):
        paths = [
            "/World/cup",
            "/World/cup/base_link",
            "/World/cup/base_link/visuals",
            "/World/plate",
        ]
        self.assertEqual(prune_nested_candidates(paths), ["/World/cup", "/World/plate"])

    def test_object_candidate_filters_internal_nodes(self):
        self.assertFalse(is_object_candidate_path("/World"))
        self.assertFalse(is_object_candidate_path("/World/rooms"))
        self.assertFalse(is_object_candidate_path("/World/rooms/room_2"))
        self.assertFalse(is_object_candidate_path("/World/cup/base_link"))
        self.assertFalse(is_object_candidate_path("/World/cup/base_link/visuals"))
        self.assertFalse(is_object_candidate_path("/World/rooms/kitchen/wall_0"))
        self.assertTrue(is_object_candidate_path("/World/cup"))

    def test_object_candidate_score_is_path_based_compatibility(self):
        self.assertGreater(object_candidate_score({"path": "/World/kitchen"}), 0)
        self.assertGreater(object_candidate_score({"path": "/World/kitchen/cup"}), 0)
        self.assertLess(object_candidate_score({"path": "/World/cup/base_link"}), 0)

    def test_prune_keeps_highest_selectable_ancestor(self):
        paths = [
            {"path": "/World/kitchen", "type_name": "Xform"},
            {"path": "/World/kitchen/cup", "type_name": "Xform"},
            {"path": "/World/kitchen/cup/base_link", "type_name": "Xform"},
        ]
        self.assertEqual(prune_nested_candidates(paths), ["/World/kitchen"])


if __name__ == "__main__":
    unittest.main()
