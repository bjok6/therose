#!/usr/bin/env python3

import os
import re
import sys
import time
import requests
from seleniumbase import SB
from urllib.parse import urlparse

# 环境变量
EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
# 代理（任选一种）
# 1) PROXY=http://user:pass@host:port  或 socks5://user:pass@host:port  或 host:port
# 2) PROXY_HOST + PROXY_PORT + 可选 PROXY_USER / PROXY_PASS + 可选 PROXY_SCHEME
PROXY = (os.environ.get("PROXY") or "").strip()
PROXY_HOST = (os.environ.get("PROXY_HOST") or "").strip()
PROXY_PORT = (os.environ.get("PROXY_PORT") or "").strip()
PROXY_USER = (os.environ.get("PROXY_USER") or "").strip()
PROXY_PASS = (os.environ.get("PROXY_PASS") or "").strip()
PROXY_SCHEME = (os.environ.get("PROXY_SCHEME") or "http").strip().lower()

BASE_URL = "https://client.therose.cloud/login"

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)


def build_proxy() -> str | None:
    """
    返回 SeleniumBase 可用的 proxy 字符串。
    格式: ip:port  或  user:pass@ip:port
    带 scheme 时保留，例如 socks5://user:pass@ip:port
    """
    raw = PROXY
    if not raw and PROXY_HOST and PROXY_PORT:
        auth = ""
        if PROXY_USER:
            # 密码中的特殊字符尽量原样放入，由调用方保证 URL 安全
            auth = f"{PROXY_USER}:{PROXY_PASS}@" if PROXY_PASS else f"{PROXY_USER}@"
        raw = f"{PROXY_SCHEME}://{auth}{PROXY_HOST}:{PROXY_PORT}"

    if not raw:
        return None

    # SeleniumBase 常见写法：user:pass@host:port 或 host:port
    # 若带 http(s)/socks  scheme，尽量转成 SB 友好格式
    if "://" in raw:
        u = urlparse(raw)
        host = u.hostname or ""
        port = u.port or ""
        if not host or not port:
            print(f"⚠️ 代理地址解析失败: {mask_proxy(raw)}")
            return None
        user = u.username or ""
        password = u.password or ""
        if user:
            auth = f"{user}:{password}@" if password is not None else f"{user}@"
            core = f"{auth}{host}:{port}"
        else:
            core = f"{host}:{port}"
        # socks 需要保留 scheme，http 代理用 core 即可
        if u.scheme.startswith("socks"):
            return f"{u.scheme}://{core}"
        return core

    return raw


def mask_proxy(proxy: str) -> str:
    """日志里隐藏代理密码。"""
    if not proxy:
        return ""
    return re.sub(r":([^:@/]+)@", r":***@", proxy)


def click_extend_button(sb):
    selectors = [
        'span:contains("Extend")',
        'button:contains(title="Extend")',
    ]
    for sel in selectors:
        try:
            if sb.find_element(sel, timeout=2):
                print(f"✅ 找到按钮，选择器: {sel}")
                sb.uc_click(sel, timeout=5)
                print("✅ 点击成功")
                return True, {}
        except Exception:
            continue
    try:
        btn = sb.find_element('button:contains("Extend")', timeout=2)
        sb.driver.execute_script("arguments[0].click();", btn)
        print("✅ 通过 JavaScript 点击成功")
        return True, {}
    except Exception as e:
        return False, {"error": str(e)}


def check_renewal_success(sb):
    """检查是否出现续期成功的提示"""
    success_selectors = [
        ".alert-success",
        ".alert.alert-success",
        'div[role="alert"].alert-success',
        "div.alert-success",
        'span:contains("successfully purchased")',
        'div:contains("successfully purchased")',
    ]

    print("⏳ 等待5秒检查续期结果...")
    time.sleep(5)

    for selector in success_selectors:
        try:
            element = sb.find_element(selector, timeout=2)
            if element:
                text = element.text
                print(f"✅ 发现成功提示！选择器: {selector}")
                print(f"📝 提示内容: {text}")
                return True, text
        except Exception:
            continue

    try:
        page_source = sb.get_page_source()
        if "successfully purchased" in page_source.lower():
            print("✅ 页面源码中发现 'successfully purchased' 关键词")
            return True, "服务器已成功续期"
    except Exception:
        pass

    return False, "未检测到续期成功提示"


def send_tg(token, chat_id, message, proxies=None):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=15,
            proxies=proxies,
        )
        if resp.status_code == 200:
            print("📨 Telegram 通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")


def dump_login_debug(sb):
    """登录失败时尽量多打诊断信息。"""
    try:
        sb.save_screenshot("login_faild.png")
        print("📷 已保存 login_faild.png")
    except Exception as e:
        print(f"⚠️ 截图失败: {e}")
    try:
        # 常见错误提示
        for sel in [
            ".alert-danger",
            ".alert.alert-danger",
            ".invalid-feedback",
            ".form-error",
            '[class*="error"]',
        ]:
            try:
                els = sb.find_elements(sel)
                for el in els:
                    t = (el.text or "").strip()
                    if t:
                        print(f"⚠️ 页面提示 [{sel}]: {t[:300]}")
            except Exception:
                pass
        body = sb.get_text("body") or ""
        snippet = " ".join(body.split())[:500]
        if snippet:
            print(f"📝 页面文本片段: {snippet}")
    except Exception as e:
        print(f"⚠️ 读取页面信息失败: {e}")


