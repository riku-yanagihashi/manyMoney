import os
import asyncio
import psycopg2
import datetime
import aiohttp
from interactions import Client, Intents, ComponentContext, slash_command, Member, Button, ButtonStyle, listen, StringSelectMenu
from interactions.api.events import Component
from server import server_thread

TOKEN = os.getenv("TOKEN")
DB_DSN = os.getenv("DB")

# SQL文を実行する関数
def execute(sql_query: str, params: tuple=(), fetch=False):
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    try:
        sql = sql_query % params
        cur.execute(sql)
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
    return data

# テーブルの作成
execute('CREATE TABLE IF NOT EXISTS balances (guildid BIGINT, userid BIGINT, balance INTEGER, PRIMARY KEY(guildid, userid))')
execute('CREATE TABLE IF NOT EXISTS admins (guildid BIGINT, userid BIGINT, PRIMARY KEY(guildid, userid))')
execute('CREATE TABLE IF NOT EXISTS requests(id SERIAL NOT NULL, guildid BIGINT, claimantid BIGINT, billeduserid BIGINT, amount BIGINT, deadline TEXT, PRIMARY KEY(id))', fetch=False)

# 所持金データを読み込む関数
def get_balance(guildid, userid):
    result = execute('SELECT balance FROM balances WHERE guildid=%s AND userid=%s', (guildid, userid), fetch=True)
    return result[0][0] if result else 0

# 所持金データを保存する関数
def set_balance(guildid, userid, balance):
    try:
        execute('INSERT INTO balances (guildid, userid, balance) VALUES (%s, %s, %s)', (guildid, userid, balance))
    except psycopg2.IntegrityError:
        execute('UPDATE balances SET balance = %s WHERE guildid = %s AND userid = %s', (balance, guildid, userid))

# 管理者ユーザーIDを読み込む関数
def get_admin_user_ids(guildid):
    data = [c[0] for c in execute('SELECT userid FROM admins WHERE guildid=%s', (guildid,), fetch=True)]
    return data

# 管理者ユーザーIDを保存する関数
def save_admin_user_id(guildid, userid):
    if userid not in get_admin_user_ids(guildid):
        execute('INSERT INTO admins (guildid, userid) VALUES (%s, %s)', (guildid, userid))

# 請求を読み込む関数
def get_requests(guildid, userid):
    data = execute('SELECT claimantid, amount, id FROM requests WHERE guildid=%s AND billeduserid=%s', (guildid, userid), fetch=True)
    return data

# 請求を保存する関数
def save_request(guildid, claimantid, billeduserid, amount):
    deadline = str(datetime.datetime.today()+datetime.timedelta(days=5))
    execute('INSERT INTO requests(guildid, claimantid, billeduserid, amount, deadline) VALUES (%s, %s, %s, %s, \'%s\')', (guildid, claimantid, billeduserid, amount, deadline))
    # 保存した請求のIDを取得
    request_id:int = execute('SELECT id FROM requests WHERE guildid=%s AND claimantid=%s AND billeduserid=%s AND amount=%s AND deadline=\'%s\'', (guildid, claimantid, billeduserid, amount, deadline), fetch=True)[0][0]
    return request_id

# 請求の情報を読み込む関数
def get_pay(id:int|list):
    if type(id)==int:
        data = execute('SELECT guildid, claimantid, billeduserid, amount FROM requests WHERE id=%s', (id,), fetch=True)[0]
    else:
        args = tuple(c for c in id)
        data = execute(f'SELECT guildid, claimantid, billeduserid, amount FROM requests WHERE id IN ({", ".join(["%s"]*len(id))})', args, fetch=True)
    return data

# 請求を支払う関数
def pay_request(id:int|list):
    data = get_pay(id)
    if type(id)==int:
        execute('DELETE FROM requests WHERE id=%s', (id,))
        set_balance(data[0], data[2], get_balance(data[0], data[2]) - data[3])
        set_balance(data[0], data[1], get_balance(data[0], data[1]) + data[3])
    else:
        amount = sum([c[3] for c in data])
        set_balance(data[0][0], data[0][2], get_balance(data[0][0], data[0][2]) - amount)
        for c in data:
            set_balance(c[0], c[1], get_balance(c[0], c[1]) + c[3])
        sql = f'DELETE FROM requests WHERE id IN ({", ".join(["%s"]*len(data))})'
        execute(sql, tuple(id))

# インテントの設定
intents = Intents.DEFAULT | Intents.GUILD_MEMBERS

