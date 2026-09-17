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

# 截图发送开关：True 表示发送截图，False 表示不发送截图
SEND_PIC = True

def send_tg_message(text, image_path=None):
    """发送带 [fday] 前缀的 Telegram 消息，根据代码中的 SEND_PIC 开关决定是否附带截图"""
    formatted_text = f"[fday]\n{text}"
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print(f"Telegram 配置缺失，跳过发送: {text}")
        return

    success = False
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
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="fr-FR",
            timezone_id="Europe/Paris"
        )
        page = context.new_page()

        try:
            print("正在访问登录页面...")
            
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

            # 填写登录信息
            page.fill('//*[@id="email"]', EMAIL)
            page.fill('//*[@id="password"]', PASSWORD)
            
            with page.expect_navigation(timeout=30000):
                page.click('//*[@id="loginForm"]/button')

            # 检查是否成功登录并进入服务页
            page.goto(SERVICES_URL, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_selector('.service-status', timeout=15000)

            status_text = page.locator('.service-status').inner_text()
            print(f"当前状态文本: {status_text}")

            date_str = status_text.split(":")[-1].strip()
            expire_date = datetime.strptime(date_str, "%d/%m/%Y")
            current_date = datetime.now()
            
            remaining_days = (expire_date - current_date).days
            print(f"服务器到期日期: {date_str}, 剩余天数: {remaining_days} 天")

            current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if remaining_days <= 2:
                print("剩余天数小于或等于2天，检查续期按钮状态...")
                
                # 寻找可点击的激活状态续期按钮（排除 is-disabled）
                renew_btn = page.locator('button.btn-renew.js-free-renew:not([disabled])')
                
                if renew_btn.count() > 0:
                    print("发现可用的续期按钮，执行续期...")
                    old_date_str = date_str
                    renew_btn.click()
                    
                    page.wait_for_timeout(5000)
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_selector('.service-status', timeout=15000)
                    
                    new_status_text = page.locator('.service-status').inner_text()
                    new_date_str = new_status_text.split(":")[-1].strip()
                    
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
                    # 按钮存在但处于 disabled / is-disabled 状态
                    msg = (
                        f"⏳ 续期按钮暂未激活\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🖥 服务器: Fday\n"
                        f"🕒 检测时间: {current_time_str}\n"
                        f"📅 当前到期日: {date_str}\n"
                        f"⏳ 剩余时长: {remaining_days}天\n"
                        f"💬 提示: 虽已到最后2天，但官方按钮尚未开放点按（可能需再等几小时）。"
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
