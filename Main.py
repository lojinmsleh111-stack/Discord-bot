import os, asyncio
from threading import Thread
import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
import aiohttp

TOKEN=os.environ["BOT_TOKEN"]
MILITARY_ROLE_ID=596381629044228136
STAFF_ROLE_ID=1524146300906508326
VIOLATIONS_CHANNEL_ID=1524700243961188352
ROLE_SYSTEM_CHANNEL_ID=1524401066345496727
TICKET_PANEL_CHANNEL_ID=1524146303028822241
RULES_CHANNEL_ID=1524148895121281204
AUTO_IMAGE_CHANNELS={1524146303406178355,1524401066345496727,1524146303028822241}
AUTO_IMAGE_URL="https://cdn.discordapp.com/attachments/1535933660119826492/1541408310530539651/image.jpg?ex=6a8d7bdb&is=6a8c2a5b&hm=e68a5e548f56195eeccb54fa2469360064e956b9120ed000da94d9a0de60de3b"
VIOLATIONS={"تفحيط":"20,000","زره":"1,000","هروب من العساكر":"حرمان أسبوع","حدحدة":"5,000 + حجز موتر","سحب جلنط":"500","توقف بنص الشارع":"700","فك لوحة بدون تصريح":"900","مسرع فوق 65 ميل":"2,000","تسببت بحادث":"200 + سجن 3 أيام","عرقلة سير":"500"}

app=Flask(__name__)
@app.route("/")
def home(): return "Discord Bot is online!"
def keep_alive(): Thread(target=lambda:app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000))),daemon=True).start()

intents=discord.Intents.default(); intents.members=True; intents.message_content=True
bot=commands.Bot(command_prefix="!",intents=intents)

def role(m,r): return isinstance(m,discord.Member) and any(x.id==r for x in m.roles)
def military(m): return role(m,MILITARY_ROLE_ID)
def staff(m): return role(m,STAFF_ROLE_ID)
def wrong(cid): return discord.Embed(title="❌ روم غير صحيح",description=f"هذا الأمر يعمل فقط في <#{cid}>.",color=discord.Color.red())
def is_ticket(c):
    if not isinstance(c,discord.TextChannel) or not c.name.startswith(("ticket-","closed-ticket-")): return False
    p=c.guild.get_channel(TICKET_PANEL_CHANNEL_ID)
    return isinstance(p,discord.TextChannel) and c.category_id==p.category_id
def owner(c):
    try: return int(c.topic.split(":",1)[1]) if c.topic and c.topic.startswith("ticket_owner:") else None
    except: return None

# =========================================================
# SLASH COMMAND CHANNEL VISIBILITY
# =========================================================

COMMAND_CHANNELS = {
    "mokhlafa": VIOLATIONS_CHANNEL_ID,
    "taqeem": ROLE_SYSTEM_CHANNEL_ID,
    "sky_vote": ROLE_SYSTEM_CHANNEL_ID,
    "no_host": ROLE_SYSTEM_CHANNEL_ID,
    "ticket_panel": TICKET_PANEL_CHANNEL_ID,
}

async def apply_command_channel_permissions():
    """Restrict Slash Commands at Discord permission level by channel."""
    if not bot.guilds or not bot.user:
        return

    app_id = bot.user.id
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        url = f"https://discord.com/api/v10/applications/{app_id}/commands"
        async with session.get(url) as response:
            if response.status != 200:
                print("❌ تعذر جلب Slash Commands:", response.status)
                return
            commands_data = await response.json()

        command_ids = {c["name"]: c["id"] for c in commands_data}

        for guild in bot.guilds:
            for command_name, channel_id in COMMAND_CHANNELS.items():
                command_id = command_ids.get(command_name)
                if not command_id:
                    print(f"⚠️ لم يتم العثور على الأمر: {command_name}")
                    continue

                permissions_url = (
                    f"https://discord.com/api/v10/applications/{app_id}/guilds/"
                    f"{guild.id}/commands/{command_id}/permissions"
                )

                payload = {
                    "permissions": [
                        {"id": str(guild.id), "type": 1, "permission": False},
                        {"id": str(channel_id), "type": 3, "permission": True},
                    ]
                }

                async with session.put(permissions_url, json=payload) as response:
                    if response.status not in (200, 204):
                        print(
                            f"❌ فشل تقييد /{command_name} في {guild.id}: "
                            f"{response.status} {await response.text()}"
                        )
                    else:
                        print(f"✅ /{command_name} -> {channel_id}")

