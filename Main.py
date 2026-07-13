import discord
from discord.ext import commands
import asyncio
from groq import Groq
import json
import os
import random
import logging
import traceback
import aiohttp
from keep_alive import keep_alive

# ================= الإعدادات =================
TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

GUILD_ID = 1524146300583546991
APPLY_CHANNEL_ID = 1524362996682330250
LOG_CHANNEL_ID = 1524146309940904022
STAFF_ROLE_ID = 1524373417137016833
ACCEPTED_ROLE_ID = 1524374959751827466

# 🆔 آيدي الرتبة المراد إزالتها تلقائياً عند القبول:
UNACCEPTED_ROLE_ID = 1524374666435887104  

USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")
# ================================================

# ─── تسجيل الأخطاء (Logging) ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("bot")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
groq_client = Groq(api_key=GROQ_API_KEY)

active_applicants: set[int] = set()

OATH_TEXT = (
    "اقسم بالله العظيم انا (اسمك) أن التزم بجميع قوانين السيرفر و أن لا اخرب أثناء الرول بلاي "
    "و أن احترم الاعضاء جميعا و أن احترم جميع أعضاء الإدارة"
)

# 🔄 ترتيب الأسئلة الجديد:
QUESTIONS = [
    "اسمك روبلوكس (الأساسي)؟",
    "اسمك روبلوكس (الغير أساسي)؟",
    "كم عمرك？",
    "📸 يرجى إرسال لقطة شاشة (صورة) لحسابك في روبلوكس يظهر فيها اسم الحساب بوضوح:",
    "هل تتعهد بالالتزام الكامل بقوانين السيرفر؟",
    f"اكتب القسم التالي بالكامل واستبدل (اسمك) باسمك الحقيقي، ثم أرسله كرسالة:\n\n\"{OATH_TEXT}\""
]

SYSTEM_PROMPT = """أنت مسؤول تقييم طلبات انضمام لسيرفر رول بلاي على روبلوكس ومحلل صور متقدم.

ستستلم المعلومات التالية:
- اسم الحساب الأساسي المكتوب: (تم التحقق منه)
- اسم الحساب الغير أساسي المكتوب: (تم التحقق منه)
- عمر المتقدم
- رابط صورة لقطة الشاشة المرفقة للحساب الشخصي
- تعهده بالالتزام بالقوانين
- نص حلف التصريح

معايير التقييم الصارمة:
1. العمر: يجب أن يكون رقماً منطقياً بين 8 و 99.
2. مطابقة الصورة: يجب عليك تحليل النص والرؤية داخل الصورة المرفقة. تأكد تماماً أن اسم المستخدم الظاهر في الصورة (Username أو Display Name) يطابق إما "اسم الحساب الأساسي" أو "اسم الحساب الغير أساسي" الذي أدخله المتقدم. إذا كانت الصورة عشوائية، لا تحتوي على حساب روبلوكس، أو الأسماء فيها مختلفة تماماً ولا صلة لها بالأسماء المكتوبة، ارفض الطلب فوراً.
3. التعهد: يجب أن يكون صريحاً وإيجابياً.
4. حلف التصريح: يجب استبدال (اسمك) باسم حقيقي واضح والالتزام بالنص الأساسي.

رد فقط بصيغة JSON بدون أي نص إضافي، بهذا الشكل:
{"decision": "accept", "reason": "سبب مختصر بالعربي"}
أو
{"decision": "reject", "reason": "سبب مختصر بالعربي واضح لرفض الصورة أو الأجوبة"}"""


def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(data: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def generate_unique_id() -> str:
    users = load_users()
    existing = {v.get("rp_id") for v in users.values()}
    while True:
        new_id = str(random.randint(1000, 999999))
        if new_id not in existing:
            return new_id


async def check_roblox_username(username: str) -> tuple[bool, str]:
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username.strip()], "excludeBannedUsers": False}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("data", [])
                    if results:
                        return True, results[0].get("name", username)
                    return False, username
    except Exception:
        pass
    return False, username


def evaluate_with_ai(primary: str, secondary: str, age: str, image_url: str, pledge: str, oath: str) -> dict:
    content = [
        {
            "type": "text",
            "text": (
                f"الحساب الأساسي المكتوب: {primary}\n"
                f"الحساب الغير أساسي المكتوب: {secondary}\n"
                f"العمر: {age}\n"
                f"التعهد بالقوانين: {pledge}\n\n"
                f"نص القسم الرسمي: {OATH_TEXT}\n"
                f"حلف التصريح المكتوب: {oath}\n"
                f"يرجى مطابقة هذه البيانات مع الصورة المرفقة أدناه والتأكد من صحة الحساب والحلف والتعهد."
            )
        }
    ]
    
    if image_url:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": image_url
            }
        })

    response = groq_client.chat.completions.create(
        model="llama-3.2-90b-vision-preview",
        max_tokens=200,
        temperature=0.1,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}
        ]
    )
    text = response.choices[0].message.content.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"decision": "reject", "reason": "تعذر تقييم الطلب أو قراءة الصورة تلقائياً"}


class ApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تقديم طلب", style=discord.ButtonStyle.blurple,
                        emoji="📝", custom_id="apply_button")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id

        if user_id in active_applicants:
            return await interaction.response.send_message(
                "⚠️ عندك طلب تقديم شغال حالياً بالخاص، كمّل عليه أو انتظر انتهاء وقته.",
                ephemeral=True
            )

        active_applicants.add(user_id)
        try:
            await self._run_application(interaction)
        except Exception:
            logger.error(f"خطأ أثناء معالجة طلب المستخدم {user_id}:\n{traceback.format_exc()}")
            active_applicants.discard(user_id)

    async def _run_application(self, interaction: discord.Interaction):
        try:
            dm = await interaction.user.create_dm()
            
            welcome_embed = discord.Embed(
                title="👋 مرحباً بكِ في التقديم!",
                description="الرجاء الإجابة على الأسئلة التالية لتتم مراجعة طلبكِ.\n\n"
                            "⚠️ **شروط التقديم:**\n"
                            "• كل سؤال يجب الرد عليه برسالة منفصلة.\n"
                            "• أحد الأسئلة يتطلب رفع صورة (لقطة شاشة) لحسابك.\n"
                            "• عندك **5 دقائق** فقط للرد على كل سؤال قبل إلغاء الطلب.",
                color=0x3498db
            )
            await dm.send(embed=welcome_embed)
            
            image_style_embed = discord.Embed(
                title="بدء تقديم الطلب",
                description="تم إرسال أسئلة التقديم بنجاح إلى رسائلك الخاصة!",
                color=0x2ecc71 
            )
            
            jump_view = discord.ui.View()
            jump_view.add_item(discord.ui.Button(
                label="الانتقال إلى الخاص", 
                url="https://discord.com/channels/@me", 
                style=discord.ButtonStyle.link
            ))
            
            await interaction.response.send_message(embed=image_style_embed, view=jump_view, ephemeral=True)
            
        except discord.Forbidden:
            active_applicants.discard(interaction.user.id)
            error_embed = discord.Embed(
                title="الرسائل الخاصة مغلقة",
                description="يرجى فتح الرسائل الخاصة (DMs) in إعدادات خصوصية السيرفر لتتمكن من استلام الأسئلة.",
                color=discord.Color.red()
            )
            try: await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except: pass
            return

        asyncio.create_task(self._collect_answers(interaction, dm))

    async def _collect_answers(self, interaction: discord.Interaction, dm: discord.DMChannel):
        answers = []
        image_url = None
        
        def check(m):
            return m.author.id == interaction.user.id and isinstance(m.channel, discord.DMChannel)

        try:
            for idx, q in enumerate(QUESTIONS, start=1):
                question_embed = discord.Embed(
                    title=f"❓ السؤال {idx} من أصل {len(QUESTIONS)}",
                    description=f"**{q}**",
                    color=0x3498db
                )
                question_embed.set_footer(text="⏱️ متبقي لديكِ 5 دقائق للرد...")
                await dm.send(embed=question_embed)
                
                try:
                    msg = await bot.wait_for("message", check=check, timeout=300)
                    
                    # الفحص بناءً على رقم السؤال الجديد (السؤال الرابع هو الصورة 📸)
                    if idx == 4:
                        if msg.attachments:
                            image_url = msg.attachments[0].url
                            answers.append("[تم إرفاق صورة الحساب]")
                        else:
                            await dm.send("⚠️ يرجى إرسال ملف صورة (لقطة شاشة) وليس نصاً مكتوباً.")
                            # إعادة تشغيل تجميع الأجوبة من جديد لتفادي التداخل
                            active_applicants.discard(interaction.user.id)
                            return
                    else:
                        answers.append(msg.content.strip())
                        
                except asyncio.TimeoutError:
                    timeout_embed = discord.Embed(
                        title="⏳ انتهى الوقت!",
                        description="للأسف استغرقتِ وقتاً طويلاً للرد. اضغطي على زر التقديم مجدداً في السيرفر للمحاولة مرة أخرى.",
                        color=discord.Color.red()
                    )
                    await dm.send(embed=timeout_embed)
                    return

            checking_embed = discord.Embed(
                title="🔍 جاري المعالجة والمطابقة...",
                description="يتم الآن التحقق من الحسابات بالذكاء الاصطناعي ومطابقة الصورة، يرجى الانتظار...",
                color=discord.Color.orange()
            )
            await dm.send(embed=checking_embed)

            try:
                primary_ok, primary_name = await check_roblox_username(answers[0])
                secondary_ok, secondary_name = await check_roblox_username(answers[1])
            except Exception:
                logger.error(f"خطأ أثناء التحقق من روبلوكس:\n{traceback.format_exc()}")
                await dm.send("⚠️ صار خطأ أثناء التحقق من حساباتك على روبلوكس، حاول مرة ثانية لاحقاً.")
                return

            if not primary_ok:
                await dm.send(f"❌ لم نتمكن من إيجاد حساب روبلوكس باسم **{answers[0]}**.\nتأكد من صحة الاسم وأعد المحاولة.")
                _send_log(interaction, answers, "reject", f"الحساب الأساسي '{answers[0]}' غير موجود على روبلوكس", primary_name, secondary_name, None, image_url)
                return

            if not secondary_ok:
                await dm.send(f"❌ لم نتمكن من إيجاد حساب روبلوكس باسم **{answers[1]}**.\nتأكد من صحة الاسم وأعد المحاولة.")
                _send_log(interaction, answers, "reject", f"الحساب الغير أساسي '{answers[1]}' غير موجود على روبلوكس", primary_name, secondary_name, None, image_url)
                return

            try:
                # الترتيب الجديد لتمرير الأجوبة للـ AI: (العمر هو الترتيب 2، الصورة هي image_url، التعهد هو الترتيب 3، الحلف هو الترتيب 4)
                result = evaluate_with_ai(primary_name, secondary_name, answers[2], image_url, answers[3], answers[4])
            except Exception:
                logger.error(f"خطأ أثناء تقييم AI:\n{traceback.format_exc()}")
                await dm.send("⚠️ صار خطأ أثناء تقييم طلبك بالذكاء الاصطناعي، تواصل مع الإدارة.")
                _send_log(interaction, answers, "reject", "خطأ تقني أثناء تقييم ومطابقة البيانات بـ AI", primary_name, secondary_name, None, image_url)
                return

            decision = result.get("decision", "reject")
            reason = result.get("reason", "بدون سبب")

            member = interaction.guild.get_member(interaction.user.id)
            rp_id = None

            if decision == "accept":
                rp_id = generate_unique_id()

                role = interaction.guild.get_role(ACCEPTED_ROLE_ID)
                if role and member:
                    try: await member.add_roles(role)
                    except: pass

                unaccepted_role = interaction.guild.get_role(UNACCEPTED_ROLE_ID)
                if unaccepted_role and member:
                    try: await member.remove_roles(unaccepted_role)
                    except: pass

                if member:
                    try: await member.edit(nick=f"RC | {primary_name} | {rp_id}")
                    except: pass

                users = load_users()
                users[str(interaction.user.id)] = {
                    "discord_tag": str(interaction.user),
                    "roblox_primary": primary_name,
                    "roblox_secondary": secondary_name,
                    "rp_id": rp_id
                }
                save_users(users)

                accept_embed = discord.Embed(
                    title="🎉 مبارك! تم قبول طلبكِ",
                    description=f"**السبب:** {reason}\n\n🆔 **رقم هويتكِ في الرول بلاي:** `{rp_id}`\nيرجى حفظ هذا الرقم جيداً لأنه سيُطلب منكِ داخل السيرفر.",
                    color=discord.Color.green()
                )
                await dm.send(embed=accept_embed)
            else:
                reject_embed = discord.Embed(
                    title="❌ نعتذر، تم رفض طلبكِ",
                    description=f"**السبب:** {reason}\n\nيمكنكِ إعادة التقديم لاحقاً والتأكد من شروط الإجابة ومطابقة لقطة الشاشة المرفقة.",
                    color=discord.Color.red()
                )
                await dm.send(embed=reject_embed)

            await _send_log_async(interaction, answers, decision, reason, primary_name, secondary_name, rp_id, image_url)

        except Exception:
            logger.error(f"خطأ أثناء جمع الأجوبة:\n{traceback.format_exc()}")
        finally:
            active_applicants.discard(interaction.user.id)


