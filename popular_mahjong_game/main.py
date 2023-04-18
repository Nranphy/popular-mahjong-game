import uvicorn
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from utils import *
from player import *
from match import *



app = FastAPI()

# 添加中间件支持跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get('/')
async def _():
    return {"text":"This is a test..."}




# hook

# @app.on_event('startup')
# async def startup_handler():
#     connection_open()
#     init_player_manager()
#     init_table_manager()

@app.on_event('shutdown')
async def shutdown_handler():
    player_manager.save_all_data()
    connection_close()



# 登录部分

async def login_auth(user_id:str, token:str):
    '''登录验证'''
    if not player_manager.if_online(user_id):
        raise UserInvalidException(401, "该用户尚未登录")
    if not player_manager.if_user_valid(user_id, token):
        raise UserInvalidException(401, "用户登录验证失败")

@app.post('/register')
async def register_handler(form:RegisterForm):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {ACCOUNT_TABLES_NAME} WHERE user_id = '{form.user_id}';")
        res = cursor.fetchone()
        if res[0]:
            raise HTTPException(422, "该用户ID已存在")
        cursor.execute(f"SELECT COUNT(*) FROM {ACCOUNT_TABLES_NAME} WHERE email = '{form.email}';")
        res = cursor.fetchone()
        if res[0]:
            raise HTTPException(422, "该邮箱已存在")
        
        cursor.execute(f"INSERT INTO {ACCOUNT_TABLES_NAME} (name, user_id, email, password, total_score) VALUES ('{form.name}', '{form.user_id}', '{form.email}', '{form.password}', {INIT_SCORE});")
        connection.commit()
    logger.info(f"新用户注册成功，用户ID为【{form.user_id}】。")
    return {
                "result":"SUCCESS",
                "text":"注册成功"
            }

@app.post('/login')
async def login_handler(form:LoginForm):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {ACCOUNT_TABLES_NAME} WHERE user_id = '{form.user_id}';")
        res = cursor.fetchone()
    if not res:
        raise HTTPException(422, "该用户ID不存在，请先注册")
    if res[4] != form.password:
        raise HTTPException(422, "密码错误")
    token = player_manager.login(form.user_id)
    logger.info(f"玩家【{form.user_id}】登录成功。")
    return {
                "result":"SUCCESS",
                "user_id":form.user_id,
                "token":token
            }

@app.post('/logout')
async def logout_handler(form:LogoutForm):
    await login_auth(form.user_id, form.token)
    await player_manager.logout(form.user_id)
    logger.info(f"玩家【{form.user_id}】已成功登出。")
    return {
                "result":"SUCCESS",
                "user_id":form.user_id
            }


# 大厅部分

@app.post('/hall')
async def hall_handler(form:ListTableForm):
    await login_auth(form.user_id, form.token)
    return {
        "type":"table_list",
        "data":table_manager.list_all_table()
    }

@app.post('/create')
async def create_table_handler(form:CreateTableForm):
    await login_auth(form.user_id, form.token)
    new_table = table_manager.create_new_table()
    logger.debug(f"新牌桌【{new_table.table_code}】创建成功。")
    return {
        "type":"table_info",
        "data": await table_manager.join_table(new_table.table_code, form.user_id)
    }

@app.post('/join')
async def join_table_handler(form:JoinTableForm):
    await login_auth(form.user_id, form.token)
    return {
        "type":"table_info",
        "data": await table_manager.join_table(form.table_code, form.user_id)
    }

@app.post('/exit')
async def exit_table_handler(form:ExitTableForm):
    await login_auth(form.user_id, form.token)
    await table_manager.exit_table(form.table_code, form.user_id)

@app.websocket('/ws/{user_id}/{token}')
async def player_connect(ws:WebSocket, user_id:str, token:str):
    try:
        await login_auth(user_id, token)
    except HTTPException as e:
        await ws.close(1008, reason=e.detail)
        logger.debug(f"玩家【{user_id}】的WebSocket连接因【{e.detail}】断开")
        return
    player = player_manager.get_online_player(user_id)
    if not player.if_in_table():
        await ws.close(1008, reason="玩家尚未在桌内，无法进行WebSocket连接。")
        logger.debug(f"玩家【{user_id}】的WebSocket连接因【用户尚未在桌内】断开")
        return
    await ws.accept()
    logger.info(f"玩家【{user_id}】WebSocket连接成功")
    await player.connect_websocket(ws)



    

if __name__ == '__main__':
    uvicorn.run(
        app=app,
        host="0.0.0.0",
        port=23333)