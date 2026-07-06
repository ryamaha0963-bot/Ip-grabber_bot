from aiohttp import web
from config import Config

async def health(request):
    return web.Response(text="OK")

def start_web():
    app = web.Application()
    app.router.add_get('/', health)
    web.run_app(app, port=Config.WEB_PORT)