@bot.event
async def on_message(m):
    if m.author.bot: return
    if m.channel.id in AUTO_IMAGE_CHANNELS:
        try: await m.channel.send(AUTO_IMAGE_URL)
        except Exception as e: print("Auto image:",e)
    await bot.process_commands(m)

class PaymentView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="تسديد المخالفة",emoji="💰",style=discord.ButtonStyle.green,custom_id="pay_violation_button")
    async def pay(self,i:discord.Interaction,b:discord.ui.Button):
        if not military(i.user): return await i.response.send_message("❌ فقط العسكريين يستطيعون تسديد المخالفة.",ephemeral=True)
        if not i.message.embeds: return await i.response.send_message("❌ لم يتم العثور على بيانات المخالفة.",ephemeral=True)
        e=i.message.embeds[0].copy(); fs=[f for f in e.fields if f.name!="💳 الحالة"]; e.clear_fields()
        for f in fs: e.add_field(name=f.name,value=f.value,inline=f.inline)
        e.add_field(name="💳 الحالة",value=f"✅ تم التسديد بواسطة {i.user.mention}",inline=False); e.color=discord.Color.green()
        b.disabled=True; b.label="تم تسديد المخالفة"; b.emoji="✅"
        await i.response.edit_message(embed=e,view=self)

class ViolationSelect(discord.ui.Select):
    def __init__(self,target,proof):
        self.target=target; self.proof=proof
        super().__init__(placeholder="اختر المخالفة...",min_values=1,max_values=1,options=[discord.SelectOption(label=k,description=f"العقوبة: {v}",value=k) for k,v in VIOLATIONS.items()])
    async def callback(self,i):
        if not military(i.user): return await i.response.send_message("❌ العسكريون فقط يستطيعون اختيار المخالفة.",ephemeral=True)
        v=self.values[0]; e=discord.Embed(title="🚔 مخالفة رول بلاي عسكرية",color=discord.Color.red())
        e.add_field(name="👤 المتخالف",value=self.target.mention,inline=False); e.add_field(name="⚠️ المخالفة",value=v,inline=True); e.add_field(name="💰 العقوبة",value=VIOLATIONS[v],inline=True); e.add_field(name="👮 العسكري",value=i.user.mention,inline=False); e.add_field(name="💳 الحالة",value="❌ غير مسددة",inline=False); e.set_image(url=self.proof); e.set_footer(text="نظام المخالفات العسكرية")
        await i.response.edit_message(content="✅ تم تسجيل المخالفة.",embed=e,view=PaymentView())
        try:
            d=e.copy(); d.title="📋 تم تسجيل مخالفة بحقك"; await self.target.send(embed=d)
        except discord.Forbidden: pass
class ViolationView(discord.ui.View):
    def __init__(self,t,p): super().__init__(timeout=300); self.add_item(ViolationSelect(t,p))

