import json
import os
import asyncio
from interactions import Client, Intents, ComponentContext, slash_command
from server import server_thread

TOKEN = os.environ.get("TOKEN")

BALANCES_FILE = 'balances.json'
ADMIN_USER_IDS_FILE = 'admin_user_ids.json'

# 所持金データを読み込む関数
def load_balances():
    try:
        with open(BALANCES_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

# 所持金データを保存する関数
def save_balances():
    with open(BALANCES_FILE, 'w') as file:
        json.dump(user_balances, file)

# 管理者ユーザーIDを読み込む関数
def load_admin_user_ids():
    try:
        with open(ADMIN_USER_IDS_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

# 管理者ユーザーIDを保存する関数
def save_admin_user_ids():
    with open(ADMIN_USER_IDS_FILE, 'w') as file:
        json.dump(admin_user_ids, file)

# インテントの設定
intents = Intents.DEFAULT | Intents.GUILD_MEMBERS

# 接続に必要なオブジェクトを生成
bot = Client(token=TOKEN, intents=intents)

# ユーザーの所持金を管理する辞書
user_balances = load_balances()
admin_user_ids = load_admin_user_ids()

# ボットが起動したときの処理
@bot.listen()
async def on_ready():
    print(f'Logged in as {bot.user.username}')

# サーバーごとにユーザーの所持金を取得する関数
def get_balance(guild_id, user_id):
    return user_balances.get(guild_id, {}).get(user_id, 0)

# サーバーごとにユーザーの所持金を設定する関数
def set_balance(guild_id, user_id, amount):
    if guild_id not in user_balances:
        user_balances[guild_id] = {}
    user_balances[guild_id][user_id] = amount
    save_balances()

# サーバー主を特定する関数
async def get_guild_owner(ctx):
    guild = await ctx.get_guild()
    return guild.owner_id

# ユーザーの所持金を表示するコマンド
@slash_command(name="balance", description="Displays your balance or the balance of a specified user", options=[
    {
        "name": "user",
        "description": "The user whose balance you want to see",
        "type": 6,  # USER
        "required": False
    }
])
async def balance(ctx: ComponentContext, user=None):
    target_user = user or ctx.author
    guild_id = str(ctx.guild_id)
    user_id = str(target_user.id)
    balance = get_balance(guild_id, user_id)
    await ctx.send(f'{target_user.mention}さんの所持金は {balance} VTD です。')

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
    
    guild_id = str(ctx.guild_id)
    giver_id = str(ctx.author.id)
    receiver_id = str(member.id)
    
    if giver_id == receiver_id:
        await ctx.send('自分自身にお金を渡すことはできません。')
        return

    if get_balance(guild_id, giver_id) < amount:
        await ctx.send('所持金が不足しています。')
        return
    
    set_balance(guild_id, giver_id, get_balance(guild_id, giver_id) - amount)
    set_balance(guild_id, receiver_id, get_balance(guild_id, receiver_id) + amount)

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
    if str(ctx.author.id) not in admin_user_ids:
        await ctx.send('このコマンドを実行する権限がありません。')
        return
    
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。')
        return
    
    guild_id = str(ctx.guild_id)
    user_id = str(member.id)
    set_balance(guild_id, user_id, get_balance(guild_id, user_id) + amount)

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
    if str(ctx.author.id) not in admin_user_ids:
        await ctx.send('このコマンドを実行する権限がありません。')
        return
    
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。')
        return
    
    guild_id = str(ctx.guild_id)
    user_id = str(member.id)
    if get_balance(guild_id, user_id) < amount:
        await ctx.send('対象ユーザーの所持金が不足しています。')
        return
    
    set_balance(guild_id, user_id, get_balance(guild_id, user_id) - amount)

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんから {amount} VTD を押収しました。')

# 管理者を追加するコマンド（サーバー主のみ実行可能）
@slash_command(name="add_admin", description="Add a user as an admin", options=[
    {
        "name": "user",
        "description": "The user to add as admin",
        "type": 6,  # USER
        "required": True
    }
])
async def add_admin(ctx: ComponentContext, user):
    guild_owner_id = await get_guild_owner(ctx)
    if str(ctx.author.id) != str(guild_owner_id):
        await ctx.send('このコマンドを実行する権限がありません。サーバー主のみが実行できます。')
        return
    
    user_id = str(user.id)
    if user_id not in admin_user_ids:
        admin_user_ids.append(user_id)
        save_admin_user_ids()
        await ctx.send(f'{user.mention} さんが管理者として追加されました。')
    else:
        await ctx.send(f'{user.mention} さんは既に管理者です。')

async def main():
    server_thread()
    await bot.astart()  # bot.start() -> bot.astart() に変更

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
