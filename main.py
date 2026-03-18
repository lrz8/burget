import argparse
from datetime import datetime
import os
import subprocess
import sys

from src.data.trade_manager import record_trade
from src.service.monitor_service import MonitorService
from src.service.session_planner import MonitorScheduler, build_schedule_plan
from src.utils.runtime import setup_logging

def main():
    parser = argparse.ArgumentParser(description="A股 AI 量化盯盘助手")
    parser.add_argument(
        "--mode",
        choices=["dashboard", "report", "schedule", "schedule-plan", "record-trade"],
        default="dashboard",
        help="dashboard: 启动 Streamlit 页面；report: 单次诊断；schedule: 计划轮询；schedule-plan: 输出今日计划；record-trade: 记录一笔交易。",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="在 report 或 schedule 模式下禁用 LLM 补充解读。",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="在 report 或 schedule 模式下发送通知。",
    )
    parser.add_argument(
        "--session",
        choices=["auto", "pre_open", "intraday", "post_close", "midday_break", "off_hours"],
        default="auto",
        help="report 模式下指定运行阶段。",
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=60,
        help="schedule 模式下的轮询间隔，单位秒。",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="schedule 模式下最多轮询次数，默认持续运行。",
    )
    parser.add_argument("--symbol", default="", help="record-trade 模式使用，交易代码。")
    parser.add_argument("--name", default="", help="record-trade 模式使用，名称。")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy", help="record-trade 模式使用，买卖方向。")
    parser.add_argument("--quantity", type=int, default=0, help="record-trade 模式使用，成交数量。")
    parser.add_argument("--price", type=float, default=0.0, help="record-trade 模式使用，成交价格。")
    parser.add_argument("--note", default="", help="record-trade 模式使用，备注。")
    parser.add_argument(
        "--timestamp",
        default="",
        help="record-trade 模式使用，格式 YYYY-MM-DD HH:MM:SS；留空则使用当前时间。",
    )
    args = parser.parse_args()

    log_path = setup_logging("launcher")
    try:
        if args.mode == "record-trade":
            if not args.symbol or args.quantity <= 0 or args.price <= 0:
                raise ValueError("record-trade 模式需要提供有效的 --symbol、--quantity、--price。")
            trade_time = datetime.strptime(args.timestamp, "%Y-%m-%d %H:%M:%S") if args.timestamp else None
            record_trade(
                symbol=args.symbol,
                name=args.name,
                side=args.side,
                quantity=args.quantity,
                price=args.price,
                note=args.note,
                timestamp=trade_time,
            )
            print("交易记录已保存。")
            return

        if args.mode == "schedule-plan":
            print("今日计划任务：")
            for item in build_schedule_plan():
                print(f"- {item['run_at']} {item['session_type']}")
            return

        if args.mode == "report":
            service = MonitorService(config_path="config/cfg.yml")
            result = service.run(
                use_llm=not args.no_llm,
                send_notification=args.notify,
                save_report=True,
                session_type=args.session,
            )
            print("======================================================")
            print("A股 AI 量化盯盘助手 - 单次诊断完成")
            print(f"运行日志文件: {log_path}")
            print(f"报告输出: {result['report_path']}")
            print("======================================================\n")
            print(result["report_content"])
            return

        if args.mode == "schedule":
            service = MonitorService(config_path="config/cfg.yml")
            scheduler = MonitorScheduler(service)
            print("======================================================")
            print("A股 AI 量化盯盘助手 - 计划轮询启动")
            print(f"运行日志文件: {log_path}")
            print(f"轮询间隔: {args.check_interval} 秒")
            print("======================================================\n")
            scheduler.run_loop(
                check_interval_seconds=args.check_interval,
                max_cycles=args.max_cycles,
                use_llm=not args.no_llm,
                send_notification=args.notify,
            )
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
