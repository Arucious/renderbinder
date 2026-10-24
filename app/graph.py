OUTPUT_MARKERS = (
    "saveimage",
    "previewimage",
    "saveanimated",
    "imagesave",
    "savevideo",
    "savewebm",
    "vhs_videocombine",
)


def is_output(class_type):
    return any(marker in class_type.lower() for marker in OUTPUT_MARKERS)


def active_nodes(graph):
    outputs = [
        key for key, node in graph.items() if is_output(node.get("class_type", ""))
    ]
    if not outputs:
        return set(graph)
    seen, todo = set(), list(outputs)
    while todo:
        key = str(todo.pop())
        if key in seen or key not in graph:
            continue
        seen.add(key)
        todo.extend(
            str(value[0])
            for value in graph[key].get("inputs", {}).values()
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)
        )
    return seen