# 接続に必要なオブジェクトを生成
bot = Client(token=TOKEN, intents=intents)

# ボットが起動したときの処理
@bot.listen()
async def on_ready():
    print(f'ログイン成功 {bot.user.username}')

# サーバー主を特定する関数
def get_guild_owner(guild_id):
    guild = bot.get_guild(guild_id)
    return guild._owner_id

# 管理者ユーザーかを判定する関数
def is_admin(guildid, userid):
    return userid in get_admin_user_ids(guildid) or get_guild_owner(guildid) == userid

# ユーザーの所持金を表示するコマンド
@slash_command(name="balance", description="ユーザーの所持金を表示するコマンド。", options=[
    {
        "name": "user",
        "description": "ユーザーを任意で指定することでそのユーザーの所持金を表示",
        "type": 6,  # USER
        "required": False
    }
])
async def balance(ctx: ComponentContext, user=None):
    await ctx.defer(ephemeral=True)
    target_user = user or ctx.author
    guild_id = str(ctx.guild_id)
    user_id = str(target_user.id)
    balance = get_balance(guild_id, user_id)
    await ctx.send(f'{target_user.mention}さんの所持金は {balance} VTD です。', ephemeral=True)

    
# 通貨の受け渡しを行うコマンド
@slash_command(name="pay", description="他の人にVTDを支払うことができるコマンド", options=[
    {
        "name": "amount",
        "description": "金額を設定",
        "type": 4,  # INTEGER
        "required": True
    },
    {
        "name": "member",
        "description": "対象を指定",
        "type": 6,  # USER
        "required": True
    }
])
async def pay(ctx: ComponentContext, amount: int, member: Member):
    await ctx.defer()
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
    
    set_balance(guild_id, giver_id, get_balance(guild_id, giver_id) - amount)
    set_balance(guild_id, receiver_id, get_balance(guild_id, receiver_id) + amount)

    # 支払ったユーザーにメッセージを送信
    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんに {amount} VTD を渡しました。')
    

# 通貨の請求を行うコマンド
@slash_command(name="request", description="他人にVTDを請求できる", options=[
    {
        "name": "amount",
        "description": "金額を設定",
        "type": 4,  # INTEGER
        "required": True
    },
    {
        "name": "member",
        "description": "対象を指定",
        "type": 6,  # USER
        "required": True
    }
])
async def request(ctx: ComponentContext, amount: int, member: Member):
    await ctx.defer()
    if amount <= 0:
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    request_id = save_request(ctx.guild_id, ctx.author_id, member.id, amount)
    button = Button(style=ButtonStyle.PRIMARY, label="支払う", custom_id=f"pay_now:{request_id},{member.id}")
    await ctx.send(f'{member.mention} さん、{ctx.author.mention} さんから {amount} VTD の請求がありました。', components=button)

# 請求の一覧を表示するコマンド
@slash_command(name="show_requests", description="請求の一覧を表示します", options=[
    {
        "name": "member",
        "description": "対象を指定",
        "type": 6,  # INTEGER
        "required": False
    }
])
async def show_requests(ctx: ComponentContext, member: Member=None):
    guild_id = ctx.guild_id
    user_id = None
    if member != None:
        user_id = member.id
    else:
        user_id = ctx.author_id
    requests = get_requests(guild_id, user_id)
    print(requests)
    msg = f'## 現在の請求\n'+'\n'.join([f'{i}. {bot.get_user(value[0]).mention}: {value[1]} VTD' for i, value in enumerate(requests)])+f'\n\n**合計:{sum([c[1] for c in requests])} VTD**'
    options = []
    for value in requests:
        member = bot.get_user(value[0])
        label = f"{member.username}: {value[1]} VTD"
        options.append({
            "label": label,
            "value": str(value[2])
        })
    
    if len(options) != 0:
        select_menu = StringSelectMenu(options, custom_id="select_request", placeholder="請求を選択してください")
        pay_all_requests = Button(style=ButtonStyle.SECONDARY, label="全て支払う", custom_id=f"pay_all:{user_id}")
        pay_request = Button(style=ButtonStyle.PRIMARY, label="支払う", custom_id="pay_selected", disabled=True)

        await ctx.send(msg, components=[[select_menu], [pay_all_requests, pay_request]], ephemeral=True)
    else:
        await ctx.send(msg, ephemeral=True)
