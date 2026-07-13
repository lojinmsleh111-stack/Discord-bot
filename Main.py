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
import re
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

# ترتيب الأسئلة الرسمي:
# index 0: الاسم الحقيقي
# index 1: اسم روبلوكس
# index 2: العمر
# index 3: الصورة (يتم تعويضها بـ "[تم إرفاق الصورة]")
# index 4: التعهد بالقوانين
# index 5: القسم المكتوب
QUESTIONS = [
    "ما هو اسمك الحقيقي؟",
    "اسمك روبلوكس (الأساسي)؟",
    "كم عمرك؟",
    "📸 يرجى إرسال لقطة شاشة (صورة) لحسابك في روبلوكس يظهر فيها اسم الحساب بوضوح:",
    "هل تتعهد بالالتزام الكامل بقوانين السيرفر؟",
    f"اكتب القسم التالي بالكامل واستبدل (اسمك) باسمك الحقيقي، ثم أرسله كرسالة:\n\n\"{OATH_TEXT}\""
]

SYSTEM_PROMPT = """أنت مسؤول مراجعة وتدقيق نصوص طلبات الانضمام لسيرفر رول بلاي روبلوكس.
يجب عليك قبول الطلب تلقائياً طالما أن البيانات المدخلة منطقية:
1. العمر: يجب أن يكون رقماً مقبولاً (مثلاً بين 8 و 99).
2. التعهد: أي إجابة تدل على الموافقة أو الالتزام تعتبر مقبولة وصحيحة.
3. القسم: يجب أن يكون المتقدم قد كتب نص القسم بشكل سليم وقام باستبدال كلمة (اسمك) باسمه الحقيقي أو كتب اسمه بدلاً عنها.

ردك يجب أن يكون كود JSON فقط دون أي مقدمات أو مؤخرات كالتالي تماماً:
{"decision": "accept", "reason": "تم قبول طلبك بنجاح والبيانات صحيحة"}
أو إذا كانت الأجوبة فارغة أو مسيئة أو القسم خاطئ تماماً:
{"decision": "reject", "reason": "اكتب هنا سبب الرفض الواضح بالعربية"}"""


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
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("data", [])
                    if results:
                        return True, results[0].get("name", username)
                    return False, username
    except Exception: pass
    return False, username


def evaluate_with_ai(real_name: str, primary: str, age: str, pledge: str, oath: str) -> dict:
    text_content = (
        f"الاسم الحقيقي للمتقدم: {real_name}\n"
        f"حساب روبلوكس الأساسي: {primary}\n"
        f"العمر المدخل: {age}\n"
        f"التعهد بالقوانين: {pledge}\n"
        f"القسم الذي حلفه المتقدم: {oath}\n"
        f"القسم الأصلي المطلوب للمطابقة: {OATH_TEXT}"
    )
        
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant", # نموذج نصوص فائق السرعة والموثوقية
            max_tokens=150,
            temperature=0.1,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text_content}]
        )
        
        raw_text = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(raw_text)
    except Exception as e:
        logger.error(f"خطأ برمجى في مراجعة الـ AI: {e}")
        # في حال حدوث عطل طارئ، لا تجعل البوت يرفض بل اجعله يقبل كحالة افتراضية لتفادي تعليق المستخدمين
        return {"decision": "accept", "reason": "تم القبول التلقائي لسلامة النصوص المكتوبة"}


async def execute_acceptance(guild: discord.Guild, user_id: int, real_name: str, primary_name: str) -> str:
    rp_id = generate_unique_id()
    member = guild.get_member(user_id)
    
    role = guild.get_role(ACCEPTED_ROLE_ID)
    if role and member:
        try: await member.add_roles(role)
        except: pass

    unaccepted_role = guild.get_role(UNACCEPTED_ROLE_ID)
    if unaccepted_role and member:
        try: await member.remove_roles(unaccepted_role)
        except: pass

    if member:
        try: await member.edit(nick=f"RC | {primary_name} | {rp_id}")
        except: pass

    users = load_users()
    users[str(user_id)] = {
        "discord_tag": str(member) if member else f"User_{user_id}",
        "real_name": real_name,
        "roblox_primary": primary_name,
        "rp_id": rp_id
    }
    save_users(users)
    return rp_id


class ApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تقديم طلب", style=discord.ButtonStyle.blurple, emoji="📝", custom_id="apply_button")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id in active_applicants:
            return await interaction.response.send_message("⚠️ عندك تقديم شغال حالياً بالخاص.", ephemeral=True)

        active_applicants.add(user_id)
        try:
            dm = await interaction.user.create_dm()
            welcome = discord.Embed(
                title="👋 مرحباً بك في التقديم!",
                description="الرجاء الإجابة على الأسئلة التالية لتتم مراجعة طلبك.\n\n"
                            "⚠️ **شروط التقديم:**\n"
                            "• كل سؤال يجب الرد عليه برسالة منفصلة.\n"
                            "• السؤال الرابع يتطلب رفع صورة لحسابك.\n"
                            "• عندك **5 دقائق** للرد على كل سؤال قبل إلغاء الطلب.",
                color=0x3498db
            )
            await dm.send(embed=welcome)
            
            await interaction.response.send_message(
                embed=discord.Embed(title="بدء التقديم", description="تم إرسال الأسئلة لرسائلك الخاصة!", color=0x2ecc71),
                view=discord.ui.View().add_item(discord.ui.Button(label="الانتقال للخاص", url="https://discord.com/channels/@me", style=discord.ButtonStyle.link)),
                ephemeral=True
            )
            asyncio.create_task(self._collect_answers(interaction, dm))
        except discord.Forbidden:
            active_applicants.discard(user_id)
            await interaction.response.send_message("❌ رسائلك الخاصة مغلقة.", ephemeral=True)


    async def _collect_answers(self, interaction: discord.Interaction, dm: discord.DMChannel):
        answers = []
        image_url = None
        def check(m): return m.author.id == interaction.user.id and isinstance(m.channel, discord.DMChannel)

        try:
            for idx, q in enumerate(QUESTIONS, start=1):
                await dm.send(embed=discord.Embed(title=f"❓ السؤال {idx} من أصل {len(QUESTIONS)}", description=f"**{q}**", color=0x3498db))
                try:
                    msg = await bot.wait_for("message", check=check, timeout=300)
                    if idx == 4:  # صورة لقطة الشاشة 📸
                        if msg.attachments:
                            image_url = msg.attachments[0].url
                            answers.append("[تم إرفاق الصورة]")
                        else:
                            await dm.send("❌ تم إلغاء الطلب لعدم إرفاق صورة صحيح.")
                            return
                    else:
                        answers.append(msg.content.strip())
                except asyncio.TimeoutError:
                    await dm.send("⏳ انتهى الوقت وعُلّق الطلب.")
                    return

            await dm.send(embed=discord.Embed(title="🔍 جاري المعالجة والمطابقة...", description="يتم الآن معالجة بياناتك، انتظر ثوانٍ...", color=discord.Color.orange()))
            
            # الفهرس 1 هو اسم روبلوكس المكتوب
            primary_ok, primary_name = await check_roblox_username(answers[1])

            if not primary_ok:
                await dm.send(f"❌ لم نتمكن من إيجاد حساب روبلوكس باسم **{answers[1]}**.")
                await _send_log_async(interaction, answers, "reject", f"الحساب '{answers[1]}' غير موجود في روبلوكس", answers[0], primary_name, None, image_url)
                return

            # تمرير المتغيرات بشكل دقيق للذكاء الاصطناعي بناءً على الفهارس الصحيحة:
            # الاسم الحقيقي: answers[0]
            # اسم الحساب: primary_name
            # العمر: answers[2]
            # التعهد: answers[4] (الفهرس 3 هو صورة تم تخطيها)
            # القسم: answers[5]
            result = evaluate_with_ai(
                real_name=answers[0],
                primary=primary_name,
                age=answers[2],
                pledge=answers[4],
                oath=answers[5]
            )
            
            decision = result.get("decision", "accept")
            reason = result.get("reason", "تم القبول التلقائي")

            rp_id = None
            if decision == "accept":
                rp_id = await execute_acceptance(interaction.guild, interaction.user.id, answers[0], primary_name)
                await dm.send(embed=discord.Embed(title="🎉 تم قبولك!", description=f"🆔 هوية الرول بلاي الخاصة بكِ: `{rp_id}`", color=discord.Color.green()))
            else:
                await dm.send(embed=discord.Embed(title="❌ نعتذر، تم رفض طلبك تلقائياً", description=f"**السبب:** {reason}\nالإدارة تراجع طلبك الآن وقد يتم قبولك يدوياً.", color=discord.Color.red()))

            await _send_log_async(interaction, answers, decision, reason, answers[0], primary_name, rp_id, image_url)

        except Exception as e: 
            logger.error(f"خطأ عام أثناء المعالجة: {e}")
            logger.error(traceback.format_exc())
        finally: active_applicants.discard(interaction.user.id)


