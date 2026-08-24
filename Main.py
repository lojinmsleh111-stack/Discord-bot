import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
from datetime import datetime

# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.environ["BOT_TOKEN"]

# رتبة العسكريين
MILITARY_ROLE_ID = 596381629044228136

# رتبة الستاف
STAFF_ROLE_ID = 1524146300906508326

# روم المخالفات
VIOLATIONS_CHANNEL_ID = 1524700243961188352

# روم التقييم + تصويت الرول
ROLE_SYSTEM_CHANNEL_ID = 1524401066345496727

# روم التكت / Ticket Panel
TICKET_PANEL_CHANNEL_ID = 1524146303028822241

# الروم المطلوب مشاهدته في تصويت الرول
RULES_CHANNEL_ID = 1524148895121281204

# الرومات التي ترسل فيها الصورة تلقائياً بعد كل رسالة
AUTO_IMAGE_CHANNELS = {
    1524146303406178355,
    1524401066345496727,
    1524146303028822241
}

AUTO_IMAGE_URL = (
    "https://cdn.discordapp.com/attachments/"
    "1535933660119826492/1541408310530539651/image.jpg"
    "?ex=6a8d7bdb&is=6a8c2a5b"
    "&hm=e68a5e548f56195eeccb54fa2469360064e956b9120ed000da94d9a0de60de3b"
)

# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================================================
# VIOLATIONS
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
# HELPERS
# =========================================================

def has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def is_military(member: discord.Member) -> bool:
    return has_role(member, MILITARY_ROLE_ID)


def is_staff(member: discord.Member) -> bool:
    return has_role(member, STAFF_ROLE_ID)


def is_ticket(channel: discord.TextChannel) -> bool:
    if not channel.name.startswith("ticket-"):
        return False

    category = channel.category

    if category is None:
        return False

    panel_channel = channel.guild.get_channel(TICKET_PANEL_CHANNEL_ID)

    if not isinstance(panel_channel, discord.TextChannel):
        return False

    return category.id == panel_channel.category_id


def get_ticket_owner(channel: discord.TextChannel):
    """
    يحاول استخراج صاحب التكت من Topic.
    Topic يكون بالشكل:
    ticket_owner:123456789
    """

    if not channel.topic:
        return None

    if not channel.topic.startswith("ticket_owner:"):
        return None

    try:
        return int(channel.topic.split(":", 1)[1])
    except ValueError:
        return None


def wrong_channel_embed(channel_id: int):
    return discord.Embed(
        title="❌ روم غير صحيح",
        description=f"هذا الأمر يعمل فقط في <#{channel_id}>.",
        color=discord.Color.red()
    )


def staff_only():
    return discord.Embed(
        title="❌ غير مسموح",
        description="هذا الأمر متاح للستاف فقط.",
        color=discord.Color.red()
    )


# =========================================================
# AUTO IMAGE
# =========================================================

@bot.event
async def on_message(message: discord.Message):

    if message.author.bot:
        return

    if message.channel.id in AUTO_IMAGE_CHANNELS:

        try:
            await message.channel.send(
                AUTO_IMAGE_URL
            )
        except Exception as e:
            print(f"Auto image error: {e}")

    await bot.process_commands(message)


# =========================================================
# VIOLATION SELECT
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
            placeholder="اختر المخالفة...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ لا يمكن تنفيذ العملية.",
                ephemeral=True
            )

        if not is_military(interaction.user):
            return await interaction.response.send_message(
                "❌ العسكريون فقط يستطيعون اختيار المخالفة.",
                ephemeral=True
            )

        violation = self.values[0]
        punishment = VIOLATIONS[violation]

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
            value=violation,
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

        embed.add_field(
            name="💳 الحالة",
            value="❌ غير مسددة",
            inline=False
        )

        if self.proof_url:
            embed.set_image(url=self.proof_url)

        embed.set_footer(
            text="نظام المخالفات العسكرية"
        )

        view = PaymentView()

        await interaction.response.edit_message(
            content="✅ تم تسجيل المخالفة.",
            embed=embed,
            view=view
        )

        # DM للمتخالف
        try:

            dm_embed = embed.copy()

            dm_embed.title = "📋 تم تسجيل مخالفة بحقك"

            dm_embed.add_field(
                name="📌 ملاحظة",
                value="يرجى مراجعة الإدارة في حال وجود اعتراض.",
                inline=False
            )

            await self.target.send(
                embed=dm_embed
            )

        except discord.Forbidden:
            print(
                f"لا يمكن إرسال DM إلى {self.target}"
            )


