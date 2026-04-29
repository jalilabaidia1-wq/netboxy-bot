#!/usr/bin/env python3
"""
NetBoxy Deploy Bot - Full Browser Automation (No gcloud)
مُحسَّن لـ Hugging Face Spaces / أي خادم Linux x86_64 مع Google Chrome
"""

import os
import re
import asyncio
import logging
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes, CallbackQueryHandler
)

# ================ إعدادات ================
BOT_TOKEN = "8667458394:AAElVGH7YpXJRaKojgOFe-IGHN8fX_q06fg"
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")  # اتركه فارغاً للسماح للكل
REQUIRED_CHANNEL = "@sksksjsjajaxasa"
CHANNEL_URL = "https://t.me/NetBoxy"

VLESS_UUID = "ba0e3984-ccc9-48a3-8074-b2f507f41ce8"
VLESS_PATH = "/@NetBoxy"
DOCKER_IMAGE = "docker.io/seifszx/seifszx"
SERVICE_NAME = "netboxy-vless"
REGION = "europe-west4"

# مسار المتصفح: نعتمد على متغير البيئة إن وُجد، وإلا افتراضي
CHROME_PATH = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/google-chrome-stable")

# ================ تجهيزات ================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================ صلاحيات المستخدم ================
def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USERS.strip():
        return True
    allowed = [int(x.strip()) for x in ALLOWED_USERS.split(",") if x.strip()]
    return user_id in allowed

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

async def require_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if await check_subscription(user_id, context):
        return True
    keyboard = [[InlineKeyboardButton("📢 اشترك في القناة", url=CHANNEL_URL)]]
    text = (
        "⛔ *يجب الاشتراك في القناة!*\n\n"
        f"اشترك في {REQUIRED_CHANNEL} ثم حاول مجدداً.\n"
        "_أرسل /start بعد الاشتراك_"
    )
    if update.callback_query:
        await update.callback_query.answer("الاشتراك مطلوب", show_alert=True)
        await update.callback_query.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return False

