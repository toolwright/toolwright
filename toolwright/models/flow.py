"""Flow models for API sequence detection."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FlowEdge(BaseModel):
    """A directed dependency between two endpoints.

    Means: the target endpoint requires data produced by the source endpoint.
    """

    source_id: str  # signature_id of the source endpoint
    target_id: str  # signature_id of the target endpoint
    linking_field: str  # field name that links them (e.g., "id", "product_id")
    confidence: float = Field(ge=0.0, le=1.0)  # 0-1 confidence score


class FlowSequence(BaseModel):
    """An ordered sequence of endpoint steps forming a workflow."""

    name: str = ""
    steps: list[str] = Field(default_factory=list)  # ordered list of signature_ids
    description: str = ""


class FlowGraph(BaseModel):
    """A graph of flow edges between endpoints."""

    edges: list[FlowEdge] = Field(default_factory=list)

    def edges_from(self, source_id: str) -> list[FlowEdge]:
        """Get all edges originating from a source endpoint."""
        return [e for e in self.edges if e.source_id == source_id]

    def edges_to(self, target_id: str) -> list[FlowEdge]:
        """Get all edges targeting a specific endpoint."""
        return [e for e in self.edges if e.target_id == target_id]

    def find_sequences(self) -> list[FlowSequence]:
        """Extract linear sequences (chains) from the flow graph.

        Finds all maximal paths by starting from nodes with no incoming edges
        (or all nodes if cycles exist) and following outgoing edges greedily
        by highest confidence.
        """
        if not self.edges:
            return []

        # Build adjacency: source -> [(target, edge)]
        adj: dict[str, list[tuple[str, FlowEdge]]] = {}
        all_nodes: set[str] = set()
        has_incoming: set[str] = set()

        for edge in self.edges:
            all_nodes.add(edge.source_id)
            all_nodes.add(edge.target_id)
            has_incoming.add(edge.target_id)
            adj.setdefault(edge.source_id, []).append((edge.target_id, edge))

        # Start from nodes with no incoming edges (roots)
        roots = all_nodes - has_incoming
        if not roots:
            # Cycle: start from all nodes
            roots = all_nodes

        sequences: list[FlowSequence] = []
        visited_chains: set[tuple[str, ...]] = set()

        for root in sorted(roots):
            chain = self._follow_chain(root, adj)
            chain_tuple = tuple(chain)
            if len(chain) >= 2 and chain_tuple not in visited_chains:
                visited_chains.add(chain_tuple)
                sequences.append(
                    FlowSequence(
                        name=f"flow_{len(sequences) + 1}",
                        steps=chain,
                    )
                )

        return sequences

    def _follow_chain(
        self,
        start: str,
        adj: dict[str, list[tuple[str, FlowEdge]]],
    ) -> list[str]:
        """Follow the highest-confidence path from a starting node."""
        chain = [start]
        visited: set[str] = {start}
        current = start

        while current in adj:
            # Pick the highest-confidence next hop not yet visited
            candidates = [
                (target, edge)
                for target, edge in adj[current]
                if target not in visited
            ]
            if not candidates:
                break
            candidates.sort(key=lambda x: -x[1].confidence)
            next_node = candidates[0][0]
            chain.append(next_node)
            visited.add(next_node)
            current = next_node

        return chain
