import asyncio
from config import Config

async def handle_health(reader, writer):
    # read request (we ignore it)
    await reader.read(1024)
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Length: 2\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "OK"
    )
    writer.write(response.encode())
    await writer.drain()
    writer.close()
    await writer.wait_closed()

async def start_web():
    server = await asyncio.start_server(
        handle_health,
        "0.0.0.0",
        Config.WEB_PORT
    )
    async with server:
        await server.serve_forever()
