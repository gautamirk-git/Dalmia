"""Business logic for Dalmia POC 1 - Intelligent Fulfillment.

NO AI in this file. It finds candidate paths, filters out the infeasible ones
(with plain-English reasons), scores the rest, and ranks them.
The AI layer (Step 11) only re-words the result.

ALL DATA IS ILLUSTRATIVE (synthetic). Source systems named below are
"candidate systems, to be confirmed in discovery" - we do not claim to know
Dalmia's internal systems.

Try it:   python3 fulfillment.py ORD-1001
"""
import csv
import os
import sys
import time

# ---- Scoring weights (percent). Change these to change which path wins. ----
DEFAULT_WEIGHTS = {
    "delivery_time": 35,
    "freight_cost": 25,
    "inventory_risk": 20,
    "capacity": 10,
    "service_priority": 10,
}

# ---- Candidate source systems (to be confirmed in discovery) ----
SRC_ORDER = "SAP / order management (candidate system)"
SRC_INV = "SAP inventory / warehouse system (candidate system)"
SRC_PLANT = "Plant production & dispatch data (candidate system)"
SRC_TMS = "TMS / logistics and freight bids (candidate system)"


# =====================================================================
# 1. Loading the data
# =====================================================================
class Network:
    """A snapshot of orders, stock, capacity, transport and routes."""

    def __init__(self):
        self.orders = {}         # order_id -> row
        self.commitments = {}    # order_id -> row
        self.dealers = {}        # dealer_id -> row
        self.skus = {}           # sku_id -> row
        self.warehouses = {}     # warehouse_id -> row (includes rail depots)
        self.plants = {}         # plant_id -> row
        self.inventory = {}      # (location_id, sku_id) -> available tons (above safety stock)
        self.capacity = {}       # (plant_id, sku_id) -> dispatch slots free
        self.transport = {}      # (origin_id, mode) -> tons available
        self.routes = {}         # route_id -> row
        self.rates = {}          # route_id -> INR per ton
        self.routes_into = {}    # to_id -> [route rows]

    def is_rail_depot(self, place_id):
        w = self.warehouses.get(place_id)
        return bool(w) and w["type"] == "Rail Depot"

    def place_info(self, place_id):
        """Display name and type of any plant, warehouse, depot or dealer."""
        if place_id in self.plants:
            return {"name": self.plants[place_id].get("plant_name") or place_id, "type": "Plant"}
        if place_id in self.warehouses:
            w = self.warehouses[place_id]
            return {"name": w.get("warehouse_name") or place_id, "type": w.get("type") or "Warehouse"}
        if place_id in self.dealers:
            return {"name": self.dealers[place_id].get("dealer_name") or place_id, "type": "Dealer"}
        return {"name": place_id, "type": "Place"}


# Names of the tables build_network needs (same names as the CSV files).
TABLES = ["orders", "delivery_commitments", "dealers", "skus", "plants", "warehouses", "inventory",
          "plant_capacity", "transport_availability", "routes", "freight_rates"]


def build_network(rows):
    """Turns tables of rows (from CSV files OR from Neo4j) into a Network."""
    n = Network()
    n.orders = {r["order_id"]: r for r in rows["orders"]}
    n.commitments = {r["order_id"]: r for r in rows["delivery_commitments"]}
    n.dealers = {r["dealer_id"]: r for r in rows.get("dealers", [])}
    n.skus = {r["sku_id"]: r for r in rows.get("skus", [])}
    n.warehouses = {r["warehouse_id"]: r for r in rows["warehouses"]}
    n.plants = {r["plant_id"]: r for r in rows["plants"]}
    for r in rows["inventory"]:
        n.inventory[(r["location_id"], r["sku_id"])] = int(r["available_tons"])
    for r in rows["plant_capacity"]:
        n.capacity[(r["plant_id"], r["sku_id"])] = int(r["dispatch_slots_free"])
    for r in rows["transport_availability"]:
        n.transport[(r["origin_id"], r["mode"])] = int(r["capacity_tons_available"])
    n.routes = {r["route_id"]: r for r in rows["routes"]}
    rate_rows = rows.get("freight_rates") or rows["routes"]      # Neo4j keeps the rate on the route itself
    n.rates = {r["route_id"]: int(r["rate_inr_per_ton"]) for r in rate_rows}
    for r in n.routes.values():
        n.routes_into.setdefault(r["to_id"], []).append(r)
    if not n.orders or not n.routes:
        raise ValueError("The data source returned no orders or no routes.")
    return n