def login(sb, email, password):
    print("🌐 打开登录页面...")
    print("⏳ 等待页面加载...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete()
    sb.sleep(2)

    print("📧 填写邮箱...")
    sb.type("#login_form_email", email, timeout=15)
    print("🔑 填写密码...")
    sb.type("#login_form_password", password, timeout=15)
    time.sleep(1)

    print("🛡 处理 Turnstile...")
    try:
        sb.uc_gui_click_captcha()
        print("✅ Turnstile 验证已点击，等待 token...")
        time.sleep(5)
    except Exception as e:
        print(f"⚠️ uc_gui_click_captcha 执行异常: {e}")
        # 再试一次
        try:
            time.sleep(2)
            sb.uc_gui_click_captcha()
            print("✅ 第二次 Turnstile 点击完成")
            time.sleep(5)
        except Exception as e2:
            print(f"⚠️ 第二次 captcha 仍失败: {e2}")

    print("🔑 点击登录按钮...")
    try:
        sb.uc_click('button:contains("Sign in")')
    except Exception:
        try:
            sb.click('button[type="submit"]')
        except Exception as e:
            print(f"⚠️ 点击登录按钮失败: {e}")

    sb.sleep(3)
    for i in range(40):
        current_url = sb.get_current_url()
        page_title = sb.get_title() or ""
        print(f"📄 当前 URL: {current_url} | Title: {page_title}")
        if "panel" in current_url or "/client-area" in current_url or "dashboard" in current_url.lower():
            print("✅ 登录成功，已跳转到 Dashboard")
            return True, current_url
        # 若仍在 login 且出现 cf 挑战页，再点一次 captcha
        if i in (8, 16, 24):
            try:
                sb.uc_gui_click_captcha()
                print("🔄 中途再次尝试 Turnstile...")
                time.sleep(3)
                try:
                    sb.uc_click('button:contains("Sign in")')
                except Exception:
                    pass
            except Exception:
                pass
        time.sleep(1)

    print(f"❌ 登录失败，当前 URL: {sb.get_current_url()}")
    dump_login_debug(sb)
    return False, sb.get_current_url()


def main():
    proxy = build_proxy()
    if proxy:
        print(f"🌐 使用代理: {mask_proxy(proxy)}")
    else:
        print("ℹ️ 未配置 PROXY，直连（GitHub Actions IP 容易被 Cloudflare 拦）")

    # requests 用的代理（Telegram 可选走同一代理）
    req_proxies = None
    if proxy:
        # 转成 requests 格式
        if "://" in proxy:
            req_proxies = {"http": proxy, "https": proxy}
        else:
            req_proxies = {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}",
            }

    print("🚀 启动浏览器")
    sb_kwargs = {
        "uc": True,
        "headless": False,
        "locale": "en",
    }
    if proxy:
        sb_kwargs["proxy"] = proxy

    with SB(**sb_kwargs) as sb:
        # 可选：打印出口 IP，确认代理生效
        try:
            sb.open("https://api.ipify.org?format=text")
            sb.sleep(2)
            ip_text = (sb.get_text("body") or "").strip()
            if ip_text and len(ip_text) < 64:
                print(f"🌍 当前出口 IP: {ip_text}")
        except Exception as e:
            print(f"⚠️ 获取出口 IP 失败: {e}")

        success, url = login(sb, EMAIL, PASSWORD)

        if not success:
            msg = "❌ 登录失败（可能是 Turnstile/代理/账号问题）"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
            return

        print("📄 开始续期流程...")

        ok, info = click_extend_button(sb)
        if not ok:
            msg = f"❌ 点击 Extend 按钮失败: {info.get('error')}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
            return

        time.sleep(1)

        try:
            button = sb.find_element('button:contains("Order now")', timeout=5)
            if button:
                print("🛒 点击 Order now 按钮...")
                sb.uc_click('button:contains("Order now")')
                print("✅ 已点击 Order now 按钮")
            else:
                msg = "❌ 未找到 Order now 按钮"
                print(msg)
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
                return
        except Exception as e:
            msg = f"❌ 点击 Order now 失败: {e}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
            return

        print("🔍 检查续期结果...")
        renewal_success, renewal_msg = check_renewal_success(sb)

        if renewal_success:
            msg = f"✅ 续期成功！{renewal_msg}"
            print(msg)
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"❌ 续期可能失败: {renewal_msg}"
            print(msg)
            sb.save_screenshot("renewal_failed.png")

        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)

    print("🏁 脚本执行完毕")


if __name__ == "__main__":
    main()
