import json
import logging
from typing import Dict, Any

from openai import OpenAI

logger = logging.getLogger(__name__)

class LLMAnalyzer:
    def __init__(self, config: Dict[str, Any]):
        llm_config = config.get("llm", {})
        self.api_key = llm_config.get("api_key", "")
        self.base_url = llm_config.get("base_url", "https://api.openai.com/v1")
        self.model = llm_config.get("model", "gpt-4o-mini")
        
        if not self.api_key:
            logger.warning("未配置 LLM API Key，LLM 分析功能可能无法使用。")
            
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def generate_review(self, market_data: Dict[str, Any], stock_data: Dict[str, Any], fund_flow: Dict[str, Any]) -> str:
        """生成补充解读文本"""
        logger.info("开始调用 LLM 生成补充解读...")
        
        if not self.api_key:
            msg = "LLM_API_KEY 缺失，跳过 LLM 分析环节。"
            logger.error(msg)
            return msg
            
        if not stock_data:
            msg = "当前没有可分析的持仓行情数据，请先检查持仓列表或行情接口状态。"
            logger.warning(msg)
            return msg

        prompt = f"""
请你作为一位谨慎的 A 股持仓诊断助手，根据以下已采集到的结构化数据生成补充解读。
你只能使用输入里真实给出的字段进行推理，不允许补充外部新闻、政策、行业传闻、主观技术位、成交阈值或任何未提供的数据。
如果数据不足以支持强判断，必须明确写“数据不足，建议观察”，不要编造理由。

**大盘指数情况:**
{json.dumps(market_data, ensure_ascii=False, indent=2, default=str)}

**大盘资金流向:**
{json.dumps(fund_flow, ensure_ascii=False, indent=2, default=str)}

**我的自选持仓及盈亏情况:**
{json.dumps(stock_data, ensure_ascii=False, indent=2, default=str)}

**输出要求：**
1. 输出长度控制在 200 到 400 中文字。
2. 只做两部分：`### 市场补充观察` 和 `### 持仓补充观察`。
3. 可以概括数据体现出的风险与机会，但不能新增任何输入之外的事实。
4. 不要重复完整表格，不要生成整篇报告，不要写免责声明标题。
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位严谨的 A 股持仓分析师。"
                            "你必须严格依据输入数据输出，不得虚构事实，不得把缺失数据伪装成结论。"
                        ),
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=2000
            )
            report = response.choices[0].message.content
            logger.info("LLM 补充解读生成完毕。")
            return report
        except Exception as e:
            logger.error(f"调用 LLM 生成补充解读时发生错误: {e}", exc_info=True)
            return f"生成补充解读失败，错误信息: {e}"
