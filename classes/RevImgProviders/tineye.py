from pathlib import Path
from aiohttp import ClientResponse
from os import path as ospath

from ..RevImgProvider import *

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    BeautifulSoup = None

class Provider(ReverseImageSearchProvider):
    name: str = "TinEye"
    base_url: str = 'https://tineye.com/search/?url={url}'

    async def search_file(self, path: Path, data: bytes) -> str:
        url = await self.temp_upload(path, data)
        resp = await self.session.get(self.base_url.format(url=url))
        if isinstance(resp, ClientResponse): return await self.parse_response(resp)
        return await resp.text()
    
    async def parse_response(self, resp: ClientResponse):
        if not BS4_AVAILABLE:
            return "BeautifulSoup4 not installed - install it to enable reverse image search"
        
        ret = ['**Pages:** ']
        soup = BeautifulSoup(await resp.text(), 'html.parser')
        pages = []
        image_link = None
        for hidden in soup.find(class_='match').select('.hidden-xs'):
            if hidden.contents[0].startswith('Page:'):
                pages.append('<{}>'.format(hidden.next_sibling['href']))
            else:
                image_link = hidden.a['href']
        ret.append('**Pages:** '.join(pages))
        if image_link is not None:
            ret.append('**direct image:** <{}>'.format(image_link))
        return '\n'.join(ret)