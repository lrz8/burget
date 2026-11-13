# Burget

一个本地运行的 A 股持仓诊断工具，主链路包含：

1. 持仓读取与维护
2. 交易记录落地
3. 行情与资金流抓取
4. 规则引擎诊断
5. LLM 补充解读
6. 历史快照对比
7. 显式选择手工持仓或交易账本推导持仓
8. 盘后自动汇总日报
9. 报告落盘与通知发送
10. Streamlit 可视化面板

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

说明：

1. 默认采用手工持仓（manual），交易记录只提供上下文，不会覆盖持仓表。升级后如需继续由完整交易历史推导持仓，请在本地配置中显式选择 trades。
2. 当前数据源为日线：盘前、盘中及非交易时段仅生成观察提示；盘后且行情日期与报告日期一致时，才生成下一交易日条件预案。行情日期缺失、过期或标的抓取失败时，不生成该标的的买卖建议。
3. 现有 12% 止盈、-8% 止损阈值保持不变，尚未经过历史收益回测；日线涨跌不再作为做 T 的依据。
4. 计划任务使用上海时间和 AkShare 交易日历，日历不可用或未覆盖目标日期时暂停自动运行；手工报告仍可使用。每个任务有效期为 120 秒，过期跳过；执行状态保存在本地 data/scheduler_state.json，重启不会补跑当日全部任务。
5. 盘后日报统计“快照浮动盈亏变化”，不包含已实现收益、交易费用和资金出入，不能当作账户当日收益。估值不完整时暂停计算变化。
6. 页面普通刷新不再写入历史快照；主动生成报告和计划任务会保存快照。

## 持仓来源与升级

本地配置 config/cfg.yml 中的 monitor.position_source 支持：

- manual（默认）：data/portfolio.csv 是当前持仓的唯一来源；记录买卖后需在持仓表更新数量和均价。
- trades：从 data/trades.csv 的完整交易历史推导仓位，手工持仓不参与合并；超过持仓数量的卖出会报错，要求补齐账本。

如果只有近期交易，可以在 trades 模式配置明确的期初持仓：

~~~yaml
monitor:
  position_source: trades
  buy_cooldown_minutes: 30
  opening_positions_path: data/opening_positions.csv
  opening_as_of: "2026-03-17 15:00:00"
~~~

期初 CSV 保持 symbol,name,holdings,buy_price 四列，代表 opening_as_of 时点的持仓；仅叠加该时点之后的交易，避免重复记账。期初文件不存在、时点未配置或交易账本无法对账时会报错，不会静默改为空仓。未来时间的交易不参与当前诊断。期初持仓文件和调度状态已加入 .gitignore。

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

1. [config/cfg.example.yml](config/cfg.example.yml)
2. [data/portfolio.example.csv](data/portfolio.example.csv)
3. [data/trades.example.csv](data/trades.example.csv)

## 测试

运行单元测试：

```bash
python3 -m unittest discover -s tests -v
```

运行离线 smoke test：

```bash
python3 tests/offline_smoke.py
```
