# 企业微信群发系统 — 主控端 FastAPI 服务

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.shared.config import Config
from app.shared.group_manager import get_group_manager
from app.master.core import get_master_core
from app.scheduler import get_scheduler
from app.master.routes.pages import router as pages_router

logger = logging.getLogger(__name__)


class MasterServer:
    """主控端 FastAPI 服务器。"""

    def __init__(self):
        self.config = Config()
        self.core = get_master_core()
        self.group_mgr = get_group_manager()

        web_dir = Path(__file__).parent.parent / "web"
        self.templates_dir = str(web_dir / "templates")
        self.static_dir = str(web_dir / "static")

        self.app = self._create_app()

    def _create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            logger.info("主控端服务启动中...")
            heartbeat_task = asyncio.create_task(self.core._heartbeat_loop())
            # 启动定时任务调度器（节假日群发、休息时段自动回复、超时预警）
            scheduler = get_scheduler()
            scheduler.start()
            yield
            logger.info("主控端服务关闭中...")
            heartbeat_task.cancel()
            scheduler = get_scheduler()
            scheduler.stop()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        app = FastAPI(title="企业微信群发系统 - 主控端", lifespan=lifespan)

        templates = Jinja2Templates(directory=self.templates_dir)
        app.mount("/static", StaticFiles(directory=self.static_dir), name="static")
        app.include_router(pages_router)
        self._register_routes(app, templates)
        self._register_ws(app)

        return app

    def _register_routes(self, app: FastAPI, templates: Jinja2Templates):
        """注册 HTTP API 路由。"""

        @app.get("/")
        async def dashboard(request: Request):
            data = self.core.get_dashboard_data()
            data["total_groups"] = self.group_mgr.get_count()
            return templates.TemplateResponse("dashboard.html", {"request": request, "data": data})

        @app.get("/api/dashboard")
        async def api_dashboard():
            data = self.core.get_dashboard_data()
            data["total_groups"] = self.group_mgr.get_count()
            return data

        @app.get("/api/workers")
        async def api_workers():
            return {"workers": list(self.core._workers.values())}

        # ---- 群列表管理 ----

        @app.get("/api/groups/list")
        async def api_groups_list():
            groups = self.group_mgr.get_all()
            return {
                "total": len(groups),
                "groups": groups,
                "assigned": self.core._group_assignment
            }

        @app.get("/api/groups")
        async def api_groups():
            return {
                "assignments": self.core._group_assignment,
                "total": self.group_mgr.get_count(),
                "all": self.group_mgr.get_all()
            }

        @app.get("/api/groups/unassigned")
        async def api_groups_unassigned():
            unassigned = self.group_mgr.get_unassigned(self.core._group_assignment)
            return {"unassigned": unassigned, "count": len(unassigned)}

        @app.get("/api/groups/export")
        async def api_groups_export():
            return {"text": self.group_mgr.export_as_text()}

        @app.post("/api/groups/add")
        async def api_add_group(data: dict):
            name = data.get("group_name", "").strip()
            if not name:
                return {"error": "群名不能为空"}, 400
            ok = self.group_mgr.add_group(name)
            return {"ok": ok, "group_name": name}

        @app.post("/api/groups/import")
        async def api_import_groups(data: dict):
            text = data.get("text", "")
            names = data.get("groups", [])
            if text:
                count = self.group_mgr.import_from_text(text)
            elif names:
                count = self.group_mgr.import_groups(names)
            else:
                return {"error": "请提供群名列表(text 或 groups)"}, 400
            return {"ok": True, "added": count, "total": self.group_mgr.get_count()}

        @app.delete("/api/groups/{group_name}")
        async def api_remove_group(group_name: str):
            ok = self.group_mgr.remove_group(group_name)
            return {"ok": ok, "group_name": group_name}

        @app.post("/api/groups/assign")
        async def api_assign_group(data: dict):
            group_name = data.get("group_name")
            worker_id = data.get("worker_id")
            if not group_name or not worker_id:
                return {"error": "缺少参数"}, 400
            self.core.assign_group(group_name, worker_id)
            return {"ok": True}

        @app.post("/api/groups/batch_assign")
        async def api_batch_assign(data: dict):
            assignments = data.get("assignments", {})
            for group_name, worker_id in assignments.items():
                self.core.assign_group(group_name, worker_id)
            return {"ok": True, "count": len(assignments)}

        # ---- 发送管理 ----

        @app.post("/api/send/trigger")
        async def api_trigger_send():
            active_groups = self.core.store.get_active_groups()
            group_names = list(active_groups.keys())
            result = await self.core.dispatch_send_tasks(group_names)
            return {
                "ok": True,
                "active_groups": len(group_names),
                "tasks_dispatched": sum(len(v) for v in result.values())
            }

        # ---- 预警管理 ----

        @app.post("/api/alerts/acknowledge")
        async def api_ack_alert(data: dict):
            group_name = data.get("group_name")
            if not group_name:
                return {"error": "缺少参数"}, 400
            store = self.core.store
            alerts = store.get_alerts()
            if group_name in alerts:
                alerts[group_name]["acknowledged"] = True
                store.save("alerts", alerts)
            return {"ok": True}

        # ---- 模板管理 ----

        @app.get("/api/templates")
        async def api_list_templates():
            from app.shared.template_engine import get_template_engine
            engine = get_template_engine()
            return {"templates": engine.list_templates()}

        @app.get("/api/templates/{name}")
        async def api_get_template(name: str):
            from app.shared.template_engine import get_template_engine
            engine = get_template_engine()
            content = engine.get_template_content(name)
            return {"name": name, "content": content}

        @app.post("/api/templates/save")
        async def api_save_template(data: dict):
            name = data.get("name")
            content = data.get("content")
            if not name or not content:
                return {"error": "缺少参数"}, 400
            from app.shared.template_engine import get_template_engine
            engine = get_template_engine()
            engine.save_template(name, content)
            return {"ok": True}

    def _register_ws(self, app: FastAPI):
        """注册 WebSocket 端点。"""

        @app.websocket("/ws/{worker_id}")
        async def ws_endpoint(websocket: WebSocket, worker_id: str):
            await websocket.accept()
            logger.info(f"执行端 WebSocket 连接: {worker_id}")
            await self.core.register_worker(worker_id, websocket)
            try:
                while True:
                    message = await websocket.receive_text()
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        data = {"type": "raw", "content": message}
                    msg_type = data.get("type", "")
                    if msg_type == "heartbeat":
                        await self.core.handle_heartbeat(worker_id, data)
                    elif msg_type == "monitor_update":
                        group_name = data.get("group_name")
                        if group_name:
                            store = self.core.store
                            store.set_active_group(group_name, {
                                "group_name": group_name,
                                "last_customer_msg": data.get("timestamp"),
                                "sender": data.get("sender", ""),
                            })
                            timeline = store.get_timeline()
                            if group_name not in timeline:
                                timeline[group_name] = {}
                            timeline[group_name]["last_customer_msg"] = data.get("timestamp")
                            timeline[group_name]["sender"] = data.get("sender", "")
                            store.save("timeline", timeline)
                    elif msg_type == "staff_reply":
                        group_name = data.get("group_name")
                        if group_name:
                            timeline = self.core.store.get_timeline()
                            if group_name in timeline:
                                timeline[group_name]["last_staff_reply"] = data.get("timestamp")
                                self.core.store.save("timeline", timeline)
                                alerts = self.core.store.get_alerts()
                                if group_name in alerts:
                                    alerts[group_name]["resolved"] = True
                                    self.core.store.save("alerts", alerts)
                    elif msg_type == "alert_trigger":
                        await self.core.broadcast_alert(data)
                    elif msg_type == "send_result":
                        await self.core.handle_send_result(worker_id, data)
                    elif msg_type == "worker_info":
                        if "info" in data:
                            self.core._workers[worker_id].update(data["info"])
            except WebSocketDisconnect:
                logger.info(f"执行端 WebSocket 断开: {worker_id}")
            except Exception as e:
                logger.error(f"执行端 WebSocket 异常: {worker_id}: {e}")
            finally:
                await self.core.unregister_worker(worker_id)

    def start(self):
        """启动主控服务。"""
        import uvicorn
        port = self.config.get("relay.master_port", 8080)
        logger.info(f"主控端 Web 服务启动于 http://localhost:{port}")
        uvicorn.run(self.app, host="0.0.0.0", port=port, log_level="info")