class ViolationView(discord.ui.View):

    def __init__(
        self,
        target: discord.Member,
        proof_url: str
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            ViolationSelect(
                target,
                proof_url
            )
        )


# =========================================================
# PAYMENT BUTTON
# =========================================================

class PaymentView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="تسديد المخالفة",
        emoji="💰",
        style=discord.ButtonStyle.green,
        custom_id="pay_violation_button"
    )
    async def pay_violation(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ يجب تنفيذ العملية داخل السيرفر.",
                ephemeral=True
            )

        if not is_military(interaction.user):
            return await interaction.response.send_message(
                "❌ فقط العسكريين يستطيعون تسديد المخالفة.",
                ephemeral=True
            )

        if not interaction.message.embeds:
            return await interaction.response.send_message(
                "❌ لم يتم العثور على بيانات المخالفة.",
                ephemeral=True
            )

        old_embed = interaction.message.embeds[0]
        embed = old_embed.copy()

        # تغيير الحالة
        new_fields = []

        for field in embed.fields:

            if field.name != "💳 الحالة":
                new_fields.append(field)

        embed.clear_fields()

        for field in new_fields:

            embed.add_field(
                name=field.name,
                value=field.value,
                inline=field.inline
            )

        embed.add_field(
            name="💳 الحالة",
            value=f"✅ تم التسديد بواسطة {interaction.user.mention}",
            inline=False
        )

        embed.color = discord.Color.green()

        button.disabled = True
        button.label = "تم تسديد المخالفة"
        button.emoji = "✅"

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


# =========================================================
# /mokhlafa
# =========================================================

@bot.tree.command(
    name="mokhlafa",
    description="تسجيل مخالفة عسكرية"
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
            embed=wrong_channel_embed(
                VIOLATIONS_CHANNEL_ID
            ),
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

    if not prove.content_type:

        return await interaction.response.send_message(
            "❌ يجب رفع صورة كـ prove.",
            ephemeral=True
        )

    if not prove.content_type.startswith("image/"):

        return await interaction.response.send_message(
            "❌ الـ prove يجب أن يكون صورة.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🚔 تسجيل مخالفة",
        description=(
            f"**المتخالف:** {person.mention}\n"
            f"**العسكري:** {interaction.user.mention}\n\n"
            "اختر المخالفة من القائمة:"
        ),
        color=discord.Color.orange()
    )

    embed.set_image(
        url=prove.url
    )

    await interaction.response.send_message(
        embed=embed,
        view=ViolationView(
            person,
            prove.url
        )
    )


# =========================================================
# /taqeem
# =========================================================

@bot.tree.command(
    name="taqeem",
    description="إرسال تقييم الرول"
)
async def taqeem(
    interaction: discord.Interaction
):

    if interaction.channel_id != ROLE_SYSTEM_CHANNEL_ID:

        return await interaction.response.send_message(
            embed=wrong_channel_embed(
                ROLE_SYSTEM_CHANNEL_ID
            ),
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
        text="يرجى تقييم الرول بشكل صحيح"
    )

    await interaction.response.send_message(
        "✅ تم إنشاء التقييم.",
        ephemeral=True
    )

    message = await interaction.channel.send(
        content="@everyone",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            everyone=True
        )
    )

    await message.add_reaction("✅")
    await message.add_reaction("❌")


# =========================================================
# /sky_vote
# =========================================================

