from datetime import datetime
from ascender.common import BaseDTO


class SystemMessage(BaseDTO):
    fatigue: float
    message: str
    first_message: bool
    timestamp: datetime
    
    def to_message(self):
        if self.first_message:
            return f"<system>Hello Hypr-chan! I'm your body, system! Any internal changes, feelings and other things that happen with your body I will notify you with feedback, you don't have to "
        return f"<system>Hello Hypr-chan! It's your body system again!\n{self.message}\nNOTE: Don't reply to me, I'm just an informer.</system>"


class HyprlandMenuMessage(BaseDTO):
    message: str
    timestamp: datetime
    first_message: bool
    
    def to_message(self):
        return f"<hyprland-interface>Hello Hypr-chan! It's your interaction interface! {self.message}\nNOTE: Don't reply to me, I'm just an informer.</hyprland-interface>"


class UserMessage(BaseDTO):
    message: str