from ascender.core import Provider, Application
from attp_client import ATTPClient


class LifecycleFactory:
    def __init__(self, client: ATTPClient) -> None:
        self.client = client
    
    async def on_startup(self):
        await self.client.connect()
    
    async def on_shutdown(self):
        await self.client.close()


def provideAttpClient(agt_token: str, organization_id: int, **attp_configs) -> Provider:
    def factory(app: Application) -> ATTPClient:
        client = ATTPClient(
            agt_token=agt_token,
            organization_id=organization_id,
            **attp_configs
        )
        lifecycle = LifecycleFactory(client)
        
        app.app.add_event_handler("startup", lifecycle.on_startup)
        app.app.add_event_handler("shutdown", lifecycle.on_shutdown)
        
        return client

    return {
        "provide": ATTPClient,
        "use_factory": factory,
        "deps": [Application]
    }