import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import logging
import os
from pathlib import Path

# 动态引入项目的相关模块
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.fetcher.market_data import get_stock_history_kline
from src.data.portfolio_manager import load_portfolio, normalize_portfolio, save_portfolio
from src.data.trade_manager import load_trade_log, record_trade
from src.service.monitor_service import MonitorService
from src.utils.runtime import setup_logging

st.set_page_config(page_title="AI 盯盘助手", page_icon="⚡", layout="wide")
LOG_PATH = setup_logging("dashboard")
logger = logging.getLogger(__name__)

def draw_kline(df_kline: pd.DataFrame, title: str):
    """使用 Plotly 绘制 K 线图"""
    if df_kline.empty:
        return None
    fig = go.Figure(data=[go.Candlestick(x=df_kline['date'],
                open=df_kline['open'],
                high=df_kline['high'],
                low=df_kline['low'],
                close=df_kline['close'])])
    fig.update_layout(title=title, xaxis_rangeslider_visible=False, height=300, margin=dict(l=0, r=0, t=30, b=0))
    return fig

def main():
    service = MonitorService(config_path="config/cfg.yml")
    st.title("⚡ AI 量化盯盘助手")
    st.markdown("通过持续更新持仓成本与行情，为你计算盈亏并生成基于现有数据的操作诊断。")
    st.caption(f"运行日志: {Path(LOG_PATH)}")
    
    # --- 左侧边栏：持仓数据管理 ---
    with st.sidebar:
        st.header("💼 我的持仓配置")
        st.markdown("在此直接修改代码、数量和买入价。修改后自动保存。")
        
        portfolio_df = load_portfolio()
        
        edited_df = st.data_editor(
            portfolio_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "symbol": st.column_config.TextColumn("股票/ETF代码", required=True),
                "name": st.column_config.TextColumn("名称 (选填)", disabled=True),
                "holdings": st.column_config.NumberColumn("持仓数量", min_value=0, step=100),
                "buy_price": st.column_config.NumberColumn("买入均价", min_value=0.0, format="%.3f")
            }
        )
        
        # 检查是否发生修改，若有修改则保存
        normalized_edited_df = normalize_portfolio(edited_df)
        if not portfolio_df.equals(normalized_edited_df):
            save_portfolio(normalized_edited_df)
            logger.info("用户更新了持仓配置，共 %s 条记录。", len(normalized_edited_df))
            st.success("✅ 持仓配置已保存！")
            
        st.markdown("---")
        st.info("💡 提示：点击主界面的【生成策略诊断】按钮获取基于当前数据的 LLM 建议。")

        st.markdown("---")
        st.header("📝 交易记录")
        with st.form("trade_record_form"):
            trade_symbol = st.text_input("代码", max_chars=6)
            trade_name = st.text_input("名称", value="")
            trade_side = st.selectbox(
                "方向",
                options=["buy", "sell"],
                format_func=lambda value: "买入" if value == "buy" else "卖出",
            )
            trade_quantity = st.number_input("数量", min_value=1, step=100, value=100)
            trade_price = st.number_input("成交价", min_value=0.0, step=0.001, format="%.3f")
            trade_note = st.text_input("备注", value="")
            submit_trade = st.form_submit_button("保存交易记录")

        if submit_trade and trade_symbol.strip():
            record_trade(
                symbol=trade_symbol.strip(),
                name=trade_name.strip(),
                side=trade_side,
                quantity=int(trade_quantity),
                price=float(trade_price),
                note=trade_note.strip(),
            )
            st.success("✅ 交易记录已保存。")

        recent_trade_df = load_trade_log().sort_values("timestamp", ascending=False).head(5)
        if not recent_trade_df.empty:
            st.dataframe(recent_trade_df, use_container_width=True, hide_index=True)

    analysis_result = None
    with st.spinner("正在刷新市场与持仓数据..."):
        analysis_result = service.run(
            portfolio_df=normalized_edited_df,
            use_llm=False,
            send_notification=False,
            save_report=False,
        )

    market_data = analysis_result["market_data"]
    stock_data = analysis_result["stock_data"]
    strategy_analysis = analysis_result["analysis"]
    session_type = analysis_result["session_type"]
    recent_trades = analysis_result["recent_trades"]
    history_summary = analysis_result["history_summary"]

    # --- 顶栏：大盘概览 ---
    st.header("📊 市场概览")
    st.caption(f"当前阶段：{session_type}")
    if market_data:
        cols = st.columns(len(market_data))
        for idx, (name, data) in enumerate(market_data.items()):
            cols[idx].metric(
                label=name,
                value=f"{data['最新价']}",
                delta=f"{data['涨跌额']} ({data['涨跌幅(%)']}%)"
            )
        st.caption(strategy_analysis["market"]["summary"])
    else:
        st.warning("未获取到指数数据。")

    st.markdown("---")

    # --- 中栏：盈亏速览与走势 ---
    st.header("🎯 持仓盈亏与近期走势")
    if normalized_edited_df.empty:
        st.warning("请先在左侧边栏添加你的监控持仓数据。")
    elif stock_data:
        df_display = []
        for code, info in stock_data.items():
            df_display.append({
                "代码": code,
                "名称": info["名称"],
                "最新价": info["最新价"],
                "成本价": info["持仓成本价"],
                "涨跌幅(%)": info["涨跌幅(%)"],
                "持仓市值": info["持仓市值(元)"],
                "浮动盈亏": info["浮动盈亏(元)"],
                "盈亏比例(%)": info["盈亏比例(%)"]
            })
        df_view = pd.DataFrame(df_display)

        def color_pnl(val):
            color = 'red' if float(val) < 0 else 'green'
            return f'color: {color}'

        st.dataframe(
            df_view.style.map(color_pnl, subset=['涨跌幅(%)', '浮动盈亏', '盈亏比例(%)']),
            use_container_width=True,
            hide_index=True
        )

        st.subheader("🧭 规则诊断结果")
        strategy_rows = []
        for item in strategy_analysis["positions"]:
            strategy_rows.append(
                {
                    "代码": item["symbol"],
                    "名称": item["name"],
                    "动作": item["action"],
                    "信号强度": item["confidence"],
                    "理由": " ".join(item["reasons"]),
                }
            )
        st.dataframe(pd.DataFrame(strategy_rows), use_container_width=True, hide_index=True)

        if history_summary:
            st.subheader("🕓 历史变化")
            st.write(history_summary.get("summary", "暂无历史快照结论。"))

        if recent_trades:
            st.subheader("🧾 最近交易")
            st.dataframe(pd.DataFrame(recent_trades), use_container_width=True, hide_index=True)

        st.subheader("📉 近期走势 (30日 K线)")
        chart_cols = st.columns(2)
        for i, code in enumerate(stock_data.keys()):
            with chart_cols[i % 2]:
                with st.spinner(f"正在获取 {code} 的 K 线数据..."):
                    kline_df = get_stock_history_kline(code)
                    fig = draw_kline(kline_df, f"{stock_data[code]['名称']} ({code})")
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("未能获取持仓行情，请检查网络、AkShare 数据源状态或代码格式。")

    st.markdown("---")

    # --- 底栏：AI 策略诊断 ---
    st.header("🤖 AI 操作诊断")
    generate_clicked = st.button(
        "⚡ 生成策略诊断",
        type="primary",
        disabled=not bool(stock_data),
    )
    if generate_clicked:
        with st.spinner("🧠 正在请求大模型进行诊断，请稍候..."):
            full_result = service.run(
                portfolio_df=normalized_edited_df,
                use_llm=True,
                send_notification=True,
                save_report=True,
            )
            report_content = full_result["report_content"]
            report_path = full_result["report_path"]
            logger.info("完成一次策略诊断生成，输出文件: %s", report_path)
            
            st.success("✅ 诊断完成！")
            st.markdown(report_content)
            st.caption(f"报告已保存到: {report_path}")
    else:
        st.info("点击上方按钮，基于当前可获取的【持仓盈亏】与【市场概览】生成策略诊断。")

if __name__ == "__main__":
    main()
