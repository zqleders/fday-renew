#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
from datetime import datetime
from pathlib import Path
import requests

# 引入 SeleniumBase 的原生 SB 环境
from seleniumbase import SB

# ── 核心配置与目录 ──────────────────────────────────────
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LOGIN_URL = os.environ.get("LOGIN_URL")
SERVICES_URL = os.environ.get("SERVICES_URL")
EMAIL = os.environ.get("FRIDAY_EMAIL")
PASSWORD = os.environ.get("FRIDAY_PASSWORD")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
SYS_PROXY = os.environ.get("http_proxy") or None

# 截图发送开关
SEND_PIC = True

def tg_send(text: str):
    """发送纯文本 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID: 
        print(f"Telegram 配置缺失，跳过发送: {text}")
        return
    try:
        formatted_text = f"[fday]\n{text}"
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": formatted_text, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print(f"发送 TG 文字通知失败: {e}")

def tg_send_photo(photo_path: str, caption: str = ""):
    """发送带图 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID or not os.path.exists(photo_path): 
        return
    try:
        formatted_caption = f"[fday]\n{caption}" if caption else "[fday]"
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as photo:
            data = {"chat_id": TG_CHAT_ID, "caption": formatted_caption}
            requests.post(url, data=data, files={"photo": photo}, timeout=30)
            print(f"[TG PHOTO INFO] 截图发送成功: {photo_path}")
    except Exception as e:
        print(f"发送 TG 图片通知失败: {e}")

def handle_cloudflare_turnstile(sb):
    """
    100% 照搬成功项目的过 Cloudflare 逻辑：
    使用 uc_gui_click_captcha() 进行物理 GUI 穿透点击
    """
    try:
        time.sleep(2)
        result = sb.driver.execute_script('return document.querySelector("input[name=\'cf-turnstile-response\']") !== null')
        if not result:
            print("[INFO] 当前页面未检测到 cf-turnstile-response 输入框，无需处理验证。")
            return True
        
        print("[INFO] 发现 Turnstile 拦截，尝试使用 SB UC 模式执行物理 GUI 点击...")
        sb.uc_gui_click_captcha()
        time.sleep(5)
        return True
    except Exception as e:
        print(f"[WARN] 处理 CF 验证时发生异常: {e}")
        return False

