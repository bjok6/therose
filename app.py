#!/usr/bin/env python3
import os
import re
import sys
import time
import requests
from seleniumbase import SB

# ====================== 环境变量 ======================
EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
COOKIE_VALUE = os.environ.get("COOKIE_VALUE") or ""   # 可选
BASE_URL = "https://client.therose.cloud/login"

# 检查必要变量
if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)

# ====================== 工具函数 ======================
def send_tg(token, chat_id, message):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        if resp.status_code == 200:
            print("📨 Telegram 通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")


def click_extend_button(sb):
    """点击 Extend 按钮"""
    selectors = [
        'button:contains("Extend")',
        'span:contains("Extend")',
        'a:contains("Extend")',
        '[title="Extend"]',
        'button.btn:contains("Extend")',
    ]
    for sel in selectors:
        try:
            if sb.is_element_visible(sel, timeout=3):
                print(f"✅ 找到 Extend 按钮，选择器: {sel}")
                sb.uc_click(sel, timeout=5)
                print("✅ 已点击 Extend")
                return True
        except:
            continue

    # 最后用 JS 点击
    try:
        sb.execute_script("""
            let btn = document.querySelector('button, a, span');
            if (btn && btn.textContent.includes('Extend')) {
                btn.click();
                return true;
            }
            return false;
        """)
        print("✅ 通过 JS 点击 Extend 成功")
        return True
    except Exception as e:
        print(f"❌ 点击 Extend 失败: {e}")
        return False


def check_renewal_success(sb):
    """检查续期是否成功"""
    print("⏳ 等待 6 秒检查续期结果...")
    time.sleep(6)

    success_keywords = [
        "successfully purchased",
        "successfully renewed",
        "extended successfully",
        "renewal successful",
        "success",
    ]

    # 先查提示框
    success_selectors = [
        '.alert-success',
        '.alert.alert-success',
        'div[role="alert"]',
        '.toast-success',
        '.notification-success',
    ]

    for selector in success_selectors:
        try:
            element = sb.find_element(selector, timeout=2)
            if element and element.is_displayed():
                text = element.text.strip()
                print(f"✅ 发现成功提示: {text}")
                return True, text
        except:
            continue

    # 检查页面源码
    try:
        page_source = sb.get_page_source().lower()
        for kw in success_keywords:
            if kw in page_source:
                print(f"✅ 页面源码中发现关键词: {kw}")
                return True, "服务器已成功续期"
    except:
        pass

    return False, "未检测到续期成功提示"


# ====================== 登录函数（加强版） ======================
def login(sb, email, password):
    print("🌐 打开登录页面...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete(timeout=20)
    sb.sleep(2)

    print("📧 填写邮箱...")
    sb.type('#login_form_email', email, timeout=15)
    sb.sleep(0.8)

    print("🔑 填写密码...")
    sb.type('#login_form_password', password, timeout=10)
    sb.sleep(1)

    print("🛡 处理 Turnstile...")
    # 多次尝试点击验证码，提高成功率
    for i in range(4):
        try:
            sb.uc_gui_click_captcha()
            print(f"✅ Turnstile 第 {i+1} 次处理成功")
            sb.sleep(2.5)
            break
        except Exception as e:
            print(f"⚠️ Turnstile 第 {i+1} 次失败: {e}")
            sb.sleep(1.5)

    sb.sleep(2)

    print("🔑 点击登录按钮...")
    login_clicked = False
    login_selectors = [
        'button:contains("Sign in")',
        'button[type="submit"]',
        'button.btn-primary',
        'input[type="submit"]',
    ]
    for sel in login_selectors:
        try:
            if sb.is_element_visible(sel, timeout=3):
                sb.uc_click(sel)
                print(f"✅ 使用选择器点击登录: {sel}")
                login_clicked = True
                break
        except:
            continue

    if not login_clicked:
        # 最后用 JS 强制点击
        try:
            sb.execute_script("""
                const btn = document.querySelector('button[type="submit"]') || 
                            document.querySelector('button');
                if (btn) btn.click();
            """)
            print("✅ 通过 JS 点击登录按钮")
        except Exception as e:
            print(f"❌ 点击登录按钮失败: {e}")

    print("⏳ 等待登录跳转（最多 45 秒）...")
    for i in range(45):
        current_url = sb.get_current_url()
        page_title = sb.get_title() or ""
        print(f"📄 [{i+1:02d}s] URL: {current_url}")

        # 登录成功判断
        if any(x in current_url.lower() for x in ["panel", "dashboard", "server", "home", "client"]):
            if "login" not in current_url.lower():
                print("✅ 登录成功，已跳转！")
                sb.save_screenshot("login_success.png")
                return True, current_url

        # 检查是否有错误提示
        try:
            error_elem = sb.find_elements('.alert-danger, .error, .invalid-feedback, .text-danger')
            for err in error_elem:
                if err.is_displayed() and err.text.strip():
                    print(f"❌ 登录错误提示: {err.text.strip()}")
                    sb.save_screenshot("login_error.png")
                    return False, current_url
        except:
            pass

        sb.sleep(1)

    print(f"❌ 登录失败，最终 URL: {sb.get_current_url()}")
    sb.save_screenshot("login_failed.png")
    return False, sb.get_current_url()


# ====================== 主流程 ======================
def main():
    print("🚀 启动浏览器")
    with SB(uc=True, headless=False, xvfb=True) as sb:        # 登录
        success, url = login(sb, EMAIL, PASSWORD)

        if not success:
            msg = "❌ 登录失败，请检查账号密码或验证码"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        print("📄 开始续期流程...")
        sb.sleep(2)

        # 点击 Extend 按钮
        if not click_extend_button(sb):
            msg = "❌ 未找到或无法点击 Extend 按钮"
            print(msg)
            sb.save_screenshot("no_extend_button.png")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        sb.sleep(2)

        # 点击 Order now 按钮
        try:
            print("🛒 寻找 Order now 按钮...")
            order_selectors = [
                'button:contains("Order now")',
                'button:contains("Order Now")',
                'button:contains("Confirm")',
                'button.btn-primary:contains("Order")',
            ]
            clicked = False
            for sel in order_selectors:
                try:
                    if sb.is_element_visible(sel, timeout=4):
                        sb.uc_click(sel)
                        print(f"✅ 已点击 Order now ({sel})")
                        clicked = True
                        break
                except:
                    continue

            if not clicked:
                # JS 备用
                sb.execute_script("""
                    let btns = document.querySelectorAll('button');
                    for (let btn of btns) {
                        if (btn.textContent.includes('Order') || btn.textContent.includes('Confirm')) {
                            btn.click();
                            break;
                        }
                    }
                """)
                print("✅ 通过 JS 点击 Order now")
        except Exception as e:
            msg = f"❌ 点击 Order now 失败: {e}"
            print(msg)
            sb.save_screenshot("order_now_failed.png")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 检查续期结果
        print("🔍 检查续期结果...")
        renewal_success, renewal_msg = check_renewal_success(sb)

        if renewal_success:
            msg = f"✅ 续期成功！\n{renewal_msg}"
            print(msg)
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"❌ 续期可能失败: {renewal_msg}"
            print(msg)
            sb.save_screenshot("renewal_failed.png")

        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)

    print("🏁 脚本执行完毕")


if __name__ == "__main__":
    main()
