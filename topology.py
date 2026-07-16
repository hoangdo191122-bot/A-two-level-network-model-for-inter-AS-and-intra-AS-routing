import networkx as nx

class Topology:
    """
    Manages the physical network graph and maps routers to Autonomous Systems (AS).
    Acts as the 'Single Source of Truth' for the simulation.
    """
    def __init__(self):
        # Physical graph using NetworkX to store nodes (routers) and edges (links) 
        self.graph = nx.Graph() 
        # Dictionary mapping: {router_id: as_number}
        self.as_membership = {} 

    def add_router(self, router_id, as_number):
        """
        Adds a router to the topology and assigns it to a specific AS
        """
        self.graph.add_node(router_id) # Add the router as a node in the graph
        self.as_membership[router_id] = as_number # Map the router to its AS
    

    def add_link(self, u, v, weight):
        """
        Creates a physical connection between two routers with an initial IGP metric
        """
        self.graph.add_edge(u, v, weight=weight)
    

    def update_link_weight(self, u, v, new_weight):
        """
        Changes the IGP weight of an existing link during runtime
        Used for simulating dynamic network conditions 
        """
        self.graph[u][v]['weight'] = new_weight # Update the 'weight' 

    def is_border_router(self, router_id):
        """
        Determines whether a router is a boarder router or not by checking the neighbors
        """
        for neighbor in self.graph.neighbors(router_id):
            if self.as_membership[neighbor] != self.as_membership[router_id]:
                return True
        return False
    