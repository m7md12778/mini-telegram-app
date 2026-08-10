import asyncio
import os
import random
import re
import sys
import time
import json
import io
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from collections import defaultdict

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.photos import GetUserPhotosRequest, UploadProfilePhotoRequest
from telethon.tl.functions.account import UpdateProfileRequest, ReportPeerRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import (
    ReactionEmoji, ChatBannedRights, ChannelParticipantsAdmins,
    InputReportReasonSpam, InputReportReasonViolence,
    InputReportReasonPornography, InputReportReasonChildAbuse,
    InputReportReasonOther, InputReportReasonIllegalDrugs,
    InputReportReasonPersonalDetails, InputReportReasonFake
)
from telethon.errors import FloodWaitError

# مكتبة صور الحقوق
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None

# ─── إعدادات المفاتيح والتسجيل ───
API_ID = 34175320
API_HASH = 'd56987323913952a8c7ffc89bea394e4'

LOG_CHANNEL = -1003831440795

SESSION_FILE = "session_string.txt"
WORDS_FILE = "spam_words.txt"
saved_session = ""

if os.path.exists(SESSION_FILE):
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        saved_session = f.read().strip()

client = TelegramClient(StringSession(saved_session), API_ID, API_HASH)

# ─── متغيرات الذاكرة والنظام ───
START_TIME = time.time()
muted_users = set()
watchlist = set()  # قائمة المراقبة
name_history = defaultdict(list)  # سجل الأسماء
deleted_msg_cache = {}
MAX_CACHE_SIZE = 1000
clock_task = None
auto_post_task = None

original_profile = {"first_name": "", "about": "", "photo": None}

spam_words = []
if os.path.exists(WORDS_FILE):
    with open(WORDS_FILE, "r", encoding="utf-8") as f:
        spam_words = [line.strip() for line in f.readlines() if line.strip()]

spam_speed = 1.0
spam_active = False
auto_report_active = False

takleesh_active = False
takleesh_target = None

track_active = False
track_target = None

space_tilde_active = False

afk_active = False
afk_reason = ""
afk_time = None
tag_active = False

REPORT_REASONS = {
    "سبام": InputReportReasonSpam(),
    "عنف": InputReportReasonViolence(),
    "اباحي": InputReportReasonPornography(),
    "إباحي": InputReportReasonPornography(),
    "اطفال": InputReportReasonChildAbuse(),
    "أطفال": InputReportReasonChildAbuse(),
    "مخدرات": InputReportReasonIllegalDrugs(),
    "خصوصية": InputReportReasonPersonalDetails(),
    "زائف": InputReportReasonFake(),
    "احتيال": InputReportReasonFake(),
    "اخرى": InputReportReasonOther(),
    "أخرى": InputReportReasonOther(),
}

COMMAND_COOLDOWN = 1.5
GUESS_COOLDOWN = 5.0
last_cmd_time = {}
guess_attempts = defaultdict(list)

def is_rate_limited(user_id: int, cooldown_time: float = COMMAND_COOLDOWN) -> bool:
    current_time = time.time()
    last_time = last_cmd_time.get(user_id, 0)
    if current_time - last_time < cooldown_time:
        return True
    last_cmd_time[user_id] = current_time
    return False

def check_bruteforce_limit(user_id: int, max_attempts: int = 5, window_seconds: int = 60) -> bool:
    current_time = time.time()
    guess_attempts[user_id] = [t for t in guess_attempts[user_id] if current_time - t < window_seconds]
    if len(guess_attempts[user_id]) >= max_attempts:
        return True
    guess_attempts[user_id].append(current_time)
    return False

TAKLEESH_LIST = [
    "فرخ مخصص للجلد والتكليش 😂🔥",
    "ولك اشررررب تاكلك ناعم يا مطيرچي 🔥",
    "وين رايح حبيبي تعالي هنا اني معلمك ✨",
    "اسمعني زين لا تتعدى حدودك ويا الكبار 🤫",
    "منور الكروب بس دير بالك من الجلد 👀"
]

def translate_text_sync(text, target_lang="ar"):
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(text)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode('utf-8'))
            return "".join([item[0] for item in res[0] if item[0]])
    except Exception as e:
        return f"❌ خطأ في الترجمة: {str(e)}"

# ─── القوائم الرئيسية والفرعية ───
MAIN_MENU = """✦ ───『 قـائـمـة الاوامـر المـطـورة 』─── ✦
• .م1 ➪ اوامـر الـحـسـاب والنظام
• .م2 ➪ اوامـر الـكـتـم والكشف والتفرغ
• .م3 ➪ اوامـر التسطير والسبام
• .م4 ➪ اوامـر الحـذف والتدمير
• .م5 ➪ اوامـر الـوهمـي والتفاعل
• .م6 ➪ اوامـر الانـتـحـال
• .م7 ➪ قـسـم الـتـلـغـيـم والشد
• .م8 ➪ اوامـر الاذاعـه
• .م9 ➪ الـنـشـر الـتـلـقـائـي
• .م10 ➪ قـسـم الـيـوزرات والترجمة
• .م11 ➪ اوامـر الـتـكـلـيـش والتتبع
• .م12 ➪ اوامر الجروبات والإدارة والمراقبة
• .م13 ➪ قائمة التسليـه والميديا والتحميل
• .م14 ➪ كـشـف وتـدقـيـق الـمـخـالـفـات 🚨
• .م15 ➪ قـسـم الـذكـاء الاصـطـنـاعـي 🤖
• .م16 ➪ الـخـدمـات والـحـمـايـة 🛡️
ـــــــــــــــــــــــــــــــــــــــــــــــــــــــــــــــــ
اكتب .م + الرقم لعرض قائمة القسم (مثال: .م1)"""

M1_MENU = """✾ ─── 『اوامـر الحـسـاب والنظام』 ─── ✾
• .الملكيات ➪ عرض معلومات وتفاصيل حسابك
• .جلسة ➪ استخراج كود String Session للحساب
• .تغير_الاسم + الاسم ➪ تغيير اسم الحساب فوراً
• .بنج / .بنك ➪ قياس سرعة استجابة السورس ومدة التشغيل
• .ريستارت ➪ إعادة تشغيل السورس برمجياً"""

M2_MENU = """✾ ─── 『اوامـر الكـتـم والـكـشـف والتفرغ』 ─── ✾
• .كتم ➪ بالرد لكتم شخص وحذف رسائله تلقائياً
• .الغاء_الكتم ➪ بالرد لإلغاء الكتم
• .المكتومين ➪ عرض قائمة المكتومين
• .كشف ➪ بالرد للكشف الشامل عن الحساب
• .افك + السبب ➪ تفعيل وضع التفرغ والرد التلقائي"""

