import os
import sys
import time
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

def handle_cloudflare_turnstile(page):
    """
    1:1 映射你提供的成功项目中的过 CF 核心逻辑：
    检查页面是否存在 cf-turnstile-response 输入框，若存在则尝试定位并点击 iframe 内部的复选框
    """
    try:
        time.sleep(2)
        # 探测是否存在输入框
        has_cf = page.evaluate('document.querySelector("input[name=\'cf-turnstile-response\']") !== null')
        if not has_cf:
            return True
        
        print("[INFO] 发现 Turnstile 拦截，尝试在 iframe 内部寻找并点击验证...")
        
        # 寻找 cloudflare 挑战 iframe
        iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
        iframe_element = page.locator(iframe_selector)
        
        if iframe_element.count() > 0:
            frame = page.frame_locator(iframe_selector)
            time.sleep(1)
            checkbox = frame.locator('input[type="checkbox"]')
            if checkbox.count() > 0:
                checkbox.click(force=True)
            else:
                frame.locator('body').click(force=True)
        else:
            # 兼容处理：尝试直接在页面上找常见的验证框点击
            print("[INFO] 未直接匹配到标准 iframe，尝试通用坐标或点击...")
            
        time.sleep(5)
        return True
    except Exception as e:
        print(f"[WARN] 处理 CF 验证过程异常: {e}")
        return False

