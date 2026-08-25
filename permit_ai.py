import os
import random
import asyncio

import aiohttp
import discord
from discord.ext import commands

# =========================================================
# CONFIG
# =========================================================

ADMIN_ROLE_ID = 1524146300906508326
LOG_CHANNEL_ID = 1524146309940904022
APPROVED_ROLE_ID = 1524374959751827466
REMOVE_ROLE_ID = 1524374666435887104

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

APPLICATION_TIMEOUT = 600

OATH_TEXT = (
    "اقسم بالله العظيم انا (فلان بن فلان) اني ماراح اخرب سمعت سيرفر "
    "ولا اتمشكل مع الاداره ولا مع المواطنين ولا اخرب سيرفر ولا "
    "اتعبث بسيرفر ولا اسب الاداره او المواطنين والله علو ماقوله شهيد"
)

QUESTIONS = [
    ("real_name", "اسمك الحقيقي :"),
    ("real_age", "عمرك الحقيقي :"),
    ("roblox_name", "اسم حسابك الأساسي :"),
    ("account_short", "اختصار حسابك :"),
]

SOURCE_OPTIONS = [
    "خويك",
    "تيك توك",
    "إعلانات أو شراكات",
]

_bot = None


# =========================================================
# HELPERS
# =========================================================

def is_admin(member):
    return (
        isinstance(member, discord.Member)
        and any(role.id == ADMIN_ROLE_ID for role in member.roles)
    )


async def ask_text(user, question):
    try:
        await user.send(question)
    except discord.Forbidden:
        return None

    def check(message):
        return (
            message.author.id == user.id
            and isinstance(message.channel, discord.DMChannel)
        )

    try:
        message = await _bot.wait_for(
            "message",
            timeout=APPLICATION_TIMEOUT,
            check=check,
        )
        return message.content.strip()
    except asyncio.TimeoutError:
        return None


async def ask_source(user):
    view = SourceView(user.id)

    try:
        await user.send(
            "من وين دخلت سيرفر :",
            view=view,
        )
    except discord.Forbidden:
        return None

    await view.wait()
    return view.result


async def ask_oath(user):
    try:
        await user.send(
            "الحلف",
            embed=discord.Embed(
                description=OATH_TEXT,
                color=discord.Color.blurple(),
            ),
        )
    except discord.Forbidden:
        return None

    return await ask_text(user, "الحلف")


# =========================================================
# SOURCE SELECT
# =========================================================

class SourceSelect(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id

        super().__init__(
            placeholder="اختر المصدر",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=option,
                    value=option,
                )
                for option in SOURCE_OPTIONS
            ],
        )

    async def callback(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ هذا الاختيار ليس لك.",
                ephemeral=True,
            )
            return

        self.view.result = self.values[0]

        await interaction.response.edit_message(
            content=f"من وين دخلت سيرفر : {self.values[0]}",
            view=None,
        )

        self.view.stop()


class SourceView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=APPLICATION_TIMEOUT)
        self.result = None
        self.add_item(SourceSelect(user_id))


# =========================================================
# GROQ
# =========================================================

async def groq_review(answers):
    if not GROQ_API_KEY:
        return (
            "مراجعة يدوية",
            "GROQ_API_KEY غير موجود في Environment Variables.",
        )

    prompt = f"""
راجع طلب تصريح رول بلاي.
أعط توصية واحدة فقط من:
قبول
رفض
مراجعة يدوية

ثم سبب مختصر.

اسم حقيقي: {answers["real_name"]}
العمر الحقيقي: {answers["real_age"]}
اسم حسابك الأساسي: {answers["roblox_name"]}
اختصار حسابك: {answers["account_short"]}
من وين دخلت سيرفر: {answers["source"]}
الحلف: {answers["oath"]}

لا تخمن معلومات غير موجودة.
لا ترفض بسبب أسلوب الكتابة فقط.
الحلف يجب أن يكون موافقًا للنص المطلوب من حيث المعنى.
"""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "أنت مساعد مراجعة إداري فقط. "
                                "قرار القبول النهائي للإدارة."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                },
                timeout=aiohttp.ClientTimeout(total=45),
            ) as response:
                data = await response.json()

        if response.status >= 400:
            return (
                "مراجعة يدوية",
                "حدث خطأ في خدمة Groq.",
            )

        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        first_line = (
            text.splitlines()[0]
            .replace("**", "")
            .strip()
            if text
            else ""
        )

        if first_line in ("قبول", "رفض", "مراجعة يدوية"):
            decision = first_line
        else:
            decision = "مراجعة يدوية"

        return decision, text[:1000] or "لا يوجد سبب."

    except Exception as error:
        print(f"[permit_ai] Groq error: {error}")
        return (
            "مراجعة يدوية",
            "تعذر الاتصال بالذكاء الاصطناعي.",
        )


