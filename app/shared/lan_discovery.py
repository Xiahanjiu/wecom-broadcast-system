# 企业微信群发系统 — 局域网自动发现模块

import logging
import socket
import json
import time
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class LANDiscovery:
    """局域网自动发现。

    启动时通过 UDP 广播 + mDNS 探测主控端。
    找到则返回主控地址直连，找不到则返回 None。
    """

    MULTICAST_GROUP = "224.0.0.199"
    MULTICAST_PORT = 9527
    SERVICE_NAME = "_wecom-broadcast._tcp.local."

    def __init__(self, is_master=False, master_port=8080):
        self._is_master = is_master
        self._master_port = master_port
        self._running = False
        self._thread = None
        self._on_discovered: Optional[Callable] = None

    # ---- 主控端：广播自己 ----

    def start_advertise(self):
        """主控端启动广播，周期性宣告自己在线。"""
        self._running = True
        self._thread = threading.Thread(
            target=self._advertise_loop,
            daemon=True,
            name="lan-advertise"
        )
        self._thread.start()
        logger.info(f"局域网广播已启动 (端口 {self._master_port})")

    def _advertise_loop(self):
        """广播循环。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        message = json.dumps({
            "type": "master_advertise",
            "host": socket.gethostbyname(socket.gethostname()),
            "port": self._master_port,
            "service": self.SERVICE_NAME
        }).encode("utf-8")

        while self._running:
            try:
                sock.sendto(message, (self.MULTICAST_GROUP, self.MULTICAST_PORT))
            except Exception as e:
                logger.debug(f"广播异常 (可忽略): {e}")
            time.sleep(5)

        sock.close()

    # ---- 执行端：探测主控 ----

    def discover(self, timeout=5) -> Optional[str]:
        """执行端探测局域网内的主控端。

        Returns:
            主控 WebSocket 地址 (ws://host:port) 或 None
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)

        # 绑定端口接收响应
        try:
            sock.bind(("0.0.0.0", self.MULTICAST_PORT))
        except OSError:
            # 端口可能被占用
            sock.bind(("0.0.0.0", 0))

        # 加入多播组
        mreq = socket.inet_aton(self.MULTICAST_GROUP) + socket.inet_aton("0.0.0.0")
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass

        # 发送探测请求
        probe = json.dumps({
            "type": "worker_discover"
        }).encode("utf-8")

        try:
            sock.sendto(probe, (self.MULTICAST_GROUP, self.MULTICAST_PORT))
        except Exception:
            pass

        # 等待响应
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(4096)
                msg = json.loads(data.decode("utf-8"))
                if msg.get("type") == "master_advertise":
                    host = msg.get("host", addr[0])
                    port = msg.get("port", 8080)
                    ws_url = f"ws://{host}:{port}"
                    logger.info(f"局域网发现主控: {ws_url}")
                    sock.close()
                    return ws_url
            except socket.timeout:
                break
            except Exception:
                continue

        sock.close()
        logger.info("局域网未发现主控")
        return None

    def stop(self):
        """停止广播/探测。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    # ---- mDNS 备选方案 ----

    @staticmethod
    def discover_mdns(timeout=5) -> Optional[str]:
        """通过 mDNS (zeroconf) 发现主控。"""
        try:
            from zeroconf import ServiceBrowser, Zeroconf, ServiceListener

            result = {"url": None, "found": threading.Event()}

            class MasterListener(ServiceListener):
                def add_service(self, zc, service_type, name):
                    info = zc.get_service_info(service_type, name)
                    if info:
                        addr = socket.inet_ntoa(info.addresses[0])
                        port = info.port
                        result["url"] = f"ws://{addr}:{port}"
                        result["found"].set()

            zc = Zeroconf()
            browser = ServiceBrowser(zc, LANDiscovery.SERVICE_NAME, MasterListener())

            result["found"].wait(timeout=timeout)
            zc.close()

            if result["url"]:
                logger.info(f"mDNS 发现主控: {result['url']}")
            return result["url"]

        except ImportError:
            logger.debug("zeroconf 未安装，跳过 mDNS 发现")
            return None
        except Exception as e:
            logger.debug(f"mDNS 发现失败: {e}")
            return None
