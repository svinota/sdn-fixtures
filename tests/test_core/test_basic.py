import pytest
from pyroute2 import AsyncIPRoute


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'async_sdn_segment',
    (
        {
            'template': '''

digraph G {
    "$ifname" [
        type=interface,
        kind=dummy,
        label=$ifname,
        ipaddr="192.168.110.20/24"
    ];
}
        '''
        },
    ),
    ids=['dummy'],
    indirect=True,
)
async def test_parametrize(async_ipr, async_sdn_segment, ifname):
    async with AsyncIPRoute() as ipr:
        idx = await ipr.link_lookup(ifname)
        assert idx
        addr = await ipr.poll(
            ipr.addr, 'dump', address='192.168.110.20', index=idx
        )
        assert addr
