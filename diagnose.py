# ============================================
# 企业微信群发系统 — 环境诊断脚本
# 运行: python diagnose.py
# ============================================

import sys
import os

PASS = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"

def main():
    print("=" * 60)
    print("  企业微信群发系统 - 环境诊断")
    print("=" * 60)
    print()

    results = []
    results.append(check_python())
    results.append(check_dependency("yaml", "PyYAML"))
    results.append(check_dependency("fastapi", "FastAPI"))
    results.append(check_dependency("uvicorn", "Uvicorn"))
    results.append(check_dependency("websockets", "websockets"))
    results.append(check_dependency("jinja2", "Jinja2"))
    results.append(check_dependency("apscheduler", "APScheduler"))
    results.append(check_uia())
    results.append(check_wecom_window())
    results.append(check_network())
    results.append(check_config())

    print()
    print("=" * 60)
    passed = sum(1 for r in results if r)
    failed = len(results) - passed
    if failed == 0:
        print(f"  全部通过 ({passed}/{len(results)}) - 环境就绪!")
    else:
        print(f"  通过 {passed}/{len(results)}, 失败 {failed} 项, 请修复后重试")
    print("=" * 60)


def check_python():
    v = sys.version_info
    ok = v.major == 3 and v.minor >= 9
    if ok:
        print(f"{PASS} Python {v.major}.{v.minor}.{v.micro}")
    else:
        print(f"{FAIL} Python {v.major}.{v.minor}.{v.micro} (需要 3.9+)")
    return ok


def check_dependency(import_name, display_name):
    try:
        __import__(import_name)
        print(f"{PASS} {display_name}")
        return True
    except ImportError:
        print(f"{FAIL} {display_name} 未安装 - pip install {import_name}")
        return False


def check_uia():
    try:
        import uiautomation
        print(f"{PASS} uiautomation (UIA 无障碍扫描)")
        return True
    except ImportError:
        print(f"{WARN} uiautomation 未安装 - OCR 降级可用")
        print(f"     安装: pip install uiautomation")
        return False


def check_wecom_window():
    try:
        import uiautomation as auto
        wecom = auto.WindowControl(Name="企业微信", searchDepth=1)
        if wecom.Exists(maxSearchSeconds=3):
            print(f"{PASS} 企业微信窗口已检测到")
            try:
                chat_list = wecom.ListControl(searchDepth=3)
                if chat_list.Exists(maxSearchSeconds=1):
                    children = chat_list.GetChildren()
                    count = len([c for c in children if c.Name and c.Name.strip()])
                    print(f"     聊天列表: {count} 个可见项")
                else:
                    chat_list = wecom.ListControl(searchDepth=4)
                    if chat_list.Exists(maxSearchSeconds=1):
                        print(f"     聊天列表(第4层) 已找到")
                    else:
                        print(f"     {WARN} 未找到聊天列表控件, 企微版本可能不兼容")
            except Exception as e:
                print(f"     {WARN} 聊天列表扫描异常: {e}")
            return True
        else:
            print(f"{WARN} 未检测到企业微信窗口 - 请确保企微已打开并登录")
            return False
    except ImportError:
        print(f"{WARN} 跳过企微窗口检测 - uiautomation 未安装")
        return False
    except Exception as e:
        print(f"{WARN} 企微检测异常: {e}")
        return False


def check_network():
    import urllib.request
    try:
        urllib.request.urlopen("https://www.baidu.com", timeout=5)
        print(f"{PASS} 网络连通 (百度可达)")
        return True
    except Exception:
        print(f"{WARN} 百度不可达 - 可能网络受限")
        return False


def check_config():
    from pathlib import Path
    config_path = Path(__file__).parent / "config.yaml"
    groups_path = Path(__file__).parent / "data" / "groups.yaml"
    ok = True

    if config_path.exists():
        print(f"{PASS} config.yaml 存在")
    else:
        print(f"{FAIL} config.yaml 缺失")
        ok = False

    if groups_path.exists():
        import yaml
        with open(groups_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        count = len(data.get("groups", []))
        print(f"{PASS} groups.yaml 存在 ({count} 个群)")
    else:
        print(f"{WARN} groups.yaml 缺失 - 请先导入群列表")
        ok = False

    return ok


if __name__ == "__main__":
    main()
