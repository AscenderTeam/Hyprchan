from ascender.core import AscModule
from ascender.core.router import routerForChildren

from .routes import routes


@AscModule(
    imports=[],
    declarations=[],
    providers=[routerForChildren(routes)],
    exports=["ROUTER_MODULE"]
)
class RoutesV1Module:
    ...