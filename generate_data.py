"""Generates the ILLUSTRATIVE synthetic CSV data for Dalmia POC 1.
No real Dalmia data is used. Run: python3 generate_data.py
"""
import csv
import os
import random
from datetime import datetime, timedelta

random.seed(42)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT, exist_ok=True)


def write(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


# ---------- SKUs ----------
skus = [
    ("SKU-OPC-BAG", "OPC", "Bag", "OPC, 50 kg bags"),
    ("SKU-PPC-BAG", "PPC", "Bag", "PPC, 50 kg bags"),
    ("SKU-PSC-BAG", "PSC", "Bag", "PSC, 50 kg bags"),
    ("SKU-PPC-BULK", "PPC", "Bulk", "PPC, bulk tanker"),
]
write("skus.csv", ["sku_id", "grade", "pack_type", "description"], skus)

# ---------- Plants ----------
plants = [
    ("PLANT-A", "Plant A", "Central", "N"),
    ("PLANT-C", "Plant C", "Central", "Y"),
    ("PLANT-E", "Plant E", "Central", "N"),
]
write("plants.csv", ["plant_id", "plant_name", "region", "has_rail_siding"], plants)

# ---------- Warehouses / depots ----------
# Rail depots are pass-through points in POC 1: they hold no stock.
warehouses = [
    ("WH-B", "Warehouse B", "Warehouse", "District-C1", "Central"),
    ("WH-F", "Warehouse F", "Warehouse", "District-C3", "Central"),
    ("WH-G", "Warehouse G", "Warehouse", "District-C5", "Central"),
    ("DEPOT-D", "Rail Depot D", "Rail Depot", "District-C2", "Central"),
    ("DEPOT-H", "Rail Depot H", "Rail Depot", "District-C6", "Central"),
]
write("warehouses.csv", ["warehouse_id", "warehouse_name", "type", "district", "region"], warehouses)

# ---------- Dealers ----------
tiers = ["Standard", "Preferred", "Strategic"]
dealers = []
for i in range(1, 16):
    did = f"DLR-{i:02d}"
    tier = "Preferred" if i in (3, 7, 11) else random.choice(tiers)
    dealers.append((did, f"Dealer {i:02d}", f"District-C{(i - 1) % 8 + 1}", "Central", tier))
write("dealers.csv", ["dealer_id", "dealer_name", "district", "region", "service_tier"], dealers)

# ---------- Inventory (on_hand, reserved, safety) ----------
inv = {
    # Plants: all 4 SKUs
    ("PLANT-A", "SKU-OPC-BAG"): (300, 90, 60),
    ("PLANT-A", "SKU-PPC-BAG"): (130, 45, 40),   # HERO: only 45 t above safety
    ("PLANT-A", "SKU-PSC-BAG"): (260, 70, 50),
    ("PLANT-A", "SKU-PPC-BULK"): (400, 100, 80),
    ("PLANT-C", "SKU-OPC-BAG"): (420, 110, 80),
    ("PLANT-C", "SKU-PPC-BAG"): (500, 120, 100),
    ("PLANT-C", "SKU-PSC-BAG"): (350, 90, 70),
    ("PLANT-C", "SKU-PPC-BULK"): (600, 150, 120),
    ("PLANT-E", "SKU-OPC-BAG"): (400, 100, 80),
    ("PLANT-E", "SKU-PPC-BAG"): (380, 110, 80),
    ("PLANT-E", "SKU-PSC-BAG"): (300, 80, 60),
    ("PLANT-E", "SKU-PPC-BULK"): (450, 120, 100),
    # Warehouses: bag SKUs only
    ("WH-B", "SKU-OPC-BAG"): (180, 50, 40),
    ("WH-B", "SKU-PPC-BAG"): (330, 80, 50),
    ("WH-B", "SKU-PSC-BAG"): (150, 40, 30),
    ("WH-F", "SKU-OPC-BAG"): (90, 40, 25),       # SCENARIO 2: only 25 t available
    ("WH-F", "SKU-PPC-BAG"): (200, 60, 40),
    ("WH-F", "SKU-PSC-BAG"): (160, 50, 30),
    ("WH-G", "SKU-OPC-BAG"): (110, 40, 30),
    ("WH-G", "SKU-PPC-BAG"): (220, 70, 40),
    ("WH-G", "SKU-PSC-BAG"): (240, 60, 40),
}
inv_rows = [(loc, sku, oh, rs, ss, oh - rs - ss) for (loc, sku), (oh, rs, ss) in inv.items()]
write("inventory.csv",
      ["location_id", "sku_id", "on_hand_tons", "reserved_tons", "safety_stock_tons", "available_tons"],
      inv_rows)

# ---------- Plant capacity ----------
cap_rows = []
for p, slots, cap, lead in [("PLANT-A", 3, 350, 24), ("PLANT-C", 4, 500, 20), ("PLANT-E", 2, 400, 28)]:
    for s in skus:
        sid = s[0]
        sl = slots
        if p == "PLANT-E" and sid == "SKU-PPC-BULK":
            sl = 0  # SCENARIO 4: no dispatch slots free
        cap_rows.append((p, sid, cap, sl, lead))
write("plant_capacity.csv",
      ["plant_id", "sku_id", "free_capacity_tons_per_day", "dispatch_slots_free", "production_lead_time_hrs"],
      cap_rows)

# ---------- Transport availability ----------
tr = [
    ("TR-01", "PLANT-A", "Truck", 120),   # HERO
    ("TR-02", "PLANT-C", "Truck", 250),
    ("TR-03", "PLANT-E", "Truck", 220),
    ("TR-04", "WH-B", "Truck", 200),      # HERO
    ("TR-05", "WH-F", "Truck", 160),
    ("TR-06", "WH-G", "Truck", 180),
    ("TR-07", "DEPOT-D", "Truck", 150),   # HERO last mile
    ("TR-08", "DEPOT-H", "Truck", 140),
    ("TR-09", "PLANT-C", "Rail", 300),    # HERO rail
]
tr_rows = [(t, o, m, c, "2026-10-05 09:00") for t, o, m, c in tr]
write("transport_availability.csv",
      ["transport_id", "origin_id", "mode", "capacity_tons_available", "available_from"], tr_rows)

# ---------- Routes and freight rates ----------
# X (illustrative base) = 900 INR/ton. Hero: A = X, B = X+40, C via rail = X-80.
routes = []   # (route_id, from, to, mode, transit_hours, status, note)
rates = []    # (route_id, rate_inr_per_ton)
_n = [0]


def add_route(frm, to, mode, hrs, rate, status="Open", note=""):
    _n[0] += 1
    rid = f"RT-{_n[0]:03d}"
    routes.append((rid, frm, to, mode, hrs, status, note))
    rates.append((rid, rate))


# Rail legs
add_route("PLANT-C", "DEPOT-D", "Rail", 22, 520)
add_route("PLANT-C", "DEPOT-H", "Rail", 26, 560)

# Scenario 1 (HERO) - DLR-03
add_route("PLANT-A", "DLR-03", "Truck", 18, 900)
add_route("WH-B", "DLR-03", "Truck", 12, 940)
add_route("DEPOT-D", "DLR-03", "Truck", 8, 300)     # rail 520 + truck 300 = 820 = X-80, 30 hrs

# Scenario 2 (stock shortage) - DLR-07: fastest source WH-F is short on OPC
add_route("WH-F", "DLR-07", "Truck", 10, 780)
add_route("PLANT-E", "DLR-07", "Truck", 16, 860)
add_route("PLANT-A", "DLR-07", "Truck", 20, 950)

# Scenario 3 (route disruption) - DLR-11: closest route is disrupted
add_route("WH-G", "DLR-11", "Truck", 9, 740, "Disrupted", "Bridge closure (illustrative)")
add_route("PLANT-A", "DLR-11", "Truck", 19, 910)
add_route("PLANT-E", "DLR-11", "Truck", 24, 1000)

# Scenario 4 (capacity limit) - DLR-05: Plant E has no dispatch slots for bulk
add_route("PLANT-E", "DLR-05", "Truck", 11, 800)
add_route("PLANT-A", "DLR-05", "Truck", 17, 890)
add_route("PLANT-C", "DLR-05", "Truck", 21, 980)

# Scenario 5 (tight commitment) - DLR-09
add_route("WH-B", "DLR-09", "Truck", 10, 760)
add_route("WH-F", "DLR-09", "Truck", 13, 820)
add_route("PLANT-A", "DLR-09", "Truck", 22, 960)

# Remaining dealers: 3 random direct sources each, plus a rail-depot option for some
special = {"DLR-03", "DLR-07", "DLR-11", "DLR-05", "DLR-09"}
direct_sources = ["PLANT-A", "PLANT-C", "PLANT-E", "WH-B", "WH-F", "WH-G"]
for d in dealers:
    did = d[0]
    if did in special:
        continue
    for src in random.sample(direct_sources, 3):
        hrs = random.randint(8, 30)
        rate = int(round((500 + 22 * hrs + random.randint(-40, 40)) / 10.0) * 10)
        add_route(src, did, "Truck", hrs, rate)
for did, depot in [("DLR-01", "DEPOT-D"), ("DLR-08", "DEPOT-D"), ("DLR-12", "DEPOT-H"), ("DLR-14", "DEPOT-H")]:
    add_route(depot, did, "Truck", random.randint(6, 10), 300)

write("routes.csv",
      ["route_id", "from_id", "to_id", "mode", "transit_hours", "status", "disruption_note"], routes)
write("freight_rates.csv", ["route_id", "rate_inr_per_ton"], rates)

# ---------- Orders and delivery commitments ----------
# (order_id, dealer, sku, qty, priority, max_transit_hours)
orders_spec = [
    ("ORD-1001", "DLR-03", "SKU-PPC-BAG", 40, "High", 36),      # HERO
    ("ORD-1002", "DLR-07", "SKU-OPC-BAG", 60, "Standard", 36),  # stock shortage
    ("ORD-1003", "DLR-11", "SKU-PSC-BAG", 50, "High", 36),      # route disruption
    ("ORD-1004", "DLR-05", "SKU-PPC-BULK", 80, "Standard", 36), # capacity limit
    ("ORD-1005", "DLR-09", "SKU-PPC-BAG", 30, "Strategic", 14), # tight commitment
]
others = [d[0] for d in dealers if d[0] not in special]
sku_ids = [s[0] for s in skus]
prios = ["Standard", "Standard", "High", "Strategic"]
for i in range(6, 21):
    dlr = others[(i - 6) % len(others)]
    sku = random.choice(sku_ids[:3])
    orders_spec.append((f"ORD-{1000 + i}", dlr, sku, random.choice([20, 25, 30, 40, 50]),
                        random.choice(prios), random.choice([36, 48])))

orders, commits = [], []
for k, (oid, dlr, sku, qty, pr, mx) in enumerate(orders_spec):
    hour = 8 + (k % 8)
    orders.append((oid, dlr, sku, qty, f"2026-10-05 {hour:02d}:00", pr, "New"))
    promised = (datetime(2026, 10, 5, hour) + timedelta(hours=mx)).strftime("%Y-%m-%d %H:%M")
    commits.append((oid, promised, mx, "Y" if pr in ("High", "Strategic") else "N"))
write("orders.csv",
      ["order_id", "dealer_id", "sku_id", "quantity_tons", "order_datetime", "priority", "status"], orders)
write("delivery_commitments.csv",
      ["order_id", "promised_by", "max_transit_hours", "penalty_flag"], commits)
