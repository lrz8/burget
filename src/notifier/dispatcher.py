import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class NotifierDispatcher:
    def __init__(self, config: Dict[str, Any]):
        notifier_config = config.get("notifier", {})
        self.serverchan_sendkey = notifier_config.get("serverchan_sendkey", "")
        self.feishu_webhook_url = notifier_config.get("feishu_webhook_url", "")

    def send_serverchan(self, title: str, content: str):
        """通过 Server酱 推送通知"""
        if not self.serverchan_sendkey:
            logger.info("未配置 Server酱 sendkey，跳过推送。")
            return
            
        logger.info("开始通过 Server酱 发送推送通知...")
        url = f"https://sctapi.ftqq.com/{self.serverchan_sendkey}.send"
        data = {
            "title": title,
            "desp": content
        }
        try:
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            logger.info("Server酱 推送成功。")
        except Exception as e:
            logger.error(f"Server酱 推送失败: {e}", exc_info=True)

    def send_feishu(self, title: str, content: str):
        """通过飞书 Webhook 推送通知"""
        if not self.feishu_webhook_url:
            logger.info("未配置 飞书 Webhook，跳过推送。")
            return
            
        logger.info("开始通过飞书 Webhook 发送推送通知...")
        
        headers = {"Content-Type": "application/json"}
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [
                            [{"tag": "text", "text": content}]
                        ]
                    }
                }
            }
        }
        
        try:
            response = requests.post(self.feishu_webhook_url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            logger.info("飞书 Webhook 推送成功。")
        except Exception as e:
            logger.error(f"飞书 Webhook 推送失败: {e}", exc_info=True)

    def notify_all(self, title: str, content: str):
        """触发所有配置的通知渠道"""
        self.send_serverchan(title, content)
        self.send_feishu(title, content)
