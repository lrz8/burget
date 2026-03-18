# Burget

一个本地运行的 A 股持仓诊断工具，主链路包含：

1. 持仓读取与维护
2. 交易记录落地
3. 行情与资金流抓取
4. 规则引擎诊断
5. LLM 补充解读
6. 历史快照对比
7. 报告落盘与通知发送
8. Streamlit 可视化面板

## 启动方式

启动 Web 面板：

```bash
python3 main.py
```

直接执行一次诊断并输出报告：

```bash
python3 main.py --mode report
```

指定阶段执行：

```bash
python3 main.py --mode report --session pre_open
python3 main.py --mode report --session intraday
python3 main.py --mode report --session post_close
```

如果不希望调用 LLM：

```bash
python3 main.py --mode report --no-llm
```

输出今天的计划任务：

```bash
python3 main.py --mode schedule-plan
```

按计划轮询运行：

```bash
python3 main.py --mode schedule --check-interval 60 --notify
```

记录一笔交易：

```bash
python3 main.py --mode record-trade --symbol 600000 --side buy --quantity 100 --price 10.52 --note "盘中试仓"
```

## 本地私密配置

这是公共仓库，以下内容不要提交：

1. `LLM_API_KEY`
2. 通知 webhook / sendkey
3. 真实持仓
4. 真实监控代码
5. 运行日志与历史报告

推荐把私密变量写入本地 shell，例如 `~/.zshrc`：

```bash
export LLM_API_KEY="your_key"
export LLM_BASE_URL="https://api.siliconflow.cn/v1"
export LLM_MODEL="deepseek-ai/DeepSeek-V3"
export SERVERCHAN_SENDKEY=""
export FEISHU_WEBHOOK_URL=""
```

然后执行：

```bash
source ~/.zshrc
```

仓库内只保留示例模板：

1. [config/cfg.example.yml](/home/lv/Burget/config/cfg.example.yml)
2. [data/portfolio.example.csv](/home/lv/Burget/data/portfolio.example.csv)
3. [data/trades.example.csv](/home/lv/Burget/data/trades.example.csv)

## 测试

运行单元测试：

```bash
python3 -m unittest discover -s tests -v
```

运行离线 smoke test：

```bash
python3 tests/offline_smoke.py
```
