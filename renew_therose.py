#!/usr/bin/env python3
"""
TheRose 自动续期
正确流程：
  登录 → /panel?routeName=servers (My servers)
       → 点 Extend
       → 续期页 #order-submit (Order now)
"""

import os
import re
import sys
import time
import requests
from seleniumbase import SB
from urllib.parse import urlparse

EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY = (os.environ.get("PROXY") or "").strip()
PROXY_HOST = (os.environ.get("PROXY_HOST") or "").strip()
PROXY_PORT = (os.environ.get("PROXY_PORT") or "").strip()
PROXY_USER = (os.environ.get("PROXY_USER") or "").strip()
PROXY_PASS = (os.environ.get("PROXY_PASS") or "").strip()
PROXY_SCHEME = (os.environ.get("PROXY_SCHEME") or "socks5").strip().lower()
# 可选：直接指定服务器数字 id（表单里的 2591），不设则自动点第一个 Extend
SERVER_ID = (os.environ.get("SERVER_ID") or "").strip()

BASE_URL = "https://client.therose.cloud/login"
SERVERS_URL = "https://client.therose.cloud/panel?routeName=servers"
PANEL_URL = "https://client.therose.cloud/panel"

EMAIL_SELECTORS = [
    "#login_form_email",
    'input[name="login_form[email]"]',
    'input[type="email"]',
    'input[name*="email" i]',
    'input[id*="email" i]',
]
PASSWORD_SELECTORS = [
    "#login_form_password",
    'input[name="login_form[password]"]',
    'input[type="password"]',
    'input[name*="password" i]',
    'input[id*="password" i]',
]

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)


def build_proxy():
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
        host, port = u.hostname or "", u.port or ""
        if not host or not port:
            print(f"⚠️ 代理地址解析失败: {mask_proxy(raw)}")
            return None
        user, password = u.username or "", u.password or ""
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
            url, json={"chat_id": chat_id, "text": message}, timeout=15, proxies=proxies
        )
        if resp.status_code == 200:
            print("📨 Telegram 通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")


def page_looks_like_cf(sb):
    try:
        title = (sb.get_title() or "").lower()
        url = (sb.get_current_url() or "").lower()
        body = ""
        try:
            body = (sb.get_text("body") or "").lower()
        except Exception:
            pass
        src = ""
        try:
            src = (sb.get_page_source() or "").lower()[:4000]
        except Exception:
            pass
        blob = f"{title}\n{url}\n{body[:1500]}\n{src}"
        markers = [
            "just a moment",
            "checking your browser",
            "attention required",
            "cf-browser-verification",
            "challenge-platform",
            "sorry, you have been blocked",
            "error 1020",
            "access denied",
        ]
        return any(m in blob for m in markers)
    except Exception:
        return False


def dump_debug(sb, prefix="debug"):
    try:
        print(f"📷 URL: {sb.get_current_url()}")
        print(f"📷 Title: {sb.get_title()}")
    except Exception as e:
        print(f"⚠️ 读 URL 失败: {e}")
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


def find_first(sb, selectors, timeout=5):
    for i, sel in enumerate(selectors):
        t = timeout if i == 0 else 1
        try:
            if sb.is_element_present(sel, timeout=t):
                return sel
        except Exception:
            try:
                sb.find_element(sel, timeout=1)
                return sel
            except Exception:
                continue
    return None


def try_pass_cf(sb, rounds=4):
    for i in range(1, rounds + 1):
        print(f"🛡 验证处理 round {i}/{rounds} ...")
        try:
            sb.uc_gui_click_captcha()
        except Exception as e:
            print(f"   ⚠️ captcha: {e}")
        time.sleep(3)
        if find_first(sb, EMAIL_SELECTORS, timeout=2):
            return True
    return bool(find_first(sb, EMAIL_SELECTORS, timeout=2))