# =========================================================
# APPLICATION EMBED
# =========================================================

def make_application_embed(member, answers, decision, reason):
    embed = discord.Embed(
        title="📋 طلب تصريح جديد",
        color=discord.Color.orange(),
    )

    embed.add_field(
        name="العضو",
        value=f"{member.mention}\n`{member.id}`",
        inline=False,
    )

    embed.add_field(
        name="اسمك الحقيقي",
        value=answers["real_name"][:1024],
        inline=False,
    )

    embed.add_field(
        name="عمرك الحقيقي",
        value=answers["real_age"][:1024],
        inline=False,
    )

    embed.add_field(
        name="اسم حسابك الأساسي",
        value=answers["roblox_name"][:1024],
        inline=False,
    )

    embed.add_field(
        name="اختصار حسابك",
        value=answers["account_short"][:1024],
        inline=False,
    )

    embed.add_field(
        name="من وين دخلت سيرفر",
        value=answers["source"][:1024],
        inline=False,
    )

    embed.add_field(
        name="الحلف",
        value=answers["oath"][:1024],
        inline=False,
    )

    embed.add_field(
        name="🤖 توصية الذكاء الاصطناعي",
        value=f"**{decision}**\n{reason[:900]}",
        inline=False,
    )

    embed.add_field(
        name="📌 الحالة",
        value="⏳ بانتظار قرار الإدارة",
        inline=False,
    )

    return embed


# =========================================================
# REVIEW BUTTONS

async def get_application_member(interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ هذا الزر للإدارة فقط.", ephemeral=True)
        return None
    if not interaction.message.embeds:
        await interaction.response.send_message("❌ بيانات الطلب غير موجودة.", ephemeral=True)
        return None
    embed=interaction.message.embeds[0]
    field=next((f for f in embed.fields if f.name=="العضو"),None)
    if field is None:
        await interaction.response.send_message("❌ لم أجد بيانات العضو.", ephemeral=True)
        return None
    parts=field.value.split("`")
    if len(parts)<2:
        await interaction.response.send_message("❌ لم أجد ID العضو.", ephemeral=True)
        return None
    try: member_id=int(parts[1])
    except ValueError:
        await interaction.response.send_message("❌ ID العضو غير صحيح.", ephemeral=True)
        return None
    member=interaction.guild.get_member(member_id)
    if member is None:
        try: member=await interaction.guild.fetch_member(member_id)
        except discord.HTTPException:
            await interaction.response.send_message("❌ العضو غير موجود في السيرفر.", ephemeral=True)
            return None
    return member


def log_update(embed,title,status,color):
    e=embed.copy(); e.title=title; e.color=color
    for i,f in enumerate(e.fields):
        if f.name=="📌 الحالة":
            e.set_field_at(i,name="📌 الحالة",value=status,inline=False); break
    return e


def roblox_name_from_embed(embed):
    f=next((f for f in embed.fields if f.name=="اسم حسابك الأساسي"),None)
    return f.value.strip() if f else "غير معروف"


class AcceptedLogView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="إزالة الرتبة",emoji="🔄",style=discord.ButtonStyle.gray,custom_id="permit_remove_role")
    async def remove_role(self,interaction,button):
        member=await get_application_member(interaction)
        if member is None: return
        role=interaction.guild.get_role(APPROVED_ROLE_ID)
        if role is None:
            await interaction.response.send_message("❌ رتبة القبول غير موجودة.",ephemeral=True); return
        try:
            if role in member.roles: await member.remove_roles(role,reason=f"إزالة رتبة التصريح بواسطة {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ البوت لا يملك صلاحية إزالة الرتبة.",ephemeral=True); return
        button.disabled=True
        await interaction.response.edit_message(embed=log_update(interaction.message.embeds[0],"🔄 تم إزالة رتبة التصريح",f"تمت إزالة الرتبة بواسطة {interaction.user.mention}",discord.Color.orange()),view=self)
        try: await member.send("🔄 تم إزالة رتبة التصريح الخاصة بك من الإدارة.")
        except discord.Forbidden: pass


