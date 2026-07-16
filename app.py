import json
import random
import time

from flask import Flask, render_template, jsonify, request, Response

from main import generate_topology, generate_prefixes, setup_bgp

app = Flask(__name__)

CURRENT_TOPO = None
CURRENT_ROUTERS = None
CURRENT_PREFIXES = None

# Tuning: how slow the simulation runs (seconds between hops)
HOP_DELAY_SECONDS = 1.6

# Cascading probability that a 1st / 2nd / 3rd / 4th link changes weight
# after a given hop. Rolled in order, stops at the first failed roll.
WEIGHT_CHANGE_PROBABILITIES = (1.0, 0.6, 0.2, 0.1)


# ──────────────────────────────────────────────────────────────────────────
# Path / cost helpers
# ──────────────────────────────────────────────────────────────────────────

def compute_full_path(src, dst_id, routers, topo):
    """
    Computes a full path by repeatedly calling get_next_hop() — exactly the
    per-hop decision logic the live simulation uses — but instantly, with
    the topology exactly as it is *right now*. Used to snapshot the
    'planned' path before anything changes.
    """
    path = [src]
    current_id = src
    visited = {src}
    dst_router = routers[dst_id]

    for _ in range(60):
        if current_id == dst_id:
            break
        nxt = routers[current_id].get_next_hop(dst_router.ip_address, dst_id)
        if nxt is None or nxt in visited:
            break
        path.append(nxt)
        visited.add(nxt)
        current_id = nxt

    return path


def compute_path_cost(path, topo):
    total = 0
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        if topo.graph.has_edge(u, v):
            total += topo.graph[u][v].get('weight', 0)
        else:
            total += 999  # broken link fallback
    return total


def apply_weight_changes(topo, planned_path, current_id, locked_edges):
    """
    Cascading weight-change roll for the current hop: always changes one
    link, then has a 60% chance to also change a 2nd (distinct) link, a
    20% chance for a 3rd, and a 10% chance for a 4th. Stops as soon as a
    roll fails. Links the packet has already actually traversed this run
    (locked_edges) are excluded — their cost is now fixed for this run.
    Returns a list of change dicts (empty list if no edges are left to
    change).
    """
    edges = [e for e in topo.graph.edges() if frozenset(e) not in locked_edges]
    already_changed = set()
    changes = []

    try:
        idx = planned_path.index(current_id)
        remaining_planned_edges = {
            frozenset((planned_path[i], planned_path[i + 1]))
            for i in range(idx, len(planned_path) - 1)
        }
    except ValueError:
        remaining_planned_edges = set()

    for probability in WEIGHT_CHANGE_PROBABILITIES:
        if random.random() >= probability:
            break

        available = [e for e in edges if frozenset(e) not in already_changed]
        if not available:
            break

        u, v = random.choice(available)
        already_changed.add(frozenset((u, v)))

        old_w = topo.graph[u][v]['weight']
        new_w = random.randint(1, 25)
        if new_w == old_w:
            new_w = new_w + 1 if new_w < 25 else new_w - 1
        topo.update_link_weight(u, v, new_w)

        changes.append({
            "u": u, "v": v, "old": old_w, "new": new_w,
            "on_planned_path_ahead": frozenset((u, v)) in remaining_planned_edges
        })

    return changes


# ──────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/generate', methods=['POST'])
def generate():
    global CURRENT_TOPO, CURRENT_ROUTERS, CURRENT_PREFIXES
    data = request.json or {}
    num_as = int(data.get('num_as', 4))
    routers_per_as = int(data.get('routers_per_as', 5))

    CURRENT_TOPO, CURRENT_ROUTERS = generate_topology(num_as, routers_per_as)
    CURRENT_PREFIXES = generate_prefixes(num_as)
    setup_bgp(CURRENT_ROUTERS, CURRENT_TOPO, CURRENT_PREFIXES)

    borders = [r for r in CURRENT_ROUTERS if CURRENT_TOPO.is_border_router(r)]
    nodes = [{"id": n, "label": n, "group": CURRENT_TOPO.as_membership[n],
              "shape": "box" if n in borders else "dot"} for n in CURRENT_TOPO.graph.nodes()]
    edges = [{"from": u, "to": v, "label": str(CURRENT_TOPO.graph[u][v]['weight']),
              "font": {"align": "top", "size": 11}} for u, v in CURRENT_TOPO.graph.edges()]
    router_list = [{"id": r.router_id, "ip": r.ip_address, "as": r.as_number} for r in CURRENT_ROUTERS.values()]

    return jsonify({"nodes": nodes, "edges": edges, "routers": router_list})


