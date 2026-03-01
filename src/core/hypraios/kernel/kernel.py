import asyncio
from ascender.common import Injectable
from attp_client import ATTPClient

from core.hypraios.constants import Phases
from core.hypraios.kernel.main_loop import MainKernelLoop
from core.hypraios.kernel.states import KernelStates
from core.hypraios.utils.dynamic_variable import DynamicVariable
from core.hypraios.utils.fault_adaptive_parameter import FaultAdaptiveParameter


@Injectable(provided_in="root")
class HyprAIOSKernel:
    def __init__(self) -> None:
        self.gamma = FaultAdaptiveParameter(value=1.0, min_delta=0.5, max_delta=3.0, step=0.05, cache_key="gamma")
        self.rho = FaultAdaptiveParameter(value=0.4, min_delta=0.1, max_delta=0.9, step=0.05, cache_key="rho")
        self.f_max = FaultAdaptiveParameter(value=100, max_delta=0.25, min_delta=0.5, step=0.002)
        self.main_loop = MainKernelLoop(self.gamma, self.rho)
        
        self.states = KernelStates(
            f=DynamicVariable(value=0, min_val=0, max_val=self.f_max.value),
            v=DynamicVariable(value=0, min_val=-1, max_val=1, clamp_on_write=True),
            e=DynamicVariable(value=0, min_val=0, max_val=1, clamp_on_write=True),
            a=DynamicVariable(value=0, min_val=0, max_val=1, clamp_on_write=True),
            c=self.main_loop.cooldown,
            phase=Phases.PASSIVE
        )
        
        self._loop_task = None
    
    async def bootup(self):
        self.states.phase = Phases.PASSIVE
        
        await self.start_awake_loop()
    
    async def shutdown(self):
        pass
    
    async def start_awake_loop(self):
        self._loop_task = asyncio.create_task(self.main_loop.loop(self.on_loop))
    
    async def start_sleep_loop(self):
        pass
    
    async def on_loop(self):
        """
        This is called everytime per main kernel loop.
        """
        # Here goes:
        # 1. AI inference and linguistic logics.
        # 2. Phase management and analysis.
        pass