"""Automatic checks for fulfillment.py.  Run: python3 test_fulfillment.py"""
import unittest

import fulfillment as f


class FulfillmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.net = f.load_network_from_csv()

    def run_order(self, oid, weights=None):
        return f.evaluate_order(self.net, oid, weights)

    # ---- Scenario 1: the hero order ----
    def test_hero_has_three_feasible_paths(self):
        r = self.run_order("ORD-1001")
        self.assertEqual(sorted(p["label"] for p in r["ranked"]), ["PLANT-A", "PLANT-C > DEPOT-D", "WH-B"])
        self.assertEqual(r["excluded"], [])

    def test_hero_numbers_match_the_brief(self):
        r = self.run_order("ORD-1001")
        by = {p["label"]: p for p in r["ranked"]}
        self.assertEqual((by["PLANT-A"]["hours"], by["PLANT-A"]["rupees_per_ton"]), (18, 900))
        self.assertEqual((by["WH-B"]["hours"], by["WH-B"]["rupees_per_ton"]), (12, 940))        # X + 40
        self.assertEqual((by["PLANT-C > DEPOT-D"]["hours"], by["PLANT-C > DEPOT-D"]["rupees_per_ton"]), (30, 820))  # X - 80
        self.assertEqual(by["PLANT-A"]["stock_left"], 5)   # near the safety threshold

    def test_hero_ranking(self):
        r = self.run_order("ORD-1001")
        self.assertEqual(r["recommended"], "WH-B")
        self.assertEqual([p["label"] for p in r["ranked"]], ["WH-B", "PLANT-C > DEPOT-D", "PLANT-A"])

    def test_rail_path_counts_as_secondary_movement(self):
        r = self.run_order("ORD-1001")
        by = {p["label"]: p for p in r["ranked"]}
        self.assertTrue(by["PLANT-C > DEPOT-D"]["secondary_movement"])
        self.assertFalse(by["WH-B"]["secondary_movement"])

    # ---- Scenarios 2-5: paths that must be filtered out, with a reason ----
    def excluded_reason(self, oid, label):
        r = self.run_order(oid)
        hit = [p for p in r["excluded"] if p["label"] == label]
        self.assertEqual(len(hit), 1, f"{label} should be excluded for {oid}")
        return " ".join(hit[0]["reasons"]), r

    def test_stock_shortage(self):
        why, r = self.excluded_reason("ORD-1002", "WH-F")
        self.assertIn("Stock shortage", why)
        self.assertEqual(r["recommended"], "PLANT-E")

    def test_route_disruption(self):
        why, r = self.excluded_reason("ORD-1003", "WH-G")
        self.assertIn("Route disrupted", why)
        self.assertEqual(r["recommended"], "PLANT-A")

    def test_capacity_limit(self):
        why, r = self.excluded_reason("ORD-1004", "PLANT-E")
        self.assertIn("No dispatch slots", why)
        self.assertEqual(r["recommended"], "PLANT-A")

    def test_delivery_promise(self):
        why, r = self.excluded_reason("ORD-1005", "PLANT-A")
        self.assertIn("delivery promise", why)
        self.assertEqual(r["recommended"], "WH-B")

    # ---- General ----
    def test_every_order_gets_a_recommendation(self):
        for oid in self.net.orders:
            r = self.run_order(oid)
            self.assertIsNotNone(r["recommended"], f"{oid} has no feasible path")
            self.assertEqual(r["ranked"][0]["rank"], 1)

    def test_feasible_paths_never_score_below_the_floor(self):
        for oid in self.net.orders:
            for p in self.run_order(oid)["ranked"]:
                self.assertTrue(f.SCORE_FLOOR <= p["total_score"] <= 100, f"{oid} {p['label']} {p['total_score']}")
                for v in p["scores"].values():
                    self.assertTrue(f.SCORE_FLOOR <= v <= 100)

    def test_hero_scores(self):
        r = self.run_order("ORD-1001")
        for got, want in zip([p["total_score"] for p in r["ranked"]], [80.9, 69.25, 63.0]):
            self.assertAlmostEqual(got, want, delta=0.1)

    def test_changing_weights_can_change_the_winner(self):
        cost_heavy = {"delivery_time": 5, "freight_cost": 70, "inventory_risk": 5, "capacity": 5, "service_priority": 15}
        self.assertEqual(self.run_order("ORD-1001", cost_heavy)["recommended"], "PLANT-C > DEPOT-D")

    def test_bad_weights_are_rejected(self):
        with self.assertRaises(ValueError):
            self.run_order("ORD-1001", {"delivery_time": -1})
        with self.assertRaises(ValueError):
            self.run_order("ORD-1001", {k: 0 for k in f.DEFAULT_WEIGHTS})

    def test_every_path_carries_source_system_facts(self):
        for p in self.run_order("ORD-1001")["ranked"]:
            self.assertTrue(all("candidate system" in fact[2] for fact in p["facts"]))

    def test_explanation_is_plain_text(self):
        r = self.run_order("ORD-1001")
        self.assertTrue(r["explanation"][0].startswith("Recommended: Warehouse B"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