@listen()
async def on_component(event: Component):
    ctx = event.ctx
    
    if ctx.custom_id.startswith("pay_now:"):
        await ctx.defer()
        request_id = int(ctx.custom_id.split(":")[1].split(",")[0])
        billed_user_id = int(ctx.custom_id.split(":")[1].split(",")[1])
        if ctx.author_id == billed_user_id:
            if not get_balance(ctx.guild_id, billed_user_id) < get_pay(request_id)[3]:
                try:
                    pay_request(request_id)
                    await ctx.send('請求が正常に支払われました。')
                except Exception as e:
                    await ctx.send(f'請求の支払いに失敗しました: {str(e)}', ephemeral=True)
            else:
                await ctx.send(f'所持金が不足しています。\n**現在の所持金:{get_balance(ctx.guild_id, billed_user_id)}**', ephemeral=True)
        else:
            await ctx.send('あなたに対する請求ではありません。', ephemeral=True)
    elif ctx.custom_id.startswith("pay_all:"):
        await ctx.defer(ephemeral=True)
        user_id = int(ctx.custom_id.split(":")[1])
        if ctx.author_id == user_id:
            if not get_balance(ctx.guild_id, user_id) < sum([c[1] for c in get_requests(ctx.guild_id, user_id)]):
                ids = [c[2] for c in get_requests(ctx.guild_id, user_id)]
                pay_request(ids)
                await ctx.send(f'全ての請求が正常に支払われました。')
            else:
                await ctx.send(f'所持金が不足しています。\n**現在の所持金:{get_balance(ctx.guild_id, user_id)}**', ephemeral=True)
        else:
            await ctx.send('あなたに対する請求ではありません。', ephemeral=True)
    elif ctx.custom_id == "select_request":
        await ctx.defer(edit_origin=True)
        # print(ctx.values[0])
        selected_request_id = int(ctx.values[0])
        select_menu = ctx.message.components[0].components[0]
        select_menu_dict = select_menu.to_dict()
        print(select_menu_dict['options'])
        for option in select_menu_dict['options']:
            if option['value'] == str(selected_request_id):
                option['default'] = True
            else:
                option['default'] = False
        select_menu = StringSelectMenu.from_dict(select_menu_dict)
        pay_all_requests = ctx.message.components[1].components[0]
        pay_request_button = Button(style=ButtonStyle.PRIMARY, label="支払う", custom_id=f"pay_selected:{selected_request_id}")

        await ctx.edit_origin(components=[[select_menu], [pay_all_requests, pay_request_button]])
    elif ctx.custom_id.startswith("pay_selected:"):
        await ctx.defer(ephemeral=True)
        request_id = int(ctx.custom_id.split(":")[1])
        print(request_id)
        try:
            billed_user_id = get_pay(request_id)[2]
            if ctx.author.id == billed_user_id:
                if not get_balance(ctx.guild_id, billed_user_id) < get_pay(request_id)[3]:
                    try:
                        pay_request(request_id)
                        await ctx.send('選択した請求が正常に支払われました。')
                    except Exception as e:
                        await ctx.send(f'請求の支払いに失敗しました: {str(e)}', ephemeral=True)
                else:
                    await ctx.send(f'所持金が不足しています。\n**現在の所持金:{get_balance(ctx.guild_id, billed_user_id)}**', ephemeral=True)
            else:
                await ctx.send('あなたに対する請求ではありません。', ephemeral=True)
        except IndexError:
            await ctx.send(content=f"既に支払い済みです。")

# 管理者がユーザーに通貨を与えるコマンド
@slash_command(name="give", description="ユーザーにVTDを与えることができる(管理者専用))", options=[
    {
        "name": "amount",
        "description": "金額を設定",
        "type": 4,  # INTEGER
        "required": True
    },
    {
        "name": "member",
        "description": "対象を指定",
        "type": 6,  # USER
        "required": True
    }
])
async def give(ctx: ComponentContext, amount: int, member: Member):
    if not is_admin(int(ctx.guild_id), int(ctx.author.id)):
        await ctx.defer(ephemeral=True)
        await ctx.send('このコマンドを実行する権限がありません。', ephemeral=True)
        return
    
    if amount <= 0:
        await ctx.defer(ephemeral=True)
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    await ctx.defer()
    guild_id = int(ctx.guild_id)
    user_id = int(member.id)
    set_balance(guild_id, user_id, get_balance(guild_id, user_id) + amount)

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんに {amount} VTD を与えました。')

