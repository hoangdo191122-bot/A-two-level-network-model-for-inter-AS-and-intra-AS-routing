import ipaddress
import networkx as nx
from models import BGPUpdate

ORIGIN_ORDER = {'IGP': 0, 'EGP': 1, 'Incomplete': 2}

class Router:
    def __init__(self, router_id, as_number, topology, ip_address=None):
        self.router_id   = router_id
        self.as_number   = as_number
        self.topology    = topology
        self.ip_address  = ip_address
        self.adj_rib_in  = {}
        self.loc_rib     = {}
        self.adj_rib_out = {}

    def receive_update(self, update):
        prefix = update.prefix
        if prefix not in self.adj_rib_in:
            self.adj_rib_in[prefix] = []
        self.adj_rib_in[prefix].append(update)
        self.run_bgp_decision_process(prefix)

    def run_intra_as_dijkstra(self, target_node_id):
        same_as  = [n for n in self.topology.as_membership
                    if self.topology.as_membership[n] == self.as_number]
        subgraph = self.topology.graph.subgraph(same_as)
        dist, path = nx.single_source_dijkstra(
            subgraph, self.router_id, target_node_id, weight='weight')
        return dist, path

    def run_bgp_decision_process(self, prefix):
        candidates = self.adj_rib_in.get(prefix, [])
        if not candidates:
            return

        def sort_key(upd):
            try:
                dist, _ = self.run_intra_as_dijkstra(upd.next_hop)
            except Exception:
                dist = float('inf')
            return (
                -getattr(upd, 'weight', 0),
                -upd.local_pref,
                len(upd.as_path),
                ORIGIN_ORDER.get(upd.origin, 2),
                upd.med,
                dist,
            )

        self.loc_rib[prefix] = min(candidates, key=sort_key)

    def get_next_hop(self, dst_ip, target_router_id):
        """
        Pure decision: given current RIB + Dijkstra, return the single next
        router-id this router would forward to — or None on failure.
        Does NOT mutate any state.
        """
        if self.router_id == target_router_id:
            return None  # already there

        dst = ipaddress.ip_address(dst_ip)
        best_update = None
        for prefix_str, update in self.loc_rib.items():
            if dst in ipaddress.ip_network(prefix_str):
                best_update = update
                break
        if best_update is None:
            return None

        target_as = best_update.as_path[-1]
        next_as   = best_update.as_path[0]

        # ── Inside destination AS: Dijkstra directly to target router ──
        if self.as_number == target_as:
            try:
                _, path = self.run_intra_as_dijkstra(target_router_id)
                return path[1] if len(path) > 1 else None
            except Exception:
                return None

        # ── Not yet in destination AS: head toward border router ────────
        next_hop_id = best_update.next_hop
        if next_hop_id != self.router_id:
            # Intra-AS Dijkstra toward the border router
            try:
                _, path = self.run_intra_as_dijkstra(next_hop_id)
                return path[1] if len(path) > 1 else None
            except Exception:
                return None

        # ── We ARE the border router: cross to next AS ──────────────────
        for neighbor_id in self.topology.graph.neighbors(self.router_id):
            if self.topology.as_membership[neighbor_id] == next_as:
                return neighbor_id
        return None
