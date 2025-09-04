from fastapi import Request

async def get_redis(request: Request):
    return request.app.state.redis

async def get_mongo(request: Request):
    return request.app.state.mongo
