import errno
from collections.abc import AsyncGenerator, Generator
from string import Template

import pytest
import pytest_asyncio
from networkx import DiGraph
from pyroute2 import IPRoute, NetlinkError
from pyroute2.common import uifname

from sdn_fixtures.main import ensure, load_source


@pytest.fixture(name='ifname')
def _ifname() -> Generator[str]:
    ifname = uifname()
    with IPRoute() as ipr:
        yield ifname
        try:
            (link,) = ipr.link('get', ifname=ifname)
            ipr.link('del', index=link.get('index'))
        except NetlinkError as e:
            if e.code != errno.ENODEV:
                raise


@pytest_asyncio.fixture(name='async_sdn_segment')
async def _async_sdn_segment(request, ifname: str) -> AsyncGenerator[DiGraph]:
    kwarg: dict[str, str] = getattr(request, 'param', {})
    url: str = kwarg.get('url', '')
    source: str = kwarg.get('template', '')

    if not url and not source:
        raise RuntimeError('Either url or template must be set')

    if url:
        source = load_source(url)

    template = Template(source)
    data = template.substitute(ifname=ifname)
    try:
        yield await ensure(present=True, data=data)
    finally:
        await ensure(present=False, data=data)
