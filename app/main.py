import os
import requests
import asyncio
import psycopg2
from interactions import Client, Intents, ComponentContext, slash_command, Member
from server import server_thread

TOKEN = os.getenv("TOKEN")
DB_DSN = os.getenv("DB")

def execute(sql_query: str, params=(), fetch=False):
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        try:
            cur.execute(sql_query, params)
            if fetch:
                data = cur.fetchall()
            else:
                data = []
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"Database connection error: {e}")
        raise e
    return data

# テーブルのカラムをBIGINTに変更する関数
def alter_columns():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    cur.execute("ALTER TABLE admins ALTER COLUMN guildid TYPE BIGINT;")
    cur.execute("ALTER TABLE admins ALTER COLUMN userid TYPE BIGINT;")
    cur.execute("ALTER TABLE balances ALTER COLUMN guildid TYPE BIGINT;")
    cur.execute("ALTER TABLE balances ALTER COLUMN userid TYPE BIGINT;")
    conn.commit()
    cur.close()
    conn.close()

alter_columns()

# テーブルの作成
execute('CREATE TABLE IF NOT EXISTS balances (guildid BIGINT, userid BIGINT, balance INTEGER, PRIMARY KEY(guildid, userid))')
execute('CREATE TABLE IF NOT EXISTS admins (guildid BIGINT, userid BIGINT, PRIMARY KEY(guildid, userid))')

def get_balance(guildid, userid):
    result = execute('SELECT balance FROM balances WHERE guildid=%s AND userid=%s', (guildid, userid), fetch=True)
    return result[0][0] if result else 0

def set_balance(guildid, userid, balance):
    try:
        execute('INSERT INTO balances (guildid, userid, balance) VALUES (%s, %s, %s)', (guildid, userid, balance))
    except psycopg2.IntegrityError:
        execute('UPDATE balances SET balance = %s WHERE guildid = %s AND userid = %s', (balance, guildid, userid))

def get_admin_user_ids(guildid):
    data = [c[0] for c in execute('SELECT userid FROM admins WHERE guildid=%s', (guildid,), fetch=True)]
    return data

def save_admin_user_id(guildid, userid):
    if userid not in get_admin_user_ids(guildid):
        execute('INSERT INTO admins (guildid, userid) VALUES (%s, %s)', (guildid, userid))

intents = Intents.DEFAULT | Intents.GUILD_MEMBERS
bot = Client(token=TOKEN, intents=intents)

@bot.listen()
async def on_ready():
    print(f'Logged in as {bot.user.username}')

def get_guild_owner(guild_id):
    guild = bot.get_guild(guild_id)
    return guild._owner_id

def is_admin(guildid, userid):
    return userid in get_admin_user_ids(guildid) or get_guild_owner(guildid) == userid

@slash_command(name="balance", description="Displays your balance")
async def balance(ctx: ComponentContext):
    guild_id = int(ctx.guild_id)
    user_id = int(ctx.author.id)
    balance = get_balance(guild_id, user_id)
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
    interaction_id = ctx.id
    interaction_token = ctx.token
    print(f'Interaction ID: {interaction_id}')
    print(f'Interaction Token: {interaction_token}')

    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    guild_id = int(ctx.guild_id)
    giver_id = int(ctx.author.id)
    receiver_id = int(member.id)
    
    if giver_id == receiver_id:
        await ctx.send('自分自身にお金を渡すことはできません。', ephemeral=True)
        return

    if get_balance(guild_id, giver_id) < amount:
        await ctx.send('所持金が不足しています。', ephemeral=True)
        return
    
    # 先に応答を返してからデータベース操作を実行
    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんに {amount} VTD を渡しました。', ephemeral=True)

    set_balance(guild_id, giver_id, get_balance(guild_id, giver_id) - amount)
    set_balance(guild_id, receiver_id, get_balance(guild_id, receiver_id) + amount)

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
    interaction_id = ctx.id
    interaction_token = ctx.token
    print(f'Interaction ID: {interaction_id}')
    print(f'Interaction Token: {interaction_token}')
    
    if not is_admin(int(ctx.guild_id), int(ctx.author.id)):
        await ctx.send('このコマンドを実行する権限がありません。', ephemeral=True)
        return
    
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    guild_id = int(ctx.guild_id)
    user_id = int(member.id)
    
    # 先に応答を返してからデータベース操作を実行
    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんに {amount} VTD を与えました。', ephemeral=True)
    
    set_balance(guild_id, user_id, get_balance(guild_id, user_id) + amount)

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
    interaction_id = ctx.id
    interaction_token = ctx.token
    print(f'Interaction ID: {interaction_id}')
    print(f'Interaction Token: {interaction_token}')
    
    if not is_admin(int(ctx.guild_id), int(ctx.author.id)):
        await ctx.send('このコマンドを実行する権限がありません。', ephemeral=True)
        return
    
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    guild_id = int(ctx.guild_id)
    user_id = int(member.id)
    if get_balance(guild_id, user_id) < amount:
        await ctx.send('対象ユーザーの所持金が不足しています。', ephemeral=True)
        return

    # 先に応答を返してからデータベース操作を実行
    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんから {amount} VTD を押収しました。', ephemeral=True)

    set_balance(guild_id, user_id, get_balance(guild_id, user_id) - amount)

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

@slash_command(name="add_admin", description="Add a user as an admin", options=[
    {
        "name": "user",
        "description": "The user to add as admin",
        "type": 6,
        "required": True
    }
])
async def add_admin(ctx: ComponentContext, user: Member):
    guild_owner_id = get_guild_owner(int(ctx.guild_id))
    if int(ctx.author.id) != int(guild_owner_id):
        await ctx.send('このコマンドを実行する権限がありません。サーバー主のみが実行できます。', ephemeral=True)
        return

    user_id = int(user.id)
    if user_id not in get_admin_user_ids(int(ctx.guild_id)):
        save_admin_user_id(int(ctx.guild_id), user_id)
        await ctx.send(f'{user.mention} さんが管理者として追加されました。', ephemeral=True)
    else:
        await ctx.send(f'{user.mention} さんは既に管理者です。', ephemeral=True)

async def main():
    server_thread()
    await bot.astart()  # bot.start() -> bot.astart() に変更

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
