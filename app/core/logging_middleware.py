import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

logger = logging.getLogger("api_network_log")

class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_body = b""
        async for chunk in request.stream():
            req_body += chunk
            
        if req_body:
            logger.info(f"[API_NETWORK_REQ] {request.method} {request.url.path} - Body: {req_body.decode('utf-8', errors='replace')}")
        else:
            logger.info(f"[API_NETWORK_REQ] {request.method} {request.url.path}")

        async def receive():
            return {"type": "http.request", "body": req_body}
        
        request._receive = receive
        
        response = await call_next(request)
        
        if isinstance(response, StreamingResponse):
            res_body = b""
            async for chunk in response.body_iterator:
                res_body += chunk
                
            logger.info(f"[API_NETWORK_RES] {request.method} {request.url.path} - Status: {response.status_code} - Body: {res_body.decode('utf-8', errors='replace')}")
            
            return Response(
                content=res_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type
            )
            
        return response
