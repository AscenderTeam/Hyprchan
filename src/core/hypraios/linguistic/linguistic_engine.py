from typing import Any
from core.hypraios.constants import Phases
from core.hypraios.kernel.states import KernelStates
from core.hypraios.utils.dynamic_variable import DynamicVariable


class LinguisticEngine:
    def __init__(self) -> None:
        self.top_p = DynamicVariable(value=0, min_val=0.1, max_val=1.0)
        self.top_k = DynamicVariable(value=10, min_val=5, max_val=100)
        self.temperature = DynamicVariable(value=0, min_val=0, max_val=1)
    
    async def feed_passive(self, inputs: list[dict[str, Any]], states: KernelStates):
        pass
    
    async def feed_active(self, inputs: list[dict[str, Any]], states: KernelStates):
        pass
    
    async def feed(self, inputs: list[dict[str, Any]], states: KernelStates):
        if states.phase == Phases.PASSIVE:
            return await self.feed_passive(inputs, states)
        
        if states.phase == Phases.ACTIVE:
            return await self.feed_active(inputs, states)