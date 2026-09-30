"""Automatic checks for the app.  Run: python3 test_app.py"""
import csv
import os
import unittest

os.environ.pop("NEO4J_URI", None)          # tests must never touch a real database

from fastapi.testclient import TestClient

import app as appmod
import fulfillment as f
import graph_store


def neo4j_shaped_rows():
    """Rows the way Neo4j would return them: real integers, None for empty notes, rate on the route."""
    folder = f.find_data_folder()
    rows = {}
    for name in f.TABLES:
        with open(os.path.join(folder, f"{name}.csv"), newline="") as fh:
            rows[name] = list(csv.DictReader(fh))
    int_cols = {"quantity_tons", "max_transit_hours", "available_tons", "dispatch_slots_free",
                "capacity_tons_available", "transit_hours", "rate_inr_per_ton"}
    for name, table in rows.items():
        for r in table:
            for k, v in list(r.items()):
                if k in int_cols:
                    r[k] = int(v)
                elif v == "":
                    r[k] = None
    rate = {r["route_id"]: r["rate_inr_per_ton"] for r in rows["freight_rates"]}
    for r in rows["routes"]:
        r["rate_inr_per_ton"] = rate[r["route_id"]]
    rows.pop("freight_rates")              # Neo4j has no separate rates table
    return rows


class AppTests(unittest.TestCase):
    def setUp(self):
        appmod._state.update(net=None, expires=0.0)
        self.client = TestClient(appmod.app)

    def test_home_page_loads(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Intelligent Fulfillment", r.text)
        self.assertIn("candidate systems", r.text)

    def test_health(self):
        j = self.client.get("/api/health").json()
        self.assertEqual(j["status"], "ok")
        self.assertEqual(j["data_source"], "builtin")

    def test_order_list(self):
        j = self.client.get("/api/orders").json()
        self.assertEqual(len(j["orders"]), 20)
        first = j["orders"][0]
        self.assertEqual(first["order_id"], "ORD-1001")
        self.assertEqual(first["scenario"], "Hero scenario")
        self.assertEqual(j["baseline_minutes"], 45.0)

    def test_hero_over_the_api(self):
        j = self.client.get("/api/evaluate/ORD-1001").json()
        self.assertEqual(j["recommended"], "WH-B")
        self.assertEqual([p["label"] for p in j["ranked"]], ["WH-B", "PLANT-C > DEPOT-D", "PLANT-A"])
        self.assertEqual(j["places"]["WH-B"]["name"], "Warehouse B")
        self.assertEqual(j["places"]["DEPOT-D"]["type"], "Rail Depot")
        self.assertEqual(j["ranked"][1]["legs"][0]["rupees_per_ton"], 520)

    def test_excluded_paths_carry_reasons(self):
        j = self.client.get("/api/evaluate/ORD-1002").json()
        self.assertEqual(j["excluded"][0]["label"], "WH-F")
        self.assertIn("Stock shortage", j["excluded"][0]["reasons"][0])

    def test_sliders_change_the_answer(self):
        j = self.client.get("/api/evaluate/ORD-1001?w=5,70,5,5,15").json()
        self.assertEqual(j["recommended"], "PLANT-C > DEPOT-D")

    def test_bad_requests(self):
        self.assertEqual(self.client.get("/api/evaluate/NOPE").status_code, 404)
        self.assertEqual(self.client.get("/api/evaluate/ORD-1001?w=1,2").status_code, 400)
        self.assertEqual(self.client.get("/api/evaluate/ORD-1001?w=a,b,c,d,e").status_code, 400)
        self.assertEqual(self.client.get("/api/evaluate/ORD-1001?w=0,0,0,0,0").status_code, 400)

    def test_neo4j_shaped_rows_give_identical_answers(self):
        net_csv = f.load_network_from_csv()
        net_neo = f.build_network(neo4j_shaped_rows())
        for oid in net_csv.orders:
            a, b = f.evaluate_order(net_csv, oid), f.evaluate_order(net_neo, oid)
            self.assertEqual(a["recommended"], b["recommended"], oid)
            self.assertEqual([p["total_score"] for p in a["ranked"]], [p["total_score"] for p in b["ranked"]], oid)
            self.assertEqual([p["reasons"] for p in a["excluded"]], [p["reasons"] for p in b["excluded"]], oid)

    def test_app_uses_the_graph_when_it_answers(self):
        orig = (graph_store.configured, graph_store.fetch_rows, graph_store.keepalive)
        calls = []
        graph_store.configured = lambda: True
        graph_store.fetch_rows = neo4j_shaped_rows
        graph_store.keepalive = lambda: calls.append("write")
        try:
            appmod._state.update(net=None, expires=0.0, last_keepalive=0.0)
            j = self.client.get("/api/health").json()
            self.assertEqual(j["data_source"], "graph")
            import time
            time.sleep(0.2)
            self.assertEqual(calls, ["write"])                       # the keep-alive write ran
            self.assertEqual(self.client.get("/api/evaluate/ORD-1001").json()["recommended"], "WH-B")
        finally:
            graph_store.configured, graph_store.fetch_rows, graph_store.keepalive = orig

    def test_app_falls_back_when_the_graph_is_paused(self):
        orig = (graph_store.configured, graph_store.fetch_rows)
        graph_store.configured = lambda: True

        def boom():
            raise ConnectionError("paused")
        graph_store.fetch_rows = boom
        try:
            appmod._state.update(net=None, expires=0.0)
            j = self.client.get("/api/evaluate/ORD-1001").json()
            self.assertEqual(j["data_source"], "builtin")
            self.assertIn("paused", j["note"])
            self.assertEqual(j["recommended"], "WH-B")               # the viewer still gets a full answer
        finally:
            graph_store.configured, graph_store.fetch_rows = orig

    def test_no_secrets_in_the_code(self):
        here = os.path.dirname(os.path.abspath(__file__))
        for name in ("app.py", "graph_store.py", "fulfillment.py"):
            with open(os.path.join(here, name)) as fh:
                text = fh.read().lower()
            self.assertNotIn("neo4j+s://", text)
            self.assertNotIn("databases.neo4j.io", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