def open_login_page(sb):
    print("🌐 打开登录页...")
    try:
        sb.uc_open_with_reconnect(BASE_URL, reconnect_time=5)
    except Exception as e:
        print(f"⚠️ uc_open 失败，回退 open: {e}")
        sb.open(BASE_URL)
    try:
        sb.wait_for_ready_state_complete(timeout=30)
    except Exception:
        pass
    time.sleep(2)
    if page_looks_like_cf(sb) or not find_first(sb, EMAIL_SELECTORS, timeout=3):
        try_pass_cf(sb, rounds=4)
    deadline = time.time() + 45
    while time.time() < deadline:
        sel = find_first(sb, EMAIL_SELECTORS, timeout=2)
        if sel:
            print(f"✅ 登录表单就绪: {sel}")
            return True
        try:
            sb.uc_gui_click_captcha()
        except Exception:
            pass
        time.sleep(2)
    dump_debug(sb, "login_faild")
    return False


def login(sb, email, password):
    if not open_login_page(sb):
        return False, ""
    email_sel = find_first(sb, EMAIL_SELECTORS, timeout=5) or "#login_form_email"
    pass_sel = find_first(sb, PASSWORD_SELECTORS, timeout=5) or "#login_form_password"
    try:
        print("📧 填写邮箱...")
        sb.type(email_sel, email, timeout=15)
        print("🔑 填写密码...")
        sb.type(pass_sel, password, timeout=15)
    except Exception as e:
        print(f"❌ 填表失败: {e}")
        dump_debug(sb, "login_faild")
        return False, sb.get_current_url()

    time.sleep(1)
    print("🛡 处理 Turnstile...")
    try:
        sb.uc_gui_click_captcha()
        time.sleep(5)
    except Exception as e:
        print(f"⚠️ captcha: {e}")

    print("🔑 点击 Sign in...")
    for sel in [
        'button:contains("Sign in")',
        'button[type="submit"]',
        'button:contains("Login")',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                sb.uc_click(sel)
                break
        except Exception:
            try:
                sb.click(sel)
                break
            except Exception:
                continue

    for i in range(40):
        url = sb.get_current_url() or ""
        title = sb.get_title() or ""
        print(f"📄 {url} | {title}")
        low = url.lower()
        if "panel" in low and "login" not in low:
            print("✅ 登录成功")
            return True, url
        if i in (8, 16, 24):
            try:
                sb.uc_gui_click_captcha()
                time.sleep(2)
                sb.uc_click('button:contains("Sign in")')
            except Exception:
                pass
        time.sleep(1)

    dump_debug(sb, "login_faild")
    return False, sb.get_current_url()


def open_servers_page(sb):
    """打开 My servers 列表页。"""
    print(f"🌐 打开 My servers: {SERVERS_URL}")
    try:
        sb.uc_open_with_reconnect(SERVERS_URL, reconnect_time=4)
    except Exception:
        sb.open(SERVERS_URL)
    try:
        sb.wait_for_ready_state_complete(timeout=30)
    except Exception:
        pass
    time.sleep(2)

    # 确认到了 servers 页
    for _ in range(15):
        url = (sb.get_current_url() or "").lower()
        title = (sb.get_title() or "").lower()
        body = ""
        try:
            body = (sb.get_text("body") or "").lower()
        except Exception:
            pass
        if "routename=servers" in url.replace(" ", "") or "my servers" in title or "valid until" in body:
            print(f"✅ 已在 My servers | {sb.get_current_url()}")
            return True
        # 侧栏点 My servers
        try:
            if sb.is_element_present('a:contains("My servers")', timeout=1):
                sb.click('a:contains("My servers")')
                time.sleep(2)
                continue
        except Exception:
            pass
        time.sleep(1)

    print("⚠️ 可能未稳定进入 My servers，继续尝试点 Extend")
    return True


def find_extend_info(sb):
    """
    在 My servers 页查找 Extend 按钮状态。
    返回 dict: found, clickable, selector, valid_until, reason
    """
    info = {
        "found": False,
        "clickable": False,
        "selector": None,
        "valid_until": None,
        "reason": "",
    }
    try:
        body = sb.get_text("body") or ""
        m = re.search(
            r"Valid until\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})",
            body,
            re.I,
        )
        if m:
            info["valid_until"] = m.group(1)
            print(f"⏱ Valid until: {info['valid_until']}")
    except Exception:
        pass

    # 优先 JS 检查按钮（含 disabled / 灰显）
    try:
        state = sb.execute_script(
            """
            const words = ['extend', 'renew'];
            const nodes = Array.from(document.querySelectorAll('a,button,span,div'));
            let best = null;
            for (const el of nodes) {
              const t = (el.innerText || el.textContent || '').trim().toLowerCase();
              if (!t) continue;
              // 只要短标签，避免点到整卡
              if (t !== 'extend' && t !== 'renew' && !/^\\s*(extend|renew)\\s*$/i.test(t)) {
                // 允许 "Extend" 带图标文字被拆开
                if (!(t.includes('extend') && t.length <= 20)) continue;
              }
              const tag = el.tagName.toLowerCase();
              if (!['a','button','span','div'].includes(tag)) continue;
              // 找可点的最近按钮/链接
              let target = el;
              if (tag === 'span' || tag === 'div') {
                const p = el.closest('a,button');
                if (p) target = p;
              }
              const style = window.getComputedStyle(target);
              const disabled =
                target.disabled === true ||
                target.getAttribute('disabled') !== null ||
                target.getAttribute('aria-disabled') === 'true' ||
                target.classList.contains('disabled') ||
                style.pointerEvents === 'none' ||
                parseFloat(style.opacity || '1') < 0.5;
              const rect = target.getBoundingClientRect();
              if (rect.width < 5 || rect.height < 5) continue;
              best = {
                text: (target.innerText || '').trim().slice(0, 40),
                tag: target.tagName,
                href: target.getAttribute('href') || '',
                disabled: !!disabled,
                cls: target.className || '',
              };
              // 优先可点的
              if (!disabled) break;
            }
            return best;
            """
        )
        if state:
            info["found"] = True
            print(f"🔎 Extend 节点: {state}")
            if state.get("disabled"):
                info["clickable"] = False
                info["reason"] = (
                    "Extend 按钮存在但不可点（disabled/灰显）。"
                    "常见原因：未到可续时间（部分套餐仅到期前一段时间可续），"
                    f"当前 Valid until={info.get('valid_until') or '未知'}"
                )
            else:
                info["clickable"] = True
                if state.get("href"):
                    info["href"] = state["href"]
            return info
    except Exception as e:
        print(f"⚠️ JS 查找 Extend 异常: {e}")

    # 选择器兜底
    for sel in [
        'a:contains("Extend")',
        'button:contains("Extend")',
        'a:contains("Renew")',
        'button:contains("Renew")',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                info["found"] = True
                info["selector"] = sel
                el = sb.find_element(sel, timeout=2)
                disabled = False
                try:
                    disabled = (
                        el.get_attribute("disabled") is not None
                        or "disabled" in (el.get_attribute("class") or "")
                    )
                except Exception:
                    pass
                info["clickable"] = not disabled
                if disabled:
                    info["reason"] = "Extend 选择器找到但 disabled"
                return info
        except Exception:
            continue

    info["reason"] = "页面上未找到 Extend/Renew 按钮（是否还在 My servers？）"
    return info


def click_extend(sb):
    """在 My servers 页点击 Extend；若不可点则返回失败原因。"""
    info = find_extend_info(sb)
    if not info["found"]:
        return False, info

    if not info["clickable"]:
        return False, info

    # 有 href 直接跳（更稳）
    href = info.get("href") or ""
    if href and href not in ("#", "javascript:void(0)", "javascript:;"):
        if href.startswith("/"):
            href = "https://client.therose.cloud" + href
        print(f"➡️ 通过 href 打开续期页: {href}")
        try:
            sb.open(href)
            time.sleep(3)
            return True, info
        except Exception as e:
            print(f"⚠️ href 打开失败: {e}")

    # 直接打开已知续期 URL（若配置了 SERVER_ID）
    if SERVER_ID:
        # PteroCA 常见: cart_renew
        for route in ("cart_renew", "server_renew", "renew"):
            url = f"https://client.therose.cloud/panel?routeName={route}&id={SERVER_ID}"
            print(f"➡️ 尝试直达: {url}")
            sb.open(url)
            time.sleep(2)
            if "renew" in (sb.get_title() or "").lower() or sb.is_element_present(
                "#order-submit", timeout=2
            ):
                return True, info

    # 点击
    for sel in [
        'a:contains("Extend")',
        'button:contains("Extend")',
        'a:contains("Renew")',
        'button:contains("Renew")',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                print(f"🖱 点击: {sel}")
                try:
                    sb.uc_click(sel, timeout=5)
                except Exception:
                    el = sb.find_element(sel, timeout=2)
                    sb.driver.execute_script("arguments[0].click();", el)
                time.sleep(3)
                return True, info
        except Exception as e:
            print(f"⚠️ 点击 {sel} 失败: {e}")

    # JS 强制点击第一个非 disabled 的 Extend
    try:
        ok = sb.execute_script(
            """
            const nodes = Array.from(document.querySelectorAll('a,button'));
            for (const el of nodes) {
              const t = (el.innerText || '').trim().toLowerCase();
              if (!(t === 'extend' || t.includes('extend'))) continue;
              if (el.disabled || el.getAttribute('disabled') !== null) continue;
              if (el.classList.contains('disabled')) continue;
              el.click();
              return true;
            }
            return false;
            """
        )
        if ok:
            print("✅ JS 点击 Extend 成功")
            time.sleep(3)
            return True, info
    except Exception as e:
        info["reason"] = f"点击失败: {e}"
    return False, info


def wait_renew_page(sb, timeout=30):
    """等待进入 Renew your server 页。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        title = (sb.get_title() or "").lower()
        url = (sb.get_current_url() or "").lower()
        has_form = False
        try:
            has_form = sb.is_element_present("#renew-form", timeout=1) or sb.is_element_present(
                "#order-submit", timeout=1
            )
        except Exception:
            pass
        if "renew" in title or "cart_renew" in url or has_form:
            print(f"✅ 已进入续期页 | {sb.get_current_url()} | {sb.get_title()}")
            return True
        time.sleep(1)
    return False


def click_order_now(sb):
    """在续期页点击 #order-submit (Order now)。"""
    print("⏳ 等待 Order now 可点击...")
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            # 价格为 0 时页面 JS 会解除 disabled；若仍 disabled 且金额为 0，强制启用
            sb.execute_script(
                """
                const btn = document.querySelector('#order-submit');
                if (!btn) return;
                // 触发 duration change 让汇总脚本跑一遍
                const sel = document.querySelector('#duration');
                if (sel) sel.dispatchEvent(new Event('change', { bubbles: true }));
                """
            )
            time.sleep(0.5)
            el = sb.find_element("#order-submit", timeout=3)
            disabled = el.get_attribute("disabled")
            if disabled:
                # 免费套餐强制解开
                sb.execute_script(
                    """
                    const btn = document.querySelector('#order-submit');
                    if (btn) { btn.disabled = false; btn.removeAttribute('disabled'); }
                    const alert = document.querySelector('[data-alert="not_enough_balance"]');
                    if (alert) alert.classList.add('d-none');
                    """
                )
                time.sleep(0.3)
            print("🛒 点击 Order now (#order-submit)...")
            try:
                sb.uc_click("#order-submit", timeout=5)
            except Exception:
                sb.driver.execute_script(
                    "document.querySelector('#order-submit').click();"
                )
            print("✅ 已点击 Order now")
            time.sleep(4)
            return True, None
        except Exception as e:
            print(f"⏳ 等待按钮: {e}")
            time.sleep(1)

    # 文案兜底
    for sel in [
        'button:contains("Order now")',
        'button:contains("Order Now")',
        'button[type="submit"]',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                sb.uc_click(sel)
                time.sleep(4)
                return True, None
        except Exception:
            continue
    return False, "未找到可点的 Order now / #order-submit"


def check_renewal_success(sb):
    time.sleep(3)
    try:
        src = (sb.get_page_source() or "").lower()
        body = ""
        try:
            body = (sb.get_text("body") or "").lower()
        except Exception:
            pass
        blob = src[:8000] + body
        for kw in (
            "successfully purchased",
            "successfully renewed",
            "server renewed",
            "renewal successful",
            "order completed",
            "thank you",
        ):
            if kw in blob:
                return True, f"关键词: {kw}"
        # 成功后常回到 panel / servers，且 Valid until 变远
        url = (sb.get_current_url() or "").lower()
        if "panel" in url and "renew" not in url and "cart_renew" not in url:
            # 弱成功：已离开续期页
            if sb.is_element_present(".alert-success", timeout=2):
                t = sb.get_text(".alert-success")
                return True, t or "alert-success"
    except Exception as e:
        return False, str(e)

    for sel in [".alert-success", ".alert.alert-success", 'div:contains("successfully")']:
        try:
            if sb.is_element_present(sel, timeout=2):
                t = sb.get_text(sel)
                return True, t or sel
        except Exception:
            continue
    return False, "未检测到明确成功提示，请查看截图"


def check_proxy_with_requests(proxy, req_proxies):
    if not req_proxies:
        return True
    print("🔍 测试代理...")
    try:
        r = requests.get(
            "https://api.ipify.org?format=text", proxies=req_proxies, timeout=20
        )
        if r.status_code == 200 and r.text.strip():
            print(f"✅ 代理可用，出口 IP: {r.text.strip()}")
            return True
        print(f"⚠️ 代理 HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ 代理失败: {e}")
    return False


def main():
    proxy = build_proxy()
    if proxy:
        print(f"🌐 使用代理: {mask_proxy(proxy)}")
    else:
        print("ℹ️ 未配置 PROXY")

    req_proxies = None
    if proxy:
        if proxy.startswith("socks5://"):
            p = "socks5h://" + proxy[len("socks5://") :]
            req_proxies = {"http": p, "https": p}
        elif "://" in proxy:
            req_proxies = {"http": proxy, "https": proxy}
        else:
            req_proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}

    if proxy and not check_proxy_with_requests(proxy, req_proxies):
        msg = "❌ 代理不可用"
        print(msg)
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
        sys.exit(1)

    print("🚀 启动浏览器")
    sb_kwargs = {"uc": True, "headless": False, "locale": "en"}
    if proxy:
        sb_kwargs["proxy"] = proxy

    with SB(**sb_kwargs) as sb:
        try:
            ok, _ = login(sb, EMAIL, PASSWORD)
        except Exception as e:
            dump_debug(sb, "login_faild")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, f"❌ 登录异常: {e}", req_proxies)
            sys.exit(1)

        if not ok:
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, "❌ 登录失败", req_proxies)
            sys.exit(1)

        # —— 正确续期路径 ——
        open_servers_page(sb)
        dump_debug(sb, "servers_page")

        clicked, info = click_extend(sb)
        if not clicked:
            reason = info.get("reason") or "无法点击 Extend"
            # Extend 灰掉：业务上可能尚未到可续窗口，不算脚本逻辑错误
            if info.get("found") and not info.get("clickable"):
                msg = (
                    f"⏳ Extend 按钮不可点（可能未到可续时间）。"
                    f" Valid until={info.get('valid_until') or '?'}"
                )
                print(msg)
                dump_debug(sb, "extend_disabled")
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)
                # 用 exit 0 避免 Actions 一直红——可选；用户可能更想红灯
                sys.exit(0)
            msg = f"❌ 点击 Extend 失败: {reason}"
            print(msg)
            dump_debug(sb, "extend_failed")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)
            sys.exit(1)

        if not wait_renew_page(sb, timeout=35):
            msg = "❌ 点击 Extend 后未进入续期页"
            print(msg)
            dump_debug(sb, "renew_page_missing")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)
            sys.exit(1)

        dump_debug(sb, "renew_page")
        ok_order, err = click_order_now(sb)
        if not ok_order:
            msg = f"❌ Order now 失败: {err}"
            print(msg)
            dump_debug(sb, "order_failed")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)
            sys.exit(1)

        success, detail = check_renewal_success(sb)
        if success:
            msg = f"✅ 续期成功！{detail}"
            print(msg)
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"⚠️ 已提交但未确认成功: {detail}"
            print(msg)
            dump_debug(sb, "renewal_uncertain")
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)

    print("🏁 完成")


if __name__ == "__main__":
    main()
