import shlex
import sys

import pydot
from networkx import DiGraph
from pydot import Dot, Node, Subgraph


def get_node_attribute(graph: DiGraph, name: str, attr: str) -> str:
    return graph.nodes[name]['config'].obj_dict.get('attributes', {}).get(attr)


def get_subgraph_type(graph: Subgraph, label: str) -> str:
    ret = graph.obj_dict.get('attributes', {}).get('type')
    if ret:
        return ret
    for key in ('vrf', 'netns'):
        if label.startswith(key):
            return key
    return ''


def normalize_name(name: str) -> str:
    return shlex.split(name)[0]


def get_subgraph_attribute(graph: DiGraph, name: str) -> tuple[str, str]:
    attrs = graph.nodes[name]['config'].obj_dict.get('attributes', {})
    return (attrs.get('subgraph', ''), attrs.get('subgraph_type', ''))


def set_subgraph_attribute(node: Node, graph: Dot | Subgraph) -> Node:
    if not isinstance(graph, Subgraph):
        return node
    if 'attributes' not in node.obj_dict:
        node.obj_dict['attributes'] = {}
    label = (
        shlex.split(graph.obj_dict.get('attributes', {}).get('label', ''))
    )[0]
    node.obj_dict['attributes']['subgraph'] = label
    node.obj_dict['attributes']['subgraph_type'] = get_subgraph_type(
        graph, label
    )
    return node


def load_subgraph(graph: Dot | Subgraph, target: DiGraph) -> None:
    for node in graph.get_nodes():
        key = normalize_name(node.get_name())
        node = set_subgraph_attribute(node, graph)
        target.add_node(key)
        target.nodes[key]['config'] = node

    for edge in graph.get_edges():
        target.add_edge(*(normalize_name(x) for x in edge.obj_dict['points']))

    for subgraph in graph.get_subgraphs():
        load_subgraph(subgraph, target)


def parse_addresses_from(graph: DiGraph, name: str, label: str):
    config = graph.nodes[name]['config']
    address_str = (
        shlex.split(config.obj_dict.get('attributes', {}).get(label, ''))
        or ['']
    )[0]
    for address in address_str.split('\\n'):
        if len(address):
            yield address


def get_interface_addresses(graph: DiGraph, name: str):
    # yield attribute
    sub_name = f'{name}:ip'
    for address in parse_addresses_from(graph, name, 'ipaddr'):
        yield address
    if sub_name in graph:
        for address in parse_addresses_from(graph, sub_name, 'label'):
            yield address


def process_node(graph: DiGraph, name: str) -> None:
    if get_node_attribute(graph, name, 'type') != 'interface':
        return
    print("interface", name)
    subgraph, subgraph_type = get_subgraph_attribute(graph, name)
    if subgraph_type:
        print("\tsubgraph", subgraph, ":", subgraph_type)
    for address in get_interface_addresses(graph, name):
        print("address", address)
    for pre_node in graph.predecessors(name):
        process_node(graph, pre_node)


def main() -> None:
    pydot_graph_list: list[Dot] | None
    pydot_graph: Dot
    nx_graph: DiGraph = DiGraph()

    with open(sys.argv[1], "r") as f:
        data = f.read()

    pydot_graph_list = pydot.graph_from_dot_data(data)
    if pydot_graph_list is not None:
        pydot_graph = pydot_graph_list[0]
    load_subgraph(pydot_graph, nx_graph)

    # process starting from terminal nodes (out_degree == 0)
    for n in nx_graph.nodes:
        if nx_graph.out_degree(n) > 0:
            continue
        process_node(nx_graph, n)


if __name__ == '__main__':
    main()
