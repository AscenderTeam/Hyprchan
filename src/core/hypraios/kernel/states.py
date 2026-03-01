from dataclasses import dataclass
from core.hypraios.constants import Phases
from core.hypraios.utils.dynamic_variable import DynamicVariable


@dataclass
class KernelStates:
    f: DynamicVariable
    v: DynamicVariable
    e: DynamicVariable
    a: DynamicVariable
    c: DynamicVariable
    
    phase: Phases