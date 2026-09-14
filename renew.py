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
    """发送带 [fday] 前缀的 Telegram 消息和截图"""
    formatted_text = f"[fday] {text}"
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print(f"Telegram 配置缺失，跳过发送: {formatted_text}")
        return

    try:
        if image_path and os.path.exists(image_path):
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(image_path, "rb") as photo:
                payload = {"chat_id": TG_CHAT_ID, "caption": formatted_text}
                files = {"photo": photo}
                requests.post(url, data=payload, files=files, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TG_CHAT_ID, "text": formatted_text}
            requests.post(url, data=payload, timeout=30)
    except Exception as e:
        print(f"发送 Telegram 消息失败: {e}")

def main():
    screenshot_path = "screenshot.png"
    
    with sync_playwright() as p:
        # 启动无头浏览器
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        try:
            print("正在访问登录页面...")
            send_tg_message("正在尝试打开登录页面...")
            
            # 访问登录页（放宽超时，或改用 domcontentloaded 避免被某些慢资源卡死）
            try:
                page.goto(LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
            except Exception as nav_err:
                print(f"导航超时，尝试截图留证: {nav_err}")
                page.screenshot(path=screenshot_path)
                send_tg_message(f"打开登录页超时/异常: {str(nav_err)}", screenshot_path)
                raise nav_err

            # 成功打开后立即截图发送
            page.screenshot(path=screenshot_path)
            send_tg_message("成功打开登录页面，准备输入账号密码...", screenshot_path)

            # 填写登录信息
            page.fill('//*[@id="email"]', EMAIL)
            page.fill('//*[@id="password"]', PASSWORD)
            
            # 点击登录按钮并等待页面跳转
            with page.expect_navigation(timeout=30000):
                page.click('//*[@id="loginForm"]/button')

            # 检查是否成功登录并进入服务页
            page.goto(SERVICES_URL, timeout=60000, wait_until="domcontentloaded")
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
                # 检查并点击续期按钮
                renew_btn = page.locator('.btn-renew.js-free-renew')
                if renew_btn.count() > 0:
                    old_date_str = date_str
                    renew_btn.click()
                    
                    # 等待几秒让后端处理并刷新状态
                    page.wait_for_timeout(5000)
                    page.reload()
                    page.wait_for_selector('.service-status', timeout=15000)
                    
                    new_status_text = page.locator('.service-status').inner_text()
                    new_date_str = new_status_text.split(":")[-1].strip()
                    
                    # 截图留存
                    page.screenshot(path=screenshot_path)

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
                    page.screenshot(path=screenshot_path)
                    send_tg_message(msg, screenshot_path)
            else:
                msg = f"剩余天数大于2天 ({remaining_days} 天)，暂不需要续期。当前到期日: {date_str}"
                print(msg)
                page.screenshot(path=screenshot_path)
                send_tg_message(msg, screenshot_path)

        except Exception as e:
            error_msg = f"脚本执行过程中发生异常: {str(e)}"
            print(error_msg)
            try:
                page.screenshot(path=screenshot_path)
                send_tg_message(error_msg, screenshot_path)
            except:
                send_tg_message(error_msg)
            sys.exit(1)
        finally:
            browser.close()

if __name__ == "__main__":
    main()
