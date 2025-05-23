import argparse
import asyncio
import logging
import shlex
import urllib.request
from collections import deque, namedtuple
from collections.abc import Generator
from urllib.parse import urlparse

import pydot
from networkx import DiGraph
from pydot import Dot, Edge, Node, Subgraph
from pyroute2 import AsyncIPRoute, netns
from pyroute2.common import uifname

logging.basicConfig(level=logging.INFO)

Qname = namedtuple('Qname', ('ifname', 'section'))


def get_node_attribute(graph: DiGraph, name: str, attr: str) -> str:
    return normalize_name(
        graph.nodes[name]
        .get('config', namedtuple('config', ('obj_dict',))({}))
        .obj_dict.get('attributes', {})
        .get(attr, '')
    )


def get_subgraph_label(subgraph: Subgraph) -> str:
    return normalize_name(
        subgraph.obj_dict.get('attributes', {}).get('label', '')
    )


def get_subgraph_type(subgraph: Subgraph) -> str:
    ret = subgraph.obj_dict.get('attributes', {}).get('type')
    if ret:
        return ret
    for key in ('vrf', 'netns'):
        if get_subgraph_label(subgraph).startswith(key):
            return key
    return ''


def normalize_name(name: str) -> str:
    if len(name):
        return shlex.split(name)[0]
    return name


def get_subgraph_attribute(graph: DiGraph, name: str) -> tuple[str, str]:
    attrs = graph.nodes[name]['config'].obj_dict.get('attributes', {})
    subgraph = attrs.get('subgraph')
    if subgraph is None:
        return ('', '')
    return (get_subgraph_label(subgraph), get_subgraph_type(subgraph))


def set_subgraph_attribute(
    target: Node | Edge, subgraph: Subgraph | Dot
) -> None:
    if not isinstance(subgraph, Subgraph):
        return
    if 'attributes' not in target.obj_dict:
        target.obj_dict['attributes'] = {}
    target.obj_dict['attributes']['subgraph'] = subgraph


def load_subgraph(graph: Dot | Subgraph, target: DiGraph) -> None:
    for node in graph.get_nodes():
        key = normalize_name(node.get_name())
        set_subgraph_attribute(node, graph)
        target.add_node(key)
        target.nodes[key]['config'] = node

    for edge in graph.get_edges():
        set_subgraph_attribute(edge, graph)
        target.add_edge(*(normalize_name(x) for x in edge.obj_dict['points']))

    for subgraph in graph.get_subgraphs():
        load_subgraph(subgraph, target)


def parse_addresses_from(graph: DiGraph, name: str, label: str):
    config = graph.nodes[name]['config']
    address_str = (
        shlex.split(config.obj_dict.get('attributes', {}).get(label, ''))
        or ['']
    )[0]
    for address in address_str.replace(' ', '\\n').split('\\n'):
        if len(address):
            yield address


def get_interface_name(graph: DiGraph, name: str) -> str:
    label = get_node_attribute(graph, name, 'label')
    if not label:
        return name
    return label


def get_interface_addresses(graph: DiGraph, name: str) -> Generator[str]:
    # yield attribute
    sub_name = f'{name}:ip'
    for address in parse_addresses_from(graph, name, 'ipaddr'):
        yield address
    if sub_name in graph:
        for address in parse_addresses_from(graph, sub_name, 'label'):
            yield address


