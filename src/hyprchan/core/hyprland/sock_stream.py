import asyncio
import os
from typing import AsyncIterator, Literal, overload

from hyprchan.core.hyprland.exceptions import UnknownRequestError


class SenderHalf:
    def __init__(self, sock_path: str | os.PathLike, read_limits: int = 8192) -> None:
        self.sock_path = sock_path
        self.read_limits = read_limits
    
    async def open_connection(self):
        return await asyncio.open_unix_connection(self.sock_path)
    
    async def send_command(self, payload: bytes) -> bytes:
        """
        Opens UNIX socket connection to Hyprland's socket receiver and sends the command.

        Args:
            payload (bytes): The payload that contains the request information encoded in bytes.

        Raises:
            UnknownRequestError: If Hyprland returns `unknown request` error.

        Returns:
            bytes: Encoded byte response, it might be JSON if payload contained `[j]/` prefix.
        """
        reader, writer = await self.open_connection()
        
        writer.write(payload)
        await writer.drain()
        
        resp = await reader.read(self.read_limits)
        
        while True:
            new_data = await reader.read(self.read_limits)
            if not new_data:
                break
            
            resp += new_data
        
        writer.close()
        
        match resp:
            case b"unknown request":
                raise UnknownRequestError(f"{payload!r} : {resp}")
            case _:
                return resp


class ReaderHalf:
    def __init__(
        self, 
        esock_path: str | os.PathLike,
        read_limits: int = 8192
    ) -> None:
        self.sock_path = esock_path
        self.read_limits = read_limits
    
    async def open_connection(self):
        return await asyncio.open_unix_connection(self.sock_path)
    
    @overload
    def listen(self) -> AsyncIterator[bytes]:
        ...
    
    @overload
    def listen(self, auto_decode: Literal[True] = True) -> AsyncIterator[str]:
        ...
        
    async def listen(self, auto_decode: bool = False) -> AsyncIterator[str] | AsyncIterator[bytes]: # type: ignore
        """
        Listen for incoming hyprland events via UNIX socket connection.

        Args:
            auto_decode (bool, optional): _description_. Defaults to False.

        Returns:
            AsyncIterator[str] | AsyncIterator[bytes]: _description_

        Yields:
            str | bytes: Incoming event data per line.
        """
        reader, writer = await self.open_connection()
        if auto_decode:
            yield "connect>>"
        else:
            yield b"connect>>"
        
        try:
            buffer = b""
            while True:
                new_data = await reader.read(self.read_limits)
                if not new_data:
                    break
                
                buffer += new_data
                while b"\n" in buffer:
                    data, buffer = buffer.split(b"\n", 1)
                    if auto_decode:
                        yield data.decode()
                        continue
                    
                    yield data
        finally:
            writer.close()
            await writer.wait_closed()



class UNIXSockStream:
    def __init__(
        self,
        *,
        sock_path: str,
        sock2_path: str | None = None,
        read_limits: int = 8192
    ) -> None:
        self.sock_path = sock_path
        self.sock2_path = sock2_path or self.sock_path
        self.read_limits = read_limits
        
        self.sender, self.reader = SenderHalf(self.sock_path, self.read_limits), ReaderHalf(self.sock2_path, self.read_limits)
    
    def split(self):
        return self.sender, self.reader
    
    async def send_command(self, payload: bytes):
        """
        Opens UNIX socket connection to Hyprland's socket receiver and sends the command.

        Args:
            payload (bytes): The payload that contains the request information encoded in bytes.

        Raises:
            UnknownRequestError: If Hyprland returns `unknown request` error.

        Returns:
            bytes: Encoded byte response, it might be JSON if payload contained `[j]/` prefix.
        """
        return await self.sender.send_command(payload)
    
    def listen(self):
        return self.reader.listen
