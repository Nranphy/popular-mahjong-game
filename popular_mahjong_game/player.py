from dataclasses import dataclass, field
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from hashlib import md5
from time import time
import asyncio

from exceptions import *
from utils import *



@dataclass
class Player:
    name:str
    '''玩家昵称'''
    user_id:str
    '''玩家独立ID'''
    email:str
    '''玩家注册邮箱'''
    total_score:int=100
    '''玩家总得分'''
    in_table:str=''
    '''玩家桌号'''
    ws:WebSocket=None
    '''玩家WebSocket连接'''

    def to_dict(self):
        return {
            "name": self.name,
            "user_id": self.user_id,
            "email": self.email,
            "total_score":self.total_score,
            "in_table":self.in_table
        }
    
    @classmethod
    def get_player(cls, user_id:str):
        '''从数据库构造玩家信息，不会实时更新'''
        args = get_player_info(user_id)
        return cls(
            name = args.get("name", "Anonymous"),
            user_id = args.get("user_id", ""),
            email = args.get("email", ""),
        )
    
    def if_in_table(self) -> bool:
        '''玩家是否在桌内'''
        return bool(self.in_table)
    
    def join_table(self, table_code:str):
        '''玩家加入牌桌'''
        if self.if_in_table() and self.in_table != table_code:
            raise PlayerJoinException(403, "用户已在其他牌局中")
        self.in_table = table_code
    
    async def exit_table(self):
        '''玩家退出当前牌桌'''
        self.in_table = ''
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.debug(f"玩家【{self.user_id}】后端关闭Websocket连接时出错，错误类型{e}。")
        self.ws = None
    
    async def connect_websocket(self, ws:WebSocket):
        self.ws = ws
        try:
            while True:
                await asyncio.sleep(10)
                await ws.send_json({
                    "type":"heartbeat"
                })
        except:
            logger.error(f"检测到用户【{self.user_id}】WebSocket连接断开。")
            self.ws = None
    
    async def update_score(self, new_score:int):
        self.total_score = new_score
        logger.debug(f"玩家【{self.user_id}】分数已更新。")
        _save_player_data(self)
        logger.debug(f"玩家【{self.user_id}】分数已保存到数据库。")


@dataclass
class PlayerManager:
    '''在线玩家管理器'''
    player_online:list[Player] = field(default_factory=list)
    '''在线玩家信息，在内存存储更新信息'''
    player_token:dict[str, str] = field(default_factory=dict)
    '''在线玩家token哈希表'''

    def get_online_player(self, user_id:str) -> Player:
        '''从在线玩家中检索目标玩家'''
        for player in self.player_online:
            if player.user_id == user_id:
                return player
        raise UserInvalidException(401, "未找到目标用户")

    def login(self, user_id:str) -> str:
        new_player = Player.get_player(user_id)
        token = self.player_token[user_id] = md5((str(new_player.to_dict())+str(time())).encode()).hexdigest()
        for player in self.player_online:
            if player.user_id == user_id:
                self.player_online.remove(player)
                break
        self.player_online.append(new_player)
        self.player_token[user_id] = token
        return token
    
    async def logout(self, user_id:str):
        if user_id in self.player_token:
            self.player_token.pop(user_id)
            player = self.get_online_player(user_id)
            if player.if_in_table():
                table_code = player.in_table
                from match import table_manager
                await table_manager.exit_table(table_code, user_id)
                _save_player_data(player)
                self.player_online.remove(player)
                return True
            return False

    def if_online(self, user_id:str) -> bool:
        return user_id in self.player_token
    
    def if_user_valid(self, user_id:str, token:str) -> bool:
        return self.player_token.get(user_id, '') == token
    
    def save_all_data(self):
        for player in self.player_online:
            _save_player_data(player)
        logger.info("所有玩家数据已保存。")



    
def _save_player_data(player:Player):
    '''更新Player分数数据'''
    with connection.cursor() as cursor:
        cursor.execute(f"""
        UPDATE {ACCOUNT_TABLES_NAME} 
        SET total_score = {player.total_score} 
        WHERE user_id = '{player.user_id}';""")
        connection.commit()
    logger.debug(f"玩家 {player.user_id} 分数数据成功保存。")

def init_player_manager():
    '''初始化在线用户管理器'''
    global player_manager
    player_manager = PlayerManager()
    logger.info("在线用户管理器初始化初始化完成")

init_player_manager()