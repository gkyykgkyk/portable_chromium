"""
مثال ماكرو: تسجيل دخول تلقائي في موقع
===========================================
كيفية الاستخدام:
  1. حط المتغيرات التالية كـ GitHub Secrets في المستودع:
     - TARGET_URL: رابط صفحة تسجيل الدخول
     - TARGET_EMAIL: البريد الإلكتروني
     - TARGET_PASSWORD: كلمة المرور

  2. شغّل الـ workflow مع:
     macro = "example_login"

ملاحظات:
  - غيّر الـ selectors (#email, #password, #login-btn) حسب الموقع المستهدف
  - كل ماكرو لازم يكون فيه دالة: async def run(context, page)
"""
import os


async def run(context, page):
    """
    يفتح موقع ويسجّل دخول تلقائياً.
    
    Args:
        context: Playwright BrowserContext (فيه كل الكوكيز والبيانات)
        page: Playwright Page (صفحة جاهزة للاستخدام)
    """
    target_url = os.environ.get("TARGET_URL", "https://example.com/login")
    email = os.environ.get("TARGET_EMAIL", "")
    password = os.environ.get("TARGET_PASSWORD", "")

    if not email or not password:
        print("⚠️ TARGET_EMAIL أو TARGET_PASSWORD غير محددين في الـ Secrets!")
        print("   أضفهم من البوت: 🔧 إدارة الأسرار (Secrets)")
        return

    print(f"🌐 فتح الموقع: {target_url}")
    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    # تسجيل الدخول (غيّر الـ selectors حسب الموقع)
    print("📧 إدخال البريد الإلكتروني...")
    await page.fill("#email", email)
    
    print("🔑 إدخال كلمة المرور...")
    await page.fill("#password", password)
    
    print("🖱️ الضغط على زر تسجيل الدخول...")
    await page.click("#login-btn")

    # انتظار تحميل الصفحة بعد تسجيل الدخول
    await page.wait_for_timeout(5000)

    # التحقق من نجاح تسجيل الدخول (اختياري)
    current_url = page.url
    print(f"📍 الصفحة الحالية بعد تسجيل الدخول: {current_url}")
    
    # أخذ لقطة شاشة للتوثيق
    screenshot_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshot.png")
    await page.screenshot(path=screenshot_path, full_page=True)
    print(f"📸 تم حفظ لقطة شاشة: {screenshot_path}")