def main():
    screenshot_target = "screenshot_target.png"
    screenshot_clicked = "screenshot_clicked.png"
    screenshot_cf = "screenshot_cf.png"
    screenshot_final = "screenshot_final.png"
    
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

        # 自动处理网页弹出的确认框（confirm/alert）
        page.on("dialog", lambda dialog: (print(f"检测到网页弹窗: {dialog.message}，已自动点击确定"), dialog.accept()))

        try:
            print("正在访问登录页面...")
            
            try:
                page.goto(LOGIN_URL, timeout=30000, wait_until="commit")
            except Exception as nav_err:
                print(f"导航超时/异常: {nav_err}")
                try:
                    page.screenshot(path=screenshot_target, timeout=5000, animations="disabled")
                    send_tg_message(f"⚠️ 打开登录页超时\n━━━━━━━━━━━━━━\n错误信息: {str(nav_err)}", screenshot_target)
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
            page.goto(SERVICES_URL, timeout=30000, wait_until="load")
            
            # 只要元素附加在 DOM 中即可
            page.wait_for_selector('.service-status', state="attached", timeout=15000)

            # 采用遍历所有匹配项的方式，找到包含文本的那个元素
            status_elements = page.locator('.service-status')
            status_text = ""
            for i in range(status_elements.count()):
                txt = status_elements.nth(i).inner_text()
                if "Renouvellement" in txt or "/" in txt:
                    status_text = txt
                    break
            
            if not status_text and status_elements.count() > 0:
                status_text = status_elements.first.inner_text()

            print(f"当前状态文本: {status_text}")

            date_str = status_text.split(":")[-1].strip()
            expire_date = datetime.strptime(date_str, "%d/%m/%Y").date()
            current_date = datetime.now().date()
            
            remaining_days = (expire_date - current_date).days
            print(f"服务器到期日期: {date_str}, 剩余天数: {remaining_days} 天")

            current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if remaining_days <= 2:
                print("剩余天数小于或等于2天，检查续期按钮状态...")
                
                # 使用组合类名和 data-uuid 精准定位续期按钮
                renew_btn = page.locator('button.btn-renew.js-free-renew[data-uuid]').first
                
                if renew_btn.count() > 0:
                    print("发现可用的续期按钮，准备加红框并执行点击...")
                    old_date_str = date_str
                    
                    try:
                        btn_html = renew_btn.evaluate("el => el.outerHTML")
                        print(f"定位到的按钮 HTML: {btn_html}")
                        
                        renew_btn.evaluate("el => { el.style.border = '4px solid red'; }")
                        
                        # 1. 截图 1：【点击前 - 目标确认图】
                        page.screenshot(path=screenshot_target, timeout=5000, animations="disabled")
                        
                        renew_btn.scroll_into_view_if_needed()
                        renew_btn.click(force=True)
                        renew_btn.evaluate("el => el.click()")
                        print("点击动作已执行")
                    except Exception as e:
                        print(f"标红或点击异常: {e}")

                    # 2. 截图 2：【点击后 - 即时现场图】
                    page.screenshot(path=screenshot_clicked, timeout=5000, animations="disabled")
                    
                    send_tg_message("🔍 【排查步骤 1/2】已锁定续期按钮（仅红框）", screenshot_target)
                    send_tg_message("🔍 【排查步骤 2/2】刚执行完点击动作的即时画面", screenshot_clicked)

                    # ── 🔥 严谨的 Cloudflare Turnstile 人机验证 3 次重试与 Token 判定逻辑 ────────────────
                    print("🛸 激活 3 次『验证->检查 Token 是否有密文』循环机制...")
                    success_loaded = False
                    
                    for cf_attempt in range(3):
                        handle_cloudflare_turnstile(page)
                        try:
                            print(f"[INFO] 正在验证云盾拦截是否成功穿透 (尝试次数: {cf_attempt + 1})...")
                            time.sleep(5)
                            
                            # 【核心判定】：根据 input 内是否有 Token 密文来严格判定是否成功打勾
                            cf_token_value = page.evaluate('''
                                (() => {
                                    const input = document.querySelector("input[name='cf-turnstile-response']");
                                    return input ? input.value : "";
                                })()
                            ''')
                            
                            if cf_token_value and len(cf_token_value.strip()) > 0:
                                print(f"[INFO] 验证成功！云盾 Token 令牌已顺利生成填充 (尝试次数: {cf_attempt + 1})")
                                success_loaded = True
                                break
                            else:
                                raise Exception("云盾输入框的 Token 依然为空，人机验证未通过")
                                
                        except Exception as e:
                            print(f"[WARN] 尝试 {cf_attempt + 1}: 未成功过验证 ({str(e)})，触发重试等待...")
                            if cf_attempt < 2:
                                time.sleep(5)

                    # 验证处理完毕后截图存档
                    page.screenshot(path=screenshot_cf, timeout=5000, animations="disabled")
                    send_tg_message(f"🛡️ 【CF验证结果】是否成功通过: {success_loaded}", screenshot_cf)

                    if success_loaded:
                        # 等待并刷新检查结果
                        print("[INFO] CF 验证已通过，等待后端同步数据...")
                        page.wait_for_timeout(5000)
                        page.reload(wait_until="load")
                        
                        page.wait_for_selector('.service-status', state="attached", timeout=15000)
                        
                        new_status_elements = page.locator('.service-status')
                        new_status_text = ""
                        for i in range(new_status_elements.count()):
                            txt = new_status_elements.nth(i).inner_text()
                            if "Renouvellement" in txt or "/" in txt:
                                new_status_text = txt
                                break
                        if not new_status_text and new_status_elements.count() > 0:
                            new_status_text = new_status_elements.first.inner_text()

                        new_date_str = new_status_text.split(":")[-1].strip()
                        new_expire_date = datetime.strptime(new_date_str, "%d/%m/%Y").date()
                        new_remaining_days = (new_expire_date - current_date).days

                        # 最终状态截图
                        page.screenshot(path=screenshot_final, timeout=5000, animations="disabled")

                        if new_date_str != old_date_str:
                            msg = (
                                f"✅ 续期成功通知 (验证码通过)\n"
                                f"━━━━━━━━━━━━━━\n"
                                f"🖥 服务器: Fday\n"
                                f"🕒 续期时间: {current_time_str}\n"
                                f"📅 新到期时间: {new_date_str}\n"
                                f"⏳ 剩余时长: {new_remaining_days}天"
                            )
                            print(msg)
                            send_tg_message(msg, screenshot_final)
                        else:
                            msg = (
                                f"⚠️ 续期状态异常 (过完验证后日期未变)\n"
                                f"━━━━━━━━━━━━━━\n"
                                f"🖥 服务器: Fday\n"
                                f"🕒 检测时间: {current_time_str}\n"
                                f"📅 当前到期日: {new_date_str}\n"
                                f"💬 提示: 已通过人机验证，但后端未接受续期请求。"
                            )
                            print(msg)
                            send_tg_message(msg, screenshot_final)
                    else:
                        print("[ERROR] 经过 3 次循环重试，CF 验证仍未打勾通过（Token 为空）")
                        send_tg_message("❌ *续期失败*: 经过 3 次重试，CF 验证未能成功通过（Token 校验未通过）。", screenshot_cf)
                else:
                    msg = (
                        f"⏳ 续期按钮暂未激活\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🖥 服务器: Fday\n"
                        f"🕒 检测时间: {current_time_str}\n"
                        f"📅 当前到期日: {date_str}\n"
                        f"⏳ 剩余时长: {remaining_days}天\n"
                        f"💬 提示: 未检测到符合条件的续期按钮。"
                    )
                    print(msg)
                    send_tg_message(msg, screenshot_target)
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
                send_tg_message(msg, screenshot_target)

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
                error_screenshot = "screenshot_error.png"
                page.screenshot(path=error_screenshot, timeout=5000, animations="disabled")
                send_tg_message(error_msg, error_screenshot)
            except:
                send_tg_message(error_msg)
            sys.exit(1)
        finally:
            browser.close()

if __name__ == "__main__":
    main()