def _read(folder, name):
    with open(os.path.join(folder, name), newline="") as f:
        return list(csv.DictReader(f))


def find_data_folder():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "data"), here):
        if os.path.exists(os.path.join(cand, "orders.csv")):
            return cand
    raise FileNotFoundError("Could not find orders.csv next to this file or in a 'data' folder.")


def load_network_from_csv(folder=None):
    folder = folder or find_data_folder()
    return build_network({name: _read(folder, f"{name}.csv") for name in TABLES})


# =====================================================================
# 2. Candidate paths
# =====================================================================
def candidate_paths(net, dealer_id):
    """Every way to reach the dealer: a direct route, or plant -> rail -> depot -> dealer."""
    paths = []
    for last in net.routes_into.get(dealer_id, []):
        if net.is_rail_depot(last["from_id"]):
            for first in net.routes_into.get(last["from_id"], []):
                paths.append([first, last])
        else:
            paths.append([last])
    return paths


# =====================================================================
# 3. Filtering (feasibility) - returns plain-English reasons
# =====================================================================
def check_path(net, order, legs):
    qty = int(order["quantity_tons"])
    sku = order["sku_id"]
    src = legs[0]["from_id"]
    max_hours = int(net.commitments[order["order_id"]]["max_transit_hours"])
    hours = sum(int(l["transit_hours"]) for l in legs)

    available = net.inventory.get((src, sku), 0)
    slots = net.capacity.get((src, sku))           # only plants have dispatch slots
    transport_tons = [net.transport.get((l["from_id"], l["mode"]), 0) for l in legs]

    nm = lambda pid: net.place_info(pid)["name"]        # friendly names in the reasons
    reasons = []
    if available < qty:
        reasons.append(f"Stock shortage: {available} t available above safety stock at {nm(src)}, {qty} t needed")
    for l in legs:
        if l["status"] != "Open":
            note = f" ({l['disruption_note']})" if l.get("disruption_note") else ""
            reasons.append(f"Route disrupted: {nm(l['from_id'])} to {nm(l['to_id'])}{note}")
    if slots is not None and slots == 0:
        reasons.append(f"No dispatch slots free at {nm(src)}")
    for l, tons in zip(legs, transport_tons):
        if tons < qty:
            reasons.append(f"Not enough {l['mode'].lower()} capacity at {nm(l['from_id'])}: {tons} t available, {qty} t needed")
    if hours > max_hours:
        reasons.append(f"Misses the delivery promise: {hours} h transit, {max_hours} h allowed")

    return {
        "reasons": reasons,
        "available": available,
        "slots": slots,
        "transport_tons": transport_tons,
        "hours": hours,
        "max_hours": max_hours,
    }


# =====================================================================
# 4. Scoring (0-100 per factor, higher is better)
# =====================================================================
# Every feasible path scores between SCORE_FLOOR and 100 on each factor, so a path that
# passed all the checks never shows a "0". The ranking is the same as with a 0-100 scale.
SCORE_FLOOR = 40


def _scale(values, higher_is_better):
    lo, hi = min(values), max(values)
    if hi == lo:
        return [100.0] * len(values)     # nothing separates them, so nobody is penalised
    return [SCORE_FLOOR + (100 - SCORE_FLOOR) * ((v - lo) if higher_is_better else (hi - v)) / (hi - lo)
            for v in values]


def _normalise(weights):
    w = dict(DEFAULT_WEIGHTS)
    w.update(weights or {})
    if any(v < 0 for v in w.values()) or sum(w.values()) == 0:
        raise ValueError("Weights must be zero or more, and not all zero.")
    total = float(sum(w.values()))
    return {k: v / total for k, v in w.items()}