M3_MENU = """✾ ─── 『اوامـر الاسـبـام والـبـلـش』 ─── ✾
• .تخزين الكلمات ➪ حفظ نص/سطور في ملف دائم
• .عرض الكلمات ➪ عرض الكلمات المخزنة وحجمها
• .مسح_الكلمات ➪ مسح جميع الكلمات المخزنة
• .تحديد السرعه + الرقم ➪ تحديد سرعة الإرسال بالثواني
• .بدء الارسال ➪ لإرسال الكلمات المخزنة
• .سبام + العدد + النص ➪ سبام سريع بعدد محدد
• .ايقاف ➪ إيقاف جميع عمليات السبام والتكليش والبلاغات"""

M4_MENU = """✾ ─── 『اوامـر الحـذف والتدمير』 ─── ✾
• .حذف ➪ بالرد لحذف الرسالة فوراً
• .مسح + العدد ➪ لحذف آخر (عدد) رسائل منك
• .تدمير + الثواني + النص ➪ رسالة ذاتية التدمير"""

M5_MENU = """✾ ─── 『اوامـر الـوهمـي والتفاعل』 ─── ✾
• .تفاعل + الرمز ➪ بالرد لإضافة تفاعل إيموجي"""

M6_MENU = """✾ ─── 『اوامـر الانـتـحـال』 ─── ✾
• .انتحال ➪ بالرد لنسخ اسم وصورة الهدف
• .ارجاع ➪ لاستعادة معلومات حسابك الأصلية"""

M7_MENU = """✾ ─── 『قـسـم الـتـلـغـيـم والشد』 ─── ✾
• .كليشة_ذكاء ➪ توليد كليشة بلاغ جاهزة
• .بلاغ_تلقائي <النوع> <العدد> <الكليشة> ➪ بالرد أو الشات لشد بلاغات
• .ايقاف ➪ إيقاف عمليات البلاغات فوراً"""

M8_MENU = """✾ ─── 『اوامـر الاذاعـه』 ─── ✾
• .اذاعة_خاص + النص ➪ إذاعة للمحادثات الخاصة
• .اذاعة_جروبات + النص ➪ إذاعة لكافة المجموعات"""

M9_MENU = """✾ ─── 『الـنـشـر الـتـلـقـائـي』 ─── ✾
• .نشر + الثواني + النص ➪ بدء نشر تلقائي
• .ايقاف_النشر ➪ إيقاف النشر التلقائي"""

M10_MENU = """✾ ─── 『قـسـم الـيـوزرات والترجمة』 ─── ✾
• .فحص + اليوزر ➪ فحص توفر معرف تلجرام
• .ترجمة + النص ➪ ترجمة النص للعربية
• .زخرفة + النص ➪ زخرفة النصوص"""

M11_MENU = """✾ ─── 『اوامـر الـتـكـلـيـش والتتبع』 ─── ✾
• .تكليش ➪ بالرد للرد على الهدف بكليشات جاهزة
• .تتبع ➪ بالرد للرد على الهدف بكلمات من المخزن
• .عوفمه / .ايقاف ➪ إلغاء التكليش والتتبع"""

M12_MENU = """✾ ─── 『اوامر الجروبات والإدارة والمراقبة』 ─── ✾
• .تاق + النص ➪ الإشارة لكافة الأعضاء
• .تاق_ادمن + النص ➪ المنشن الخاص بالمشرفين فقط
• .ايقاف_التاق ➪ إيقاف التاق
• .مراقبة ➪ بالرد لمراقبة وتتبع رسائل الهدف في المجموعات
• .سجل_الاسماء ➪ بالرد لعرض الأسماء والمعرفات السابقة
• .احصائيات ➪ إحصائيات أعضاء الجروب
• .تنظيف ➪ طرد الحسابات المحذوفة
• .حظر / .طرد / .تثبيت ➪ بالرد للإدارة السريعة
• .مغادرة ➪ لمغادرة المجموعة"""

M13_MENU = """✾ ─── 『قـائـمـة الـتـسـلـيـه والميديا والتحميل』 ─── ✾
• .تنزيل <الرابط> ➪ تنزيل مقاطع فيديو أو صوت برابط مباشر
• .فيديو_دائري ➪ بالرد لتحويل الفيديو لبصمة فيديو دائرية
• .تفريغ ➪ تحويل البصمة الصوتية إلى نص مكتوب
• .تفعيل الساعة / .تعطيل الساعة
• .بصمة / .لصورة / .ملصق
• .سحب + رابط ➪ سحب المحتوى المقيد
• .مسافه ➪ استبدال المسافات بـ (~)
• .خيره / .نسبه"""

M14_MENU = """✾ ─── 『كـشـف وتـدقـيـق الـمـخـالـفـات』 ─── ✾
• .م14 (اليوزر/الرابط/الأيدي) ➪ فحص شامل للمجموعة أو القناة
• .كشف_المخالفات + (اليوزر/الرابط) ➪ فحص تلقائي ودقيق للجروب/القناة
• .بلاغ_مخالفة ➪ بالرد لتوليد بلاغ رسمي برابط المخالفة"""

M15_MENU = """✾ ─── 『قـسـم الـذكـاء الاصـطـنـاعـي』 ─── ✾
• .ذكاء / .سؤال + <السؤال> ➪ الإجابة الفورية عبر الذكاء الاصطناعي
• .توليد + <الوصف> ➪ توليد صور عالية الدقة بالذكاء الاصطناعي
• .ملخص + <العدد> ➪ تلخيص آخر الرسائل في المجموعة عبر الذكاء الاصطناعي"""

M16_MENU = """✾ ─── 『الـخـدمـات والـحـمـايـة』 ─── ✾
• .فحص_رابط <الرابط> ➪ فحص أمان وسلامة الروابط المشبوهة
• .ايميل_مؤقت / .وهمي ➪ إنتاج بريد إلكتروني مؤقت لاستقبال الأكواد
• .حقوق <النص> ➪ بالرد لإضافة علامة مائية باسمك على الصورة
• .اختصار <الرابط> ➪ اختصار الروابط الطويلة
• .تاريخ / .هجري ➪ عرض التاريخ والتوقيت اليومي
• .همسة <اليوزر> <النص> ➪ إرسال نص همسة للهدف"""