@bot.tree.command(name="mokhlafa",description="تسجيل مخالفة عسكرية")
@app_commands.describe(person="الشخص المتخالف",prove="صورة إثبات المخالفة")
async def mokhlafa(i,person:discord.Member,prove:discord.Attachment):
    if i.channel_id!=VIOLATIONS_CHANNEL_ID: return await i.response.send_message(embed=wrong(VIOLATIONS_CHANNEL_ID),ephemeral=True)
    if not military(i.user): return await i.response.send_message("❌ هذا الأمر للعسكريين فقط.",ephemeral=True)
    if not prove.content_type or not prove.content_type.startswith("image/"): return await i.response.send_message("❌ الـ prove يجب أن يكون صورة.",ephemeral=True)
    e=discord.Embed(title="🚔 تسجيل مخالفة",description=f"**المتخالف:** {person.mention}\n**العسكري:** {i.user.mention}\n\nاختر المخالفة من القائمة:",color=discord.Color.orange()); e.set_image(url=prove.url)
    await i.response.send_message(embed=e,view=ViolationView(person,prove.url))

@bot.tree.command(name="taqeem",description="إرسال تقييم الرول")
async def taqeem(i):
    if i.channel_id!=ROLE_SYSTEM_CHANNEL_ID: return await i.response.send_message(embed=wrong(ROLE_SYSTEM_CHANNEL_ID),ephemeral=True)
    text="__**تقييم الرول**__\n\n__**في حال رول عجبك قيم الرول ✔️:**__\n\n__**في حال حطيت خطاء وانت مبلك تايم 5ساعات**__\n\n__**ملاحظه لو الهوست طلع مظلوم بتقييم فك تكت عليك او عليكم راح تتحاسبون**__\n\n@everyone"
    await i.response.send_message("✅ تم إرسال التقييم.",ephemeral=True); m=await i.channel.send(text,allowed_mentions=discord.AllowedMentions(everyone=True)); await m.add_reaction("✅"); await m.add_reaction("❌")

@bot.tree.command(name="sky_vote",description="تصويت رول بلاي سكاي ون")
@app_commands.describe(host="حساب الهوست",assistant="هل معك مساعد؟",role_type="نوع الرول",rolls_done="كم رول سويت",required_players="العدد المطلوب لبداية الرول")
@app_commands.choices(assistant=[app_commands.Choice(name="نعم",value="نعم"),app_commands.Choice(name="لا",value="لا")])
async def sky_vote(i,host:str,assistant:app_commands.Choice[str],role_type:str,rolls_done:int,required_players:int):
    if i.channel_id!=ROLE_SYSTEM_CHANNEL_ID: return await i.response.send_message(embed=wrong(ROLE_SYSTEM_CHANNEL_ID),ephemeral=True)
    if rolls_done<0 or required_players<=0: return await i.response.send_message("❌ القيم المدخلة غير صحيحة.",ephemeral=True)
    text=f"__**تصويت رول بلاي سكاي ون**__\n\n__**حساب الهوست:**__ {host}\n\n__**معك مساعد:**__ {assistant.value}\n\n__**نوع الرول:**__ {role_type}\n\n__**كم رول سويت:**__ {rolls_done}\n\n__**<#${RULES_CHANNEL_ID}> لازم تشوفه**__\n\n__**العدد المطلوب لبدا رول:**__ {required_players}\n\n@everyone".replace("<#${RULES_CHANNEL_ID}>",f"<#{RULES_CHANNEL_ID}>")
    await i.response.send_message("✅ تم إرسال التصويت.",ephemeral=True); m=await i.channel.send(text,allowed_mentions=discord.AllowedMentions(everyone=True)); await m.add_reaction("✅")

@bot.tree.command(name="no_host",description="إرسال رسالة عدم وجود هوست")
async def no_host(i):
    if i.channel_id!=ROLE_SYSTEM_CHANNEL_ID: return await i.response.send_message(embed=wrong(ROLE_SYSTEM_CHANNEL_ID),ephemeral=True)
    await i.response.send_message("✅ تم إرسال الرسالة.",ephemeral=True); await i.channel.send("__**لايوجد رول حالياً انتظرو لين مايجي هوست يفتح **__\n\n@everyone",allowed_mentions=discord.AllowedMentions(everyone=True))

class TicketPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="فتح تكت",emoji="🎫",style=discord.ButtonStyle.blurple,custom_id="open_ticket_button")
    async def open(self,i,b):
        g=i.guild; p=g.get_channel(TICKET_PANEL_CHANNEL_ID)
        if not isinstance(p,discord.TextChannel) or p.category is None: return await i.response.send_message("❌ روم التكت يجب أن يكون داخل Category.",ephemeral=True)
        for c in g.text_channels:
            if is_ticket(c) and owner(c)==i.user.id: return await i.response.send_message(f"❌ عندك تكت مفتوح بالفعل: {c.mention}",ephemeral=True)
        sr=g.get_role(STAFF_ROLE_ID); ow={g.default_role:discord.PermissionOverwrite(view_channel=False),i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True,embed_links=True),g.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True,manage_messages=True,manage_permissions=True,embed_links=True)}
        if sr: ow[sr]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_messages=True,attach_files=True,embed_links=True)
        c=await g.create_text_channel(f"ticket-{i.user.name}".lower().replace(" ","-")[:90],category=p.category,overwrites=ow,topic=f"ticket_owner:{i.user.id}")
        e=discord.Embed(title="🎫 تذكرتك",description=f"مرحباً {i.user.mention} 👋\n\nتم فتح التكت بنجاح.\nيرجى كتابة طلبك وانتظار الإدارة.",color=discord.Color.blurple())
        await c.send(content=i.user.mention,embed=e,view=TicketControlView()); await i.response.send_message(f"✅ تم فتح تكتك: {c.mention}",ephemeral=True)

class TicketControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="استلام",emoji="🙋",style=discord.ButtonStyle.green,custom_id="ticket_claim")
    async def claim(self,i,b):
        if not staff(i.user): return await i.response.send_message("❌ الستاف فقط يستطيع استلام التكت.",ephemeral=True)
        await i.channel.send(embed=discord.Embed(title="🙋 تم استلام التكت",description=f"تم استلام التكت بواسطة {i.user.mention}.",color=discord.Color.green())); await i.response.send_message("✅ تم استلام التكت.",ephemeral=True)
    @discord.ui.button(label="إغلاق",emoji="🔒",style=discord.ButtonStyle.gray,custom_id="ticket_close")
    async def close(self,i,b):
        if not staff(i.user): return await i.response.send_message("❌ الستاف فقط يستطيع إغلاق التكت.",ephemeral=True)
        o=owner(i.channel); m=i.guild.get_member(o) if o else None
        if m:
            try: await i.channel.set_permissions(m,view_channel=True,send_messages=False,read_message_history=True)
            except discord.Forbidden: pass
        await i.channel.edit(name=f"closed-{i.channel.name}"[:100]); await i.response.send_message("🔒 تم إغلاق التكت.")
    @discord.ui.button(label="حذف",emoji="🗑️",style=discord.ButtonStyle.red,custom_id="ticket_delete")
    async def delete(self,i,b):
        if not staff(i.user): return await i.response.send_message("❌ الستاف فقط يستطيع حذف التكت.",ephemeral=True)
        await i.response.send_message("🗑️ سيتم حذف التكت خلال 5 ثوانٍ."); await asyncio.sleep(5)
        try: await i.channel.delete()
        except discord.Forbidden: pass

async def ticket_check(i):
    if not is_ticket(i.channel): await i.response.send_message("❌ هذا الأمر يعمل داخل التكتات فقط.",ephemeral=True); return False
    if not staff(i.user): await i.response.send_message(embed=discord.Embed(title="❌ غير مسموح",description="هذا الأمر متاح للستاف فقط.",color=discord.Color.red()),ephemeral=True); return False
    return True

