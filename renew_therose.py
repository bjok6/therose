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
# 代理：Actions 里由 Hysteria2 客户端提供本地 SOCKS5
#   PROXY=socks5://127.0.0.1:1080
# 也支持 http://user:pass@host:port / host:port 等
# 拆分写法：PROXY_HOST + PROXY_PORT + 可选 PROXY_USER / PROXY_PASS / PROXY_SCHEME
PROXY = (os.environ.get("PROXY") or "").strip()
PROXY_HOST = (os.environ.get("PROXY_HOST") or "").strip()
PROXY_PORT = (os.environ.get("PROXY_PORT") or "").strip()
PROXY_USER = (os.environ.get("PROXY_USER") or "").strip()
PROXY_PASS = (os.environ.get("PROXY_PASS") or "").strip()
PROXY_SCHEME = (os.environ.get("PROXY_SCHEME") or "socks5").strip().lower()

BASE_URL = "https://client.therose.cloud/login"

EMAIL_SELECTORS = [
    "#login_form_email",
    'input[name="login_form[email]"]',
    'input[type="email"]',
    'input[name*="email" i]',
    'input[id*="email" i]',
    'input[autocomplete="username"]',
    'input[autocomplete="email"]',
]
PASSWORD_SELECTORS = [
    "#login_form_password",
    'input[name="login_form[password]"]',
    'input[type="password"]',
    'input[name*="password" i]',
    'input[id*="password" i]',
    'input[autocomplete="current-password"]',
]

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)


def build_proxy():
    """
    返回 SeleniumBase 可用的 proxy 字符串。
    格式: ip:port  或  user:pass@ip:port
    socks 保留 scheme: socks5://user:pass@ip:port
    """
    raw = PROXY
    if not raw and PROXY_HOST and PROXY_PORT:
        auth = ""
        if PROXY_USER:
            auth = f"{PROXY_USER}:{PROXY_PASS}@" if PROXY_PASS else f"{PROXY_USER}@"
        raw = f"{PROXY_SCHEME}://{auth}{PROXY_HOST}:{PROXY_PORT}"

    if not raw:
        return None

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
        if u.scheme.startswith("socks"):
            return f"{u.scheme}://{core}"
        return core

    return raw


def mask_proxy(proxy):
    if not proxy:
        return ""
    return re.sub(r":([^:@/]+)@", r":***@", proxy)


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


def page_looks_like_cf(sb):
    """是否仍停在 Cloudflare / 人机验证页。"""
    try:
        title = (sb.get_title() or "").lower()
        url = (sb.get_current_url() or "").lower()
        src = (sb.get_page_source() or "").lower()
        body = ""
        try:
            body = (sb.get_text("body") or "").lower()
        except Exception:
            pass
        markers = [
            "just a moment",
            "checking your browser",
            "attention required",
            "cf-browser-verification",
            "challenge-platform",
            "turnstile",
            "enable javascript and cookies",
            "sorry, you have been blocked",
            "error 1020",
            "error 1005",
            "access denied",
        ]
        blob = f"{title}\n{url}\n{body[:2000]}\n{src[:5000]}"
        return any(m in blob for m in markers)
    except Exception:
        return False


def dump_debug(sb, prefix="debug"):
    """失败时保存截图 + HTML + 基本信息。"""
    try:
        url = sb.get_current_url()
        title = sb.get_title() or ""
        print(f"📷 调试 URL: {url}")
        print(f"📷 调试 Title: {title}")
    except Exception as e:
        print(f"⚠️ 读取 URL/Title 失败: {e}")

    try:
        sb.save_screenshot(f"{prefix}.png")
        print(f"📷 已保存 {prefix}.png")
    except Exception as e:
        print(f"⚠️ 截图失败: {e}")

    try:
        html = sb.get_page_source() or ""
        with open(f"{prefix}.html", "w", encoding="utf-8", errors="ignore") as f:
            f.write(html)
        print(f"📄 已保存 {prefix}.html ({len(html)} bytes)")
    except Exception as e:
        print(f"⚠️ 保存 HTML 失败: {e}")

    try:
        body = sb.get_text("body") or ""
        snippet = " ".join(body.split())[:800]
        if snippet:
            print(f"📝 页面文本: {snippet}")
    except Exception:
        pass

    if page_looks_like_cf(sb):
        print("⚠️ 页面疑似仍在 Cloudflare/验证拦截状态")


