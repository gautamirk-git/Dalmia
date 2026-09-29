"""Checks the synthetic CSVs against the data dictionary and the 4 test scenarios.
Run: python3 validate_data.py
This is a rough sanity check only. The real filter/score logic is built in Step 8.
"""
import csv
import os
import sys

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load(name):
    with open(os.path.join(D, name)) as f:
        return list(csv.DictReader(f))


EXPECTED_COLS = {
    "orders.csv": ["order_id", "dealer_id", "sku_id", "quantity_tons", "order_datetime", "priority", "status"],
    "dealers.csv": ["dealer_id", "dealer_name", "district", "region", "service_tier"],
    "skus.csv": ["sku_id", "grade", "pack_type", "description"],
    "plants.csv": ["plant_id", "plant_name", "region", "has_rail_siding"],
    "warehouses.csv": ["warehouse_id", "warehouse_name", "type", "district", "region"],
    "inventory.csv": ["location_id", "sku_id", "on_hand_tons", "reserved_tons", "safety_stock_tons", "available_tons"],
    "plant_capacity.csv": ["plant_id", "sku_id", "free_capacity_tons_per_day", "dispatch_slots_free", "production_lead_time_hrs"],
    "transport_availability.csv": ["transport_id", "origin_id", "mode", "capacity_tons_available", "available_from"],
    "routes.csv": ["route_id", "from_id", "to_id", "mode", "transit_hours", "status", "disruption_note"],
    "freight_rates.csv": ["route_id", "rate_inr_per_ton"],
    "delivery_commitments.csv": ["order_id", "promised_by", "max_transit_hours", "penalty_flag"],
}
errors = []

data = {}
for fn, cols in EXPECTED_COLS.items():
    rows = load(fn)
    data[fn] = rows
    if list(rows[0].keys()) != cols:
        errors.append(f"{fn}: columns differ from dictionary")

orders = data["orders.csv"]
dealers = {r["dealer_id"] for r in data["dealers.csv"]}
skus = {r["sku_id"] for r in data["skus.csv"]}
plants = {r["plant_id"] for r in data["plants.csv"]}
whs = {r["warehouse_id"]: r for r in data["warehouses.csv"]}
locations = plants | set(whs)
routes = {r["route_id"]: r for r in data["routes.csv"]}
rate = {r["route_id"]: int(r["rate_inr_per_ton"]) for r in data["freight_rates.csv"]}
commit = {r["order_id"]: r for r in data["delivery_commitments.csv"]}

# --- referential integrity ---
for o in orders:
    if o["dealer_id"] not in dealers: errors.append(f"{o['order_id']}: unknown dealer")
    if o["sku_id"] not in skus: errors.append(f"{o['order_id']}: unknown sku")
    if o["order_id"] not in commit: errors.append(f"{o['order_id']}: no commitment")
for r in data["inventory.csv"]:
    if r["location_id"] not in locations: errors.append(f"inventory: unknown location {r['location_id']}")
    if r["sku_id"] not in skus: errors.append("inventory: unknown sku")
    if int(r["on_hand_tons"]) - int(r["reserved_tons"]) - int(r["safety_stock_tons"]) != int(r["available_tons"]):
        errors.append(f"inventory: available math wrong {r}")
for rid, r in routes.items():
    if r["from_id"] not in locations: errors.append(f"{rid}: unknown from {r['from_id']}")
    if r["to_id"] not in locations | dealers: errors.append(f"{rid}: unknown to {r['to_id']}")
    if rid not in rate: errors.append(f"{rid}: no freight rate")
for rid in rate:
    if rid not in routes: errors.append(f"freight_rates: unknown route {rid}")
for r in data["plant_capacity.csv"]:
    if r["plant_id"] not in plants or r["sku_id"] not in skus: errors.append("capacity: bad key")

# --- path building (simple version of the Step 7/8 logic) ---
stock = {(r["location_id"], r["sku_id"]): int(r["available_tons"]) for r in data["inventory.csv"]}
slots = {(r["plant_id"], r["sku_id"]): int(r["dispatch_slots_free"]) for r in data["plant_capacity.csv"]}
truck = {r["origin_id"]: int(r["capacity_tons_available"]) for r in data["transport_availability.csv"] if r["mode"] == "Truck"}
rail = {r["origin_id"]: int(r["capacity_tons_available"]) for r in data["transport_availability.csv"] if r["mode"] == "Rail"}
into = {}
for r in routes.values():
    into.setdefault(r["to_id"], []).append(r)


def paths_for(dealer):
    out = []
    for last in into.get(dealer, []):
        if last["from_id"] in whs and whs[last["from_id"]]["type"] == "Rail Depot":
            for first in into.get(last["from_id"], []):
                out.append([first, last])
        else:
            out.append([last])
    return out