@bot.tree.command(name="ticket_call",description="نداء صاحب التكت في الخاص")
async def ticket_call(i):
    if not await ticket_check(i): return
    m=i.guild.get_member(owner(i.channel)) if owner(i.channel) else None
    if not m: return await i.response.send_message("❌ لم أستطع معرفة صاحب التكت.",ephemeral=True)
    try: await m.send(embed=discord.Embed(title="🔔 نداء من الإدارة",description=f"لديك نداء في التكت **{i.channel.name}**.\nيرجى التوجه للتكت.",color=discord.Color.orange())); await i.response.send_message(f"✅ تم إرسال نداء إلى {m.mention}.",ephemeral=True)
    except discord.Forbidden: await i.response.send_message("❌ لا أستطيع إرسال رسالة خاصة لهذا العضو.",ephemeral=True)

@bot.tree.command(name="ticket_rename",description="تغيير اسم التكت")
@app_commands.describe(name="الاسم الجديد")
async def ticket_rename(i,name:str):
    if not await ticket_check(i): return
    name=name.strip()
    if not name: return await i.response.send_message("❌ اكتب اسماً صحيحاً.",ephemeral=True)
    if not name.startswith(("ticket-","closed-")): name="ticket-"+name
    try: await i.channel.edit(name=name[:100]); await i.response.send_message(f"✅ تم تغيير الاسم إلى `{name[:100]}`.")
    except discord.Forbidden: await i.response.send_message("❌ البوت لا يملك صلاحية تغيير اسم الروم.",ephemeral=True)

@bot.tree.command(name="ticket_add",description="إضافة شخص إلى التكت")
@app_commands.describe(member="الشخص الذي تريد إضافته")
async def ticket_add(i,member:discord.Member):
    if not await ticket_check(i): return
    try: await i.channel.set_permissions(member,view_channel=True,send_messages=True,read_message_history=True,attach_files=True,embed_links=True); await i.response.send_message(f"✅ تمت إضافة {member.mention} إلى التكت.")
    except discord.Forbidden: await i.response.send_message("❌ لا أملك صلاحية تعديل الروم.",ephemeral=True)

@bot.tree.command(name="ticket_remove",description="إزالة شخص من التكت")
@app_commands.describe(member="الشخص الذي تريد إزالته")
async def ticket_remove(i,member:discord.Member):
    if not await ticket_check(i): return
    if owner(i.channel)==member.id: return await i.response.send_message("❌ لا يمكنك إزالة صاحب التكت.",ephemeral=True)
    try: await i.channel.set_permissions(member,overwrite=None); await i.response.send_message(f"✅ تمت إزالة {member.mention} من التكت.")
    except discord.Forbidden: await i.response.send_message("❌ لا أملك صلاحية تعديل الروم.",ephemeral=True)

@bot.tree.command(name="ticket_panel",description="إرسال لوحة فتح التكت")
async def ticket_panel(i):
    if i.channel_id!=TICKET_PANEL_CHANNEL_ID: return await i.response.send_message(embed=wrong(TICKET_PANEL_CHANNEL_ID),ephemeral=True)
    if not staff(i.user): return await i.response.send_message("❌ الستاف فقط.",ephemeral=True)
    e=discord.Embed(title="🎫 نظام التكت",description="اضغط على الزر بالأسفل لفتح تكت.\n\n• لا تفتح أكثر من تكت بدون سبب.\n• اشرح طلبك بوضوح.\n• انتظر الإدارة.",color=discord.Color.blurple())
    await i.channel.send(embed=e,view=TicketPanelView()); await i.response.send_message("✅ تم إرسال لوحة التكت.",ephemeral=True)

@bot.event
async def setup_hook():
    bot.add_view(TicketPanelView()); bot.add_view(TicketControlView()); bot.add_view(PaymentView())

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands")
        await asyncio.sleep(2)
        await apply_command_channel_permissions()
    except Exception as e:
        print("❌ Sync/permissions error:", e)

if __name__=="__main__":
    keep_alive(); bot.run(TOKEN)
