'''数据库连接等工具模块'''

from pydantic import BaseModel, EmailStr, constr
from loguru import logger
import pymysql

READY_TIMEOUT = 10
'''准备限制时间'''

MATCH_PLAYER_COUNT = 2
'''对局玩家人数'''

THINKING_TIME_LIMIT = 60
'''玩家考虑时间'''

TABLE_WAIT_TIME = 600
'''牌桌未满限制时间'''

INIT_SCORE = 100
'''玩家初始分'''

ACCOUNT_TABLES_NAME = "account"
'''用户注册数据表单'''

TABLE_TABLES_NAME = "tables"
'''牌局信息'''


class RegisterForm(BaseModel):
    name: constr(regex=r'^[a-zA-Z\u4e00-\u9fa5]+$', max_length=7)
    user_id: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=5, max_length=15)
    email: EmailStr
    password: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=8)

class LoginForm(BaseModel):
    user_id: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=5, max_length=15)
    password: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=8)

class LogoutForm(BaseModel):
    user_id: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=5, max_length=15)
    token: str


class ListTableForm(BaseModel):
    user_id: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=5, max_length=15)
    token: str

class CreateTableForm(BaseModel):
    user_id: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=5, max_length=15)
    token: str

class JoinTableForm(BaseModel):
    table_code: constr(regex=r'^[0-9]{4}$')
    user_id: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=5, max_length=15)
    token: str

class ExitTableForm(BaseModel):
    table_code: constr(regex=r'^[0-9]{4}$')
    user_id: constr(regex=r'^[a-zA-Z0-9_]+$', min_length=5, max_length=15)
    token: str


# 数据库连接管理

def connection_open(host='localhost',
            user='mahjong',
            password='MahjongPassword123456',
            database='mahjong',
            **kwargs):
    '''连接到数据库，并将连接暂存到本模块connection变量'''
    global connection
    try:
        connection = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            **kwargs
        )
    except Exception as e:
        logger.error("数据库连接错误，请检查配置项。")
        raise e
    logger.info("数据库连接成功。")
    __init_check()

def __init_check():
    '''如果未创建所需表，则创建并初始化所需表'''
    logger.debug("开始检查是否创建所需表")
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW TABLES LIKE '{ACCOUNT_TABLES_NAME}';")
        res = cursor.fetchone()
        if res:
            logger.info(f"检测到登录表 {ACCOUNT_TABLES_NAME} 已存在。")
        else:
            logger.info(f"登录表 {ACCOUNT_TABLES_NAME} 不存在，开始创建。")
            cursor.execute(f"""
            CREATE TABLE {ACCOUNT_TABLES_NAME}(
            id INT NOT NULL AUTO_INCREMENT,
            name VARCHAR(7) NOT NULL,
            user_id VARCHAR(15) NOT NULL,
            email VARCHAR(320) NOT NULL,
            password VARCHAR(32) NOT NULL,
            total_score INT NOT NULL,
            PRIMARY KEY (id)
            );""")
            connection.commit()
            logger.info(f"登录表 {ACCOUNT_TABLES_NAME} 创建成功！")

def connection_close():
    '''关闭数据库连接'''
    connection.close()
    logger.info("数据库连接已关闭。")

def get_player_info(user_id:str) -> dict:
    '''从数据库获取玩家信息'''
    info_col = ["id", "name", "user_id", "email", "total_score"]
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {','.join(info_col)} FROM {ACCOUNT_TABLES_NAME} WHERE user_id = '{user_id}';")
        res = cursor.fetchone()
    return dict(zip(info_col, res))

connection_open()