@bot.tree.command(
    name="sky_vote",
    description="تصويت رول بلاي سكاي ون"
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
        app_commands.Choice(
            name="نعم",
            value="نعم"
        ),
        app_commands.Choice(
            name="لا",
            value="لا"
        )
    ]
)
async def sky_vote(
    interaction: discord.Interaction,
    host: str,
    assistant: app_commands.Choice[str],
    role_type: str,
    rolls_done: int,
    required_players: int
):

    if interaction.channel_id != ROLE_SYSTEM_CHANNEL_ID:

        return await interaction.response.send_message(
            embed=wrong_channel_embed(
                ROLE_SYSTEM_CHANNEL_ID
            ),
            ephemeral=True
        )

    if rolls_done < 0:

        return await interaction.response.send_message(
            "❌ عدد الرولات غير صحيح.",
            ephemeral=True
        )

    if required_players <= 0:

        return await interaction.response.send_message(
            "❌ العدد المطلوب يجب أن يكون أكبر من صفر.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🎮 تصويت رول بلاي سكاي ون",
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

    await interaction.response.send_message(
        embed=embed
    )

    message = interaction.original_response()

    await message.add_reaction("✅")
    await message.add_reaction("❌")


# =========================================================
# TICKET SYSTEM
# =========================================================

class TicketPanelView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="فتح تكت",
        emoji="🎫",
        style=discord.ButtonStyle.blurple,
        custom_id="open_ticket_button"
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild

        if guild is None:

            return await interaction.response.send_message(
                "❌ لا يمكن فتح تكت هنا.",
                ephemeral=True
            )

        # البحث عن تكت مفتوح للمستخدم
        for channel in guild.text_channels:

            if not is_ticket(channel):
                continue

            owner_id = get_ticket_owner(channel)

            if owner_id == interaction.user.id:

                return await interaction.response.send_message(
                    f"❌ عندك تكت مفتوح بالفعل: {channel.mention}",
                    ephemeral=True
                )

        panel_channel = guild.get_channel(
            TICKET_PANEL_CHANNEL_ID
        )

        if not isinstance(
            panel_channel,
            discord.TextChannel
        ):

            return await interaction.response.send_message(
                "❌ لم يتم العثور على روم التكت.",
                ephemeral=True
            )

        category = panel_channel.category

        if category is None:

            return await interaction.response.send_message(
                "❌ روم التكت يجب أن يكون داخل Category.",
                ephemeral=True
            )

        staff_role = guild.get_role(
            STAFF_ROLE_ID
        )

        overwrites = {

            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            interaction.user:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True
                ),

            guild.me:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True,
                    manage_messages=True,
                    embed_links=True
                )
        }

        if staff_role:

            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True
            )

        channel_name = (
            f"ticket-{interaction.user.name}"
        ).lower()

        channel_name = channel_name.replace(
            " ",
            "-"
        )[:90]

        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"ticket_owner:{interaction.user.id}",
            reason=f"Ticket opened by {interaction.user}"
        )

        embed = discord.Embed(
            title="🎫 تذكرتك",
            description=(
                f"مرحباً {interaction.user.mention} 👋\n\n"
                "تم فتح التكت بنجاح.\n"
                "يرجى كتابة طلبك وانتظار أحد أعضاء الإدارة.\n\n"
                "🔔 **يمكن للستاف استلام التكت.**"
            ),
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text="Ticket System"
        )

        await ticket_channel.send(
            content=interaction.user.mention,
            embed=embed,
            view=TicketControlView()
        )

        await interaction.response.send_message(
            f"✅ تم فتح تكتك: {ticket_channel.mention}",
            ephemeral=True
        )


