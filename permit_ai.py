import os
import random
import asyncio
from typing import Optional

import aiohttp
import discord
from discord.ext import commands

ADMIN_ROLE_ID = 1524146300906508326
LOG_CHANNEL_ID = 1524146309940904022
APPROVED_ROLE_ID = 1524374959751827466
REMOVE_ROLE_ID = 1524374666435887104
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
TIMEOUT = 600

QUESTIONS = [
    ("real_name", "اسمك الحقيقي :"),
    ("real_age", "عمرك الحقيقي :"),
    ("roblox_name", "اسم حسابك الأساسي :"),
    ("account_short", "اختصار حسابك :"),
]
SOURCES = ["خويك", "تيك توك", "إعلانات أو شراكات"]
OATH = ("اقسم بالله العظيم انا (فلان بن فلان) اني ماراح اخرب سمعت سيرفر "
        "ولا اتمشكل مع الاداره ولا مع المواطنين ولا اخرب سيرفر ولا "
        "اتعبث بسيرفر ولا اسب الاداره او المواطنين والله علو ماقوله شهيد")

bot: commands.Bot

def is_admin(member):
    return isinstance(member, discord.Member) and any(
        r.id == ADMIN_ROLE_ID for r in member.roles
    )

async def ask_text(user, text):
    try:
        await user.send(text)
        msg = await bot.wait_for(
            "message", timeout=TIMEOUT,
            check=lambda m: m.author.id == user.id and isinstance(m.channel, discord.DMChannel)
        )
        return msg.content.strip()
    except (asyncio.TimeoutError, discord.Forbidden):
        return None

