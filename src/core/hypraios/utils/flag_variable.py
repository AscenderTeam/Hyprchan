import asyncio



class RaceConditionError(Exception):
    pass


class FlagVariable:
    def __init__(self, initial_value: bool) -> None:
        self.value = initial_value
        self.alock = asyncio.Lock()
    
    async def aset(self, value: bool):
        async with self.alock:
            self.value = value
    
    def __bool__(self):
        return self.value