def score_paths(feasible, order, weights):
    """Adds scores to each feasible path. Standard orders lean on cost, High/Strategic on speed."""
    if not feasible:
        return
    w = _normalise(weights)
    time_s = _scale([p["hours"] for p in feasible], higher_is_better=False)
    cost_s = _scale([p["rupees_per_ton"] for p in feasible], higher_is_better=False)
    risk_s = _scale([p["stock_left"] for p in feasible], higher_is_better=True)
    cap_s = _scale([p["min_transport_tons"] for p in feasible], higher_is_better=True)
    urgent = order["priority"] in ("High", "Strategic")
    for i, p in enumerate(feasible):
        pri = time_s[i] if urgent else cost_s[i]
        p["scores"] = {
            "delivery_time": round(time_s[i], 1),
            "freight_cost": round(cost_s[i], 1),
            "inventory_risk": round(risk_s[i], 1),
            "capacity": round(cap_s[i], 1),
            "service_priority": round(pri, 1),
        }
        p["total_score"] = round(
            w["delivery_time"] * time_s[i] + w["freight_cost"] * cost_s[i] +
            w["inventory_risk"] * risk_s[i] + w["capacity"] * cap_s[i] +
            w["service_priority"] * pri, 1)


# =====================================================================
# 5. Plain-English (no AI) explanation
# =====================================================================
def _compare(win, other):
    bits = []
    dh = other["hours"] - win["hours"]
    bits.append(f"{abs(dh)} h faster" if dh > 0 else f"{abs(dh)} h slower" if dh < 0 else "same transit time")
    dc = win["rupees_per_ton"] - other["rupees_per_ton"]
    bits.append(f"₹{abs(dc)}/ton more" if dc > 0 else f"₹{abs(dc)}/ton less" if dc < 0 else "same freight")
    ds = win["stock_left"] - other["stock_left"]
    if ds:
        bits.append(f"{abs(ds)} t {'more' if ds > 0 else 'less'} stock left above safety level")
    return f"Compared with {other['name']}: " + ", ".join(bits) + "."


def explain(order, ranked, excluded):
    if not ranked:
        return ["No feasible path. Escalate to a planner."] + [f"{p['name']}: {'; '.join(p['reasons'])}" for p in excluded]
    win = ranked[0]
    lines = [f"Recommended: {win['name']} (score {win['total_score']}/100) - {win['hours']} h, "
             f"₹{win['rupees_per_ton']}/ton, {win['stock_left']} t left above safety stock."]
    fastest = min(ranked, key=lambda p: p["hours"])
    cheapest = min(ranked, key=lambda p: p["rupees_per_ton"])
    tags = []
    if win is fastest:
        tags.append("the fastest option")
    if win is cheapest:
        tags.append("the cheapest option")
    if tags:
        lines.append("It is " + " and ".join(tags) + ".")
    if cheapest is not win:
        lines.append(f"Trade-off: {cheapest['name']} is cheaper by ₹{win['rupees_per_ton'] - cheapest['rupees_per_ton']}/ton "
                     f"but takes {cheapest['hours'] - win['hours']} h longer.")
    for other in ranked[1:]:
        lines.append(_compare(win, other))
    for p in excluded:
        lines.append(f"Excluded {p['name']}: " + "; ".join(p["reasons"]) + ".")
    return lines


