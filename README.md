---
title: Portable Chromium
emoji: 🌐
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# Portable Chromium State Manager

متصفح Chromium مصمم ليكون "محمولاً" بالكامل، بحيث تستطيع تسجيل الدخول لحساباتك، تثبيت إضافات الـ VPN، وترك صفحات وفيديوهات مفتوحة، ثم ضغط هذا كله في ملف واحد تشاركه مع أي شخص ليفتحه ويكمل نفس الجلسة من أي مكان.

## الميزات
- **استقلال عن النظام:** يتم استخراج الكوكيز والبيانات بعيداً عن تشفير Windows DPAPI.
- **استعادة وقت الفيديوهات:** يعمل من خلال إضافة داخلية تسجل أين توقفت في فيديوهات مثل يوتيوب وتعيدك لنفس النقطة.
- **التشغيل السحابي عبر GitHub Actions:** يشتغل تلقائياً عبر GitHub Actions مع حفظ الجلسة بين كل تشغيل.
- **نظام ماكرو:** تقدر تكتب سكربتات أتمتة (فتح مواقع، تسجيل دخول، إلخ) وتشغّلها تلقائياً.

## طريقة التشغيل على ويندوز (Windows)

1. قم بتثبيت المتطلبات:
   ```cmd
   pip install -r requirements.txt
   playwright install chromium
   ```

2. لفتح المتصفح وبدء التصفح:
   ```cmd
   python main.py start
   ```
   (يمكنك الآن تثبيت إضافات وفتح مواقع وتسجيل الدخول. عند الانتهاء قم بإغلاق المتصفح وسيقوم النظام بحفظ بياناتك تلقائياً).

3. لتصدير ملف الجلسة لمشاركته:
   ```cmd
   python main.py export
   ```
   سينتج لك ملف `session.crsession`.

4. لاستيراد ملف جلسة أرسله لك شخص آخر:
   ```cmd
   python main.py import session.crsession
   ```

## طريقة التشغيل على GitHub Actions

### الإعداد الأولي

1. أنشئ مستودع GitHub جديد (خاص أو عام).
2. ارفع جميع ملفات هذا المجلد للمستودع (بما في ذلك مجلد `.github/workflows/`).
3. أضف الـ Secrets المطلوبة في إعدادات المستودع:
   - **Settings → Secrets and variables → Actions → New repository secret**
   - `SESSION_PASSWORD` - كلمة مرور لتشفير ملف الجلسة
   - `VLESS_LINK` - (اختياري) رابط VLESS للبروكسي

### التشغيل

يمكنك تشغيل الـ workflow بثلاث طرق:

**1. يدوياً من GitHub:**
   - اذهب لتبويب **Actions** → **Browser Session** → **Run workflow**
   - حدد اسم الماكرو (اختياري) والمدة

**2. عبر البوت (Telegram):**
   - البوت يستخدم `workflow_dispatch` لتشغيل الـ Action تلقائياً
   - يمكنك جدولة التشغيل يومياً في وقت محدد

**3. عبر الـ API:**
   ```bash
   curl -X POST \
     -H "Authorization: token YOUR_GITHUB_TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     https://api.github.com/repos/OWNER/REPO/actions/workflows/browser_session.yml/dispatches \
     -d '{"ref":"main","inputs":{"macro":"example_login","duration":"10"}}'
   ```

### حفظ الجلسة
- يتم حفظ ملف `session.crsession` تلقائياً كـ GitHub Artifact بعد كل تشغيل.
- في التشغيل التالي يتم تحميل آخر جلسة محفوظة واستيرادها تلقائياً.
- الجلسة تبقى محفوظة لمدة 90 يوم.

## نظام الماكرو

الماكروهات هي سكربتات Python موجودة في مجلد `macros/`. كل ماكرو لازم يحتوي على دالة:

```python
async def run(context, page):
    # الكود بتاعك هنا
    await page.goto("https://example.com")
    await page.fill("#email", os.environ.get("TARGET_EMAIL"))
    # ...
```

### إنشاء ماكرو جديد

1. أنشئ ملف Python جديد في مجلد `macros/` (مثلاً `my_task.py`).
2. اكتب دالة `async def run(context, page)` بداخله.
3. استخدم `os.environ.get()` لقراءة البيانات الحساسة من GitHub Secrets.
4. شغّل الـ workflow مع `macro = "my_task"`.

### مثال جاهز
شوف ملف `macros/example_login.py` كمثال لماكرو تسجيل دخول تلقائي.
