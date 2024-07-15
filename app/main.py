import os
import asyncio
import asyncpg
from interactions import Client, Intents, ComponentContext, slash_command, Member
from server import server_thread

TOKEN = os.getenv("TOKEN")
DB_DSN = os.getenv("DB")

async def execute(sql_query: str, params=(), fetch=False):
    conn = await asyncpg.connect(DB_DSN)
    try:
        if fetch:
            data = await conn.fetch(sql_query, *params)
        else:
            await conn.execute(sql_query, *params)
            data = []
    except Exception as e:
        raise e
    finally:
        await conn.close()
    return data

# テーブルのカラムをBIGINTに変更する関数
async def alter_columns():
    conn = await asyncpg.connect(DB_DSN)
    try:
        await conn.execute("ALTER TABLE admins ALTER COLUMN guildid TYPE BIGINT;")
        await conn.execute("ALTER TABLE admins ALTER COLUMN userid TYPE BIGINT;")
        await conn.execute("ALTER TABLE balances ALTER COLUMN guildid TYPE BIGINT;")
        await conn.execute("ALTER TABLE balances ALTER COLUMN userid TYPE BIGINT;")
    finally:
        await conn.close()

await alter_columns()

# テーブルの作成
await execute('CREATE TABLE IF NOT EXISTS balances (guildid BIGINT, userid BIGINT, balance INTEGER, PRIMARY KEY(guildid, userid))')
await execute('CREATE TABLE IF NOT EXISTS admins (guildid BIGINT, userid BIGINT, PRIMARY KEY(guildid, userid))')

async def get_balance(guildid, userid):
    result = await execute('SELECT balance FROM balances WHERE guildid=$1 AND userid=$2', (guildid, userid), fetch=True)
    return result[0][0] if result else 0

async def set_balance(guildid, userid, balance):
    try:
        await execute('INSERT INTO balances (guildid, userid, balance) VALUES ($1, $2, $3)', (guildid, userid, balance))
    except asyncpg.UniqueViolationError:
        await execute('UPDATE balances SET balance = $1 WHERE guildid = $2 AND userid = $3', (balance, guildid, userid))

async def get_admin_user_ids(guildid):
    data = [c['userid'] for c in await execute('SELECT userid FROM admins WHERE guildid=$1', (guildid,), fetch=True)]
    return data

async def save_admin_user_id(guildid, userid):
    if userid not in await get_admin_user_ids(guildid):
        await execute('INSERT INTO admins (guildid, userid) VALUES ($1, $2)', (guildid, userid))

intents = Intents.DEFAULT | Intents.GUILD_MEMBERS
bot = Client(token=TOKEN, intents=intents)

@bot.listen()
async def on_ready():
    print(f'Logged in as {bot.user.username}')

async def get_guild_owner(guild_id):
    guild = await bot.get_guild(guild_id)
    return guild.owner_id

async def is_admin(guildid, userid):
    return userid in await get_admin_user_ids(guildid) or await get_guild_owner(guildid) == userid

@slash_command(name="balance", description="Displays your balance")
async def balance(ctx: ComponentContext):
    guild_id = int(ctx.guild_id)
    user_id = int(ctx.author.id)
    balance = await get_balance(guild_id, user_id)
    await ctx.send(f'{ctx.author.mention}さんの所持金は {balance} VTD です。', ephemeral=True)

@slash_command(name="pay", description="Pay VTD to another user", options=[
    {
        "name": "amount",
        "description": "Amount to pay",
        "type": 4,
        "required": True
    },
    {
        "name": "member",
        "description": "Member to pay",
        "type": 6,
        "required": True
    }
])
async def pay(ctx: ComponentContext, amount: int, member: Member):
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    guild_id = int(ctx.guild_id)
    giver_id = int(ctx.author.id)
    receiver_id = int(member.id)
    
    if giver_id == receiver_id:
        await ctx.send('自分自身にお金を渡すことはできません。', ephemeral=True)
        return

    if await get_balance(guild_id, giver_id) < amount:
        await ctx.send('所持金が不足しています。', ephemeral=True)
        return
    
    await set_balance(guild_id, giver_id, await get_balance(guild_id, giver_id) - amount)
    await set_balance(guild_id, receiver_id, await get_balance(guild_id, receiver_id) + amount)

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんに {amount} VTD を渡しました。', ephemeral=True)

@slash_command(name="request", description="Request VTD from another user", options=[
    {
        "name": "amount",
        "description": "Amount to request",
        "type": 4,
        "required": True
    },
    {
        "name": "member",
        "description": "Member to request",
        "type": 6,
        "required": True
    }
])
async def request(ctx: ComponentContext, amount: int, member: Member):
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    await ctx.send(f'{member.mention} さん、{ctx.author.mention} さんから {amount} VTD の請求がありました。', ephemeral=True)

@slash_command(name="give", description="Give VTD to a user (Admin only)", options=[
    {
        "name": "amount",
        "description": "Amount to give",
        "type": 4,
        "required": True
    },
    {
        "name": "member",
        "description": "Member to give",
        "type": 6,
        "required": True
    }
])
async def give(ctx: ComponentContext, amount: int, member: Member):
    if not await is_admin(int(ctx.guild_id), int(ctx.author.id)):
        await ctx.send('このコマンドを実行する権限がありません。', ephemeral=True)
        return
    
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    guild_id = int(ctx.guild_id)
    user_id = int(member.id)
    await set_balance(guild_id, user_id, await get_balance(guild_id, user_id) + amount)

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんに {amount} VTD を与えました。', ephemeral=True)

@slash_command(name="confiscation", description="Confiscate VTD from a user (Admin only)", options=[
    {
        "name": "amount",
        "description": "Amount to confiscate",
        "type": 4,
        "required": True
    },
    {
        "name": "member",
        "description": "Member to confiscate from",
        "type": 6,
        "required": True
    }
])
async def confiscation(ctx: ComponentContext, amount: int, member: Member):
    if not await is_admin(int(ctx.guild_id), int(ctx.author.id)):
        await ctx.send('このコマンドを実行する権限がありません。', ephemeral=True)
        return
    
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    guild_id = int(ctx.guild_id)
    user_id = int(member.id)
    if await get_balance(guild_id, user_id) < amount:
        await ctx.send('対象ユーザーの所持金が不足しています。', ephemeral=True)
        return
    
    await set_balance(guild_id, user_id, await get_balance(guild_id, user_id) - amount)

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんから {amount} VTD を押収しました。', ephemeral=True)

@slash_command(name="add_admin", description="Add a user as an admin", options=[
    {
        "name": "user",
        "description": "The user to add as admin",
        "type": 6,
        "required": True
    }
])
async def add_admin(ctx: ComponentContext, user: Member):
    guild_owner_id = await get_guild_owner(int(ctx.guild_id))
    if int(ctx.author.id) != int(guild_owner_id):
        await ctx.send('このコマンドを実行する権限がありません。サーバー主のみが実行できます。', ephemeral=True)
        return

    user_id = int(user.id)
    if user_id not in await get_admin_user_ids(int(ctx.guild_id)):
        await save_admin_user_id(int(ctx.guild_id), user_id)
        await ctx.send(f'{user.mention} さんが管理者として追加されました。', ephemeral=True)
    else:
        await ctx.send(f'{user.mention} さんは既に管理者です。', ephemeral=True)

async def main():
    server_thread()
    await bot.astart()  # bot.start() -> bot.astart() に変更

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