class TicketControlView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="استلام",
        emoji="🙋",
        style=discord.ButtonStyle.green,
        custom_id="ticket_claim"
    )
    async def claim(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not isinstance(
            interaction.user,
            discord.Member
        ):

            return await interaction.response.send_message(
                "❌ خطأ.",
                ephemeral=True
            )

        if not is_staff(interaction.user):

            return await interaction.response.send_message(
                "❌ الستاف فقط يستطيع استلام التكت.",
                hemeral=True
            )

        embed = discord.Embed(
            title="🙋 تم استلام التكت",
            description=(
                f"تم استلام التكت بواسطة "
                f"{interaction.user.mention}."
            ),
            color=discord.Color.green()
        )

        await interaction.channel.send(
            embed=embed
        )

        await interaction.response.send_message(
            "✅ تم استلام التكت.",
            ephemeral=True
        )

    @discord.ui.button(
        label="إغلاق",
        emoji="🔒",
        style=discord.ButtonStyle.gray,
        custom_id="ticket_close"
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not isinstance(
            interaction.user,
            discord.Member
        ):

            return

        if not is_staff(interaction.user):

            return await interaction.response.send_message(
                "❌ الستاف فقط يستطيع إغلاق التكت.",
                ephemeral=True
            )

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):

            return

        owner_id = get_ticket_owner(channel)

        if owner_id:

            owner = channel.guild.get_member(
                owner_id
            )

            if owner:

                try:
                    await channel.set_permissions(
                        owner,
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True
                    )
                except Exception:
                    pass

        await channel.edit(
            name=f"closed-{channel.name}"[:100]
        )

        await interaction.response.send_message(
            "🔒 تم إغلاق التكت.",
        )

    @discord.ui.button(
        label="حذف",
        emoji="🗑️",
        style=discord.ButtonStyle.red,
        custom_id="ticket_delete"
    )
    async def delete(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not isinstance(
            interaction.user,
            discord.Member
        ):

            return

        if not is_staff(interaction.user):

            return await interaction.response.send_message(
                "❌ الستاف فقط يستطيع حذف التكت.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "🗑️ سيتم حذف التكت خلال 5 ثوانٍ."
        )

        await asyncio.sleep(5)

        try:
            await interaction.channel.delete(
                reason=f"Ticket deleted by {interaction.user}"
            )
        except Exception:
            pass


# =========================================================
# TICKET SLASH COMMAND CHECK
# =========================================================

async def ticket_command_check(
    interaction: discord.Interaction
):

    if not isinstance(
        interaction.channel,
        discord.TextChannel
    ):

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل التكتات فقط.",
            ephemeral=True
        )

        return False

    if not is_ticket(
        interaction.channel
    ):

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل التكتات فقط.",
            ephemeral=True
        )

        return False

    if not isinstance(
        interaction.user,
        discord.Member
    ):

        await interaction.response.send_message(
            "❌ لا يمكن تنفيذ الأمر.",
            ephemeral=True
        )

        return False

    if not is_staff(
        interaction.user
    ):

        await interaction.response.send_message(
            embed=staff_only(),
            ephemeral=True
        )

        return False

    return True


# =========================================================
# /ticket_call
# =========================================================

@bot.tree.command(
    name="ticket_call",
    description="نداء صاحب التكت في الخاص"
)
async def ticket_call(
    interaction: discord.Interaction
):

    if not await ticket_command_check(
        interaction
    ):
        return

    owner_id = get_ticket_owner(
        interaction.channel
    )

    if not owner_id:

        return await interaction.response.send_message(
            "❌ لم أستطع معرفة صاحب التكت.",
            ephemeral=True
        )

    member = interaction.guild.get_member(
        owner_id
    )

    if not member:

        return await interaction.response.send_message(
            "❌ صاحب التكت غير موجود في السيرفر.",
            ephemeral=True
        )

    try:

        embed = discord.Embed(
            title="🔔 نداء من الإدارة",
            description=(
                f"لديك نداء من الإدارة في تكتك:\n"
                f"**{interaction.channel.name}**\n\n"
                "يرجى التوجه إلى التكت."
            ),
            color=discord.Color.orange()
        )

        await member.send(
            embed=embed
        )

        await interaction.response.send_message(
            f"✅ تم إرسال نداء إلى {member.mention}.",
            ephemeral=True
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ لا أستطيع إرسال رسالة خاصة لهذا العضو.",
            ephemeral=True
        )


# =========================================================
# /ticket_rename
# =========================================================