# 管理者がユーザーから通貨を押収するコマンド
@slash_command(name="confiscation", description="ユーザーからVTDを押収するコマンド", options=[
    {
        "name": "amount",
        "description": "金額を設定",
        "type": 4,  # INTEGER
        "required": True
    },
    {
        "name": "member",
        "description": "対象を設定",
        "type": 6,  # USER
        "required": True
    }
])
async def confiscation(ctx: ComponentContext, amount: int, member: Member):
    if not is_admin(int(ctx.guild_id), int(ctx.author.id)):
        await ctx.defer(ephemeral=True)
        await ctx.send('このコマンドを実行する権限がありません。', ephemeral=True)
        return
    
    if amount <= 0:
        await ctx.defer(ephemeral=True)
        await ctx.send('金額は正の整数でなければなりません。', ephemeral=True)
        return
    
    guild_id = int(ctx.guild_id)
    user_id = int(member.id)
    if get_balance(guild_id, user_id) < amount:
        await ctx.defer(ephemeral=True)
        await ctx.send('対象ユーザーの所持金が不足しています。', ephemeral=True)
        return
    
    await ctx.defer()
    
    set_balance(guild_id, user_id, get_balance(guild_id, user_id) - amount)

    await ctx.send(f'{ctx.author.mention} さんが {member.mention} さんから {amount} VTD を押収しました。')

# 管理者を追加するコマンド（サーバー主のみ実行可能）
@slash_command(name="add_admin", description="このアプリの管理者権限ユーザーを設定します", options=[
    {
        "name": "user",
        "description": "対象を指定",
        "type": 6,  # USER
        "required": True
    }
])
async def add_admin(ctx: ComponentContext, user: Member):
    await ctx.defer(ephemeral=True)
    guild_owner_id = get_guild_owner(int(ctx.guild_id))
    if str(ctx.author.id) != str(guild_owner_id):
        await ctx.send('このコマンドを実行する権限がありません。サーバー主のみが実行できます。', ephemeral=True)
        return

    user_id = int(user.id)
    if user_id not in get_admin_user_ids(int(ctx.guild_id)):
        save_admin_user_id(int(ctx.guild_id), user_id)
        await ctx.send(f'{user.mention} さんが管理者として追加されました。', ephemeral=True)
    else:
        await ctx.send(f'{user.mention} さんは既に管理者です。', ephemeral=True)

# 管理者表示だぜぃ
@slash_command(name="admin_list", description="管理者リストを表示")
async def admin_list(ctx: ComponentContext):
    await ctx.defer(ephemeral=True) # 考え中みたいなやつ（多分）
    
    guild_id = ctx.guild_id
    admin_ids = get_admin_user_ids(guild_id)
    admin_mentions = []
    for admin_id in admin_ids:
        user = await bot.fetch_user(admin_id)
        if user:
            admin_mentions.append(user.mention)
    
    if admin_mentions:
        msg = "現在の管理者:\n" + "\n".join(admin_mentions)
    else:
        msg = "管理者が見つかりませんでした。"
    
    await ctx.send(msg, ephemeral=True)

# すべてのユーザーの所持金をセットできるコマンド
@slash_command(name="set_all_balances", description="すべてのユーザーの所持金を設定できる", options=[
    {
        "name": "amount",
        "description": "金額を設定",
        "type": 4,  # INTEGER
        "required": True
    }
])
async def set_all_balances(ctx: ComponentContext, amount: int):
    await ctx.defer(ephemeral=True)

    if not is_admin(int(ctx.guild_id), int(ctx.author.id)):
        await ctx.send('このコマンドを実行する権限がありません。', ephemeral=True)
        return
    
    if amount < 0:
        await ctx.send('金額は0以上でなければなりません。', ephemeral=True)
        return

    guild_id = ctx.guild_id
    url = f"https://discord.com/api/v10/guilds/{guild_id}/members?limit=1000"
    headers = {
        "Authorization": f"Bot {TOKEN}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                await ctx.send(f'メンバーの取得に失敗しました。ステータスコード: {response.status}', ephemeral=True)
                return
            
            members = await response.json()

    for member in members:
        user_id = int(member["user"]["id"])
        # balancesテーブルにユーザーが存在するか確認し、存在しない場合は新規に追加する
        if get_balance(guild_id, user_id) == 0:
            set_balance(guild_id, user_id, amount)
        else:
            execute('UPDATE balances SET balance = %s WHERE guildid = %s AND userid = %s', (amount, guild_id, user_id))

    await ctx.send(f'すべてのユーザーの所持金が {amount} VTD に設定されました。', ephemeral=True)
# TODO:あと何があるん？

async def main():
    server_thread()
    await bot.astart()
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