def _send_log(interaction, answers, decision, reason, primary, secondary, rp_id, image_url):
    asyncio.create_task(_send_log_async(interaction, answers, decision, reason, primary, secondary, rp_id, image_url))


async def _send_log_async(interaction, answers, decision, reason, primary, secondary, rp_id, image_url):
    color = discord.Color.green() if decision == "accept" else discord.Color.red()
    embed = discord.Embed(title="📋 طلب رول بلاي — تقييم AI والصورة", color=color)
    embed.add_field(name="العضو", value=interaction.user.mention, inline=False)
    embed.add_field(name="حساب أساسي", value=f"`{primary}`", inline=True)
    embed.add_field(name="حساب غير أساسي", value=f"`{secondary}`", inline=True)
    embed.add_field(name="العمر", value=answers[2] if len(answers) > 2 else "غير معروف", inline=True)
    
    # جلب التعهد والحلف بناءً على ترتيب الفهارس الجديد في مصفوفة الإجابات
    pledge_val = answers[3][:500] if len(answers) > 3 else "غير معروف"
    oath_val = answers[4][:800] if len(answers) > 4 else "غير معروف"
    
    embed.add_field(name="التعهد", value=pledge_val, inline=False)
    embed.add_field(name="حلف التصريح", value=oath_val, inline=False)
    
    embed.add_field(name="قرار البوت", value="✅ قبول" if decision == "accept" else "❌ رفض", inline=True)
    embed.add_field(name="السبب", value=reason, inline=True)
    if rp_id:
        embed.add_field(name="🆔 رقم الهوية", value=f"`{rp_id}`", inline=True)
    
    if image_url:
        embed.set_image(url=image_url)
        
    embed.set_footer(text=f"Discord ID: {interaction.user.id}")

    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        view = RevokeView(interaction.user.id) if decision == "accept" else None
        await log_channel.send(embed=embed, view=view)


