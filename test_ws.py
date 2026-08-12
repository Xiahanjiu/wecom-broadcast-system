import asyncio
import websockets

async def test():
    try:
        async with websockets.connect(
            "wss://european-implement-examples-guest.trycloudflare.com",
            close_timeout=10
        ) as ws:
            await ws.send('{"type":"test"}')
            print("WebSocket OK: connected and sent")
    except Exception as e:
        print(f"WebSocket FAIL: {e}")

asyncio.run(test())
