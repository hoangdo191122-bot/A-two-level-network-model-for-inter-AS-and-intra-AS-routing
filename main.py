import random
import json
import networkx as nx
from topology import Topology
from router import Router
from models import BGPUpdate, IPPackage

def generate_topology(num_as, routers_per_as):
    topo = Topology()
    routers = {}

    for as_num in range(100, (num_as + 1) * 100, 100):
        for r in range(1, routers_per_as + 1):
            router_id = f'R{as_num}_{r}'
            topo.add_router(router_id, as_num)
            ip = f'10.{as_num // 100}.0.{r}'
            routers[router_id] = Router(router_id, as_num, topo, ip_address=ip)

    for as_num in range(100, (num_as + 1) * 100, 100):
        as_routers = [f'R{as_num}_{r}' for r in range(1, routers_per_as + 1)]
        for i in range(len(as_routers) - 1):
            topo.add_link(as_routers[i], as_routers[i + 1], random.randint(1, 10))

        for _ in range(routers_per_as):
            u, v = random.sample(as_routers, 2)
            if not topo.graph.has_edge(u, v):
                topo.add_link(u, v, random.randint(1, 10))

    as_list = list(range(100, (num_as + 1) * 100, 100))
    for i in range(len(as_list)):
        as_a = as_list[i]
        as_b = as_list[(i + 1) % len(as_list)]
        router_as_a = random.choice([f'R{as_a}_{r}' for r in range(1, routers_per_as + 1)])
        router_as_b = random.choice([f'R{as_b}_{r}' for r in range(1, routers_per_as + 1)])
        topo.add_link(router_as_a, router_as_b, random.randint(10, 20))

    return topo, routers

def generate_prefixes(num_as):
    prefixes = {}
    for as_num in range(100, (num_as + 1) * 100, 100):
        prefixes[as_num] = f'10.{as_num // 100}.0.0/24'
    return prefixes

def setup_bgp(routers, topo, prefixes):
    # 1. Build an AS-level graph to calculate actual BGP AS-Paths
    as_graph = nx.Graph()
    as_border_map = {} 
    
    for u, v in topo.graph.edges():
        as_u = topo.as_membership[u]
        as_v = topo.as_membership[v]
        if as_u != as_v:
            as_graph.add_edge(as_u, as_v)
            as_border_map[(as_u, as_v)] = u
            as_border_map[(as_v, as_u)] = v

    # 2. Distribute routes (reset RIBs first so this can also be called
    #    again later, e.g. to reconverge after a link weight change)
    for router_id, router in routers.items():
        router.adj_rib_in = {}
        router.loc_rib = {}
        router.adj_rib_out = {}

        own_prefix = prefixes[router.as_number]
        router.receive_update(BGPUpdate(
            prefix=own_prefix, as_path=[router.as_number], next_hop=router_id
        ))
        
        for target_as, prefix in prefixes.items():
            if target_as == router.as_number:
                continue
            
            try:
                # Find shortest AS path (e.g., [500, 600, 100, 200])
                path = nx.shortest_path(as_graph, router.as_number, target_as)
                next_as = path[1] # The immediate next AS hop
                next_hop_router = as_border_map[(router.as_number, next_as)]
                
                update = BGPUpdate(
                    prefix=prefix,
                    as_path=path[1:], # Store the rest of the path: [600, 100, 200]
                    next_hop=next_hop_router
                )
                router.receive_update(update)
            except nx.NetworkXNoPath:
                pass

def print_topology(topo):
    print("\n--- Topology Overview ---")
    print(f"Total Routers: {len(topo.graph.nodes)}")
    print(f"Total Links: {len(topo.graph.edges)}")
    as_edges = set()
    for u, v in topo.graph.edges():
        if topo.as_membership[u] != topo.as_membership[v]:
            as_edges.add(tuple(sorted([topo.as_membership[u], topo.as_membership[v]])))
    print("Inter-AS Links:")
    for a, b in sorted(as_edges):
        print(f"  AS{a} <---> AS{b}")
    print("-------------------------\n")

def export_for_web(topo, package_path):
    nodes = [{"id": n, "label": n, "group": topo.as_membership[n]} for n in topo.graph.nodes()]
    edges = [{"from": u, "to": v} for u, v in topo.graph.edges()]
    
    with open("network_data.json", "w") as f:
        json.dump({"nodes": nodes, "edges": edges, "path": package_path}, f)
    print("\n[+] Exported 'network_data.json' for the web visualizer!")

def weight_changer(package, topo):
    edges = list(topo.graph.edges())
    u, v = random.choice(edges)
    new_weight = random.randint(1, 20)
    print(f"  ⚡ Weight changed: {u} ↔ {v} → {new_weight}")
    topo.update_link_weight(u, v, new_weight)

def simulate_packet(src_router_id, dst_ip, routers, on_hop=None):
    print(f"\n{'='*50}")
    print(f"Package: {src_router_id} → {dst_ip}")
    print(f"{'='*50}")

    package = IPPackage(src_ip="10.0.0.1", dst_ip=dst_ip)
    routers[src_router_id].forward_package(package, routers, on_hop)

    print(f"\nPath: {' → '.join(package.current_path)}")
    print(f"Total Hops: {package.hop_count}")
    return package

if __name__ == '__main__':
    NUM_AS = 6
    ROUTERS_PER_AS = 10

    topo, routers = generate_topology(NUM_AS, ROUTERS_PER_AS)
    prefixes = generate_prefixes(NUM_AS)
    setup_bgp(routers, topo, prefixes)

    print_topology(topo)

    src = 'R500_1'
    dst_ip = '10.2.0.1'  

    print("--- Simulation without dynamic weight changes ---")
    package = simulate_packet(src, dst_ip, routers)
    
    # Export layout and routing path for the website
    export_for_web(topo, package.current_path)
