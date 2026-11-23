"""Small ordered ConfigNode writer. Repeated keys and child nodes keep their order."""

from dataclasses import dataclass, field


@dataclass
class Node:
    kind: str
    entries: list = field(default_factory=list)

    def __init__(self, kind, **values):
        self.kind = kind
        self.entries = list(values.items())

    def add(self, key, value):
        self.entries.append((key, value))
        return self

    def child(self, child):
        self.entries.append(child)
        return self

    def set(self, key, value):
        positions = [i for i, entry in enumerate(self.entries) if isinstance(entry, tuple) and entry[0] == key]
        if len(positions) != 1:
            raise ValueError(f"Expected one {key} in {self.kind}")
        self.entries[positions[0]] = (key, value)

    def values(self, key):
        return [e[1] for e in self.entries if isinstance(e, tuple) and e[0] == key]

    def children(self, kind):
        return [e for e in self.entries if isinstance(e, Node) and e.kind == kind]

    def render(self, depth=0):
        tab = "    " * depth
        lines = [tab + self.kind, tab + "{"] if self.kind else []
        inner = depth + bool(self.kind)
        for entry in self.entries:
            if isinstance(entry, Node):
                lines.append(entry.render(inner))
            else:
                key, value = entry
                lines.append("    " * inner + f"{key} = {value}")
        if self.kind:
            lines.append(tab + "}")
        return "\n".join(lines)

    def write(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render() + "\n", encoding="utf-8")


def read_node(path):
    """Read KSP's line-oriented configuration, including stock craft attachment keys."""
    root = Node("")
    stack, pending = [root], None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.partition("//")[0].strip()
        if not line:
            continue
        if line == "}":
            if pending or len(stack) == 1:
                raise ValueError(f"Unexpected closing brace in {path}: {raw}")
            stack.pop()
        elif line == "{":
            if not pending:
                raise ValueError(f"Missing node name in {path}")
            obj = Node(pending)
            stack[-1].child(obj)
            stack.append(obj)
            pending = None
        elif "=" in line:
            key, value = line.split("=", 1)
            stack[-1].add(key.strip(), value.strip())
        else:
            if pending:
                raise ValueError(f"Missing opening brace for {pending} in {path}")
            pending = line
    if len(stack) != 1 or pending:
        raise ValueError(f"Unclosed node in {path}")
    return root
