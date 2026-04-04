class DynamicVariable:
    def __init__(
        self,
        value: float,
        min_val: float = 0.0,
        max_val: float = 1.0,
        decay: float = 0.0,
        clamp_on_write: bool = True
    ) -> None:
        self._value = value
        self.min_val = min_val
        self.max_val = max_val
        self.decay = decay
        self.clamp_on_write = clamp_on_write
    
    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, new_val: float):
        if self.clamp_on_write:
            self._value = max(self.min_val, min(self.max_val, new_val))
        else:
            self._value = new_val
    
    def clamp(self):
        self._value = max(self.min_val, min(self.max_val, self._value))
    
    def step(self):
        if self.decay > 0:
            self._value *= self.decay