def try_pass_cf(sb, rounds=4):
    """多次尝试通过 Cloudflare / Turnstile。"""
    for i in range(1, rounds + 1):
        print(f"🛡 验证处理 round {i}/{rounds} ...")
        try:
            # UC 专用：断开重连，利于过 CF
            if hasattr(sb, "uc_gui_click_captcha"):
                sb.uc_gui_click_captcha()
                print("   ✅ uc_gui_click_captcha 已执行")
        except Exception as e:
            print(f"   ⚠️ captcha 点击异常: {e}")
        time.sleep(4)
        try:
            if hasattr(sb, "uc_gui_handle_captcha"):
                sb.uc_gui_handle_captcha()
        except Exception:
            pass
        time.sleep(2)
        if not page_looks_like_cf(sb):
            # 再确认登录框是否出现
            if find_first(sb, EMAIL_SELECTORS, timeout=3):
                print("✅ 验证后已出现登录表单")
                return True
            # 可能不是 CF，只是慢
            print("ℹ️ 不像 CF 页，但登录框尚未出现")
        else:
            print("   仍像验证页，继续...")
    return bool(find_first(sb, EMAIL_SELECTORS, timeout=3))


def find_first(sb, selectors, timeout=5):
    """返回第一个存在的选择器，否则 None。"""
    for sel in selectors:
        try:
            if sb.is_element_present(sel, timeout=timeout if sel == selectors[0] else 1):
                return sel
        except Exception:
            try:
                sb.find_element(sel, timeout=1)
                return sel
            except Exception:
                continue
    return None


def wait_for_login_form(sb, total_seconds=60):
    """等待登录表单出现，期间继续处理验证。"""
    deadline = time.time() + total_seconds
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        sel = find_first(sb, EMAIL_SELECTORS, timeout=2)
        if sel:
            print(f"✅ 找到邮箱输入框: {sel}")
            return sel
        url = ""
        title = ""
        try:
            url = sb.get_current_url()
            title = sb.get_title() or ""
        except Exception:
            pass
        print(f"⏳ 等待登录表单... #{attempt} | {url} | {title}")
        if page_looks_like_cf(sb) or attempt % 3 == 0:
            try:
                sb.uc_gui_click_captcha()
            except Exception:
                pass
            time.sleep(3)
        else:
            time.sleep(2)
    return None


def open_login_page(sb):
    """用 UC 方式打开登录页，尽量过 CF。"""
    print("🌐 打开登录页面 (uc_open_with_reconnect)...")
    try:
        sb.uc_open_with_reconnect(BASE_URL, reconnect_time=5)
    except Exception as e:
        print(f"⚠️ uc_open_with_reconnect 失败，回退 open: {e}")
        try:
            sb.open(BASE_URL)
        except Exception as e2:
            print(f"❌ 打开页面失败: {e2}")
            dump_debug(sb, "open_failed")
            return False

    try:
        sb.wait_for_ready_state_complete(timeout=30)
    except Exception:
        pass
    time.sleep(2)

    try:
        print(f"📄 打开后 URL: {sb.get_current_url()}")
        print(f"📄 打开后 Title: {sb.get_title()}")
    except Exception:
        pass

    if page_looks_like_cf(sb) or not find_first(sb, EMAIL_SELECTORS, timeout=3):
        print("🛡 需要处理验证 / 等待表单...")
        try_pass_cf(sb, rounds=5)
        # 再 reconnect 一次
        if not find_first(sb, EMAIL_SELECTORS, timeout=2):
            print("🔄 再次 uc_open_with_reconnect ...")
            try:
                sb.uc_open_with_reconnect(BASE_URL, reconnect_time=6)
                time.sleep(3)
                try_pass_cf(sb, rounds=3)
            except Exception as e:
                print(f"⚠️ 二次打开失败: {e}")

    email_sel = wait_for_login_form(sb, total_seconds=45)
    if not email_sel:
        print("❌ 登录表单始终未出现（代理不可用 / CF 拦截 / 页面结构变化）")
        dump_debug(sb, "login_faild")
        return False
    return True


