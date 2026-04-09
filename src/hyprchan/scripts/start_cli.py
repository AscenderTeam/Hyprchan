import os

from ascender.core import Application, inject
from ascender.core._builder.build import build
from ascender.core.cli_engine import BasicCLI, Command, Parameter


@Command(
    name="start",
    description="Starts the hyprchan gateway",
    usage="hyprchan start [options]",
)
class StartCLI(BasicCLI):
    def __init__(self): ...

    host: str = Parameter("127.0.0.1", names=["--host", "-H"])
    port: int = Parameter(8000, names=["--port", "-p"])

    def execute(self) -> None:
        os.environ.setdefault("ASC_HOST", self.host)
        os.environ.setdefault("ASC_PORT", str(self.port))

        application = inject(Application)
        build(application, {})
