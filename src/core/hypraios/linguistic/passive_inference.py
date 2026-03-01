from typing import Any


class PassiveProcessor:
    def __init__(self, inputs: list[dict[str, Any]]) -> None:
        self.inputs = inputs
    
    async def process_inputs(self, inference_count: int):
        """
        Processes all inputs, that are related to system and hyprland-interface.
        If inputs don't satisfy the format requirement, then they are skipped or passed as "received unknown input, something bothers you." depending on intensity that should ALL inputs define.
        If unknown type of inputs (those that don't match the required format) are present, accumulate them and if there is majority of them, then make one single system message telling Hypr-chan that something serious bothering her system.
        Sort same type of inputs into one depending on balance of amount, if there's a lot of same inputs in sequence, the priority is more!
        System messages shouldn't be same-same text, diversification of messages (e.g. "There's X happening" to "X happening in you" matters!)
        
        Input required formats:
        {
            "type": string, // type of input (if not present, it's unknwon type of input!)
            "amplitude": float, // the quality and amplitude level of the input, higher - prior.
            "description": string, // Mandatory description of input
            "origin": string // Where this input is coming from
        }
        
        Args:
            inference_count (int): Amount of inference that happened
        """
        ...
    
    async def inference_invoke(self):
        """
        Invoke LM Inference after given processing inputs.
        NOTE: Execute this function, ONLY after `process_inputs(...)`
        """
        ...