def login(sb, email, password):
    if not open_login_page(sb):
        return False, sb.get_current_url() if hasattr(sb, "get_current_url") else ""

    email_sel = find_first(sb, EMAIL_SELECTORS, timeout=5) or "#login_form_email"
    pass_sel = find_first(sb, PASSWORD_SELECTORS, timeout=5) or "#login_form_password"

    try:
        print(f"📧 填写邮箱 ({email_sel})...")
        sb.type(email_sel, email, timeout=15)
        print(f"🔑 填写密码 ({pass_sel})...")
        sb.type(pass_sel, password, timeout=15)
    except Exception as e:
        print(f"❌ 填写表单失败: {e}")
        dump_debug(sb, "login_faild")
        return False, sb.get_current_url()

    time.sleep(1)

    print("🛡 提交前处理 Turnstile...")
    try:
        sb.uc_gui_click_captcha()
        print("✅ Turnstile 已点击，等待 token...")
        time.sleep(5)
    except Exception as e:
        print(f"⚠️ uc_gui_click_captcha: {e}")
        try:
            time.sleep(2)
            sb.uc_gui_click_captcha()
            time.sleep(5)
        except Exception as e2:
            print(f"⚠️ 第二次 captcha 失败: {e2}")

    print("🔑 点击登录按钮...")
    clicked = False
    for sel in [
        'button:contains("Sign in")',
        'button[type="submit"]',
        'input[type="submit"]',
        'button:contains("Login")',
        'button:contains("Log in")',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                sb.uc_click(sel)
                clicked = True
                print(f"✅ 已点击: {sel}")
                break
        except Exception:
            try:
                sb.click(sel)
                clicked = True
                break
            except Exception:
                continue
    if not clicked:
        print("⚠️ 未找到登录按钮，尝试回车提交")
        try:
            sb.press_keys(pass_sel, "\n")
        except Exception:
            pass

    time.sleep(3)
    for i in range(40):
        try:
            current_url = sb.get_current_url()
            page_title = sb.get_title() or ""
        except Exception:
            current_url, page_title = "", ""
        print(f"📄 当前 URL: {current_url} | Title: {page_title}")
        low = current_url.lower()
        if any(x in low for x in ("panel", "client-area", "dashboard", "/home")):
            if "login" not in low:
                print("✅ 登录成功")
                return True, current_url
        if "panel" in low:
            print("✅ 登录成功，已跳转到 panel")
            return True, current_url
        if i in (8, 16, 24):
            try:
                sb.uc_gui_click_captcha()
                time.sleep(2)
                try:
                    sb.uc_click('button:contains("Sign in")')
                except Exception:
                    pass
            except Exception:
                pass
        time.sleep(1)

    print(f"❌ 登录失败，当前 URL: {sb.get_current_url()}")
    dump_debug(sb, "login_faild")
    return False, sb.get_current_url()


def click_extend_button(sb):
    selectors = [
        'span:contains("Extend")',
        'button:contains("Extend")',
        'a:contains("Extend")',
    ]
    for sel in selectors:
        try:
            if sb.find_element(sel, timeout=2):
                print(f"✅ 找到按钮: {sel}")
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
                print(f"✅ 成功提示: {text}")
                return True, text
        except Exception:
            continue
    try:
        page_source = sb.get_page_source()
        if "successfully purchased" in page_source.lower():
            return True, "服务器已成功续期"
    except Exception:
        pass
    return False, "未检测到续期成功提示"


def check_proxy_with_requests(proxy, req_proxies):
    """用 requests 先测代理，避免浏览器白等。"""
    if not req_proxies:
        return True
    print("🔍 用 requests 测试代理连通性...")
    try:
        r = requests.get("https://api.ipify.org?format=text", proxies=req_proxies, timeout=20)
        if r.status_code == 200 and r.text.strip():
            print(f"✅ 代理可用，出口 IP: {r.text.strip()}")
            return True
        print(f"⚠️ 代理测试异常 HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"❌ 代理测试失败: {e}")
        print("   请确认 PROXY 格式/账号密码/是否允许 HTTPS CONNECT")
        print("   示例: http://user:pass@host:port  或  socks5://user:pass@host:port")
        print(f"   当前: {mask_proxy(proxy or '')}")
        # 端口 443 的“裸 IP:443”经常不是标准 HTTP 代理
        if proxy and proxy.rstrip("/").endswith(":443") and "://" not in (PROXY or proxy):
            print("   提示: 你配置的是 host:443。若这不是 HTTP 代理端口，浏览器会打不开页面。")
    return False


def main():
    proxy = build_proxy()
    if proxy:
        print(f"🌐 使用代理: {mask_proxy(proxy)}")
        if re.fullmatch(r"[\d.]+:443", proxy):
            print("⚠️ 注意: 代理为 IP:443。若登录页打不开，多半不是可用的 HTTP/SOCKS 代理。")
    else:
        print("ℹ️ 未配置 PROXY，直连（GitHub Actions IP 容易被 Cloudflare 拦）")

    req_proxies = None
    if proxy:
        # requests + PySocks：socks5h 让远端做 DNS，避免 DNS 泄漏/解析失败
        if proxy.startswith("socks5://"):
            p = "socks5h://" + proxy[len("socks5://") :]
            req_proxies = {"http": p, "https": p}
        elif proxy.startswith("socks5h://") or proxy.startswith("socks4"):
            req_proxies = {"http": proxy, "https": proxy}
        elif "://" in proxy:
            req_proxies = {"http": proxy, "https": proxy}
        else:
            req_proxies = {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}",
            }

    proxy_ok = check_proxy_with_requests(proxy, req_proxies)
    if proxy and not proxy_ok:
        msg = "❌ 代理不可用，中止（请检查 PROXY Secret）"
        print(msg)
        # Telegram 直连再试一次（代理挂了时）
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=None)
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
        sys.exit(1)

    print("🚀 启动浏览器")
    sb_kwargs = {
        "uc": True,
        "headless": False,
        "locale": "en",
        "page_load_strategy": "normal",
    }
    if proxy:
        sb_kwargs["proxy"] = proxy

    with SB(**sb_kwargs) as sb:
        try:
            success, url = login(sb, EMAIL, PASSWORD)
        except Exception as e:
            print(f"❌ 登录过程异常: {e}")
            dump_debug(sb, "login_faild")
            send_tg(
                TG_BOT_TOKEN,
                TG_CHAT_ID,
                f"❌ 登录异常: {e}",
                proxies=req_proxies,
            )
            sys.exit(1)

        if not success:
            msg = "❌ 登录失败（表单未出现 / Turnstile / 代理 / 账号）"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
            sys.exit(1)

        print("📄 开始续期流程...")
        ok, info = click_extend_button(sb)
        if not ok:
            msg = f"❌ 点击 Extend 按钮失败: {info.get('error')}"
            print(msg)
            dump_debug(sb, "extend_failed")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
            sys.exit(1)

        time.sleep(1)
        try:
            button = sb.find_element('button:contains("Order now")', timeout=8)
            if button:
                print("🛒 点击 Order now 按钮...")
                sb.uc_click('button:contains("Order now")')
                print("✅ 已点击 Order now 按钮")
            else:
                msg = "❌ 未找到 Order now 按钮"
                print(msg)
                dump_debug(sb, "order_failed")
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
                sys.exit(1)
        except Exception as e:
            msg = f"❌ 点击 Order now 失败: {e}"
            print(msg)
            dump_debug(sb, "order_failed")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)
            sys.exit(1)

        print("🔍 检查续期结果...")
        renewal_success, renewal_msg = check_renewal_success(sb)
        if renewal_success:
            msg = f"✅ 续期成功！{renewal_msg}"
            print(msg)
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"❌ 续期可能失败: {renewal_msg}"
            print(msg)
            dump_debug(sb, "renewal_failed")

        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, proxies=req_proxies)

    print("🏁 脚本执行完毕")


if __name__ == "__main__":
    main()
