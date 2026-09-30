"""Reads the network from Neo4j (your Aura graph) and keeps the free instance awake.

The connection details come ONLY from environment variables (set in Render's dashboard):
    NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD      (NEO4J_DATABASE is optional)
Nothing secret is ever stored in the code or in GitHub.
"""
import os

# One query per table. The column names match the CSV files, so the same
# logic (fulfillment.build_network) can use either source.
QUERIES = {
    "orders": """
        MATCH (o:Order)-[:PLACED_BY]->(d:Dealer)
        MATCH (o)-[:FOR_PRODUCT]->(s:SKU)
        RETURN o.id AS order_id, d.id AS dealer_id, s.id AS sku_id, o.quantity_tons AS quantity_tons,
               o.order_datetime AS order_datetime, o.priority AS priority, o.status AS status""",
    "delivery_commitments": """
        MATCH (o:Order)-[:HAS_COMMITMENT]->(c:Commitment)
        RETURN o.id AS order_id, c.promised_by AS promised_by,
               c.max_transit_hours AS max_transit_hours, c.penalty_flag AS penalty_flag""",
    "dealers": """
        MATCH (d:Dealer)
        RETURN d.id AS dealer_id, d.name AS dealer_name, d.district AS district, d.service_tier AS service_tier""",
    "skus": """
        MATCH (s:SKU) RETURN s.id AS sku_id, s.description AS description""",
    "plants": """
        MATCH (p:Plant) RETURN p.id AS plant_id, p.name AS plant_name""",
    "warehouses": """
        MATCH (w:Warehouse) RETURN w.id AS warehouse_id, w.name AS warehouse_name, w.type AS type""",
    "inventory": """
        MATCH (l:Place)-[r:STOCKS]->(s:SKU)
        RETURN l.id AS location_id, s.id AS sku_id, r.available_tons AS available_tons""",
    "plant_capacity": """
        MATCH (p:Plant)-[:HAS_CAPACITY]->(c:Capacity)-[:FOR_SKU]->(s:SKU)
        RETURN p.id AS plant_id, s.id AS sku_id, c.dispatch_slots_free AS dispatch_slots_free""",
    "transport_availability": """
        MATCH (l:Place)-[:HAS_TRANSPORT]->(t:Transport)
        RETURN l.id AS origin_id, t.mode AS mode, t.capacity_tons_available AS capacity_tons_available""",
    "routes": """
        MATCH (a:Place)-[r:CONNECTS_TO]->(b:Place)
        RETURN r.route_id AS route_id, a.id AS from_id, b.id AS to_id, r.mode AS mode,
               r.transit_hours AS transit_hours, r.status AS status,
               r.disruption_note AS disruption_note, r.rate_inr_per_ton AS rate_inr_per_ton""",
}

# A tiny write. Neo4j Free pauses an instance after 3 days with no WRITE (reads and
# console logins do not count), so the app does this now and then while it is in use.
KEEPALIVE_QUERY = "MERGE (m:Meta {id: 'keepalive'}) SET m.last_seen = datetime() RETURN m.last_seen AS last_seen"


def configured():
    return all(os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"))


def _driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        connection_timeout=8,
    )


def _session(driver):
    return driver.session(database=os.environ.get("NEO4J_DATABASE") or None)


def fetch_rows():
    driver = _driver()
    try:
        with _session(driver) as session:
            return {name: [dict(rec) for rec in session.run(query)] for name, query in QUERIES.items()}
    finally:
        driver.close()


def keepalive():
    driver = _driver()
    try:
        with _session(driver) as session:
            return str(session.run(KEEPALIVE_QUERY).single()["last_seen"])
    finally:
        driver.close()
