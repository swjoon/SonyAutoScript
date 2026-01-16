import os
import time
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# =========================
# 설정
# =========================
URL = "https://store.sony.co.kr/product-view/102263765"

# 체크 주기 정책
CHECK_INTERVAL_SOLDOUT_SEC = 60  # 품절(또는 구매불가)일 때: 1분
CHECK_INTERVAL_AVAILABLE_SEC = 3600  # 구매가능일 때: 1시간

ABOUT_SELECTOR = "div.product_view_about"
TITLE_SELECTOR = f"{ABOUT_SELECTOR} p.product_tit"
FINAL_BUTTON_SELECTOR = f"{ABOUT_SELECTOR} .result_btn_inner li.final a.btn_style"
IMAGE_SELECTOR = 'img[alt="상품이미지"]'  # 첫 번째 이미지 사용

PREVIEW_HTML_PATH = "email_preview.html"

SEND_REAL_EMAIL = True  # False면 메일은 안 보내고 미리보기 파일만 생성


# =========================
# 유틸
# =========================
def absolutize_url(src: str) -> str:
    """//로 시작하는 URL을 https://로 보정"""
    if not src:
        return ""
    src = src.strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://store.sony.co.kr" + src
    return src


# =========================
# 크롤링/판정
# =========================
def check_stock():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)

            # about_class (soldout 포함 여부 판단)
            page.wait_for_selector(ABOUT_SELECTOR, timeout=20000)
            about_class = (
                page.locator(ABOUT_SELECTOR).first.get_attribute("class") or ""
            ).strip()
            is_soldout_block = "soldout" in about_class

            # 제품명
            page.wait_for_selector(TITLE_SELECTOR, timeout=20000)
            title = (page.locator(TITLE_SELECTOR).first.inner_text() or "").strip()

            # 이미지
            image_url = ""
            try:
                page.wait_for_selector(IMAGE_SELECTOR, timeout=15000)
                src = (
                    page.locator(IMAGE_SELECTOR).first.get_attribute("src") or ""
                ).strip()
                image_url = absolutize_url(src)
            except Exception:
                image_url = ""

            # 최종 버튼
            page.wait_for_selector(FINAL_BUTTON_SELECTOR, timeout=20000)
            btn = page.locator(FINAL_BUTTON_SELECTOR).first
            text = (btn.inner_text() or "").strip()
            class_attr = (btn.get_attribute("class") or "").strip()

            is_disabled = "disabled" in class_attr
            is_temp_soldout = text == "일시품절"

            ok = (not is_disabled) and (not is_temp_soldout)
            ok = ok and (not is_soldout_block)

            detail = (
                f"about_class='{about_class}', soldout_block={is_soldout_block}, "
                f"finalText='{text}', finalClass='{class_attr}', disabled={is_disabled}"
            )

            product = {
                "title": title,
                "image_url": image_url,
                "button_text": text,
                "about_class": about_class,
            }
            return ok, detail, product

        except PwTimeout:
            return (
                False,
                "timeout: selector not found / load too slow",
                {"title": "", "image_url": "", "button_text": "", "about_class": ""},
            )
        except Exception as e:
            return (
                False,
                f"exception: {type(e).__name__}: {e}",
                {"title": "", "image_url": "", "button_text": "", "about_class": ""},
            )
        finally:
            browser.close()