async def process_node(
    ipr_stack: deque[AsyncIPRoute], graph: DiGraph, name: str, present: bool
) -> None:
    '''Process an interface and upwards.

    * ensure the interface
    * set link, master
    * ensure vlan/vxlan/... uplinks for bridges
    * set IP addresses

    Todo:

    * vlan filters,
    * routes
    * SRv6
    * MPLS
    '''
    # we start from the interface
    if get_node_attribute(graph, name, 'type') != 'interface':
        qname_args = name.split(':')
        if len(qname_args) != 2:
            return
        qname = Qname(*qname_args)
        if (
            qname.section == 'ip'
            and get_node_attribute(graph, name, 'shape') == 'note'
        ):
            if (
                len(
                    [
                        x
                        for x in graph.successors(qname.ifname)
                        if get_node_attribute(graph, x, 'shape') != 'note'
                    ]
                )
                == 0
            ):
                await process_node(ipr_stack, graph, qname.ifname, present)
                return
        logging.info(f'skip node {name}')
        return
    spec: dict[str, int | str | dict[str, str]]
    subgraph: str
    subgraph_type: str
    kind: str
    ifname: str
    ipr_idx: int

    kind = get_node_attribute(graph, name, 'kind')
    ifname = get_node_attribute(graph, name, 'label')
    subgraph, subgraph_type = get_subgraph_attribute(graph, name)
    logging.info(
        f'process interface node {name}: ifname={ifname}, kind={kind}'
    )
    spec = {
        'ifname': ifname,
        'state': get_node_attribute(graph, name, 'state') or 'up',
    }

    if kind is not None:
        spec['kind'] = kind

    ipr_idx = -1
    # setup netns
    if subgraph_type == 'netns':
        if present:
            logging.info(f'ensure netns={subgraph}')
            ipr_stack.append(AsyncIPRoute(netns=subgraph))
            await ipr_stack[-1].setup_endpoint()
            ipr_idx = -2
        else:
            try:
                netns.remove(subgraph)
            except FileNotFoundError:
                pass

    # setup veth
    if present and kind == 'veth':
        link = [
            x.get('link')
            async for x in await ipr_stack[-1].link('dump')
            if x.get('ifname') == ifname
        ]
        if link:
            spec['ifname'] = (
                await ipr_stack[ipr_idx].link('get', index=link)
            )[0].get('ifname')
        else:
            spec['ifname'] = uifname()
        peer = {'ifname': ifname}
        if subgraph_type == 'netns':
            peer['net_ns_fd'] = subgraph
        spec['peer'] = peer
        logging.info(f'veth peer={ifname}, uplink={spec["ifname"]}')

    # setup vxlan
    if present and kind == 'vxlan':
        spec['vxlan_id'] = int(get_node_attribute(graph, name, 'vxlan_id'))
        for x in graph.successors(name):
            if get_node_attribute(graph, x, 'kind') != 'bridge':
                spec['vxlan_link'] = (
                    await ipr_stack[ipr_idx].link_lookup(
                        get_interface_name(graph, x)
                    )
                )[0]
                break
    master = []
    for uplink in graph.successors(name):
        if get_node_attribute(graph, uplink, 'type') != 'interface':
            continue
        if get_node_attribute(graph, uplink, 'kind') == 'bridge':
            master = await ipr_stack[ipr_idx].link_lookup(
                get_node_attribute(graph, uplink, 'label')
            )
            break
    if master and present:
        spec['master'] = master[0]
    logging.info(f'ensure interface {spec}')
    interface = await ipr_stack[ipr_idx].ensure(
        ipr_stack[ipr_idx].link, present=present, **spec
    )

    # post-init: enforce state
    #
    # e.g. veth peers should be set here
    #
    if present:
        await ipr_stack[-1].link(
            'set',
            index=await ipr_stack[-1].link_lookup(ifname),
            state=spec['state'],
        )

    # setup VRF
    if subgraph_type == 'vrf':
        logging.info(f'ensure vrf={subgraph}')
        vrf = await ipr_stack[-1].ensure(
            ipr_stack[-1].link,
            present=present,
            **{
                'ifname': subgraph,
                'kind': 'vrf',
                'vrf_table': int(subgraph.strip('vrf')),
                'state': 'up',
            },
        )
        if present:
            await ipr_stack[-1].link('set', index=interface[0], master=vrf[0])

    if present:
        for address in get_interface_addresses(graph, name):
            logging.info(f'interface {name} address: {address}')
            await ipr_stack[-1].ensure(
                ipr_stack[-1].addr,
                present=present,
                address=address,
                index=await ipr_stack[-1].link_lookup(ifname),
            )
    for pre_node in graph.predecessors(name):
        await process_node(ipr_stack, graph, pre_node, present)

    # cleanup netns
    if subgraph_type == 'netns':
        ipr_stack.pop().close()


def load_source(url):
    parsed = urlparse(url)
    if parsed.scheme in ('http', 'https'):
        source = urllib.request.urlopen(url)
    else:
        source = open(url, 'rb')
    with source:
        return source.read().decode('utf-8')


async def ensure(present: bool, data: str) -> DiGraph:
    pydot_graph_list: list[Dot] | None
    pydot_graph: Dot
    nx_graph: DiGraph = DiGraph()
    ipr_stack: deque[AsyncIPRoute] = deque([AsyncIPRoute()])

    pydot_graph_list = pydot.graph_from_dot_data(data)
    if pydot_graph_list is not None:
        pydot_graph = pydot_graph_list[0]
    load_subgraph(pydot_graph, nx_graph)

    # process starting from terminal nodes (out_degree == 0)
    try:
        for n in nx_graph.nodes:
            if nx_graph.out_degree(n) > 0:
                continue
            await process_node(ipr_stack, nx_graph, n, present)
    finally:
        for ipr in ipr_stack:
            ipr.close()
    return nx_graph


def run() -> None:
    aparser = argparse.ArgumentParser(
        prog='pyroute2-dot', description='apply dot files med SND definitions'
    )
    aparser.add_argument('action')
    aparser.add_argument('filename')
    args = aparser.parse_args()
    data = load_source(args.filename)
    asyncio.run(ensure(present=args.action.lower() != 'down', data=data))


if __name__ == '__main__':
    run()