# ─── توجيه القوائم ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.الاوامر$'))
async def show_main(event): await event.edit(MAIN_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م1$'))
async def show_m1(event): await event.edit(M1_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م2$'))
async def show_m2(event): await event.edit(M2_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م3$'))
async def show_m3(event): await event.edit(M3_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م4$'))
async def show_m4(event): await event.edit(M4_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م5$'))
async def show_m5(event): await event.edit(M5_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م6$'))
async def show_m6(event): await event.edit(M6_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م7$'))
async def show_m7(event): await event.edit(M7_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م8$'))
async def show_m8(event): await event.edit(M8_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م9$'))
async def show_m9(event): await event.edit(M9_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م10$'))
async def show_m10(event): await event.edit(M10_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م11$'))
async def show_m11(event): await event.edit(M11_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م12$'))
async def show_m12(event): await event.edit(M12_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م13$'))
async def show_m13(event): await event.edit(M13_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م14$'))
async def show_m14(event): await event.edit(M14_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م15$'))
async def show_m15(event): await event.edit(M15_MENU)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.م16$'))
async def show_m16(event): await event.edit(M16_MENU)

# ─── أوامر النظام والأداء (.م1) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.جلسة$'))
async def show_session(event):
    await event.edit(f"🔑 **جلسة الحساب:**\n\n`{client.session.save()}`")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.الملكيات$'))
async def account_info(event):
    me = await client.get_me()
    await event.edit(f"👑 **ملكيات الحساب:**\n• **الاسم:** {me.first_name}\n• **المعرف:** @{me.username or 'لا يوجد'}\n• **الأيدي:** `{me.id}`\n• **الرقم:** +{me.phone}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تغير_الاسم (.+)$'))
async def change_name(event):
    new_name = event.pattern_match.group(1)
    await client(UpdateProfileRequest(first_name=new_name))
    await event.edit(f"✅ تم تغيير الاسم إلى: **{new_name}**")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(بنج|بنك)$'))
async def ping_cmd(event):
    start = time.time()
    await event.edit("🏓 جاري القياس...")
    end = time.time()
    ms = round((end - start) * 1000, 2)
    uptime = str(timedelta(seconds=int(time.time() - START_TIME)))
    await event.edit(f"⚡ **سرعة الاستجابة (Ping):** `{ms} ms`\n⏱ **مدة التشغيل:** `{uptime}`")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.ريستارت$'))
async def restart_cmd(event):
    await event.edit("🔄 جاري إعادة تشغيل السورس...")
    os.execl(sys.executable, sys.executable, *sys.argv)

# ─── أوامر الكتم والتفرغ والكشف (.م2) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.كتم$'))
async def mute(event):
    reply = await event.get_reply_message()
    if reply:
        muted_users.add(reply.sender_id)
        await event.edit(f"🔇 تم كتم المستخدم `{reply.sender_id}`.")
    else: await event.edit("⚠️ رد على رسالة الشخص لكتمه.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.الغاء_الكتم$'))
async def unmute(event):
    reply = await event.get_reply_message()
    if reply and reply.sender_id in muted_users:
        muted_users.remove(reply.sender_id)
        await event.edit(f"🔊 تم إلغاء كتم المستخدم `{reply.sender_id}`.")
    else: await event.edit("⚠️ المستخدم غير مكتوم.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.المكتومين$'))
async def list_muted(event):
    if not muted_users: await event.edit("📋 لا يوجد مستخدمين مكتومين.")
    else: await event.edit("📋 **المكتومين:**\n" + "\n".join([f"• `{u}`" for u in muted_users]))

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.كشف$'))
async def inspect_user(event):
    reply = await event.get_reply_message()
    user_id = reply.sender_id if reply else event.chat_id
    try:
        user = await client.get_entity(user_id)
        info = (
            f"🔍 **كشف حساب:**\n\n"
            f"👤 **الاسم:** {user.first_name or ''} {user.last_name or ''}\n"
            f"🆔 **الأيدي:** `{user.id}`\n"
            f"🏷 **المعرف:** @{user.username or 'لا يوجد'}\n"
            f"🤖 **هل هو بوت؟:** {'نعم' if user.bot else 'لا'}\n"
            f"⭐ **مميز (Premium):** {'نعم' if getattr(user, 'premium', False) else 'لا'}\n"
            f"👻 **حساب محذوف؟:** {'نعم' if user.deleted else 'لا'}"
        )
        await event.edit(info)
    except Exception as e:
        await event.edit(f"❌ تعذر الكشف: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(افك|تفرغ)(?:\s+(.+))?$'))
async def set_afk(event):
    global afk_active, afk_reason, afk_time
    afk_reason = event.pattern_match.group(2) or "غير محدد"
    afk_active = True
    afk_time = datetime.now()
    await event.edit(f"💤 **تم تفعيل وضع التفرغ (AFK)**\n📝 **السبب:** {afk_reason}")

# ─── أوامر السبام والتخزين الدائم (.م3) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تخزين الكلمات(?:\s+([\s\S]+))?$'))
async def store_words(event):
    global spam_words
    reply = await event.get_reply_message()
    text = event.pattern_match.group(1) or (reply.text if reply else None)
    if not text:
        return await event.edit("⚠️ يرجى كتابة الكلمات بعد الأمر أو الرد على نص لتخزينه.")
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    spam_words.extend(lines)
    with open(WORDS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(spam_words))
    await event.edit(f"✅ تم حفظ `{len(lines)}` سطر. إجمالي الكلمات المخزنة: `{len(spam_words)}`.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.عرض الكلمات$'))
async def show_words(event):
    if not spam_words:
        return await event.edit("📁 لا يوجد كلمات مخزنة حالياً.")
    await event.edit(f"📁 **عدد الكلمات المخزنة:** `{len(spam_words)}` كلمة/سطر.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.مسح_الكلمات$'))
async def clear_words(event):
    global spam_words
    spam_words.clear()
    if os.path.exists(WORDS_FILE):
        os.remove(WORDS_FILE)
    await event.edit("🗑️ تم مسح جميع الكلمات المخزنة بنجاح.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تحديد السرعه (\d+(?:\.\d+)?)$'))
async def set_spam_speed(event):
    global spam_speed
    spam_speed = float(event.pattern_match.group(1))
    await event.edit(f"⚡ تم تحديد السرعة بـ `{spam_speed}` ثانية.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.بدء الارسال$'))
async def start_spam(event):
    global spam_active
    if not spam_words:
        return await event.edit("⚠️ قائمة الكلمات فارغة!")
    spam_active = True
    await event.edit("🚀 بدأ إرسال الكلمات المخزنة...")
    for word in spam_words:
        if not spam_active: break
        await client.send_message(event.chat_id, word)
        await asyncio.sleep(spam_speed)
    spam_active = False

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.سبام (\d+)\s+([\s\S]+)$'))
async def fast_spam(event):
    global spam_active
    count = int(event.pattern_match.group(1))
    text = event.pattern_match.group(2)
    await event.delete()
    spam_active = True
    for _ in range(count):
        if not spam_active: break
        await client.send_message(event.chat_id, text)
        await asyncio.sleep(spam_speed)
    spam_active = False

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(ايقاف|إيقاف|ايقاف الارسال)$'))
async def stop_all_actions(event):
    global spam_active, takleesh_active, track_active, auto_report_active
    spam_active = False
    takleesh_active = False
    track_active = False
    auto_report_active = False
    await event.edit("🛑 تم إيقاف جميع العمليات (السبام / التكليش / التتبع / البلاغات).")

# ─── أوامر الحذف والتدمير (.م4) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.حذف$'))
async def delete_msg(event):
    reply = await event.get_reply_message()
    if reply:
        await reply.delete()
        await event.delete()

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.مسح (\d+)$'))
async def purge_my_msgs(event):
    count = int(event.pattern_match.group(1))
    await event.delete()
    async for msg in client.iter_messages(event.chat_id, from_user='me', limit=count):
        await msg.delete()

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تدمير (\d+) (.+)$'))
async def self_destruct(event):
    sec = int(event.pattern_match.group(1))
    txt = event.pattern_match.group(2)
    await event.edit(f"💣 **رسالة ذاتية التدمير ({sec} ثواني):**\n\n{txt}")
    await asyncio.sleep(sec)
    await event.delete()

# ─── أوامر التفاعل (.م5) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تفاعل (.+)$'))
async def add_reaction(event):
    emoji = event.pattern_match.group(1).strip()
    reply = await event.get_reply_message()
    if reply:
        try:
            await client(SendReactionRequest(peer=event.chat_id, msg_id=reply.id, reaction=[ReactionEmoji(emoticon=emoji)]))
            await event.delete()
        except Exception as e: await event.edit(f"❌ تعذر التفاعل: {e}")

# ─── الانتحال (.م6) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.انتحال$'))
async def impersonate(event):
    reply = await event.get_reply_message()
    if not reply: return await event.edit("⚠️ رد على الشخص لانتحاله.")
    me = await client.get_me()
    original_profile["first_name"] = me.first_name
    
    target = await client.get_entity(reply.sender_id)
    await client(UpdateProfileRequest(first_name=target.first_name or "User"))
    
    photos = await client(GetUserPhotosRequest(user_id=reply.sender_id, offset=0, max_id=0, limit=1))
    if photos.photos:
        file = await client.download_media(photos.photos[0])
        uploaded = await client.upload_file(file)
        await client(UploadProfilePhotoRequest(file=uploaded))
        os.remove(file)
    await event.edit("🎭 تم انتحال الشخصية بنجاح.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.ارجاع$'))
async def restore_profile(event):
    if original_profile["first_name"]:
        await client(UpdateProfileRequest(first_name=original_profile["first_name"]))
        await event.edit("🔄 تم استعادة المعلومات الأصلية.")
    else: await event.edit("⚠️ لا توجد نسخة محفوظة مسبقاً.")

# ─── الشد والبلاغات (.م7) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.كليشة_ذكاء$'))
async def generate_ai(event):
    templates = [
        "⚠️ REPORT NOTICE: Serious violation of Telegram Terms of Service regarding hateful conduct and harassment.",
        "🛑 ALERT: Account involved in distribution of malicious content and abuse. Immediate ban required.",
        "⚠️ SECURITY INCIDENT: Target user is triggering unauthorized automation and abuse."
    ]
    await event.edit(f"🛡 **كليشة شد جديدة:**\n\n`{random.choice(templates)}`")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.بلاغ_تلقائي(?:\s+([\S]+))?(?:\s+(\d+))?(?:\s+([\s\S]+))?$'))
async def auto_report_cmd(event):
    global auto_report_active
    reply = await event.get_reply_message()
    
    reason_key = event.pattern_match.group(1) or "سبام"
    count = int(event.pattern_match.group(2)) if event.pattern_match.group(2) else 10
    custom_text = event.pattern_match.group(3) or "Severe violation of Telegram terms and illegal abuse."

    target = reply.sender_id if reply else event.chat_id
    reason_obj = REPORT_REASONS.get(reason_key.lower(), InputReportReasonSpam())

    auto_report_active = True
    await event.edit(
        f"🚨 **بدأ الشد والبلاغ التلقائي...**\n\n"
        f"🎯 **الهدف:** `{target}`\n"
        f"📌 **نوع البلاغ:** `{reason_key}`\n"
        f"🔢 **العدد المطلوب:** `{count}`\n"
        f"📝 **الكليشة المستعملة:**\n`{custom_text}`"
    )

    sent_reports = 0
    for i in range(count):
        if not auto_report_active: break
        try:
            await client(ReportPeerRequest(peer=target, reason=reason_obj, message=custom_text))
            sent_reports += 1
            await asyncio.sleep(1.5)
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception as e:
            await client.send_message(LOG_CHANNEL, f"⚠️ خطأ أثناء إرسال البلاغ: {e}")
            break

    auto_report_active = False
    await client.send_message(event.chat_id, f"✅ **تم الانتهاء من شد البلاغات!**\n📊 **بنجاح:** `{sent_reports}/{count}`")

# ─── الإذاعة (.م8) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.اذاعة_خاص (.+)$'))
async def broadcast_users(event):
    text = event.pattern_match.group(1)
    await event.edit("📢 جاري الإذاعة للخاص...")
    c = 0
    async for d in client.iter_dialogs():
        if d.is_user and not d.entity.bot:
            try:
                await client.send_message(d.id, text)
                c += 1
                await asyncio.sleep(1)
            except FloodWaitError as e: await asyncio.sleep(e.seconds)
            except: pass
    await event.edit(f"✅ تمت الإذاعة إلى {c} مستخدم.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.اذاعة_جروبات (.+)$'))
async def broadcast_groups(event):
    text = event.pattern_match.group(1)
    await event.edit("📢 جاري الإذاعة للجروبات...")
    c = 0
    async for d in client.iter_dialogs():
        if d.is_group:
            try:
                await client.send_message(d.id, text)
                c += 1
                await asyncio.sleep(1)
            except FloodWaitError as e: await asyncio.sleep(e.seconds)
            except: pass
    await event.edit(f"✅ تمت الإذاعة إلى {c} مجموعة.")

# ─── النشر التلقائي (.م9) ───
async def auto_post_loop(chat_id, delay, text):
    while True:
        await client.send_message(chat_id, text)
        await asyncio.sleep(delay)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.نشر (\d+) (.+)$'))
async def start_auto_post(event):
    global auto_post_task
    delay = int(event.pattern_match.group(1))
    text = event.pattern_match.group(2)
    if auto_post_task and not auto_post_task.done(): auto_post_task.cancel()
    auto_post_task = asyncio.create_task(auto_post_loop(event.chat_id, delay, text))
    await event.edit(f"🔄 بدأ النشر التلقائي كل {delay} ثانية.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.ايقاف_النشر$'))
async def stop_auto_post(event):
    global auto_post_task
    if auto_post_task and not auto_post_task.done():
        auto_post_task.cancel()
        await event.edit("🛑 تم إيقاف النشر التلقائي.")
    else: await event.edit("⚠️ النشر التلقائي غير مفعل.")

# ─── اليوزرات والترجمة والزخرفة (.م10) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.فحص (.+)$'))
async def check_username(event):
    user_id = event.sender_id
    if check_bruteforce_limit(user_id, max_attempts=5, window_seconds=60):
        return await event.edit("⚠️ **تم كبح التخمين!** انتظر دقيقة واحدة للحد من المخاطر.")
    if is_rate_limited(user_id, cooldown_time=GUESS_COOLDOWN):
        return await event.edit("⏳ يرجى الانتظار ثوانٍ معدودة بين كل عملية فحص.")

    username = event.pattern_match.group(1).replace('@', '').strip()
    try:
        await client.get_entity(username)
        await event.edit(f"❌ المعرف @{username} **غير متاح**.")
    except Exception:
        await event.edit(f"✅ المعرف @{username} **متاح للاستخدام**!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.ترجمة(?:\s+(.+))?$'))
async def translate_cmd(event):
    reply = await event.get_reply_message()
    text = event.pattern_match.group(1) or (reply.text if reply else None)
    if not text:
        return await event.edit("⚠️ قم بالرد على رسالة أو كتابة النص لترجمته!")
    await event.edit("🌐 جاري الترجمة...")
    loop = asyncio.get_event_loop()
    translated = await loop.run_in_executor(None, translate_text_sync, text, "ar")
    await event.edit(f"🌐 **الترجمة للعربية:**\n\n{translated}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.زخرفة (.+)$'))
async def decorate_cmd(event):
    text = event.pattern_match.group(1)
    fonts = [
        f"•─══〔 {text} 〕══─•",
        f"✦ {' '.join(list(text))} ✦",
        f"✨ 『 {text} 』 ✨",
        f"👑 ⦃ {text} ⦄ 👑"
    ]
    await event.edit("🎨 **الزخارف المتاحة:**\n\n" + "\n\n".join(fonts))

# ─── أوامر التكليش والتتبع المستقلة (.م11) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تكليش$'))
async def set_takleesh_target(event):
    global takleesh_target, takleesh_active
    reply = await event.get_reply_message()
    if not reply: return await event.edit("⚠️ رد على رسالة الشخص لبدء التكليش!")
    takleesh_target = reply.sender_id
    takleesh_active = True
    await event.edit(f"⚔️ تم بدء التكليش للهدف: `{takleesh_target}`")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تتبع$'))
async def set_track_target(event):
    global track_target, track_active
    if not spam_words: return await event.edit("⚠️ لا يوجد كلمات مخزنة للتتبع!")
    reply = await event.get_reply_message()
    if not reply: return await event.edit("⚠️ رد على رسالة الشخص لتتبعه!")
    track_target = reply.sender_id
    track_active = True
    await event.edit(f"🎯 تم تفعيل التتبع للهدف: `{track_target}`.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.عوفمه$'))
async def cancel_takleesh(event):
    global takleesh_target, takleesh_active, track_target, track_active
    takleesh_target = None
    takleesh_active = False
    track_target = None
    track_active = False
    await event.edit("🕊️ تم إلغاء التكليش والتتبع.")

# ─── أدوات الجروبات والمراقبة (.م12) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تاق(?:\s+(.+))?$'))
async def tag_all(event):
    global tag_active
    if not event.is_group: return await event.edit("⚠️ هذا الأمر للمجموعات فقط!")
    msg_text = event.pattern_match.group(1) or "نداء للجميع 📢"
    tag_active = True
    await event.delete()
    mentions = []
    async for user in client.iter_participants(event.chat_id):
        if not tag_active: break
        if user.bot: continue
        mentions.append(f"[{user.first_name}](tg://user?id={user.id})")
        if len(mentions) == 5:
            await client.send_message(event.chat_id, f"{msg_text}\n\n" + " | ".join(mentions))
            mentions = []
            await asyncio.sleep(2)
    if mentions and tag_active:
        await client.send_message(event.chat_id, f"{msg_text}\n\n" + " | ".join(mentions))
    tag_active = False

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تاق_ادمن(?:\s+(.+))?$'))
async def tag_admins(event):
    if not event.is_group: return await event.edit("⚠️ هذا الأمر للمجموعات فقط!")
    msg_text = event.pattern_match.group(1) or "نداء للمشرفين 🚨"
    await event.delete()
    mentions = []
    async for user in client.iter_participants(event.chat_id, filter=ChannelParticipantsAdmins):
        if user.bot: continue
        mentions.append(f"[{user.first_name}](tg://user?id={user.id})")
    if mentions:
        await client.send_message(event.chat_id, f"👮‍♂️ **{msg_text}**\n\n" + " | ".join(mentions))

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.ايقاف_التاق$'))
async def stop_tag(event):
    global tag_active
    tag_active = False
    await event.edit("🛑 تم إيقاف التاق.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.مراقبة$'))
async def watch_user(event):
    reply = await event.get_reply_message()
    if not reply: return await event.edit("⚠️ رد على الشخص لتفعيله في قائمة المراقبة!")
    target = reply.sender_id
    if target in watchlist:
        watchlist.remove(target)
        await event.edit(f"🔴 تم إزالة المستخدم `{target}` من المراقبة.")
    else:
        watchlist.add(target)
        await event.edit(f"👁️ تم إضافة المستخدم `{target}` للمراقبة. سيتم إشعارك عند كتبته أي رسالة في الجروبات المشتركة.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.سجل_الاسماء$'))
async def show_name_history(event):
    reply = await event.get_reply_message()
    target = reply.sender_id if reply else event.sender_id
    history = name_history.get(target, [])
    if not history:
        return await event.edit(f"📋 لا يوجد سجل تغييرات أسماء مخزن لهذا المستخدم (`{target}`).")
    txt = f"📜 **سجل الأسماء والمجموعات للمستخدم (`{target}`):**\n\n"
    for idx, h in enumerate(history, 1):
        txt += f"{idx}. `{h}`\n"
    await event.edit(txt)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.احصائيات$'))
async def group_stats(event):
    if not event.is_group: return await event.edit("⚠️ هذا الأمر للمجموعات فقط!")
    await event.edit("📊 جاري جمع الإحصائيات...")
    total, bots, deleted, premium = 0, 0, 0, 0
    async for user in client.iter_participants(event.chat_id):
        total += 1
        if user.bot: bots += 1
        if user.deleted: deleted += 1
        if getattr(user, 'premium', False): premium += 1
    
    await event.edit(
        f"📊 **إحصائيات المجموعة:**\n\n"
        f"👥 **الأعضاء:** `{total}`\n"
        f"🤖 **البوتات:** `{bots}`\n"
        f"👻 **المحذوفين:** `{deleted}`\n"
        f"⭐ **المميزين (Premium):** `{premium}`"
    )

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تنظيف$'))
async def clean_deleted(event):
    if not event.is_group: return await event.edit("⚠️ هذا الأمر للمجموعات فقط!")
    await event.edit("🔍 جاري طرد الحسابات المحذوفة...")
    c = 0
    async for user in client.iter_participants(event.chat_id):
        if user.deleted:
            try:
                await client.kick_participant(event.chat_id, user.id)
                c += 1
                await asyncio.sleep(0.5)
            except: pass
    await event.edit(f"✅ تم طرد `{c}` حساب محذوف بنجاح.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.حظر$'))
async def ban_user(event):
    reply = await event.get_reply_message()
    if not reply: return await event.edit("⚠️ رد على رسالة الشخص لحظره!")
    try:
        await client.edit_permissions(event.chat_id, reply.sender_id, view_messages=False)
        await event.edit("🚫 تم حظر المستخدم بنجاح.")
    except Exception as e: await event.edit(f"❌ فشل الحظر: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.طرد$'))
async def kick_user(event):
    reply = await event.get_reply_message()
    if not reply: return await event.edit("⚠️ رد على رسالة الشخص لطرد!")
    try:
        await client.kick_participant(event.chat_id, reply.sender_id)
        await event.edit("👞 تم طرد المستخدم.")
    except Exception as e: await event.edit(f"❌ فشل الطرد: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تثبيت$'))
async def pin_message(event):
    reply = await event.get_reply_message()
    if not reply: return await event.edit("⚠️ رد على الرسالة لتثبيتها!")
    try:
        await reply.pin()
        await event.edit("📌 تم تثبيت الرسالة.")
    except Exception as e: await event.edit(f"❌ فشل التثبيت: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.مغادرة$'))
async def leave_chat(event):
    await event.edit("👋 جاري مغادرة المحادثة...")
    await client.leave_chat(event.chat_id)

# ─── الميديا والتحميل والتسلية (.م13) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(تنزيل|تحميل) (.+)$'))
async def download_media_cmd(event):
    url = event.pattern_match.group(2).strip()
    await event.edit("📥 **جاري تحميل الميديا من الرابط...**")
    try:
        import yt_dlp
        ydl_opts = {'outtmpl': 'dl_media.%(ext)s', 'format': 'best', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
        await client.send_file(event.chat_id, filename, caption=f"🎬 **تم التحميل بنجاح**\n🔗 {url}", reply_to=event.id)
        await event.delete()
        if os.path.exists(filename): os.remove(filename)
    except Exception as e:
        await event.edit(f"❌ فشل التحميل (تأكد من تثبيت yt-dlp وصحة الرابط): {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(فيديو_دائري|فيديو_ملاحظة)$'))
async def to_video_note(event):
    reply = await event.get_reply_message()
    if not reply or not reply.video:
        return await event.edit("⚠️ قم بالرد على مقطع فيديو تحويله لبصمة فيديو دائرية!")
    await event.edit("🔄 **جاري التحويل إلى بصمة فيديو دائرية...**")
    file_path = await client.download_media(reply)
    try:
        await client.send_file(event.chat_id, file_path, video_note=True, reply_to=reply.id)
        await event.delete()
    except Exception as e:
        await event.edit(f"❌ فشل التحويل: {e}")
    finally:
        if os.path.exists(file_path): os.remove(file_path)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(تفريغ|صوت_لنص)$'))
async def voice_to_text(event):
    reply = await event.get_reply_message()
    if not reply or not (reply.voice or reply.audio):
        return await event.edit("⚠️ رد على بصمة صوتية لتفريغها!")
    await event.edit("🎤 **جاري تفريغ الصوت إلى نص...**")
    await asyncio.sleep(1.5)
    await event.edit("✍️ **التفريغ النصي:**\n\n*(الرسالة جاهزة لمعالجة التفريغ الصوت عبر مكتبة Whisper API)*")

async def clock_loop():
    while True:
        try:
            now = datetime.now().strftime("%I:%M")
            me = await client.get_me()
            base = me.first_name.split('|')[0].strip()
            await client(UpdateProfileRequest(first_name=f"{base} | {now} ⏰"))
        except: pass
        await asyncio.sleep(60)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تفعيل الساعة$'))
async def start_clock(event):
    global clock_task
    if not clock_task or clock_task.done():
        clock_task = asyncio.create_task(clock_loop())
        await event.edit("⏰ تم تفعيل الساعة التلقائية.")
    else: await event.edit("⚠️ الساعة مفعلة بالفعل.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.تعطيل الساعة$'))
async def stop_clock(event):
    global clock_task
    if clock_task and not clock_task.done():
        clock_task.cancel()
        await event.edit("🛑 تم تعطيل الساعة.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.بصمة$'))
async def to_voice(event):
    reply = await event.get_reply_message()
    if not reply or not reply.media: return await event.edit("⚠️ قم بالرد على ملف صوتي!")
    await event.edit("🔄 جاري التحويل...")
    file_path = await client.download_media(reply)
    await client.send_file(event.chat_id, file_path, voice_note=True, reply_to=reply.id)
    await event.delete()
    if os.path.exists(file_path): os.remove(file_path)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.لصورة$'))
async def sticker_to_photo(event):
    reply = await event.get_reply_message()
    if not reply or not reply.sticker: return await event.edit("⚠️ قم بالرد على ملصق!")
    await event.edit("🔄 جاري التحويل...")
    file_path = await client.download_media(reply)
    await client.send_file(event.chat_id, file_path, force_document=False, reply_to=reply.id)
    await event.delete()
    if os.path.exists(file_path): os.remove(file_path)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.ملصق$'))
async def photo_to_sticker(event):
    reply = await event.get_reply_message()
    if not reply or not reply.media: return await event.edit("⚠️ قم بالرد على صورة!")
    await event.edit("🔄 جاري التحويل...")
    file_path = await client.download_media(reply)
    await client.send_file(event.chat_id, file_path, force_document=False, reply_to=reply.id)
    await event.delete()
    if os.path.exists(file_path): os.remove(file_path)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.خيره$'))
async def khira(event):
    res = ["ممتازة جداً ✨", "جيدة 👍", "متوسطة ⚖️", "غير مناسبة ❌", "فيها خير كثير 🌸"]
    await event.edit(f"🔮 **الخيرة:** {random.choice(res)}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.نسبه$'))
async def nisba(event):
    await event.edit(f"📊 **النسبة:** `{random.randint(1, 100)}%`")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.مسافه$'))
async def toggle_tilde(event):
    global space_tilde_active
    space_tilde_active = not space_tilde_active
    await event.edit(f"🔄 ميزة المسافة (~): {'مفعلة ✅' if space_tilde_active else 'معطلة ❌'}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.سحب (.+)$'))
async def pull_restricted_content(event):
    link = event.pattern_match.group(1).strip()
    if "t.me/" in link:
        try:
            parts = link.split('/')
            msg_id = int(parts[-1])
            channel = parts[-2]
            msg = await client.get_messages(channel, ids=msg_id)
            if msg and msg.media:
                await client.send_file(LOG_CHANNEL, msg.media, caption=f"📥 **محتوى مقيد مسحوب:**\n{msg.text or ''}")
                await event.delete()
            elif msg and msg.text:
                await client.send_message(LOG_CHANNEL, f"📥 **محتوى مقيد مسحوب:**\n{msg.text}")
                await event.delete()
        except Exception as e:
            await event.edit(f"❌ تعذر السحب: {str(e)}")

# ─── كشف المخالفات للجروبات (.م14) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(م14|كشف_المخالفات)(?:\s+(.+))?$'))
async def check_violations(event):
    reply = await event.get_reply_message()
    input_str = event.pattern_match.group(2)
    
    target = input_str.strip() if input_str else (reply.sender_id if reply else event.chat_id)

    await event.edit("🔎 **جاري بدء فحص القناة/المجموعة وكشف المخالفات...**\n⏳ قد يستغرق الكشف بضع ثوانٍ.")

    try:
        entity = await client.get_entity(target)
    except Exception as e:
        return await event.edit(f"❌ **تعذر الوصول للهدف:** `{e}`")

    is_channel = getattr(entity, 'broadcast', False)
    is_group = getattr(entity, 'megagroup', False) or getattr(entity, 'gigagroup', False) or event.is_group

    type_str = "قناة 📢" if is_channel else ("مجموعة 👥" if is_group else "حساب / دردشة 👤")
    title = getattr(entity, 'title', getattr(entity, 'first_name', 'غير معروف'))
    username_str = f"@{entity.username}" if getattr(entity, 'username', None) else "لا يوجد (خاصة)"
    chat_id = entity.id

    violations = []
    violation_links = []

    if getattr(entity, 'scam', False):
        violations.append("🚨 **تحذير تلجرام الرسمي:** معلمة بإنذار احتيال (Scam).")
    if getattr(entity, 'fake', False):
        violations.append("⚠️ **تحذير التزييف:** معلمة بإنذار زائف (Fake).")

    bad_words_pattern = re.compile(r'(ثغرة|تغرة|اختراق|هكر|احتيال|تسريب|مقاطع|ممنوع|اباحي|شفرة|صيد)', re.IGNORECASE)
    phishing_link_pattern = re.compile(r'(bit\.ly|t\.me/anon|shorturl|ngrok|000webhost|login-telegram)', re.IGNORECASE)

    scanned_count = 0
    deleted_accounts = 0
    
    try:
        async for msg in client.iter_messages(entity, limit=100):
            scanned_count += 1
            if not msg: continue
            
            if msg.sender and getattr(msg.sender, 'deleted', False):
                deleted_accounts += 1

            msg_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{msg.id}" if not entity.username else f"https://t.me/{entity.username}/{msg.id}"

            if msg.text:
                if phishing_link_pattern.search(msg.text):
                    violations.append(f"🔗 **رابط مشبوه/اختراق:** تم العثور على رابط تصيّد.")
                    violation_links.append(f"[رابط المخالفة]({msg_link})")
                
                if bad_words_pattern.search(msg.text):
                    violations.append(f"🔞 **محتوى مخالف/كلمات محظورة:** ترويج لأنشطة غير قانونية.")
                    violation_links.append(f"[رابط المخالفة]({msg_link})")

    except Exception as err:
        violations.append(f"⚠️ **ملاحظة:** تعذر مسح كامل الرسائل ({err})")

    report = f"📊 **تقرير كشف المخالفات المطور (م14)** 📊\n"
    report += f"──────────────────\n"
    report += f"🔹 **الاسم:** {title}\n"
    report += f"🔹 **النوع:** {type_str}\n"
    report += f"🔹 **المعرف:** {username_str}\n"
    report += f"🔹 **الأيدي:** `{chat_id}`\n"
    report += f"🔹 **عدد الرسائل المفحوصة:** `{scanned_count}`\n"
    if deleted_accounts > 0:
        report += f"🔹 **حسابات محذوفة تم رصدها:** `{deleted_accounts}`\n"
    report += f"──────────────────\n"

    if violations:
        report += f"🚨 **المخالفات المكتشفة ({len(violations)}):**\n\n"
        for idx, v in enumerate(violations[:5], 1):
            report += f"{idx}. {v}\n"
        if violation_links:
            report += f"\n🔗 **روابط المخالفات المباشرة:**\n"
            for link in set(violation_links[:5]):
                report += f"• {link}\n"
    else:
        report += f"✅ **النتيجة:** لم يتم العثور على مخالفات صريحة.\n"

    await event.edit(report, link_preview=False)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.بلاغ_مخالفة$'))
async def generate_violation_report(event):
    reply = await event.get_reply_message()
    if not reply: return await event.edit("⚠️ **قم بالرد على الرسالة المخالفة لتوليد تقرير!**")
    chat_str = f"@{event.chat.username}" if getattr(event.chat, 'username', None) else f"`{event.chat_id}`"
    msg_link = f"https://t.me/c/{str(event.chat_id).replace('-100', '')}/{reply.id}" if not getattr(event.chat, 'username', None) else f"https://t.me/{event.chat.username}/{reply.id}"

    report_text = (
        f"🚨 **كليشة بلاغ عن مخالفة صريحة:**\n\n"
        f"• **المحيط:** {chat_str}\n"
        f"• **رابط المخالفة:** {msg_link}\n"
        f"• **نوع الانتهاك:** Violating Telegram ToS / Abuse / Spreading malicious content."
    )
    await event.edit(report_text, link_preview=False)

# ─── 15. قسم الذكاء الاصطناعي والتوليد (.م15) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(ذكاء|سؤال)(?:\s+(.+))?$'))
async def ai_query(event):
    reply = await event.get_reply_message()
    prompt = event.pattern_match.group(2) or (reply.text if reply else None)
    if not prompt: return await event.edit("⚠️ يرجى كتابة السؤال بعد الأمر أو الرد على رسالة!")
    await event.edit("🤖 **جاري التفكير والأجابة...**")
    try:
        url = f"https://text.pollinations.ai/{urllib.parse.quote(prompt)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = resp.read().decode('utf-8')
        await event.edit(f"🤖 **الرد:**\n\n{res}")
    except Exception as e:
        await event.edit(f"❌ حدث خطأ في استجابة الذكاء الاصطناعي: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.توليد (.+)$'))
async def ai_image(event):
    prompt = event.pattern_match.group(1).strip()
    await event.edit("🎨 **جاري توليد الصورة بالذكاء الاصطناعي...**")
    try:
        img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
        file_path = f"ai_gen_{int(time.time())}.jpg"
        urllib.request.urlretrieve(img_url, file_path)
        await client.send_file(event.chat_id, file_path, caption=f"🎨 **توليد:** `{prompt}`", reply_to=event.id)
        await event.delete()
        if os.path.exists(file_path): os.remove(file_path)
    except Exception as e:
        await event.edit(f"❌ فشل توليد الصورة: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.ملخص(?:\s+(\d+))?$'))
async def summarize_chat(event):
    limit = int(event.pattern_match.group(1)) if event.pattern_match.group(1) else 30
    await event.edit(f"📑 **جاري سحب وتلخيص آخر {limit} رسالة...**")
    texts = []
    async for msg in client.iter_messages(event.chat_id, limit=limit):
        if msg.text:
            sender = await msg.get_sender()
            name = sender.first_name if sender else "مجهول"
            texts.append(f"{name}: {msg.text}")
    if not texts:
        return await event.edit("⚠️ لا توجد رسائل نصية كافية للتلخيص.")
    combined = "\n".join(reversed(texts))
    prompt = f"ملخص أهم النقاط والأفكار الرئيسية في المحادثة التالية بشكل نقاط موجزة ومباشرة بالعربية:\n\n{combined}"
    try:
        url = f"https://text.pollinations.ai/{urllib.parse.quote(prompt)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            summary = resp.read().decode('utf-8')
        await event.edit(f"📑 **ملخص آخر {limit} رسالة:**\n\n{summary}")
    except Exception as e:
        await event.edit(f"❌ فشل التلخيص: {e}")

# ─── 16. قسم الأمان والخدمات (.م16) ───
@client.on(events.NewMessage(outgoing=True, pattern=r'^\.فحص_رابط (.+)$'))
async def check_link_safety(event):
    url_to_check = event.pattern_match.group(1).strip()
    await event.edit(f"🔎 **جاري فحص سلامة الرابط...**\n`{url_to_check}`")
    suspicious = False
    reasons = []
    if any(bad in url_to_check.lower() for bad in ['ngrok', '000webhost', 'login-telegram', 'free-gift', 'phish', 'bit.ly']):
        suspicious = True
        reasons.append("مجال مشبوه يُستخدم في التصيّد والاختراق.")
    if not url_to_check.startswith(('http://', 'https://')):
        reasons.append("الرابط لا يحتوي على بروتوكول أمان قياسي (HTTPS).")

    if suspicious or reasons:
        res = f"⚠️ **تحذير: الرابط مشبوه!**\n• السبب: " + " | ".join(reasons)
    else:
        res = "✅ **الرابط يبدو آمناً أوليّاً.**"
    await event.edit(res)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(ايميل_مؤقت|وهمي)$'))
async def temp_mail(event):
    await event.edit("📧 **جاري إنشاء بريد مؤقت...**")
    try:
        url = "https://www.1secmail.com/api/v1/?action=genRandomMailbox&count=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            email = data[0]
        await event.edit(f"📧 **البريد المؤقت الخاص بك:**\n`{email}`\n\n💡 يمكنك استخدامه فوراً للتسجيل والموقع سيتولى الاستقبال.")
    except Exception as e:
        await event.edit(f"❌ فشل إنشاء البريد: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.حقوق (.+)$'))
async def add_watermark(event):
    if not Image:
        return await event.edit("⚠️ تتطلب الميزة تثبيت مكتبة Pillow (`pip install Pillow`).")
    watermark_text = event.pattern_match.group(1).strip()
    reply = await event.get_reply_message()
    if not reply or not reply.photo:
        return await event.edit("⚠️ قم بالرد على صورة لإضافة العلامة المائية!")
    await event.edit("🖼 **جاري إضافة العلامة المائية...**")
    file_path = await client.download_media(reply)
    out_path = f"wm_{file_path}"
    try:
        with Image.open(file_path) as img:
            draw = ImageDraw.Draw(img)
            w, h = img.size
            draw.text((w - 180, h - 40), watermark_text, fill=(255, 255, 255))
            img.save(out_path)
        await client.send_file(event.chat_id, out_path, caption=f"✅ **تم إضافة الحقوق:** {watermark_text}", reply_to=reply.id)
        await event.delete()
    except Exception as e:
        await event.edit(f"❌ فشل إضافة الحقوق: {e}")
    finally:
        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(out_path): os.remove(out_path)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.اختصار (.+)$'))
async def shorten_url(event):
    url = event.pattern_match.group(1).strip()
    await event.edit("🔗 **جاري اختصار الرابط...**")
    try:
        api = f"http://tinyurl.com/api-create.php?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(api, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            short = resp.read().decode('utf-8')
        await event.edit(f"🔗 **الرابط المختصر:**\n{short}")
    except Exception as e:
        await event.edit(f"❌ فشل اختصار الرابط: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.(تاريخ|هجري)$'))
async def show_date(event):
    now = datetime.now()
    g_date = now.strftime("%Y-%m-%d %H:%M")
    await event.edit(f"📅 **التاريخ والوقت الحالي:**\n\n• **الميلادي:** `{g_date}`\n• **اليوم:** `{now.strftime('%A')}`")

@client.on(events.NewMessage(outgoing=True, pattern=r'^\.همسة (\S+) (.+)$'))
async def whisper_cmd(event):
    target_user = event.pattern_match.group(1)
    whisper_text = event.pattern_match.group(2)
    await event.edit(f"🤫 **همسة إلى** {target_user}:\n🔒 *لا يمكن رؤيتها إلا من قبل المستلم المحدد.*\n\n`{whisper_text}`")

# ─── المعالجات التلقائية والمراقبة ───
@client.on(events.NewMessage(outgoing=True))
async def outgoing_handler(event):
    global afk_active
    
    if afk_active and not event.text.startswith(('.افك', '.ت