def build_email_html(
    title: str, image_url: str, ok: bool, url: str, detail: str, now: str
) -> str:
    dot = "🟢" if ok else "🔴"
    status_text = "구매 가능" if ok else "품절 / 구매불가"
    badge_bg = "#16a34a" if ok else "#ef4444"  # green / red
    badge_fg = "#ffffff"

    safe_title = title if title else "(제품명 추출 실패)"

    img_html = ""
    if image_url:
        img_html = f"""
        <div style="margin-top:16px;">
          <img src="{image_url}" alt="product"
               style="width:100%; max-width:560px; border-radius:14px; border:1px solid #eef2f7; display:block;">
        </div>
        """

    cta_bg = "#0b57d0"
    cta_fg = "#ffffff"

    return f"""
    <div style="margin:0; padding:0; background:#f6f7fb;">
      <div style="max-width:640px; margin:0 auto; padding:24px;">
        
        <!-- CARD -->
        <div style="background:#ffffff; border:1px solid #e9edf3; border-radius:18px; overflow:hidden;
                    box-shadow:0 10px 30px rgba(17,24,39,0.06);">
          
          <!-- HEADER -->
          <div style="padding:18px 20px; background:linear-gradient(135deg, #0b57d0 0%, #5b8cff 100%);">
            <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
              <div style="color:#ffffff;">
                <div style="font-size:12px; opacity:0.9; letter-spacing:0.2px;">Sony Store Stock Watch</div>
                <div style="font-size:18px; font-weight:700; margin-top:4px;">{dot} 상태 변경 알림</div>
              </div>
              <div style="background:rgba(255,255,255,0.18); color:#ffffff; padding:8px 12px; border-radius:999px;
                          font-size:12px; white-space:nowrap;">
                {now}
              </div>
            </div>
          </div>

          <!-- BODY -->
          <div style="padding:20px;">
            <!-- TITLE + BADGE -->
            <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px;">
              <div style="flex:1;">
                <div style="font-size:20px; font-weight:800; color:#111827; line-height:1.25;">
                  {safe_title}
                </div>
                <div style="margin-top:8px; color:#6b7280; font-size:13px; line-height:1.4;">
                  아래 버튼을 눌러 상품 페이지에서 최종 구매 가능 여부를 확인하세요.
                </div>
              </div>
              <div style="background:{badge_bg}; color:{badge_fg}; padding:8px 12px; border-radius:999px;
                          font-size:12px; font-weight:700; white-space:nowrap;">
                {status_text}
              </div>
            </div>

            {img_html}

            <!-- CTA -->
            <div style="margin-top:18px;">
              <a href="{url}" target="_blank"
                 style="display:inline-block; background:{cta_bg}; color:{cta_fg}; text-decoration:none;
                        padding:12px 16px; border-radius:12px; font-size:14px; font-weight:700;">
                🔗 상품 페이지 열기
              </a>
              <div style="margin-top:10px; font-size:12px; color:#9ca3af;">
                링크가 안 눌리면 아래 URL을 복사해서 브라우저에 붙여넣어 주세요.<br>
                <span style="color:#6b7280;">{url}</span>
              </div>
            </div>

            <!-- DIVIDER -->
            <div style="height:1px; background:#eef2f7; margin:18px 0;"></div>

            <!-- FOOTER INFO -->
            <div style="display:flex; gap:12px; flex-wrap:wrap;">
              <div style="flex:1; min-width:220px; background:#f9fafb; border:1px solid #eef2f7; border-radius:12px; padding:12px;">
                <div style="font-size:12px; font-weight:700; color:#111827;">판정 근거</div>
                <div style="margin-top:6px; font-size:12px; color:#6b7280; line-height:1.45; word-break:break-word;">
                  {detail}
                </div>
              </div>

              <div style="flex:1; min-width:220px; background:#f9fafb; border:1px solid #eef2f7; border-radius:12px; padding:12px;">
                <div style="font-size:12px; font-weight:700; color:#111827;">상태 안내</div>
                <div style="margin-top:6px; font-size:12px; color:#6b7280; line-height:1.45;">
                  • {dot} 표시가 <b>🟢</b>이면 구매 가능으로 판단했습니다.<br>
                  • 실제 결제 가능 여부는 사이트 정책/수량 제한에 따라 달라질 수 있습니다.
                </div>
              </div>
            </div>
          </div>

          <!-- BOTTOM -->
          <div style="padding:14px 20px; background:#f9fafb; border-top:1px solid #eef2f7;
                      color:#9ca3af; font-size:11px; line-height:1.5;">
            본 메일은 자동 감지 스크립트에 의해 발송되었습니다. (1분/1시간 주기 정책에 따라 발송)
          </div>
        </div>
      </div>
    </div>
    """


def save_email_preview(html: str, path: str = PREVIEW_HTML_PATH):
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def send_email_html(subject: str, html: str):
    gmail_user = "이메일"
    gmail_app_pw = "앱 비번"
    to_email = "수신받을 이메일"

    msg = MIMEText(html, "html", _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_user, gmail_app_pw)
        smtp.sendmail(gmail_user, [to_email], msg.as_string())


# =========================
# 메인 루프
# =========================
def main_loop():
    last_state = None  # None / "SOLDOUT" / "AVAILABLE"
    current_interval = CHECK_INTERVAL_SOLDOUT_SEC

    while True:
        ok, detail, product = check_stock()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        title = product.get("title", "")
        image_url = product.get("image_url", "")

        state = "AVAILABLE" if ok else "SOLDOUT"

        print(f"\n[{now}] state={state} detail={detail}")
        print(f"  title={title}")
        print(f"  image={image_url}")

        # --- 상태 변화 감지 ---
        if last_state is None:
            current_interval = (
                CHECK_INTERVAL_AVAILABLE_SEC
                if state == "AVAILABLE"
                else CHECK_INTERVAL_SOLDOUT_SEC
            )

        elif last_state == "SOLDOUT" and state == "AVAILABLE":
            subject = "🟢 소니스토어 구매 가능으로 변경됨"
            html = build_email_html(title, image_url, True, URL, detail, now)

            if SEND_REAL_EMAIL:
                send_email_html(subject, html)

            current_interval = CHECK_INTERVAL_AVAILABLE_SEC

        elif last_state == "AVAILABLE" and state == "SOLDOUT":
            subject = "🔴 소니스토어 품절/구매불가로 변경됨"
            html = build_email_html(title, image_url, False, URL, detail, now)

            if SEND_REAL_EMAIL:
                send_email_html(subject, html)

            current_interval = CHECK_INTERVAL_SOLDOUT_SEC

        if last_state == "AVAILABLE" and state == "AVAILABLE":
            subject = "🟢 소니스토어 구매 가능 상태 유지(정기 알림)"
            html = build_email_html(title, image_url, True, URL, detail, now)

            if SEND_REAL_EMAIL:
                send_email_html(subject, html)

            current_interval = CHECK_INTERVAL_AVAILABLE_SEC

        if state == "SOLDOUT":
            current_interval = CHECK_INTERVAL_SOLDOUT_SEC

        last_state = state

        time.sleep(current_interval)


if __name__ == "__main__":
    main_loop()