class SourceSelect(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        super().__init__(
            placeholder="اختر المصدر",
            options=[discord.SelectOption(label=x, value=x) for x in SOURCES]
        )
    async def callback(self, interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ هذا الاختيار ليس لك.", ephemeral=True)
        self.view.result = self.values[0]
        await interaction.response.edit_message(content=f"من وين دخلت سيرفر : {self.values[0]}", view=None)
        self.view.stop()

class SourceView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=TIMEOUT)
        self.result = None
        self.add_item(SourceSelect(user_id))

async def ask_source(user):
    view = SourceView(user.id)
    try:
        await user.send("من وين دخلت سيرفر :", view=view)
    except discord.Forbidden:
        return None
    await view.wait()
    return view.result

async def groq_review(a):
    if not GROQ_API_KEY:
        return "مراجعة يدوية", "GROQ_API_KEY غير مضبوط."
    prompt = f"""راجع طلب تصريح رول بلاي. أعط توصية: قبول أو رفض أو مراجعة يدوية، ثم سبب مختصر.
اسم حقيقي: {a['real_name']}
العمر الحقيقي: {a['real_age']}
اسم حسابك الأساسي: {a['roblox_name']}
اختصار حسابك: {a['account_short']}
من وين دخلت سيرفر: {a['source']}
الحلف: {a['oath']}
لا تخمن معلومات غير موجودة ولا ترفض بسبب أسلوب الكتابة فقط."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model": GROQ_MODEL, "temperature": 0,
                      "messages":[{"role":"system","content":"أنت مساعد مراجعة إداري فقط."},
                                  {"role":"user","content":prompt}]},
                timeout=45
            ) as r:
                data = await r.json()
        text = data["choices"][0]["message"]["content"].strip()
        first = text.splitlines()[0].replace("**","").strip()
        decision = first if first in ("قبول","رفض","مراجعة يدوية") else "مراجعة يدوية"
        return decision, text[:1000]
    except Exception as e:
        print("Groq:", e)
        return "مراجعة يدوية", "تعذر الاتصال بالذكاء الاصطناعي."

def application_embed(member, a, decision, reason):
    e = discord.Embed(title="📋 طلب تصريح جديد", color=discord.Color.orange())
    e.add_field(name="العضو", value=f"{member.mention}\n`{member.id}`", inline=False)
    for key, title in [
        ("real_name","اسمك الحقيقي"), ("real_age","عمرك الحقيقي"),
        ("roblox_name","اسم حسابك الأساسي"), ("account_short","اختصار حسابك"),
        ("source","من وين دخلت سيرفر"), ("oath","الحلف")]:
        e.add_field(name=title, value=a[key][:1024], inline=False)
    e.add_field(name="🤖 توصية الذكاء الاصطناعي",
                value=f"**{decision}**\n{reason}", inline=False)
    e.add_field(name="📌 الحالة", value="⏳ بانتظار قرار الإدارة", inline=False)
    return e

class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def member(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ هذا الزر للإدارة فقط.", ephemeral=True)
            return None
        e = interaction.message.embeds[0]
        raw = next((f.value for f in e.fields if f.name == "العضو"), "")
        digits = "".join(c for c in raw if c.isdigit())
        if not digits:
            await interaction.response.send_message("❌ لم أجد العضو.", ephemeral=True)
            return None
        try:
            return interaction.guild.get_member(int(digits)) or await interaction.guild.fetch_member(int(digits))
        except discord.HTTPException:
            await interaction.response.send_message("❌ العضو غير موجود.", ephemeral=True)
            return None

    async def status(self, interaction, title, value, color):
        e = interaction.message.embeds[0].copy()
        for i, f in enumerate(e.fields):
            if f.name == "📌 الحالة":
                e.set_field_at(i, name="📌 الحالة", value=value, inline=False)
        e.title, e.color = title, color
        for c in self.children: c.disabled = True
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="قبول", emoji="✅", style=discord.ButtonStyle.green, custom_id="permit_accept")
    async def accept(self, interaction, button):
        m = await self.member(interaction)
        if not m: return
        approved = interaction.guild.get_role(APPROVED_ROLE_ID)
        old = interaction.guild.get_role(REMOVE_ROLE_ID)
        if not approved:
            return await interaction.response.send_message("❌ رتبة القبول غير موجودة.", ephemeral=True)
        try:
            if old and old in m.roles: await m.remove_roles(old)
            if approved not in m.roles: await m.add_roles(approved)
            roblox = next((f.value.strip() for f in interaction.message.embeds[0].fields
                           if f.name == "اسم حسابك الأساسي"), "غير معروف")
            nick = f"SN | {roblox} | {random.randint(10000,99999)}"[:32]
            await m.edit(nick=nick)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ البوت لا يملك صلاحيات الرتب/الاسم.", ephemeral=True)
        await self.status(interaction, "✅ تم قبول التصريح",
                           f"مقبول بواسطة {interaction.user.mention}\nالاسم الجديد: `{nick}`",
                           discord.Color.green())
        try: await m.send(f"✅ تم قبول تصريحك. اسمك الجديد: `{nick}`")
        except discord.Forbidden: pass

    @discord.ui.button(label="رفض", emoji="❌", style=discord.ButtonStyle.red, custom_id="permit_reject")
    async def reject(self, interaction, button):
        m = await self.member(interaction)
        if not m: return
        await self.status(interaction, "❌ تم رفض التصريح",
                           f"مرفوض بواسطة {interaction.user.mention}", discord.Color.red())
        try: await m.send("❌ تم رفض تصريحك من الإدارة.")
        except discord.Forbidden: pass

    @discord.ui.button(label="سحب التصريح", emoji="🔄", style=discord.ButtonStyle.gray, custom_id="permit_revoke")
    async def revoke(self, interaction, button):
        m = await self.member(interaction)
        if not m: return
        role = interaction.guild.get_role(APPROVED_ROLE_ID)
        try:
            if role and role in m.roles: await m.remove_roles(role)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ لا أستطيع إزالة الرتبة.", ephemeral=True)
        await self.status(interaction, "🔄 تم سحب التصريح",
                           f"تم سحب التصريح بواسطة {interaction.user.mention}", discord.Color.orange())
        try: await m.send("🔄 تم سحب تصريحك من الإدارة.")
        except discord.Forbidden: pass

class ApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="تقديم تصريح", emoji="📋",
                                        style=discord.ButtonStyle.blurple,
                                        custom_id="permit_apply"))

    @discord.ui.button(label="تقديم تصريح", emoji="📋", style=discord.ButtonStyle.blurple, custom_id="permit_apply_2")
    async def apply_button(self, interaction, button):
        await run_application(interaction)

async def run_application(interaction):
    user = interaction.user
    await interaction.response.send_message("📩 تم إرسال الأسئلة إلى الخاص.", ephemeral=True)
    answers = {}
    for key, question in QUESTIONS:
        x = await ask_text(user, question)
        if not x:
            try: await user.send("❌ انتهى وقت التقديم أو تعذر استقبال إجابتك.")
            except discord.Forbidden: pass
            return
        answers[key] = x
    answers["source"] = await ask_source(user)
    if not answers["source"]: return
    await user.send("الحلف")
    try:
        await user.send(OATH)
    except discord.Forbidden: return
    answers["oath"] = await ask_text(user, "الحلف")
    if not answers["oath"]: return
    decision, reason = await groq_review(answers)
    log = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if not isinstance(log, discord.TextChannel): return
    member = interaction.guild.get_member(user.id)
    if member:
        await log.send(embed=application_embed(member, answers, decision, reason), view=ReviewView())
    try: await user.send("✅ تم استلام طلبك وسيتم مراجعته من الإدارة.")
    except discord.Forbidden: pass

@bot.command(name="setup_apply")
async def setup_apply(ctx):
    if not is_admin(ctx.author):
        return await ctx.reply("❌ هذا الأمر للإدارة فقط.", delete_after=5)
    await ctx.send(embed=discord.Embed(title="📋 تصريح", description="اضغط على الزر للتقديم.", color=discord.Color.blurple()),
                   view=ApplyView())

async def setup_permit_system(bot_instance):
    global bot
    bot = bot_instance
    bot.add_view(ApplyView())
    bot.add_view(ReviewView())
