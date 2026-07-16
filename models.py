

class BGPUpdate:

    def __init__(self, prefix, as_path, next_hop, origin='IGP', local_pref=100, med=0, withdrawn_prefixes=None):
        
        self.prefix = prefix                
        
        # Well-known Mandatory Attributes 
        self.as_path = as_path              # list of as-nubers
        self.next_hop = next_hop            # IP of next boarderrouter to destination
        self.origin = origin                # origin (IGP, EGP, Incomplete)
        
        # Well-known Discretionary & Optional Attributes 
        self.local_pref = local_pref        # prefered router for exit 
        self.med = med                      # prefered router for entry 
        
        # information about no longer reachable prefixes
        self.withdrawn_prefixes = withdrawn_prefixes if withdrawn_prefixes else [] # [1, 11]

    def __repr__(self):
        return f"BGPUpdate(Prefix: {self.prefix}, AS_PATH: {self.as_path}, NextHop: {self.next_hop})"


class IPPackage:
    def __init__(self, src_ip, dst_ip, target_router_id=None, payload="Data"):
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.target_router_id = target_router_id  # NEW: Exact final destination node
        self.payload = payload
        self.hop_count = 0
        self.current_path = []

    def add_hop(self, router_id):
        self.hop_count += 1
        self.current_path.append(router_id)

    def __repr__(self):
        return f"IPPackage(To: {self.dst_ip} ({self.target_router_id}), Hops: {self.hop_count})"