@bot.tree.command(
    name="ticket_rename",
    description="تغيير اسم التكت"
)
@app_commands.describe(
    name="الاسم الجديد"
)
async def ticket_rename(
    interaction: discord.Interaction,
    name: str
):

    if not await ticket_command_check(
        interaction
    ):
        return

    channel = interaction.channel

    name = name.strip()

    if not name:

        return await interaction.response.send_message(
            "❌ اكتب اسماً صحيحاً.",
            ephemeral=True
        )

    if len(name) > 90:

        return await interaction.response.send_message(
            "❌ اسم التكت طويل جداً.",
            ephemeral=True
        )

    if not name.startswith("ticket-"):

        name = f"ticket-{name}"

    try:

        await channel.edit(
            name=name
        )

        await interaction.response.send_message(
            f"✅ تم تغيير اسم التكت إلى `{name}`."
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ البوت لا يملك صلاحية تغيير اسم الروم.",
            ephemeral=True
        )


# =========================================================
# /ticket_add
# =========================================================

@bot.tree.command(
    name="ticket_add",
    description="إضافة شخص إلى التكت"
)
@app_commands.describe(
    member="الشخص الذي تريد إضافته"
)
async def ticket_add(
    interaction: discord.Interaction,
    member: discord.Member
):

    if not await ticket_command_check(
        interaction
    ):
        return

    try:

        await interaction.channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )

        await interaction.response.send_message(
            f"✅ تمت إضافة {member.mention} إلى التكت."
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ البوت لا يملك صلاحية تعديل صلاحيات الروم.",
            ephemeral=True
        )


# =========================================================
# /ticket_remove
# =========================================================

@bot.tree.command(
    name="ticket_remove",
    description="إزالة شخص من التكت"
)
@app_commands.describe(
    member="الشخص الذي تريد إزالته"
)
async def ticket_remove(
    interaction: discord.Interaction,
    member: discord.Member
):

    if not await ticket_command_check(
        interaction
    ):
        return

    owner_id = get_ticket_owner(
        interaction.channel
    )

    if owner_id == member.id:

        return await interaction.response.send_message(
            "❌ لا يمكنك إزالة صاحب التكت.",
            ephemeral=True
        )

    try:

        await interaction.channel.set_permissions(
            member,
            overwrite=None
        )

        await interaction.response.send_message(
            f"✅ تمت إزالة {member.mention} من التكت."
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ البوت لا يملك صلاحية تعديل صلاحيات الروم.",
            ephemeral=True
        )


# =========================================================
# /ticket_panel
# =========================================================

@bot.tree.command(
    name="ticket_panel",
    description="إرسال لوحة فتح التكت"
)
async def ticket_panel(
    interaction: discord.Interaction
):

    if interaction.channel_id != TICKET_PANEL_CHANNEL_ID:

        return await interaction.response.send_message(
            embed=wrong_channel_embed(
                TICKET_PANEL_CHANNEL_ID
            ),
            ephemeral=True
        )

    if not isinstance(
        interaction.user,
        discord.Member
    ):

        return

    if not is_staff(
        interaction.user
    ):

        return await interaction.response.send_message(
            embed=staff_only(),
            ephemeral=True
        )

    embed = discord.Embed(
        title="🎫 نظام التكت",
        description=(
            "اضغط على الزر الموجود بالأسفل لفتح تكت.\n\n"
            "📌 **ملاحظات:**\n"
            "• لا تفتح أكثر من تكت بدون سبب.\n"
            "• اشرح مشكلتك بشكل واضح.\n"
            "• انتظر أحد أعضاء الإدارة."
        ),
        color=discord.Color.blurple()
    )

    embed.set_footer(
        text="Ticket System"
    )

    await interaction.channel.send(
        embed=embed,
        view=TicketPanelView()
    )

    await interaction.response.send_message(
        "✅ تم إرسال لوحة التكت.",
        ephemeral=True
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(
        f"✅ Logged in as {bot.user}"
    )

    try:

        synced = await bot.tree.sync()

        print(
            f"✅ Synced {len(synced)} slash commands"
        )

    except Exception as e:

        print(
            f"❌ Slash command sync error: {e}"
        )


# =========================================================
# PERSISTENT VIEWS
# =========================================================

@bot.event
async def setup_hook():

    bot.add_view(
        TicketPanelView()
    )

    bot.add_view(
        TicketControlView()
    )

    bot.add_view(
        PaymentView()
    )


# =========================================================
# RUN
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "BOT_TOKEN غير موجود في Environment Variables"
    )

bot.run(TOKEN)
           
