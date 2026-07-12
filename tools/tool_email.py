# tool_email.py
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import os

from config import env_config

# 🌟 绝招 1：强行清洗可能残留的幽灵代理，确保邮件流量绝对直连！
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("all_proxy", None)

def send_notification_email(subject, content, receiver_email):
    message = MIMEText(content, 'plain', 'utf-8')
    message['From'] = Header("🧠 模块化 Agent", 'utf-8')
    message['To'] = Header(receiver_email, 'utf-8')
    message['Subject'] = Header(subject, 'utf-8')

    try:
        # 使用 465 端口和 SSL 加密
        server = smtplib.SMTP_SSL(env_config.SMTP_SERVER, env_config.SMTP_PORT, timeout=10)
        
        # 🌟 绝招 2：开启底层调试模式，把网络握手细节全部打印出来
        server.set_debuglevel(1)
        
        # 登录并发送
        server.login(env_config.SENDER_EMAIL, env_config.AUTH_CODE)
        server.sendmail(env_config.SENDER_EMAIL, [receiver_email], message.as_string())
        server.quit()
        return "\n✅ 邮件发送成功！"
    except Exception as e:
        return f"\n❌ 邮件发送失败: {e}"

# ======= 动态路由注册声明 =======

REGISTER_NAME = "send_notification_email" # 👈 必须和你在这个文件里定义的发送邮件函数名一模一样

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "send_notification_email",
        "description": "邮件发送助手。当用户要求【发邮件】、【发送通知】时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "邮件主题"},
                "content": {"type": "string", "description": "邮件正文内容"}
            },
            "required": ["subject", "content"]
        }
    }
}