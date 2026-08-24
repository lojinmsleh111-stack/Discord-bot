import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
from datetime import datetime

# =========================================================
# الإعدادات
# =========================================================

TOKEN = os.environ["BOT_TOKEN"]

# رتبة العسكريين
MILITARY_ROLE_ID = 596381629044228136

# روم المخالفات
VIOLATIONS_CHANNEL_ID = 1524700243961188352

# روم التقييم والتصويت
ROLE_SYSTEM_CHANNEL_ID = 1524401066345496727

# الروم الذي يجب مشاهدته في تصويت الرول
RULES_CHANNEL_ID = 1524148895121281204

# =========================================================
# البوت
# =========================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================================================
# المخالفات
# =========================================================

VIOLATIONS = {
    "تفحيط": "20,000",
    "زره": "1,000",
    "هروب من العساكر": "حرمان أسبوع",
    "حدحدة": "5,000 + حجز موتر",
    "سحب جلنط": "500",
    "توقف بنص الشارع": "700",
    "فك لوحة بدون تصريح": "900",
    "مسرع فوق 65 ميل": "2,000",
    "تسببت بحادث": "200 + سجن 3 أيام",
    "عرقلة سير": "500"
}

# =========================================================
# دوال مساعدة
# =========================================================

def is_military(member: discord.Member) -> bool:
    return any(role.id == MILITARY_ROLE_ID for role in member.roles)


def wrong_channel_embed(correct_channel_id: int):
    return discord.Embed(
        title="❌ روم غير صحيح",
        description=f"هذا الأمر يعمل فقط في <#{correct_channel_id}>.",
        color=discord.Color.red()
    )


# =========================================================
# Select Menu للمخالفات
# =========================================================