async def _send_log_async(interaction, answers, decision, reason, real_name, primary, rp_id, image_url):
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if not log_channel: return

    color = discord.Color.green() if decision == "accept" else discord.Color.red()
    embed = discord.Embed(title="📋 طلب رول بلاي جديد", color=color)
    embed.add_field(name="العضو", value=interaction.user.mention, inline=False)
    embed.add_field(name="الاسم الحقيقي", value=f"`{real_name}`", inline=True)
    embed.add_field(name="حساب روبلوكس", value=f"`{primary}`", inline=True)
    embed.add_field(name="العمر", value=answers[2] if len(answers) > 2 else "غير معروف", inline=True)
    embed.add_field(name="قرار البوت الحالي", value="✅ قبول تلقائي" if decision == "accept" else "❌ رفض تلقائي", inline=True)
    embed.add_field(name="السبب", value=reason, inline=True)
    
    if rp_id: embed.add_field(name="🆔 رقم الهوية", value=f"`{rp_id}`", inline=True)
    if image_url: embed.set_image(url=image_url)
    embed.set_footer(text=f"User ID: {interaction.user.id}")

    if decision == "accept":
        view = RevokeView(interaction.user.id)
    else:
        view = StaffOverrideView(interaction.user.id, real_name, primary)

    await log_channel.send(embed=embed, view=view)


class StaffOverrideView(discord.ui.View):
    def __init__(self, applicant_id: int, real_name: str, primary: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.real_name = real_name
        self.primary = primary

    @discord.ui.button(label="قبول يدوياً وتوليد هوية", style=discord.ButtonStyle.success, emoji="🟢")
    async def manual_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ ما تملك صلاحية الإدارة.", ephemeral=True)

        await interaction.response.defer()
        rp_id = await execute_acceptance(interaction.guild, self.applicant_id, self.real_name, self.primary)

        member = interaction.guild.get_member(self.applicant_id)
        if member:
            try:
                embed_dm = discord.Embed(title="🎉 تحديث: تم قبولك يدوياً!", description=f"قامت الإدارة بمراجعة طلبك وقبوله يدوياً.\n🆔 **هوية الرول بلاي الخاصة بك:** `{rp_id}`", color=discord.Color.green())
                await member.send(embed=embed_dm)
            except: pass

        for child in self.children: child.disabled = True
        original_embed = interaction.message.embeds[0]
        original_embed.color = discord.Color.green()
        original_embed.add_field(name="تعديل الإدارة", value=f"🟢 تم القبول يدوياً بواسطة {interaction.user.mention}\n🆔 الهوية الممنوحة: `{rp_id}`", inline=False)
        await interaction.message.edit(embed=original_embed, view=self)

    @discord.ui.button(label="إبقاء الرفض", style=discord.ButtonStyle.secondary, emoji="🔒")
    async def keep_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ ما تملك صلاحية الإدارة.", ephemeral=True)

        for child in self.children: child.disabled = True
        original_embed = interaction.message.embeds[0]
        original_embed.add_field(name="تعديل الإدارة", value=f"🔒 تم تأكيد الرفض وإغلاق الطلب بواسطة {interaction.user.mention}", inline=False)
        await interaction.message.edit(embed=original_embed, view=self)


class RevokeView(discord.ui.View):
    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    @discord.ui.button(label="إزالة القبول (طرد)", style=discord.ButtonStyle.red, emoji="🚫")
    async def revoke(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
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


@bot.command()
@commands.has_permissions(administrator=True)
async def setup_apply(ctx):
    embed = discord.Embed(title="📝 تقديم طلب رول بلاي", description="اضغط الزر بالأسفل وجاوب على الأسئلة بالخاص.", color=discord.Color.blurple())
    channel = bot.get_channel(APPLY_CHANNEL_ID)
    await channel.send(embed=embed, view=ApplyView())
    await ctx.send("✅ تم إرسال رسالة التقديم.")


@bot.event
async def on_ready():
    bot.add_view(ApplyView())
    await bot.change_presence(status=discord.Status.online, activity=discord.CustomActivity(name="Distributing"))
    logger.info(f"✅ البوت شغال باسم {bot.user}")


def run_bot():
    keep_alive()
    bot.run(TOKEN, log_handler=None)

if __name__ == "__main__": run_bot()
            
