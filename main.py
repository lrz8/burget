import argparse
import os
import subprocess
import sys

from src.service.monitor_service import MonitorService
from src.utils.runtime import setup_logging

def main():
    parser = argparse.ArgumentParser(description="A股 AI 量化盯盘助手")
    parser.add_argument(
        "--mode",
        choices=["dashboard", "report"],
        default="dashboard",
        help="dashboard: 启动 Streamlit 页面；report: 直接执行一次策略诊断并输出报告。",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="在 report 模式下禁用 LLM 补充解读。",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="在 report 模式下发送通知。",
    )
    args = parser.parse_args()

    log_path = setup_logging("launcher")
    try:
        if args.mode == "report":
            service = MonitorService(config_path="config/cfg.yml")
            result = service.run(
                use_llm=not args.no_llm,
                send_notification=args.notify,
                save_report=True,
            )
            print("======================================================")
            print("A股 AI 量化盯盘助手 - 单次诊断完成")
            print(f"运行日志文件: {log_path}")
            print(f"报告输出: {result['report_path']}")
            print("======================================================\n")
            print(result["report_content"])
            return

        print("======================================================")
        print("🚀 欢迎使用 A股 AI 量化盯盘助手")
        print("正在启动 Web 控制面板，请在弹出的浏览器窗口中进行操作。")
        print("如果不小心关闭了窗口，可以在浏览器中输入本地地址重新打开。")
        print(f"运行日志文件: {log_path}")
        print("======================================================\n")

        current_dir = os.path.dirname(os.path.abspath(__file__))
        app_path = os.path.join(current_dir, "src", "dashboard", "app.py")
        subprocess.run([sys.executable, "-m", "streamlit", "run", app_path])
    except KeyboardInterrupt:
        print("\n盯盘助手已安全退出。")
    except Exception as e:
        print(f"启动失败: {e}")

if __name__ == "__main__":
    main()