# ================ محرك النشر عبر المتصفح ================
async def deploy_via_browser(link: str, progress_message) -> str:
    """
    تشغيل Google Chrome headless، تنفيذ كل خطوات إنشاء الخدمة على Cloud Run،
    وإرجاع رابط الخدمة المنشورة.
    """
    from playwright.async_api import async_playwright
    import urllib.request

    # 1. تشغيل Chrome مع منفذ debugging
    process = subprocess.Popen(
        [
            CHROME_PATH,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=9222",
            "--remote-debugging-address=127.0.0.1",
            "--user-data-dir=/tmp/chrome_session"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setpgrp  # يجعل العملية في مجموعة جديدة لتجنب قتلها
    )

    # 2. انتظر حتى يستجيب Chrome
    cdp_url = "http://127.0.0.1:9222"
    for _ in range(12):
        try:
            urllib.request.urlopen(f"{cdp_url}/json/version", timeout=2)
            break
        except Exception:
            await asyncio.sleep(1.5)
    else:
        raise Exception("لم يبدأ Chrome بنجاح")

    try:
        async with async_playwright() as p:
            # 3. الاتصال بالمتصفح
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            page = await context.new_page()

            # 4. فتح رابط SSO والوصول إلى الكونسول
            await progress_message.edit_text("⏳ فتح الرابط وتسجيل الدخول...")
            await page.goto(link, wait_until="networkidle", timeout=120000)
            await page.wait_for_url("**console.cloud.google.com**", timeout=60000)
            await asyncio.sleep(5)

            # 5. استخراج project_id
            current_url = page.url
            match = re.search(r'project=([\w-]+)', current_url)
            if not match:
                raise ValueError("لم يُعثر على project ID في الرابط")
            project_id = match.group(1)

            # 6. التوجه إلى Cloud Run
            run_url = f"https://console.cloud.google.com/run?project={project_id}"
            await progress_message.edit_text(f"📁 المشروع: `{project_id}`\n⏳ فتح Cloud Run...")
            await page.goto(run_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

            # 7. الضغط على "CREATE SERVICE"
            try:
                await page.click('button:has-text("CREATE SERVICE")', timeout=10000)
            except Exception:
                await page.click('button:has-text("Create Service")', timeout=10000)

            await progress_message.edit_text("🛠️ ملء إعدادات الخدمة...")
            await page.wait_for_selector('input[name="image"]', timeout=15000)
            await page.fill('input[name="image"]', DOCKER_IMAGE)

            # 8. اختيار المنطقة (إذا لم تكن محددة)
            try:
                region_btn = await page.wait_for_selector('mat-select[aria-label="Region"]', timeout=3000)
                await region_btn.click()
                await asyncio.sleep(1)
                await page.click(f'mat-option:has-text("{REGION}")')
            except Exception:
                pass

            # 9. السماح بالوصول غير المصرح
            try:
                await page.click(
                    'mat-radio-group[aria-label="Authentication"] mat-radio-button:has-text("Allow unauthenticated")'
                )
            except Exception:
                pass

            # 10. فتح الإعدادات المتقدمة
            try:
                await page.click('button:has-text("Advanced")')
            except Exception:
                pass
            await asyncio.sleep(1)

            # 11. تعيين بيئة التنفيذ: Second generation
            try:
                exec_block = await page.wait_for_selector('text=Execution environment', timeout=3000)
                parent = await exec_block.evaluate_handle('(el) => el.closest(".form-group")')
                dropdown = await parent.wait_for_selector('mat-select')
                await dropdown.click()
                await asyncio.sleep(0.8)
                await page.click('mat-option:has-text("Second generation")')
            except Exception:
                pass

            # 12. تعيين الفوترة: Instance‑based (بدون خنق المعالج)
            try:
                billing_block = await page.wait_for_selector('text=Billing', timeout=3000)
                parent = await billing_block.evaluate_handle('(el) => el.closest(".form-group")')
                dropdown = await parent.wait_for_selector('mat-select')
                await dropdown.click()
                await asyncio.sleep(0.8)
                await page.click('mat-option:has-text("Instance‑based")')
            except Exception:
                pass

            # 13. التزامن: 1000، المهلة: 3600، النسخ: 0-10
            try:
                await page.fill('input[formcontrolname="concurrency"]', "1000")
            except Exception:
                pass
            try:
                await page.fill('input[formcontrolname="timeout"]', "3600")
            except Exception:
                pass
            try:
                await page.fill('input[formcontrolname="minInstances"]', "0")
            except Exception:
                pass
            try:
                await page.fill('input[formcontrolname="maxInstances"]', "10")
            except Exception:
                pass

            # 14. الذاكرة 2 GiB والمعالج 1 vCPU
            try:
                await page.click('button:has-text("Container(s)")')
            except Exception:
                pass
            try:
                mem_block = await page.wait_for_selector('text=Memory', timeout=3000)
                parent = await mem_block.evaluate_handle('(el) => el.closest(".form-group")')
                dropdown = await parent.wait_for_selector('mat-select')
                await dropdown.click()
                await asyncio.sleep(0.5)
                await page.click('mat-option:has-text("2 GiB")')
            except Exception:
                pass
            try:
                cpu_block = await page.wait_for_selector('text=CPU', timeout=3000)
                parent = await cpu_block.evaluate_handle('(el) => el.closest(".form-group")')
                dropdown = await parent.wait_for_selector('mat-select')
                await dropdown.click()
                await asyncio.sleep(0.5)
                await page.click('mat-option:has-text("1")')
            except Exception:
                pass

            # 15. إنشاء الخدمة
            await progress_message.edit_text("🚀 جاري إنشاء الخدمة...")
            await page.click('button:has-text("CREATE")')
            await page.wait_for_url("**/deploy**", timeout=300000)
            await asyncio.sleep(8)

            # 16. استخراج رابط الخدمة
            service_url = None
            try:
                url_el = await page.wait_for_selector('a:has-text(".run.app")', timeout=15000)
                service_url = await url_el.text_content()
            except Exception:
                # خطة بديلة: البحث في نص الصفحة
                text = await page.text_content('body')
                match = re.search(r'https://[\w-]+\.europe-west4\.run\.app', text)
                service_url = match.group(0) if match else None

            if not service_url:
                raise ValueError("تعذّر استخراج رابط الخدمة")

            return service_url.strip()

    finally:
        # إغلاق المتصفح
        process.terminate()
        process.wait()

# ================ بناء رابط VLESS ================
def build_vless_uri(service_url: str) -> str:
    host = service_url.replace("https://", "")
    return (
        f"vless://{VLESS_UUID}@youtube.com:443"
        f"?path={VLESS_PATH.replace('/', '%2F')}"
        f"&security=tls&encryption=none"
        f"&host={host}"
        f"&type=ws&sni=youtube.com"
        f"#NetBoxy-VLESS-WS"
    )

# ================ محادثة البوت ================
WAITING_FOR_LINK = 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ غير مصرح لك.")
        return
    if not await require_subscription(update, context):
        return
    await update.message.reply_text(
        "🚀 *NetBoxy Deploy Bot*\n\n"
        "أرسل رابط SSO الذي تلقيته من المعمل:\n"
        "`/deploy <الرابط>` أو أرسل الرابط مباشرة.\n\n"
        "سأقوم بإنشاء خدمة VLESS تلقائياً.",
        parse_mode="Markdown"
    )

async def deploy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ غير مصرح.")
        return
    if not await require_subscription(update, context):
        return ConversationHandler.END
    await update.message.reply_text("📎 أرسل رابط Google Cloud SSO الآن.\nأو أرسل /cancel للإلغاء.")
    return WAITING_FOR_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not (link.startswith("https://") and "skills.google" in link.lower()):
        await update.message.reply_text("❌ الرابط غير صحيح. أعد المحاولة.")
        return WAITING_FOR_LINK

    msg = await update.message.reply_text("⏳ جاري بدء المتصفح...")
    try:
        service_url = await deploy_via_browser(link, msg)
        vless = build_vless_uri(service_url)
        await msg.edit_text(
            f"✅ *تم النشر بنجاح!*\n\n"
            f"🔗 رابط الخدمة:\n`{service_url}`\n\n"
            f"📡 رابط VLESS:\n`{vless}`\n\n"
            "_انسخه وأضفه إلى تطبيق V2RayNG_",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception("Deploy failed")
        await msg.edit_text(f"❌ خطأ:\n`{str(e)[:400]}`")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END

async def handle_direct_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not is_allowed(update.effective_user.id):
        return
    if not await require_subscription(update, context):
        return
    if "skills.google" in link.lower():
        return await receive_link(update, context)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    await update.message.reply_text(
        "📖 *كيفية الاستخدام:*\n\n"
        "1. احصل على رابط SSO من معمل Google Cloud.\n"
        "2. أرسله للبوت (أو مع الأمر `/deploy`).\n"
        "3. انتظر حتى يتم إنشاء الخدمة تلقائياً.\n"
        "4. استلم رابط VLESS.\n\n"
        "لا تحتاج لأي شيء آخر.",
        parse_mode="Markdown"
    )

# ================ تشغيل البوت ================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("deploy", deploy_command)],
        states={
            WAITING_FOR_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_link))

    print("🤖 NetBoxy Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()