class RevokeView(discord.ui.View):
    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    @discord.ui.button(label="إزالة القبول", style=discord.ButtonStyle.red, emoji="🚫")
    async def revoke(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles:
            return await interaction.response.send_message("ما تملك صلاحية.", ephemeral=True)

        member = interaction.guild.get_member(self.applicant_id)
        role = interaction.guild.get_role(ACCEPTED_ROLE_ID)
        if member and role and role in member.roles:
            await member.remove_roles(role)
            try: await member.send("⚠️ تم سحب رتبة الرول بلاي منك بواسطة الإدارة.")
            except: pass

        users = load_users()
        if str(self.applicant_id) in users:
            del users[str(self.applicant_id)]
            save_users(users)

        button.disabled = True
        button.label = "تم السحب"
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"تم سحب القبول بواسطة {interaction.user.mention}", ephemeral=False)


@bot.command()
@commands.has_permissions(administrator=True)
async def setup_apply(ctx):
    embed = discord.Embed(
        title="📝 تقديم طلب رول بلاي",
        description="اضغط الزر بالأسفل وجاوب على الأسئلة اللي توصلك بالخاص.",
        color=discord.Color.blurple()
    )
    channel = bot.get_channel(APPLY_CHANNEL_ID)
    await channel.send(embed=embed, view=ApplyView())
    await ctx.send("✅ تم إرسال رسالة التقديم.")


@bot.event
async def on_ready():
    bot.add_view(ApplyView())
    await bot.change_presence(status=discord.Status.online, activity=discord.CustomActivity(name="Distributing"))
    logger.info(f"✅ البوت شغال باسم {bot.user}")


@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"خطأ غير متوقع بالحدث '{event}':\n{traceback.format_exc()}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions): return await ctx.send("❌ ما تملك صلاحية تنفيذ هذا الأمر.")
    if isinstance(error, commands.CommandNotFound): return
    logger.error(f"خطأ بأمر '{ctx.command}':\n{''.join(traceback.format_exception(type(error), error, error.__traceback__))}")
    await ctx.send("⚠️ صار خطأ أثناء تنفيذ الأمر، تم تسجيله للمراجعة.")


def run_bot():
    keep_alive()
    while True:
        try:
            bot.run(TOKEN, log_handler=None)
        except discord.errors.LoginFailure:
            logger.error("❌ التوكن غير صالح (Improper token). تأكد من قيمة BOT_TOKEN وأعد التشغيل.")
            break
        except Exception:
            logger.error(f"⚠️ توقف البوت بسبب خطأ غير متوقع:\n{traceback.format_exc()}")
            logger.info("🔄 إعادة تشغيل البوت خلال 5 ثوانٍ...")
            import time
            time.sleep(5)
            continue
        else: break

run_bot()
        