class RejectedLogView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="قبول",emoji="✅",style=discord.ButtonStyle.green,custom_id="permit_rejected_accept")
    async def accept(self,interaction,button):
        member=await get_application_member(interaction)
        if member is None: return
        try:
            approved=interaction.guild.get_role(APPROVED_ROLE_ID); old=interaction.guild.get_role(REMOVE_ROLE_ID)
            if approved is None: raise RuntimeError("رتبة القبول غير موجودة.")
            if old and old in member.roles: await member.remove_roles(old,reason=f"قبول يدوي بواسطة {interaction.user}")
            if approved not in member.roles: await member.add_roles(approved,reason=f"قبول يدوي بواسطة {interaction.user}")
            nickname=f"SN | {roblox_name_from_embed(interaction.message.embeds[0])} | {random.randint(10000,99999)}"[:32]
            await member.edit(nick=nickname,reason=f"قبول يدوي بواسطة {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ البوت لا يملك صلاحية تعديل الرتب أو الاسم.",ephemeral=True); return
        except RuntimeError as e:
            await interaction.response.send_message(f"❌ {e}",ephemeral=True); return
        await interaction.response.edit_message(embed=log_update(interaction.message.embeds[0],"✅ تم قبول التصريح يدويًا",f"تم القبول بواسطة {interaction.user.mention}\nالاسم الجديد: `{nickname}`",discord.Color.green()),view=AcceptedLogView())
        try: await member.send(f"✅ تم قبول تصريحك من الإدارة.\nاسمك الجديد: `{nickname}`")
        except discord.Forbidden: pass


class PendingLogView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="قبول",emoji="✅",style=discord.ButtonStyle.green,custom_id="permit_manual_accept")
    async def accept(self,interaction,button):
        member=await get_application_member(interaction)
        if member is None: return
        try:
            approved=interaction.guild.get_role(APPROVED_ROLE_ID); old=interaction.guild.get_role(REMOVE_ROLE_ID)
            if approved is None: raise RuntimeError("رتبة القبول غير موجودة.")
            if old and old in member.roles: await member.remove_roles(old)
            if approved not in member.roles: await member.add_roles(approved)
            nickname=f"SN | {roblox_name_from_embed(interaction.message.embeds[0])} | {random.randint(10000,99999)}"[:32]
            await member.edit(nick=nickname)
        except discord.Forbidden:
            await interaction.response.send_message("❌ البوت لا يملك صلاحية تعديل الرتب أو الاسم.",ephemeral=True); return
        except RuntimeError as e:
            await interaction.response.send_message(f"❌ {e}",ephemeral=True); return
        await interaction.response.edit_message(embed=log_update(interaction.message.embeds[0],"✅ تم قبول التصريح يدويًا",f"تم القبول بواسطة {interaction.user.mention}\nالاسم الجديد: `{nickname}`",discord.Color.green()),view=AcceptedLogView())
        try: await member.send(f"✅ تم قبول تصريحك من الإدارة.\nاسمك الجديد: `{nickname}`")
        except discord.Forbidden: pass

    @discord.ui.button(label="رفض",emoji="❌",style=discord.ButtonStyle.red,custom_id="permit_manual_reject")
    async def reject(self,interaction,button):
        member=await get_application_member(interaction)
        if member is None: return
        await interaction.response.edit_message(embed=log_update(interaction.message.embeds[0],"❌ تم رفض التصريح",f"تم الرفض بواسطة {interaction.user.mention}",discord.Color.red()),view=RejectedLogView())
        try: await member.send("❌ تم رفض تصريحك من الإدارة.")
        except discord.Forbidden: pass


# APPLY BUTTON
# =========================================================

class ApplyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="تقديم تصريح",
            emoji="📋",
            style=discord.ButtonStyle.blurple,
            custom_id="permit_apply",
        )

    async def callback(self, interaction):
        await run_application(interaction)


class ApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ApplyButton())


# =========================================================
# APPLICATION PROCESS
# =========================================================