@app.route('/api/router/<router_id>', methods=['GET'])
def get_router_info(router_id):
    if not CURRENT_ROUTERS or router_id not in CURRENT_ROUTERS:
        return jsonify({"error": "Router not found"}), 404

    router = CURRENT_ROUTERS[router_id]
    rib = [{"prefix": p, "as_path": u.as_path, "next_hop": u.next_hop,
            "local_pref": u.local_pref, "med": u.med} for p, u in router.loc_rib.items()]

    return jsonify({
        "id": router.router_id, "as_number": router.as_number, "ip": router.ip_address,
        "is_border": CURRENT_TOPO.is_border_router(router_id), "rib": rib
    })


@app.route('/api/simulate_stream')
def simulate_stream():
    """
    Server-Sent Events endpoint. Streams the live, per-hop routing process:

      planned_path  -> the path Dijkstra/BGP would choose right now (snapshot)
      hop           -> a router was just reached, forwarding decided live
      weight_changed-> a link's weight changed *during* transit
      done          -> destination reached; final cost comparison included

    Every hop, get_next_hop() is called fresh against the CURRENT topology
    state — this is the "per-hop Dijkstra" approach: no path is fixed in
    advance, each router decides locally and live.
    """
    src = request.args.get('src')
    dst_id = request.args.get('dst')

    try:
        hop_delay = max(0.1, min(5.0, int(request.args.get('delay', 1600)) / 1000.0))
    except (TypeError, ValueError):
        hop_delay = HOP_DELAY_SECONDS

    def stream():
        global CURRENT_TOPO, CURRENT_ROUTERS

        if not CURRENT_ROUTERS or src not in CURRENT_ROUTERS or dst_id not in CURRENT_ROUTERS:
            yield sse('error', {"message": "Invalid topology or router IDs"})
            return

        topo = CURRENT_TOPO
        routers = CURRENT_ROUTERS
        dst_router = routers[dst_id]

        # ── 1. Snapshot the planned path BEFORE anything changes ──────────
        planned_path = compute_full_path(src, dst_id, routers, topo)
        planned_cost_before = compute_path_cost(planned_path, topo)
        yield sse('planned_path', {"path": planned_path, "cost": planned_cost_before})
        time.sleep(hop_delay)

        # ── 2. Live, per-hop routing ────────────────────────────────────
        actual_path = [src]
        current_id = src
        visited = {src}
        weight_changes = []
        traversed_edges = set()  # links already crossed this run — cost is now locked
        hop_count = 0
        max_hops = 60

        while current_id != dst_id and hop_count < max_hops:
            # Cascading chance per hop: 100% / 60% / 20% / 10% for 1st,
            # 2nd, 3rd, 4th link weight change mid-transit. Already
            # traversed links are excluded and keep their fixed cost.
            hop_changes = apply_weight_changes(topo, planned_path, current_id, traversed_edges)
            if hop_changes:
                # Re-run BGP decision process network-wide once, so RIBs
                # reflect the new weights (mirrors an OSPF-style
                # reconvergence, simplified/instant here)
                setup_bgp(routers, topo, CURRENT_PREFIXES)

                for change in hop_changes:
                    weight_changes.append(change)
                    yield sse('weight_changed', change)
                    time.sleep(hop_delay * 0.6)

            # ── Per-hop decision: recompute next hop fresh, right now ────
            nxt = routers[current_id].get_next_hop(dst_router.ip_address, dst_id)

            if nxt is None:
                yield sse('error', {"message": f"No route found from {current_id}"})
                return
            if nxt in visited:
                yield sse('error', {"message": f"Loop detected at {nxt}, aborting"})
                return

            rerouted = False
            try:
                idx = planned_path.index(current_id)
                rerouted = (idx + 1 >= len(planned_path)) or (planned_path[idx + 1] != nxt)
            except ValueError:
                rerouted = True

            actual_path.append(nxt)
            visited.add(nxt)
            traversed_edges.add(frozenset((current_id, nxt)))
            hop_count += 1

            yield sse('hop', {
                "from": current_id, "to": nxt, "hop_number": hop_count,
                "rerouted": rerouted, "is_destination": nxt == dst_id
            })

            current_id = nxt
            time.sleep(hop_delay)

        # ── 3. Final cost comparison ────────────────────────────────────
        actual_cost = compute_path_cost(actual_path, topo)
        planned_cost_after = compute_path_cost(planned_path, topo)  # counterfactual: same old route, new weights

        updated_edges = [{"from": u, "to": v, "label": str(topo.graph[u][v]['weight']),
                           "font": {"align": "top", "size": 11}} for u, v in topo.graph.edges()]

        yield sse('done', {
            "planned_path": planned_path,
            "actual_path": actual_path,
            "weight_changes": weight_changes,
            "costs": {
                "planned_before_changes": planned_cost_before,
                "planned_after_changes": planned_cost_after,
                "actual": actual_cost
            },
            "updated_edges": updated_edges
        })

    return Response(stream(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)
