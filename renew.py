import os
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

# 从环境变量（GitHub Secrets）安全获取配置
LOGIN_URL = os.environ.get("LOGIN_URL")
SERVICES_URL = os.environ.get("SERVICES_URL")
EMAIL = os.environ.get("FRIDAY_EMAIL")
PASSWORD = os.environ.get("FRIDAY_PASSWORD")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

def send_tg_message(text, image_path=None):
    """发送带 [fday] 前缀的 Telegram 消息，若图片发送超时或失败则自动降级为纯文本"""
    formatted_text = f"[fday] {text}"
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print(f"Telegram 配置缺失，跳过发送: {formatted_text}")
        return

    success = False
    try:
        # 尝试发送带图片的通知
        if image_path and os.path.exists(image_path):
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(image_path, "rb") as photo:
                payload = {"chat_id": TG_CHAT_ID, "caption": formatted_text}
                files = {"photo": photo}
                # 将超时时间稍微放宽到 45 秒
                response = requests.post(url, data=payload, files=files, timeout=45)
                if response.status_code == 200:
                    success = True
                else:
                    print(f"Telegram 返回非 200 状态码: {response.text}")
    except Exception as e:
        print(f"发送带图 Telegram 消息超时或失败: {e}，正在尝试降级为纯文本...")

    # 如果没有图片，或者图片发送失败，则自动降级发送纯文本消息
    if not success:
        try:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            # 如果是因为图片超时失败，在文本后加个小提示
            text_to_send = formatted_text if not image_path else f"{formatted_text} (注: 截图发送超时)"
            payload = {"chat_id": TG_CHAT_ID, "text": text_to_send}
            requests.post(url, data=payload, timeout=30)
            print("已成功降级发送纯文本 Telegram 通知。")
        except Exception as text_err:
            print(f"降级发送纯文本也失败: {text_err}")

def main():
    screenshot_path = "screenshot.png"
    
    with sync_playwright() as p:
        # 启动无头浏览器并加入防检测参数
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        # 伪装成真实的桌面端 Chrome 浏览器和法语区域环境
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="fr-FR",
            timezone_id="Europe/Paris"
        )
        page = context.new_page()

        try:
            print("正在访问登录页面...")
            send_tg_message("正在尝试打开登录页面...")
            
            try:
                page.goto(LOGIN_URL, timeout=30000, wait_until="commit")
            except Exception as nav_err:
                print(f"导航超时/异常: {nav_err}")
                try:
                    page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
                    send_tg_message(f"打开登录页超时，当前页面截图如下:", screenshot_path)
                except Exception as sc_err:
                    send_tg_message(f"打开登录页超时，且截图失败: {str(nav_err)} | {str(sc_err)}")
                raise nav_err

            page.wait_for_timeout(1000)
            page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
            send_tg_message("成功打开登录页面，当前页面状态:", screenshot_path)

            # 填写登录信息
            page.fill('//*[@id="email"]', EMAIL)
            page.fill('//*[@id="password"]', PASSWORD)
            
            # 点击登录按钮并等待页面跳转
            with page.expect_navigation(timeout=30000):
                page.click('//*[@id="loginForm"]/button')

            # 检查是否成功登录并进入服务页
            page.goto(SERVICES_URL, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_selector('.service-status', timeout=15000)

            # 获取到期日期文本，例如 "Renouvellement : 16/09/2026"
            status_text = page.locator('.service-status').inner_text()
            print(f"当前状态文本: {status_text}")

            # 解析日期
            date_str = status_text.split(":")[-1].strip()
            expire_date = datetime.strptime(date_str, "%d/%m/%Y")
            current_date = datetime.now()
            
            # 计算剩余天数
            remaining_days = (expire_date - current_date).days
            print(f"服务器到期日期: {date_str}, 剩余天数: {remaining_days} 天")

            if remaining_days <= 2:
                print("剩余天数小于或等于2天，开始执行续期操作...")
                renew_btn = page.locator('.btn-renew.js-free-renew')
                if renew_btn.count() > 0:
                    old_date_str = date_str
                    renew_btn.click()
                    
                    page.wait_for_timeout(5000)
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_selector('.service-status', timeout=15000)
                    
                    new_status_text = page.locator('.service-status').inner_text()
                    new_date_str = new_status_text.split(":")[-1].strip()
                    
                    page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")

                    if new_date_str != old_date_str:
                        msg = f"续期成功！原到期日: {old_date_str}，新到期日: {new_date_str}"
                        print(msg)
                        send_tg_message(msg, screenshot_path)
                    else:
                        msg = f"续期点击后日期未发生变化 ({new_date_str})，可能续期失败或还未生效。"
                        print(msg)
                        send_tg_message(msg, screenshot_path)
                else:
                    msg = "未找到可用的续期按钮（可能未到时间或元素不存在）。"
                    print(msg)
                    page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
                    send_tg_message(msg, screenshot_path)
            else:
                msg = f"剩余天数大于2天 ({remaining_days} 天)，暂不需要续期。当前到期日: {date_str}"
                print(msg)
                page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
                send_tg_message(msg, screenshot_path)

        except Exception as e:
            error_msg = f"脚本执行过程中发生异常: {str(e)}"
            print(error_msg)
            try:
                page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
                send_tg_message(error_msg, screenshot_path)
            except:
                send_tg_message(error_msg)
            sys.exit(1)
        finally:
            browser.close()

if __name__ == "__main__":
    main()
