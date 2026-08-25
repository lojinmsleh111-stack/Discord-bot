import o
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
# =========================================================

class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def get_member(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ هذا الزر للإدارة فقط.",
                ephemeral=True,
            )
            return None

        if not interaction.message.embeds:
            await interaction.response.send_message(
                "❌ بيانات الطلب غير موجودة.",
                ephemeral=True,
            )
            return None

        embed = interaction.message.embeds[0]

        member_field = next(
            (
                field
                for field in embed.fields
                if field.name == "العضو"
            ),
            None,
        )

        if member_field is None:
            await interaction.response.send_message(
                "❌ لم أجد بيانات العضو.",
                ephemeral=True,
            )
            return None

        member_id_text = member_field.value.split("`")

        if len(member_id_text) < 2:
            await interaction.response.send_message(
                "❌ لم أجد ID العضو.",
                ephemeral=True,
            )
            return None

        try:
            member_id = int(member_id_text[1])
        except ValueError:
            await interaction.response.send_message(
                "❌ ID العضو غير صحيح.",
                ephemeral=True,
            )
            return None

        member = interaction.guild.get_member(member_id)

        if member is None:
            try:
                member = await interaction.guild.fetch_member(member_id)
            except discord.HTTPException:
                await interaction.response.send_message(
                    "❌ العضو غير موجود في السيرفر.",
                    ephemeral=True,
                )
                return None

        return member

    async def update_status(
        self,
        interaction,
        title,
        status,
        color,
    ):
        embed = interaction.message.embeds[0].copy()

        for index, field in enumerate(embed.fields):
            if field.name == "📌 الحالة":
                embed.set_field_at(
                    index,
                    name="📌 الحالة",
                    value=status,
                    inline=False,
                )
                break

        embed.title = title
        embed.color = color

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=embed,
            view=self,
        )

    @discord.ui.button(
        label="قبول",
        emoji="✅",
        style=discord.ButtonStyle.green,
        custom_id="permit_accept",
    )
    async def accept(self, interaction, button):
        member = await self.get_member(interaction)

        if member is None:
            return

        approved_role = interaction.guild.get_role(
            APPROVED_ROLE_ID
        )

        old_role = interaction.guild.get_role(
            REMOVE_ROLE_ID
        )

        if approved_role is None:
            await interaction.response.send_message(
                "❌ رتبة القبول غير موجودة.",
                ephemeral=True,
            )
            return

        try:
            if old_role and old_role in member.roles:
                await member.remove_roles(
                    old_role,
                    reason=f"Permit accepted by {interaction.user}",
                )

            if approved_role not in member.roles:
                await member.add_roles(
                    approved_role,
                    reason=f"Permit accepted by {interaction.user}",
                )

            embed = interaction.message.embeds[0]

            roblox_field = next(
                (
                    field
                    for field in embed.fields
                    if field.name == "اسم حسابك الأساسي"
                ),
                None,
            )

            roblox_name = (
                roblox_field.value.strip()
                if roblox_field
                else "غير معروف"
            )

            random_number = random.randint(
                10000,
                99999,
            )

            nickname = (
                f"SN | {roblox_name} | {random_number}"
            )[:32]

            await member.edit(
                nick=nickname,
                reason=f"Permit accepted by {interaction.user}",
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ البوت لا يملك صلاحية تعديل الرتب أو الاسم. "
                "تأكد أن رتبة البوت أعلى من الرتب المطلوبة.",
                ephemeral=True,
            )
            return

        await self.update_status(
            interaction,
            "✅ تم قبول التصريح",
            (
                f"مقبول بواسطة {interaction.user.mention}\n"
                f"الاسم الجديد: `{nickname}`"
            ),
            discord.Color.green(),
        )

        try:
            await member.send(
                f"✅ تم قبول تصريحك.\n"
                f"اسمك الجديد: `{nickname}`"
            )
        except discord.Forbidden:
            pass

    @discord.ui.button(
        label="رفض",
        emoji="❌",
        style=discord.ButtonStyle.red,
        custom_id="permit_reject",
    )
    async def reject(self, interaction, button):
        member = await self.get_member(interaction)

        if member is None:
            return

        await self.update_status(
            interaction,
            "❌ تم رفض التصريح",
            f"مرفوض بواسطة {interaction.user.mention}",
            discord.Color.red(),
        )

        try:
            await member.send(
                "❌ تم رفض تصريحك من الإدارة."
            )
        except discord.Forbidden:
            pass

    @discord.ui.button(
        label="سحب التصريح",
        emoji="🔄",
        style=discord.ButtonStyle.gray,
        custom_id="permit_revoke",
    )
    async def revoke(self, interaction, button):
        member = await self.get_member(interaction)

        if member is None:
            return

        approved_role = interaction.guild.get_role(
            APPROVED_ROLE_ID
        )

        try:
            if (
                approved_role
                and approved_role in member.roles
            ):
                await member.remove_roles(
                    approved_role,
                    reason=f"Permit revoked by {interaction.user}",
                )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ البوت لا يملك صلاحية إزالة الرتبة.",
                ephemeral=True,
            )
            return

        await self.update_status(
            interaction,
            "🔄 تم سحب التصريح",
            f"تم سحب التصريح بواسطة {interaction.user.mention}",
            discord.Color.orange(),
        )

        try:
            await member.send(
                "🔄 تم سحب تصريحك من الإدارة."
            )
        except discord.Forbidden:
            pass


# =========================================================
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
    user = interaction.user

    await interaction.response.send_message(
        "📩 تم إرسال الأسئلة إلى الخاص.",
        ephemeral=True,
    )

    answers = {}

    for key, question in QUESTIONS:
        answer = await ask_text(
            user,
            question,
        )

        if not answer:
            try:
                await user.send(
                    "❌ انتهى وقت التقديم أو تعذر استقبال إجابتك."
                )
            except discord.Forbidden:
                pass
            return

        answers[key] = answer

    source = await ask_source(user)

    if not source:
        try:
            await user.send(
                "❌ انتهى وقت التقديم أو لم يتم اختيار المصدر."
            )
        except discord.Forbidden:
            pass
        return

    answers["source"] = source

    oath = await ask_oath(user)

    if not oath:
        try:
            await user.send(
                "❌ انتهى وقت التقديم أو لم يتم إرسال الحلف."
            )
        except discord.Forbidden:
            pass
        return

    answers["oath"] = oath

    ai_decision, ai_reason = await groq_review(
        answers
    )

    log_channel = interaction.guild.get_channel(
        LOG_CHANNEL_ID
    )

    if not isinstance(log_channel, discord.TextChannel):
        try:
            await user.send(
                "❌ لم يتم العثور على روم اللوق."
            )
        except discord.Forbidden:
            pass
        return

    member = interaction.guild.get_member(
        user.id
    )

    if member is None:
        return

    await log_channel.send(
        embed=make_application_embed(
            member,
            answers,
            ai_decision,
            ai_reason,
        ),
        view=ReviewView(),
    )

    try:
        await user.send(
            "✅ تم استلام طلبك وسيتم مراجعته من الإدارة."
        )
    except discord.Forbidden:
        pass


# =========================================================
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
    bot_instance.add_view(ReviewView())

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
