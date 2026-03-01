from ascender.core import Application, inject


class ServiceLifecycle:
    application: Application = inject(Application)
    
    def __init__(self) -> None:
        self.application.app.add_event_handler("startup", self.on_startup)
        self.application.app.add_event_handler("shutdown", self.on_shutdown)
    
    async def on_startup(self):
        ...
    
    async def on_shutdown(self):
        ...