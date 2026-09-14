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

# 截图发送开关：true 表示发送截图，false 表示不发送截图
SEND_PIC = False

def send_tg_message(text, image_path=None):
    """发送带 [fday] 前缀的 Telegram 消息，根据代码中的 SEND_PIC 开关决定是否附带截图"""
    formatted_text = f"[fday]\n{text}"
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print(f"Telegram 配置缺失，跳过发送: {text}")
        return

    success = False
    # 只有当 SEND_PIC 为 True、图片路径有效且文件存在时，才尝试发送带图消息
    if SEND_PIC and image_path and os.path.exists(image_path):
        try:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(image_path, "rb") as photo:
                payload = {"chat_id": TG_CHAT_ID, "caption": formatted_text}
                files = {"photo": photo}
                response = requests.post(url, data=payload, files=files, timeout=45)
                if response.status_code == 200:
                    success = True
                else:
                    print(f"Telegram 返回非 200 状态码: {response.text}")
        except Exception as e:
            print(f"发送带图 Telegram 消息超时或失败: {e}，正在尝试降级为纯文本...")

    # 如果开关关闭，或者图片发送失败，则发送纯文本通知
    if not success:
        try:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TG_CHAT_ID, "text": formatted_text}
            requests.post(url, data=payload, timeout=30)
            print("已成功发送纯文本 Telegram 通知。")
        except Exception as text_err:
            print(f"发送纯文本 Telegram 消息失败: {text_err}")

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
            send_tg_message("🌐 正在尝试打开登录页面...")
            
            try:
                page.goto(LOGIN_URL, timeout=30000, wait_until="commit")
            except Exception as nav_err:
                print(f"导航超时/异常: {nav_err}")
                try:
                    page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
                    send_tg_message(f"⚠️ 打开登录页超时\n━━━━━━━━━━━━━━\n错误信息: {str(nav_err)}", screenshot_path)
                except Exception as sc_err:
                    send_tg_message(f"⚠️ 打开登录页超时，且截图失败: {str(nav_err)} | {str(sc_err)}")
                raise nav_err

            page.wait_for_timeout(1000)
            page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
            send_tg_message("✅ 成功打开登录页面，准备执行登录...", screenshot_path)

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

            current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
                    
                    # 重新计算新到期日的剩余天数
                    new_expire_date = datetime.strptime(new_date_str, "%d/%m/%Y")
                    new_remaining_days = (new_expire_date - current_date).days

                    page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")

                    if new_date_str != old_date_str:
                        msg = (
                            f"✅ 续期成功通知\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"🖥 服务器: Fday\n"
                            f"🕒 续期时间: {current_time_str}\n"
                            f"📅 新到期时间: {new_date_str}\n"
                            f"⏳ 剩余时长: {new_remaining_days}天"
                        )
                        print(msg)
                        send_tg_message(msg, screenshot_path)
                    else:
                        msg = (
                            f"⚠️ 续期状态异常\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"🖥 服务器: Fday\n"
                            f"🕒 检测时间: {current_time_str}\n"
                            f"📅 当前到期日: {new_date_str}\n"
                            f"💬 提示: 点击后日期未变，可能未生效。"
                        )
                        print(msg)
                        send_tg_message(msg, screenshot_path)
                else:
                    msg = (
                        f"⚠️ 续期按钮未找到\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🖥 服务器: Fday\n"
                        f"🕒 检测时间: {current_time_str}\n"
                        f"📅 当前到期日: {date_str}\n"
                        f"⏳ 剩余时长: {remaining_days}天"
                    )
                    print(msg)
                    page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
                    send_tg_message(msg, screenshot_path)
            else:
                msg = (
                    f"ℹ️ 服务器状态通知\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🖥 服务器: Fday\n"
                    f"🕒 检测时间: {current_time_str}\n"
                    f"📅 当前到期日: {date_str}\n"
                    f"⏳ 剩余时长: {remaining_days}天\n"
                    f"💬 提示: 剩余天数大于2天，暂不需要续期。"
                )
                print(msg)
                page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
                send_tg_message(msg, screenshot_path)

        except Exception as e:
            error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            error_msg = (
                f"❌ 脚本运行异常通知\n"
                f"━━━━━━━━━━━━━━\n"
                f"🖥 服务器: Fday\n"
                f"🕒 发生时间: {error_time}\n"
                f"🚨 错误详情: {str(e)}"
            )
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
