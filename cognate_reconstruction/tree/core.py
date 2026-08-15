"""Minimal Newick tree model and native n-ary traversal for the workbench."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class TreeNode:
    """A classification-tree node with downward children and a parent link."""

    label: str | None = None
    children: list[TreeNode] = field(default_factory=list)
    branch_length: float | None = None
    parent: TreeNode | None = field(default=None, repr=False)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def is_polytomy(self) -> bool:
        return len(self.children) > 2

    def get_leaves(self) -> list[TreeNode]:
        if self.is_leaf:
            return [self]
        leaves: list[TreeNode] = []
        for child in self.children:
            leaves.extend(child.get_leaves())
        return leaves

    def get_leaf_labels(self) -> set[str]:
        return {
            leaf.label for leaf in self.get_leaves() if leaf.label is not None
        }


def _convert_newick_node(raw: object) -> TreeNode:
    raw_label = raw.name or None  # type: ignore[union-attr]
    if raw_label and len(raw_label) >= 2 and raw_label[0] == raw_label[-1] == "'":
        raw_label = raw_label[1:-1].replace("''", "'")
    node = TreeNode(
        label=raw_label,
        branch_length=raw.length,  # type: ignore[union-attr]
    )
    for raw_child in raw.descendants:  # type: ignore[union-attr]
        child = _convert_newick_node(raw_child)
        child.parent = node
        node.children.append(child)
    return node


def parse_newick(newick_text: str) -> TreeNode:
    """Parse exactly one Newick tree, retaining labels and polytomies."""
    import newick as newick_package  # type: ignore[import-untyped]

    newick_text = newick_text.strip()
    if not newick_text:
        raise ValueError("Newick input is empty")
    try:
        trees = newick_package.loads(newick_text)
    except Exception as error:
        raise ValueError(f"invalid Newick tree: {error}") from error
    if not trees:
        raise ValueError("Newick input did not contain a tree")
    if len(trees) != 1:
        raise ValueError(
            f"Newick input contained {len(trees)} trees; expected exactly one"
        )
    return _convert_newick_node(trees[0])


def validate_unique_leaf_labels(root: TreeNode) -> None:
    """Reject missing or repeated leaf identifiers before reconstruction."""
    labels = [leaf.label for leaf in root.get_leaves()]
    if missing := sum(label is None or not label.strip() for label in labels):
        raise ValueError(f"classification tree has {missing} unlabeled leaf/leaves")
    counts = Counter(label for label in labels if label is not None)
    duplicates = sorted(label for label, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"classification tree has duplicate leaf IDs: {duplicates}")


def assign_node_ids(root: TreeNode) -> dict[int, str]:
    """Assign deterministic IDs to unlabeled internal nodes."""
    assigned: dict[int, str] = {}
    used: set[str] = set()

    def visit(node: TreeNode, path: str) -> None:
        node_id = node.label or f"internal:{path}"
        if node_id in used:
            raise ValueError(f"tree node identifier {node_id!r} is not unique")
        assigned[id(node)] = node_id
        used.add(node_id)
        for index, child in enumerate(node.children):
            visit(child, f"{path}.{index}")

    visit(root, "root")
    return assigned


def internal_node_ids(root: TreeNode) -> tuple[str, ...]:
    assigned = assign_node_ids(root)
    return tuple(
        assigned[id(parent)] for _, parent in postorder_groups(root)
    )


def postorder_groups(
    root: TreeNode,
) -> Iterator[tuple[tuple[TreeNode, ...], TreeNode]]:
    """Yield native n-ary child groups in bottom-up reconstruction order."""
    if root.is_leaf:
        return
    if len(root.children) < 2:
        raise ValueError(
            "classification trees must be normalized before traversal; "
            f"node {root.label!r} has {len(root.children)} child"
        )
    for child in root.children:
        yield from postorder_groups(child)
    yield tuple(root.children), root
