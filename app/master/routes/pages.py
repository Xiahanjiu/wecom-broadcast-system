# 企业微信群发系统 — 主控端 Web 页面路由

from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()

# pages.py 位于 app/master/routes/pages.py
# 向上 3 层到 app/，再找 web/templates
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))


@router.get("/alerts")
async def alerts_page(request: Request):
    return TEMPLATES.TemplateResponse("alerts.html", {"request": request})


@router.get("/groups")
async def groups_page(request: Request):
    return TEMPLATES.TemplateResponse("groups.html", {"request": request})


@router.get("/templates")
async def templates_page(request: Request):
    return TEMPLATES.TemplateResponse("templates.html", {"request": request})


@router.get("/logs")
async def logs_page(request: Request):
    return TEMPLATES.TemplateResponse("logs.html", {"request": request})
