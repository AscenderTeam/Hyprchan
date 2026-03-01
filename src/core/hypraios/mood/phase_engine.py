import re
from core.hypraios.kernel.states import KernelStates


class PhaseEngine:
    def __init__(
        self, 
        kernel_states: KernelStates
    ) -> None:
        self.kernel_states = kernel_states
        self.CONTROL_TAG_RE = re.compile(
            r"<control\b[^>]*>(.*?)</control>",
            re.IGNORECASE | re.DOTALL
        )

    async def process_interaction_delta(self, output: str, input: str):
        # Convert input and output embedding tokens into scalar delta value.
        # Which will be used for ining 
        pass
    
    async def handle_commands(self, text: str):
        pass
    
    async def after_inference(
        self, 
        input: str,
        output: str
    ):
        """
        Fired after each inference

        Args:
            output (str): Given LLM's output that may contain specific control tags.
            input (str): If state is active, user input is given here, sometimes also system inputs as well. If no priority system inputs given, then previous output used.
        """
        pass