async def run_application(interaction):
    user=interaction.user
    await interaction.response.send_message("📩 تم إرسال الأسئلة إلى الخاص.",ephemeral=True)
    answers={}
    for key,question in QUESTIONS:
        answer=await ask_text(user,question)
        if not answer:
            try: await user.send("❌ انتهى وقت التقديم أو تعذر استقبال إجابتك.")
            except discord.Forbidden: pass
            return
        answers[key]=answer
    source=await ask_source(user)
    if not source:
        try: await user.send("❌ انتهى وقت التقديم أو لم يتم اختيار المصدر.")
        except discord.Forbidden: pass
        return
    answers["source"]=source
    oath=await ask_oath(user)
    if not oath:
        try: await user.send("❌ انتهى وقت التقديم أو لم يتم إرسال الحلف.")
        except discord.Forbidden: pass
        return
    answers["oath"]=oath

    decision,reason=await groq_review(answers)
    log_channel=interaction.guild.get_channel(LOG_CHANNEL_ID)
    if not isinstance(log_channel,discord.TextChannel): return
    member=interaction.guild.get_member(user.id)
    if member is None: return
    base=make_application_embed(member,answers,decision,reason)

    if decision=="قبول":
        try:
            approved=interaction.guild.get_role(APPROVED_ROLE_ID); old=interaction.guild.get_role(REMOVE_ROLE_ID)
            if approved is None: raise RuntimeError("رتبة القبول غير موجودة.")
            if old and old in member.roles: await member.remove_roles(old,reason="قبول تلقائي بواسطة Groq")
            if approved not in member.roles: await member.add_roles(approved,reason="قبول تلقائي بواسطة Groq")
            nickname=f"SN | {answers['roblox_name'].strip()} | {random.randint(10000,99999)}"[:32]
            await member.edit(nick=nickname,reason="قبول تصريح تلقائي")
            e=log_update(base,"✅ تم قبول التصريح تلقائيًا",f"🤖 تم القبول تلقائيًا بواسطة الذكاء الاصطناعي.\nالاسم الجديد: `{nickname}`",discord.Color.green())
            await log_channel.send(embed=e,view=AcceptedLogView())
            try: await user.send(f"✅ تم قبول تصريحك تلقائيًا.\nاسمك الجديد: `{nickname}`")
            except discord.Forbidden: pass
        except (discord.Forbidden,RuntimeError) as error:
            e=log_update(base,"⚠️ تعذر القبول التلقائي",f"يحتاج تدخل الإدارة.\n`{error}`",discord.Color.orange())
            await log_channel.send(embed=e,view=PendingLogView())
        return

    if decision=="رفض":
        e=log_update(base,"❌ تم رفض التصريح تلقائيًا","🤖 تم الرفض تلقائيًا بواسطة الذكاء الاصطناعي.\nيمكن للإدارة الضغط على «قبول». ",discord.Color.red())
        await log_channel.send(embed=e,view=RejectedLogView())
        try: await user.send("❌ تم رفض تصريحك تلقائيًا.")
        except discord.Forbidden: pass
        return

    e=log_update(base,"⏳ تصريح يحتاج مراجعة يدوية","⚠️ لم يعطِ الذكاء الاصطناعي قرارًا نهائيًا.\nالقرار للإدارة.",discord.Color.orange())
    await log_channel.send(embed=e,view=PendingLogView())
    try: await user.send("⏳ تم استلام طلبك وسيتم مراجعته من الإدارة.")
    except discord.Forbidden: pass


# SETUP
# =========================================================

async def setup_permit_system(bot_instance):
    """
    Called from Main.py inside setup_hook():

        await setup_permit_system(bot)
    """

    global _bot
    _bot = bot_instance

    # Persistent buttons
    bot_instance.add_view(ApplyView())
    bot_instance.add_view(AcceptedLogView())
    bot_instance.add_view(RejectedLogView())
    bot_instance.add_view(PendingLogView())

    # Register !setup_apply on the existing bot.
    # The command is intentionally registered here so this
    # module does not need a second Bot instance.
    if bot_instance.get_command("setup_apply") is None:

        @bot_instance.command(name="setup_apply")
        async def setup_apply(ctx):
            if not isinstance(ctx.author, discord.Member):
                return

            if not is_admin(ctx.author):
                await ctx.reply(
                    "❌ هذا الأمر للإدارة فقط.",
                    delete_after=5,
                )
                return

            embed = discord.Embed(
                title="📋 تصريح",
                description="اضغط على الزر للتقديم.",
                color=discord.Color.blurple(),
            )

            await ctx.send(
                embed=embed,
                view=ApplyView(),
            )
