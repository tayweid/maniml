"""
Graph theory objects for maniml.
"""

import numpy as np
from manim.renderer.opengl.mobject.types.vectorized_mobject import VGroup
from manim.renderer.opengl.mobject.geometry import Circle, Line, Arrow
from manim.renderer.opengl.mobject.svg.text_mobject import Text
from manim.renderer.opengl.constants import *
import warnings


class Graph(VGroup):
    """
    A graph visualization with vertices and edges.
    
    CE-compatible Graph implementation for ManimGL.
    """
    
    def __init__(
        self,
        vertices,
        edges,
        layout="circular",
        layout_config=None,
        vertex_config=None,
        edge_config=None,
        labels=False,
        label_config=None,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        self.vertices_list = list(vertices)
        self.edges_list = list(edges)
        
        # Default configs
        self.vertex_config = {
            "radius": 0.3,
            "color": BLUE,
            "fill_opacity": 0.5,
        }
        if vertex_config:
            self.vertex_config.update(vertex_config)
            
        self.edge_config = {
            "color": WHITE,
            "stroke_width": 2,
        }
        if edge_config:
            self.edge_config.update(edge_config)
            
        self.label_config = {
            "font_size": 24,
            "color": WHITE,
        }
        if label_config:
            self.label_config.update(label_config)
        
        # Create layout
        self.layout_config = layout_config or {}
        self.positions = self._compute_layout(layout)
        
        # Create graph elements
        self.vertices = {}
        self.edges = {}
        self.labels = {}
        
        self._create_vertices()
        self._create_edges()
        
        if labels:
            self._create_labels()
            
        # Add all to group
        self.add(*self.vertices.values())
        self.add(*self.edges.values())
        if labels:
            self.add(*self.labels.values())
    
    def _compute_layout(self, layout_type):
        """Compute vertex positions based on layout type."""
        n = len(self.vertices_list)
        positions = {}
        
        if layout_type == "circular":
            radius = self.layout_config.get("radius", 2.5)
            center = self.layout_config.get("center", ORIGIN)
            start_angle = self.layout_config.get("start_angle", 0)
            
            for i, vertex in enumerate(self.vertices_list):
                angle = start_angle + 2 * PI * i / n
                pos = center + radius * np.array([np.cos(angle), np.sin(angle), 0])
                positions[vertex] = pos
                
        elif layout_type == "tree":
            # Simple tree layout
            root = self.layout_config.get("root", self.vertices_list[0])
            layer_height = self.layout_config.get("layer_height", 1.5)
            layer_width = self.layout_config.get("layer_width", 4)
            
            # Build tree structure (BFS)
            from collections import deque, defaultdict
            
            adjacency = defaultdict(list)
            for v1, v2 in self.edges_list:
                adjacency[v1].append(v2)
                adjacency[v2].append(v1)
            
            visited = {root}
            queue = deque([(root, 0, 0)])
            layer_counts = defaultdict(int)
            positions[root] = np.array([0, 0, 0])
            
            while queue:
                vertex, layer, index = queue.popleft()
                
                if layer > 0:
                    # Position based on layer and index
                    total_in_layer = len([v for v, l, _ in queue if l == layer]) + 1
                    x = (index - total_in_layer/2) * layer_width / max(1, total_in_layer - 1)
                    y = -layer * layer_height
                    positions[vertex] = np.array([x, y, 0])
                
                for neighbor in adjacency[vertex]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        layer_counts[layer + 1] += 1
                        queue.append((neighbor, layer + 1, layer_counts[layer + 1] - 1))
                        
        elif layout_type == "spring":
            warnings.warn("Spring layout not implemented, using circular", UserWarning)
            return self._compute_layout("circular")
            
        elif layout_type == "custom":
            # Expect positions in layout_config
            positions = self.layout_config.get("positions", {})
            # Fill in missing positions
            for i, vertex in enumerate(self.vertices_list):
                if vertex not in positions:
                    positions[vertex] = np.array([i, 0, 0])
                    
        else:
            # Default grid layout
            cols = int(np.ceil(np.sqrt(n)))
            spacing = self.layout_config.get("spacing", 1.5)
            
            for i, vertex in enumerate(self.vertices_list):
                row = i // cols
                col = i % cols
                x = (col - cols/2) * spacing
                y = -(row - n/cols/2) * spacing
                positions[vertex] = np.array([x, y, 0])
                
        return positions
    
    def _create_vertices(self):
        """Create vertex mobjects."""
        for vertex in self.vertices_list:
            pos = self.positions.get(vertex, ORIGIN)
            
            # Allow per-vertex config
            config = self.vertex_config.copy()
            if isinstance(vertex, dict):
                vertex_id = vertex.get("id")
                config.update(vertex)
            else:
                vertex_id = vertex
                
            vertex_mob = Circle(**config)
            vertex_mob.move_to(pos)
            self.vertices[vertex_id] = vertex_mob
    
    def _create_edges(self):
        """Create edge mobjects."""
        for i, edge in enumerate(self.edges_list):
            if len(edge) == 2:
                v1, v2 = edge
                config = self.edge_config.copy()
            else:
                # Allow weighted edges (v1, v2, weight) or edges with config
                v1, v2 = edge[:2]
                config = self.edge_config.copy()
                if len(edge) > 2 and isinstance(edge[2], dict):
                    config.update(edge[2])
            
            if v1 in self.vertices and v2 in self.vertices:
                start = self.vertices[v1].get_center()
                end = self.vertices[v2].get_center()
                
                # Check if directed
                if config.get("directed", False):
                    edge_mob = Arrow(
                        start, end,
                        buff=self.vertex_config["radius"],
                        **{k: v for k, v in config.items() if k != "directed"}
                    )
                else:
                    edge_mob = Line(start, end, **config)
                    
                self.edges[(v1, v2)] = edge_mob
    
    def _create_labels(self):
        """Create vertex labels."""
        for vertex in self.vertices_list:
            if isinstance(vertex, dict):
                vertex_id = vertex.get("id")
                label_text = vertex.get("label", str(vertex_id))
            else:
                vertex_id = vertex
                label_text = str(vertex)
                
            label = Text(label_text, **self.label_config)
            label.move_to(self.vertices[vertex_id].get_center())
            self.labels[vertex_id] = label
    
    def add_vertex_labels(self, label_dict=None):
        """Add labels to vertices."""
        if label_dict is None:
            label_dict = {v: str(v) for v in self.vertices_list}
            
        labels_group = VGroup()
        
        for vertex, label_text in label_dict.items():
            if vertex in self.vertices:
                label = Text(str(label_text), **self.label_config)
                label.move_to(self.vertices[vertex].get_center())
                self.labels[vertex] = label
                labels_group.add(label)
                
        self.add(labels_group)
        return labels_group
    
    def get_vertex(self, vertex_id):
        """Get a specific vertex mobject."""
        return self.vertices.get(vertex_id)
    
    def get_edge(self, v1, v2):
        """Get a specific edge mobject."""
        return self.edges.get((v1, v2)) or self.edges.get((v2, v1))
    
    def get_neighbors(self, vertex):
        """Get all neighbors of a vertex."""
        neighbors = []
        for v1, v2 in self.edges_list:
            if v1 == vertex:
                neighbors.append(v2)
            elif v2 == vertex:
                neighbors.append(v1)
        return neighbors
    
    def highlight_path(self, path, **kwargs):
        """Highlight a path through the graph."""
        animations = []
        
        # Highlight vertices
        for vertex in path:
            if vertex in self.vertices:
                animations.append(
                    self.vertices[vertex].animate.set_color(
                        kwargs.get("vertex_color", RED)
                    )
                )
        
        # Highlight edges
        for i in range(len(path) - 1):
            edge = self.get_edge(path[i], path[i + 1])
            if edge:
                animations.append(
                    edge.animate.set_color(
                        kwargs.get("edge_color", RED)
                    )
                )
                
        return animations