from interactions import Client, Intents, ComponentContext, slash_command

TOKEN = ''


# インテントの設定
intents = Intents.DEFAULT | Intents.GUILD_MEMBERS

# 接続に必要なオブジェクトを生成
bot = Client(token=TOKEN, intents=intents)

# ユーザーの所持金を管理する辞書
user_balances = {}

# ボットが起動したときの処理
@bot.event
async def on_ready():
    print(f'Logged in as {bot.me.name}')

# ユーザーの所持金を表示するコマンド
@slash_command(name="balance", description="Displays your balance")
async def balance(ctx: ComponentContext):
    user_id = str(ctx.author.id)
    balance = user_balances.get(user_id, 0)
    await ctx.send(f'{ctx.author.mention}さんの所持金は {balance} VTD です。')

# 通貨の受け渡しを行うコマンド
@slash_command(name="pay", description="Pay VTD to another user", options=[
    {
        "name": "amount",
        "description": "Amount to pay",
        "type": 4,  # INTEGER
        "required": True
    },
    {
        "name": "member",
        "description": "Member to pay",
        "type": 6,  # USER
        "required": True
    }
])
async def pay(ctx: ComponentContext, amount: int, member):
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。')
        return
    
    giver_id = str(ctx.author.id)
    receiver_id = str(member.id)
    
    if giver_id == receiver_id:
        await ctx.send('自分自身にお金を渡すことはできません。')
        return

    if user_balances.get(giver_id, 0) < amount:
        await ctx.send('所持金が不足しています。')
        return
    
    user_balances[giver_id] = user_balances.get(giver_id, 0) - amount
    user_balances[receiver_id] = user_balances.get(receiver_id, 0) + amount

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんに {amount} VTD を渡しました。')

# 通貨の請求を行うコマンド
@slash_command(name="request", description="Request VTD from another user", options=[
    {
        "name": "amount",
        "description": "Amount to request",
        "type": 4,  # INTEGER
        "required": True
    },
    {
        "name": "member",
        "description": "Member to request",
        "type": 6,  # USER
        "required": True
    }
])
async def request(ctx: ComponentContext, amount: int, member):
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。')
        return
    
    await ctx.send(f'{member.mention} さん、{ctx.author.mention} さんから {amount} VTD の請求がありました。')

# 管理者がユーザーに通貨を与えるコマンド
@slash_command(name="give", description="Give VTD to a user (Admin only)", options=[
    {
        "name": "amount",
        "description": "Amount to give",
        "type": 4,  # INTEGER
        "required": True
    },
    {
        "name": "member",
        "description": "Member to give",
        "type": 6,  # USER
        "required": True
    }
])
async def give(ctx: ComponentContext, amount: int, member):
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。')
        return
    
    user_id = str(member.id)
    user_balances[user_id] = user_balances.get(user_id, 0) + amount

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんに {amount} VTD を与えました。')

# 管理者がユーザーから通貨を押収するコマンド
@slash_command(name="confiscation", description="Confiscate VTD from a user (Admin only)", options=[
    {
        "name": "amount",
        "description": "Amount to confiscate",
        "type": 4,  # INTEGER
        "required": True
    },
    {
        "name": "member",
        "description": "Member to confiscate from",
        "type": 6,  # USER
        "required": True
    }
])
async def confiscation(ctx: ComponentContext, amount: int, member):
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。')
        return
    
    user_id = str(member.id)
    if user_balances.get(user_id, 0) < amount:
        await ctx.send('対象ユーザーの所持金が不足しています。')
        return
    
    user_balances[user_id] = user_balances.get(user_id, 0) - amount

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんから {amount} VTD を押収しました。')

# Botの起動とDiscordサーバーへの接続
bot.start()