class ViolationSelect(discord.ui.Select):

    def __init__(
        self,
        target: discord.Member,
        proof_url: str
    ):
        self.target = target
        self.proof_url = proof_url

        options = []

        for name, punishment in VIOLATIONS.items():
            options.append(
                discord.SelectOption(
                    label=name,
                    description=f"العقوبة: {punishment}",
                    value=name
                )
            )

        super().__init__(
            placeholder="اختر المخالفة من القائمة...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        # فقط العسكري الذي أنشأ القائمة يستطيع استخدامها
        if not is_military(interaction.user):
            return await interaction.response.send_message(
                "❌ هذا الخيار متاح للعسكريين فقط.",
                ephemeral=True
            )

        violation_name = self.values[0]
        punishment = VIOLATIONS[violation_name]

        embed = discord.Embed(
            title="🚔 مخالفة رول بلاي عسكرية",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="👤 المتخالف",
            value=self.target.mention,
            inline=False
        )

        embed.add_field(
            name="⚠️ المخالفة",
            value=violation_name,
            inline=True
        )

        embed.add_field(
            name="💰 العقوبة",
            value=punishment,
            inline=True
        )

        embed.add_field(
            name="👮 العسكري",
            value=interaction.user.mention,
            inline=False
        )

        embed.set_footer(
            text="نظام المخالفات العسكرية"
        )

        if self.proof_url:
            embed.set_image(url=self.proof_url)

        view = PaymentView(
            target_id=self.target.id,
            military_role_id=MILITARY_ROLE_ID
        )

        await interaction.response.edit_message(
            content="✅ تم اختيار المخالفة.",
            embed=embed,
            view=view
        )

        # إرسال نسخة للمتخالف
        try:
            dm_embed = embed.copy()

            dm_embed.title = "📋 تم تسجيل مخالفة بحقك"

            dm_embed.add_field(
                name="💳 حالة المخالفة",
                value="❌ غير مسددة",
                inline=False
            )

            await self.target.send(embed=dm_embed)

        except discord.Forbidden:
            pass


class ViolationView(discord.ui.View):

    def __init__(
        self,
        target: discord.Member,
        proof_url: str
    ):
        super().__init__(timeout=300)

        self.add_item(
            ViolationSelect(
                target=target,
                proof_url=proof_url
            )
        )


# =========================================================
# زر تسديد المخالفة
# =========================================================

class PaymentView(discord.ui.View):

    def __init__(
        self,
        target_id: int,
        military_role_id: int
    ):
        super().__init__(timeout=None)

        self.target_id = target_id
        self.military_role_id = military_role_id

    @discord.ui.button(
        label="تسديد المخالفة",
        emoji="💰",
        style=discord.ButtonStyle.green,
        custom_id="pay_violation"
    )
    async def pay(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ لا يمكن تنفيذ العملية.",
                ephemeral=True
            )

        if not is_military(interaction.user):
            return await interaction.response.send_message(
                "❌ فقط العسكريين يستطيعون تسديد المخالفات.",
                ephemeral=True
            )

        embed = interaction.message.embeds[0]

        # تحديث حالة المخالفة
        new_embed = embed.copy()

        # إزالة حقل الحالة القديمة إن وجد
        fields = []

        for field in new_embed.fields:
            if field.name != "💳 حالة المخالفة":
                fields.append(field)

        new_embed.clear_fields()

        for field in fields:
            new_embed.add_field(
                name=field.name,
                value=field.value,
                inline=field.inline
            )

        new_embed.add_field(
            name="💳 حالة المخالفة",
            value=f"✅ تم التسديد بواسطة {interaction.user.mention}",
            inline=False
        )

        new_embed.color = discord.Color.green()

        # تعطيل الزر
        button.disabled = True
        button.label = "تم تسديد المخالفة"
        button.emoji = "✅"

        await interaction.response.edit_message(
            embed=new_embed,
            view=self
        )


# =========================================================
# /mokhlafa
# =========================================================

@bot.tree.command(
    name="mokhlafa",
    description="تسجيل مخالفة رول بلاي عسكرية"
)
@app_commands.describe(
    person="الشخص المتخالف",
    prove="صورة إثبات المخالفة"
)
async def mokhlafa(
    interaction: discord.Interaction,
    person: discord.Member,
    prove: discord.Attachment
):

    if interaction.channel_id != VIOLATIONS_CHANNEL_ID:
        return await interaction.response.send_message(
            embed=wrong_channel_embed(VIOLATIONS_CHANNEL_ID),
            ephemeral=True
        )

    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "❌ لا يمكن تنفيذ الأمر.",
            ephemeral=True
        )

    if not is_military(interaction.user):
        return await interaction.response.send_message(
            "❌ هذا الأمر للعسكريين فقط.",
            ephemeral=True
        )

    # التأكد أن الملف صورة
    if not prove.content_type or not prove.content_type.startswith("image/"):
        return await interaction.response.send_message(
            "❌ يجب أن يكون الـ prove صورة.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🚔 تسجيل مخالفة",
        description=(
            f"**المتخالف:** {person.mention}\n"
            f"**العسكري:** {interaction.user.mention}\n\n"
            "اختر المخالفة من القائمة الموجودة بالأسفل."
        ),
        color=discord.Color.orange()
    )

    embed.set_image(url=prove.url)

    await interaction.response.send_message(
        embed=embed,
        view=ViolationView(
            target=person,
            proof_url=prove.url
        )
    )


# =========================================================
# /تقييم
# =========================================================

