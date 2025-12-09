import pytest
from pyroute2 import AsyncIPRoute


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'sdn',
    (
        {
            'yaml': '''

segment:
    - interface: test
      ifname: {uifname()}
      kind: dummy
      ipaddr: {allocate()}
'''
        },
    ),
    ids=['dummy'],
    indirect=True,
)
async def test_parametrize(async_ipr, sdn):
    async with AsyncIPRoute() as ipr:
        idx = await ipr.link_lookup(sdn.interfaces['test']['ifname'])
        assert len(idx) == 1 and idx[0] == sdn.interfaces['test']['index']
        addr = await ipr.poll(
            ipr.addr, 'dump', address='192.168.110.20', index=idx
        )
        assert addr
