from dataclasses import dataclass
from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hypraios.utils.dynamic_variable import DynamicVariable


@dataclass
class KernelStates:
    f: DynamicVariable
    v: DynamicVariable
    e: DynamicVariable
    a: DynamicVariable
    c: DynamicVariable
    
    phase: Phases