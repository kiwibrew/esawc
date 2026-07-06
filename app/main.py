import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from app.database import init_db
from app.routers import auth, api
from app.dependencies import get_current_user
from starlette import status

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB on startup
    await init_db()
    yield

app = FastAPI(
    title="ESA WorldCover 2021 v2 API",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
    docs_url=None,  # Disable default docs
    redoc_url=None   # Disable default redoc
)

# Include routers
app.include_router(auth.router)
app.include_router(api.router)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html(request: Request, user=Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    bearer_token = user.bearer_token or ""

    html = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
        swagger_ui_parameters=app.swagger_ui_parameters,
        init_oauth={"clientId": ""},
    )

    # Inject JS to pre-populate the bearer token for the logged-in user
    inject = ""
    if bearer_token:
        inject = f"""
<script>
window.addEventListener('load', function() {{
    const interval = setInterval(function() {{
        if (window.ui) {{
            clearInterval(interval);
            window.ui.preauthorizeApiKey('BearerAuth', '{bearer_token}');
        }}
    }}, 100);
}});
</script>
"""
    back_button = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<style>
  #back-to-home { position: fixed; top: 12px; left: 12px; z-index: 9999; }
</style>
<div id="back-to-home">
  <a href="/" class="btn btn-secondary btn-sm">&larr; Back to Home</a>
</div>
"""
    body = html.body.decode("utf-8") + inject + back_button
    return HTMLResponse(content=body, status_code=html.status_code)

@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(request: Request, user=Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools():
    return JSONResponse(content={})