def evaluate(o):
    qty, sku, cm = int(o["quantity_tons"]), o["sku_id"], commit[o["order_id"]]
    res = []
    for legs in paths_for(o["dealer_id"]):
        src = legs[0]["from_id"]
        hrs = sum(int(l["transit_hours"]) for l in legs)
        cost = sum(rate[l["route_id"]] for l in legs)
        avail = stock.get((src, sku), 0)
        why = None
        if avail < qty: why = f"stock shortage ({avail} t available, {qty} t needed)"
        elif any(l["status"] != "Open" for l in legs): why = "route disrupted"
        elif (src in plants and slots.get((src, sku), 0) == 0): why = "no dispatch slots"
        elif any((rail if l["mode"] == "Rail" else truck).get(l["from_id"], 0) < qty for l in legs): why = "transport capacity"
        elif hrs > int(cm["max_transit_hours"]): why = f"misses commitment ({hrs} h > {cm['max_transit_hours']} h)"
        cap = min((rail if l["mode"] == "Rail" else truck).get(l["from_id"], 0) for l in legs)
        res.append(dict(src=src, hrs=hrs, cost=cost, buffer=avail - qty, cap=cap, why=why,
                        via=" > ".join(l["from_id"] for l in legs)))
    return res


def scale(vals, higher_better):
    lo, hi = min(vals), max(vals)
    if hi == lo: return [50.0] * len(vals)
    return [((v - lo) if higher_better else (hi - v)) / (hi - lo) * 100 for v in vals]


results = {o["order_id"]: evaluate(o) for o in orders}

print("\n=== Candidate paths per order ===")
for o in orders:
    oid = o["order_id"]
    res = results[oid]
    ok = [p for p in res if not p["why"]]
    print(f"{oid} ({o['dealer_id']}, {o['sku_id']}, {o['quantity_tons']} t): {len(res)} paths, {len(ok)} feasible")
    if not ok: errors.append(f"{oid}: no feasible path")

def expect(oid, cond, msg):
    if not cond: errors.append(f"{oid}: {msg}")

r = results["ORD-1001"]
expect("ORD-1001", len(r) == 3 and all(not p["why"] for p in r), "hero should have 3 feasible paths")
by = {p["src"]: p for p in r}
expect("ORD-1001", (by["PLANT-A"]["hrs"], by["PLANT-A"]["cost"]) == (18, 900), "Plant A should be 18 h / 900")
expect("ORD-1001", (by["WH-B"]["hrs"], by["WH-B"]["cost"]) == (12, 940), "Warehouse B should be 12 h / X+40")
expect("ORD-1001", (by["PLANT-C"]["hrs"], by["PLANT-C"]["cost"]) == (30, 820), "Plant C should be 30 h / X-80")
expect("ORD-1001", by["PLANT-A"]["buffer"] <= 10, "Plant A should sit near safety threshold")

r = results["ORD-1002"]; w = {p["src"]: p for p in r}
expect("ORD-1002", w["WH-F"]["why"] and "stock" in w["WH-F"]["why"], "WH-F should fail on stock")
expect("ORD-1002", any(not p["why"] for p in r), "needs a feasible alternative")
r = results["ORD-1003"]; w = {p["src"]: p for p in r}
expect("ORD-1003", w["WH-G"]["why"] == "route disrupted", "WH-G route should be disrupted")
r = results["ORD-1004"]; w = {p["src"]: p for p in r}
expect("ORD-1004", w["PLANT-E"]["why"] == "no dispatch slots", "Plant E should have no slots")
r = results["ORD-1005"]; w = {p["src"]: p for p in r}
expect("ORD-1005", w["PLANT-A"]["why"] and "commitment" in w["PLANT-A"]["why"], "Plant A should miss commitment")
expect("ORD-1005", not w["WH-B"]["why"], "WH-B should pass")

print("\n=== Scenario detail ===")
for oid in ["ORD-1001", "ORD-1002", "ORD-1003", "ORD-1004", "ORD-1005"]:
    print(oid)
    for p in results[oid]:
        print(f"   {p['via']:<26} {p['hrs']:>3} h  INR {p['cost']:>4}/t  buffer {p['buffer']:>4} t  ->", p["why"] or "FEASIBLE")

# rough hero score check (weights 35/25/20/10/10) - formal version comes in Step 8
ok = [p for p in results["ORD-1001"] if not p["why"]]
t = scale([p["hrs"] for p in ok], False); c = scale([p["cost"] for p in ok], False)
b = scale([p["buffer"] for p in ok], True); k = scale([p["cap"] for p in ok], True)
pr = t  # High priority: rewards speed
scores = {p["src"]: round(.35*t[i] + .25*c[i] + .20*b[i] + .10*k[i] + .10*pr[i], 1) for i, p in enumerate(ok)}
print("\nRough hero scores (0-100):", scores)
if max(scores, key=scores.get) != "WH-B":
    errors.append(f"hero winner is {max(scores, key=scores.get)}, expected WH-B")

print("\nRESULT:", "PASS" if not errors else "FAIL")
for e in errors: print(" -", e)
sys.exit(1 if errors else 0)