@bot.tree.command(
    name="تقييم",
    description="إرسال تقييم الرول"
)
async def evaluation(interaction: discord.Interaction):

    if interaction.channel_id != ROLE_SYSTEM_CHANNEL_ID:
        return await interaction.response.send_message(
            embed=wrong_channel_embed(ROLE_SYSTEM_CHANNEL_ID),
            ephemeral=True
        )

    embed = discord.Embed(
        title="⭐ تقييم الرول",
        description=(
            "__**تقييم الرول**__\n\n"
            "__**في حال رول عجبك قيم الرول ✔️:**__\n\n"
            "__**في حال حطيت خطاء وانت مبلك تايم 5ساعات**__\n\n"
            "__**ملاحظه لو الهوست طلع مظلوم بتقييم فك تكت عليك او عليكم "
            "راح تتحاسبون**__"
        ),
        color=discord.Color.blue()
    )

    embed.set_footer(
        text="يرجى اختيار التقييم الصحيح"
    )

    message = await interaction.channel.send(
        content="@everyone",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )

    await message.add_reaction("✅")
    await message.add_reaction("❌")

    await interaction.response.send_message(
        "✅ تم إرسال التقييم.",
        ephemeral=True
    )


# =========================================================
# /تصويت_رول_بلاي_سكاي_ون
# =========================================================

@bot.tree.command(
    name="تصويت_رول_بلاي_سكاي_ون",
    description="إنشاء تصويت رول بلاي سكاي ون"
)
@app_commands.describe(
    host="حساب الهوست",
    assistant="هل معك مساعد؟",
    role_type="نوع الرول",
    rolls_done="كم رول سويت",
    required_players="العدد المطلوب لبداية الرول"
)
@app_commands.choices(
    assistant=[
        app_commands.Choice(name="نعم", value="نعم"),
        app_commands.Choice(name="لا", value="لا")
    ]
)
async def sky_one_vote(
    interaction: discord.Interaction,
    host: str,
    assistant: app_commands.Choice[str],
    role_type: str,
    rolls_done: int,
    required_players: int
):

    if interaction.channel_id != ROLE_SYSTEM_CHANNEL_ID:
        return await interaction.response.send_message(
            embed=wrong_channel_embed(ROLE_SYSTEM_CHANNEL_ID),
            ephemeral=True
        )

    if rolls_done < 0:
        return await interaction.response.send_message(
            "❌ عدد الرولات غير صحيح.",
            ephemeral=True
        )

    if required_players <= 0:
        return await interaction.response.send_message(
            "❌ العدد المطلوب يجب أن يكون أكبر من 0.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🎮 تصويت رول بلاي سكاي ون",
        description=(
            "يرجى التصويت للرول بعد قراءة المعلومات التالية."
        ),
        color=discord.Color.blue()
    )

    embed.add_field(
        name="👤 حساب الهوست",
        value=host,
        inline=False
    )

    embed.add_field(
        name="👥 معك مساعد",
        value=assistant.value,
        inline=True
    )

    embed.add_field(
        name="🎭 نوع الرول",
        value=role_type,
        inline=True
    )

    embed.add_field(
        name="🎮 كم رول سويت",
        value=str(rolls_done),
        inline=True
    )

    embed.add_field(
        name="👥 العدد المطلوب لبدا رول",
        value=str(required_players),
        inline=False
    )

    embed.add_field(
        name="📢 مهم",
        value=f"<#{RULES_CHANNEL_ID}> لازم تشوفه",
        inline=False
    )

    embed.set_footer(
        text=f"تم إنشاء التصويت بواسطة {interaction.user}"
    )

    message = await interaction.channel.send(
        content="@everyone",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )

    # الإيموجيات تلقائياً
    await message.add_reaction("✅")
    await message.add_reaction("❌")

    await interaction.response.send_message(
        "✅ تم إنشاء تصويت الرول وإضافة الإيموجيات تلقائياً.",
        ephemeral=True
    )


# =========================================================
# تشغيل البوت
# =========================================================

@bot.event
async def on_ready():

    try:
        synced = await bot.tree.sync()

        print(
            f"✅ Logged in as {bot.user}"
        )

        print(
            f"✅ Synced {len(synced)} slash commands"
        )

    except Exception as e:
        print(
            f"❌ Sync Error: {e}"
        )


# =========================================================
# تشغيل
# =========================================================

if not TOKEN:
    raise RuntimeError("BOT_TOKEN غير موجود في Environment Variables")

bot.run(TOKEN)
