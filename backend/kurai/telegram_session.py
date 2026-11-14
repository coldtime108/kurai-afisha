"""Use the computer's existing network settings, as the web model client does."""

from aiohttp import ClientSession
from aiogram.client.session.aiohttp import AiohttpSession


class SystemNetworkSession(AiohttpSession):
    async def create_session(self):
        # aiogram's default factory omits trust_env. Preserve its connector and
        # lifecycle while allowing aiohttp to use the user's configured proxy.
        if self._should_reset_connector:
            await self.close()
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                connector=self._connector_type(**self._connector_init),
                trust_env=True,
            )
            self._should_reset_connector = False
        return self._session