def main():
    screenshot_target = OUTPUT_DIR / "screenshot_target.png"
    screenshot_clicked = OUTPUT_DIR / "screenshot_clicked.png"
    screenshot_cf = OUTPUT_DIR / "screenshot_cf.png"
    screenshot_final = OUTPUT_DIR / "screenshot_final.png"
    screenshot_error = OUTPUT_DIR / "screenshot_error.png"

    # 代理设置对齐
    current_proxy = SYS_PROXY
    if current_proxy and not current_proxy.startswith("socks5://") and not current_proxy.startswith("http://"):
        current_proxy = "socks5://127.0.0.1:10808"

    opts = {
        "uc": True,
        "test": True,
        "locale": "zh",
        "headed": False,
        "timeout_multiplier": 0.4
    }
    if current_proxy:
        opts["proxy"] = current_proxy

    print(f"🚀 正在初始化 SeleniumBase UC 环境，代理节点: {current_proxy}")

    try:
        with SB(**opts) as sb:
            sb.driver.set_page_load_timeout(45)
            sb.driver.set_window_size(1920, 1080)

            print("正在访问登录页面...")
            try:
                sb.driver.get(LOGIN_URL)
            except Exception as nav_err:
                print(f"导航超时/异常: {nav_err}")
                try:
                    sb.driver.save_screenshot(str(screenshot_target))
                    tg_send_photo(str(screenshot_target), f"⚠️ 打开登录页超时\n错误信息: {str(nav_err)}")
                except:
                    tg_send(f"⚠️ 打开登录页超时，且截图失败: {str(nav_err)}")
                raise nav_err

            time.sleep(3)

            # 填写登录信息
            try:
                sb.type('//*[@id="email"]', EMAIL)
                sb.type('//*[@id="password"]', PASSWORD)
                sb.click('//*[@id="loginForm"]/button')
            except Exception as login_err:
                print(f"填写登录表单失败: {login_err}")

            time.sleep(5)

            # 进入服务页
            print(f"正在跳转至服务页: {SERVICES_URL}")
            sb.driver.get(SERVICES_URL)
            time.sleep(5)

            # 备份网页源码用于排查
            try:
                with open(OUTPUT_DIR / "page_source.html", "w", encoding="utf-8") as f:
                    f.write(sb.get_page_source())
            except:
                pass

            # 获取服务状态
            status_elements = sb.find_elements('.service-status')
            status_text = ""
            for i in range(len(status_elements)):
                txt = status_elements[i].text
                if "Renouvellement" in txt or "/" in txt:
                    status_text = txt
                    break
            
            if not status_text and len(status_elements) > 0:
                status_text = status_elements[0].text

            print(f"当前状态文本: {status_text}")

            date_str = status_text.split(":")[-1].strip()
            expire_date = datetime.strptime(date_str, "%d/%m/%Y").date()
            current_date = datetime.now().date()
            
            remaining_days = (expire_date - current_date).days
            print(f"服务器到期日期: {date_str}, 剩余天数: {remaining_days} 天")

            current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if remaining_days <= 2:
                print("剩余天数小于或等于2天，检查续期按钮状态...")
                
                renew_btn_selector = 'button.btn-renew.js-free-renew[data-uuid]'
                if sb.is_element_visible(renew_btn_selector):
                    print("发现可用的续期按钮，准备加红框并执行点击...")
                    old_date_str = date_str
                    
                    try:
                        # 标红按钮
                        sb.execute_script(f'document.querySelector("{renew_btn_selector}").style.border = "4px solid red";')
                        
                        # 截图 1：目标确认图
                        sb.driver.save_screenshot(str(screenshot_target))
                        tg_send_photo(str(screenshot_target), "🔍 【排查步骤 1/2】已锁定续期按钮（红框标出）")
                        
                        sb.click(renew_btn_selector)
                        print("点击动作已执行")
                    except Exception as e:
                        print(f"标红或点击异常: {e}")

                    time.sleep(3)
                    
                    # 截图 2：点击后的即时现场图
                    sb.driver.save_screenshot(str(screenshot_clicked))
                    tg_send_photo(str(screenshot_clicked), "🔍 【排查步骤 2/2】刚执行完点击动作的即时画面")

                    # ── 🔥 3 次重试与 Token 判定逻辑 ────────────────
                    print("🛸 激活 3 次循环机制处理人机验证...")
                    success_loaded = False
                    
                    for cf_attempt in range(3):
                        handle_cloudflare_turnstile(sb)
                        try:
                            print(f"[INFO] 正在检测验证状态 (尝试次数: {cf_attempt + 1})...")
                            time.sleep(5)
                            
                            # 严格依据 input 内是否有 Token 密文判定
                            cf_token_value = sb.driver.execute_script('''
                                (() => {
                                    const input = document.querySelector("input[name='cf-turnstile-response']");
                                    return input ? input.value : "";
                                })()
                            ''')
                            
                            if cf_token_value and len(cf_token_value.strip()) > 0:
                                print(f"[INFO] 验证通过！云盾 Token 令牌已顺利生成填充 (尝试次数: {cf_attempt + 1})")
                                success_loaded = True
                                break
                            else:
                                print(f"[WARN] 尝试 {cf_attempt + 1}: Token 仍为空，人机验证未通过")
                                
                        except Exception as e:
                            print(f"[WARN] 尝试 {cf_attempt + 1} 异常: {e}")
                            
                        if cf_attempt < 2:
                            time.sleep(5)

                    # 验证处理完毕后截图存档并发送 TG 带图通知
                    sb.driver.save_screenshot(str(screenshot_cf))
                    tg_send_photo(str(screenshot_cf), f"🛡️ 【CF验证结果】是否成功通过: {success_loaded}")

                    if success_loaded:
                        print("[INFO] CF 验证已通过，等待后端同步数据...")
                        time.sleep(5)
                        sb.driver.get(SERVICES_URL)
                        time.sleep(5)
                        
                        new_status_elements = sb.find_elements('.service-status')
                        new_status_text = ""
                        for i in range(len(new_status_elements)):
                            txt = new_status_elements[i].text
                            if "Renouvellement" in txt or "/" in txt:
                                new_status_text = txt
                                break
                        if not new_status_text and len(new_status_elements) > 0:
                            new_status_text = new_status_elements[0].text

                        new_date_str = new_status_text.split(":")[-1].strip()
                        new_expire_date = datetime.strptime(new_date_str, "%d/%m/%Y").date()
                        new_remaining_days = (new_expire_date - current_date).days

                        # 最终状态截图
                        sb.driver.save_screenshot(str(screenshot_final))

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
                            tg_send_photo(str(screenshot_final), msg)
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
                            tg_send_photo(str(screenshot_final), msg)
                    else:
                        print("[ERROR] 经过 3 次循环重试，CF 验证仍未通过（Token 为空）")
                        tg_send_photo(str(screenshot_cf), "❌ *续期失败*: 经过 3 次重试，CF 验证未能成功通过（Token 校验未通过）。")
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
                    sb.driver.save_screenshot(str(screenshot_target))
                    tg_send_photo(str(screenshot_target), msg)
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
                sb.driver.save_screenshot(str(screenshot_target))
                tg_send_photo(str(screenshot_target), msg)

        print("[INFO] 脚本运行结束")
        os._exit(0)

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
            sb.driver.save_screenshot(str(screenshot_error))
            tg_send_photo(str(screenshot_error), error_msg)
        except:
            tg_send(error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()
