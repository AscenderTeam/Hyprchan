from ascender.core.applications.application import Application


class ServiceLifecycle:
    def __init__(self, application: Application) -> None:
        self.application = application
        application.app.add_event_handler("startup", self.on_startup)
        application.app.add_event_handler("shutdown", self.on_shutdown)

    async def on_startup(self): ...

    async def on_shutdown(self): ...