# =====================================================================
# 6. The main function
# =====================================================================
def evaluate_order(net, order_id, weights=None):
    t0 = time.perf_counter()
    order = net.orders[order_id]
    qty = int(order["quantity_tons"])
    sku = order["sku_id"]
    candidates, feasible, excluded = [], [], []

    for legs in candidate_paths(net, order["dealer_id"]):
        chk = check_path(net, order, legs)
        src = legs[0]["from_id"]
        label = src if len(legs) == 1 else f"{src} > {legs[-1]['from_id']}"
        name = " → ".join(net.place_info(pid)["name"] for pid in [src] + [l["from_id"] for l in legs[1:]])
        rate = sum(net.rates[l["route_id"]] for l in legs)
        p = {
            "label": label,
            "name": name,
            "source": src,
            "legs": [{"route_id": l["route_id"], "from": l["from_id"], "to": l["to_id"], "mode": l["mode"],
                      "hours": int(l["transit_hours"]), "status": l["status"],
                      "rupees_per_ton": net.rates[l["route_id"]]} for l in legs],
            "hours": chk["hours"],
            "rupees_per_ton": rate,
            "total_freight_inr": rate * qty,
            "stock_available": chk["available"],
            "stock_left": chk["available"] - qty,
            "dispatch_slots": chk["slots"],
            "min_transport_tons": min(chk["transport_tons"]),
            "promised_max_hours": chk["max_hours"],
            "secondary_movement": len(legs) > 1,     # extra handling via a depot
            "feasible": not chk["reasons"],
            "reasons": chk["reasons"],
            "facts": [
                ("Order quantity and priority", f"{qty} t, {order['priority']}", SRC_ORDER),
                ("Delivery promise", f"within {chk['max_hours']} h", SRC_ORDER),
                ("Stock available above safety level", f"{chk['available']} t at {src}", SRC_INV),
                ("Transit time", f"{chk['hours']} h", SRC_TMS),
                ("Freight rate", f"₹{rate}/ton", SRC_TMS),
                ("Truck / rail capacity", f"{min(chk['transport_tons'])} t", SRC_TMS),
            ] + ([("Dispatch slots free", f"{chk['slots']}", SRC_PLANT)] if chk["slots"] is not None else []),
        }
        candidates.append(p)
        (feasible if p["feasible"] else excluded).append(p)

    score_paths(feasible, order, weights)
    ranked = sorted(feasible, key=lambda p: (-p["total_score"], p["hours"], p["rupees_per_ton"]))
    for i, p in enumerate(ranked, 1):
        p["rank"] = i

    ids = {order["dealer_id"]}
    for p in candidates:
        for l in p["legs"]:
            ids.update((l["from"], l["to"]))
    return {
        "order_id": order_id,
        "dealer_id": order["dealer_id"],
        "sku_id": sku,
        "sku_description": net.skus.get(sku, {}).get("description", sku),
        "quantity_tons": qty,
        "priority": order["priority"],
        "promised_max_hours": int(net.commitments[order_id]["max_transit_hours"]),
        "places": {pid: net.place_info(pid) for pid in sorted(ids)},
        "weights_used": {k: round(v * 100, 1) for k, v in _normalise(weights).items()},
        "recommended": ranked[0]["label"] if ranked else None,
        "ranked": ranked,
        "excluded": excluded,
        "explanation": explain(order, ranked, excluded),
        "decision_time_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


# =====================================================================
# 7. Command-line view:  python3 fulfillment.py ORD-1001
# =====================================================================
def _print(res):
    print(f"\n{res['order_id']}  |  {res['quantity_tons']} t {res['sku_id']}  |  dealer {res['dealer_id']}  |  priority {res['priority']}")
    print(f"{'Rank':<5}{'Path':<22}{'Hours':>6}{'Rs/ton':>8}{'Left(t)':>9}{'Score':>8}   Factor scores (time/cost/stock/cap/priority)")
    for p in res["ranked"]:
        s = p["scores"]
        print(f"{p['rank']:<5}{p['label']:<22}{p['hours']:>6}{p['rupees_per_ton']:>8}{p['stock_left']:>9}{p['total_score']:>8}   "
              f"{s['delivery_time']}/{s['freight_cost']}/{s['inventory_risk']}/{s['capacity']}/{s['service_priority']}")
    for p in res["excluded"]:
        print(f"OUT  {p['label']:<22}{p['hours']:>6}{p['rupees_per_ton']:>8}          " + "; ".join(p["reasons"]))
    print()
    for line in res["explanation"]:
        print("  " + line)
    print(f"\n  (decision computed in {res['decision_time_ms']} ms)")


if __name__ == "__main__":
    network = load_network_from_csv()
    ids = sys.argv[1:] or ["ORD-1001"]
    for oid in ids:
        _print(evaluate_order(network, oid))
