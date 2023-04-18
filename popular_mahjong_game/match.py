from typing import Optional, Deque, Literal
from collections import deque, Counter
from dataclasses import dataclass, field
from fastapi import WebSocket
from loguru import logger
from hashlib import md5
import random
import asyncio

from player import Player, player_manager
from utils import MATCH_PLAYER_COUNT, THINKING_TIME_LIMIT, READY_TIMEOUT, TABLE_WAIT_TIME
from exceptions import *


@dataclass
class PlayerInMatch:
    name:str
    '''玩家昵称'''
    user_id:str
    '''玩家独立ID'''
    player_index:int
    '''牌局玩家序号'''
    ws:WebSocket
    '''玩家WebSocket连接'''
    close:list[str]=field(default_factory=list)
    '''玩家手牌'''
    open:list[tuple[str,...]]=field(default_factory=list)
    '''玩家副露，为(种类,牌,...)元组'''
    draw:str=None
    '''摸到的单张牌'''
    discard:list[tuple[str,bool]]=field(default_factory=list)
    '''牌河，为(牌,是否手切)元组'''
    score:int=0
    '''玩家获得分数'''
    
    @classmethod
    def construct(cls, player:Player, index:int):
        '''通过局外 Player 构造局内 PlayerInMatch 对象'''
        return cls(
            name=player.name,
            user_id=player.user_id,
            player_index=index,
            ws=player.ws,
            score=player.total_score
        )
    
    def action_check(self, new:str=None, target_player_index:int=None, need_discard:bool=False, only_discard:bool=False) -> list[dict]:
        actions = []
        if only_discard or need_discard:
            actions.append({
                "action": "discard",
                "player_index": self.player_index,
            })
            if only_discard:
                return actions
        if new:
            if target_player_index==None:
                actions:list[dict] = actions+self._kan_check(new, target_player_index)+self._win_check(new, target_player_index)
            else:
                actions:list[dict] = actions+self._kan_check(new, target_player_index)+self._win_check(new, target_player_index)\
                    +self._chi_check(new, target_player_index)+self._pon_check(new, target_player_index)
        return actions
        

    def _chi_check(self, new:str, target_player_index:int) -> list[dict]:
        res = []
        if not ((self.player_index and self.player_index-1==target_player_index) or (not self.player_index and target_player_index+1==MATCH_PLAYER_COUNT)):
            return res
        num, type = int(new[0]), new[1]
        # (A) B C型
        if f"{num+1}"+type in self.close and f"{num+2}"+type in self.close:
            res.append({
                "action": "chi",
                "tile_type": new,
                "player_index": self.player_index,
                "target_player_index": target_player_index,
                "tiles": [f"{num+1}"+type, f"{num+2}"+type]
            })
        # A (B) C型
        if f"{num-1}"+type in self.close and f"{num+1}"+type in self.close:
            res.append({
                "action": "chi",
                "tile_type": new,
                "player_index": self.player_index,
                "target_player_index": target_player_index,
                "tiles": [f"{num-1}"+type, f"{num+1}"+type]
            })
        # A B (C)型
        if f"{num-1}"+type in self.close and f"{num-2}"+type in self.close:
            res.append({
                "action": "chi",
                "tile_type": new,
                "player_index": self.player_index,
                "target_player_index": target_player_index,
                "tiles": [f"{num-1}"+type, f"{num-2}"+type]
            })
        return res

    def _pon_check(self, new:str, target_player_index:int) -> list[dict]:
        if self.close.count(new)>=2:
            return [{
                "action": "pon",
                "tile_type": new,
                "player_index": self.player_index,
                "target_player_index": target_player_index
            }]
        else:
            return []

    def _kan_check(self, new:str, target_player_index:int=None) -> list[dict]:
        res = []
        if target_player_index==None:
            # 检查暗杠
            temp_close = self.close.copy() + [new]
            cnt = Counter(temp_close)
            for i,v in cnt:
                if v==4:
                    res.append({
                        "action":"kan",
                        "kan_type":"concealed",
                        "tile_type":i,
                        "player_index": self.player_index,
                        "target_player_index": target_player_index
                    })
            # 检查加杠
            for open in self.open:
                if open[0] == 'pon' and open[1]==new:
                    res.append({
                        "action":"kan",
                        "kan_type":"extended",
                        "tile_type":new,
                        "player_index": self.player_index,
                        "target_player_index": target_player_index
                    })
        else:
            # 检查大明杠
            if self.close.count(new)==3:
                res.append({
                    "action":"kan",
                    "kan_type":"exposed",
                    "tile_type":new,
                    "player_index": self.player_index,
                    "target_player_index": target_player_index
                })
        return res

    def _win_check(self, new:str, target_player_index:int=None) -> list[dict]:
        from collections import Counter
        all_close = Counter(self.close+[new])
        posible = []
        def get_next_tile(tile:str)->str:
            num = int(tile[0])
            if num==9:
                return ''
            else:
                return str(num+1)+tile[1]
        def get_last_tile(tile:str)->str:
            num = int(tile[0])
            if num==1:
                return ''
            else:
                return str(num-1)+tile[1]
        def dfs(last_close:Counter[str], temp_tiles:list[tuple[str]]):
            nonlocal posible
            # 边界条件，只剩雀头或不合法
            if sum(last_close.values()) <= 2:
                for k,v in last_close.items():
                    if v==2:
                        posible.append(temp_tiles+[[k]*2])
                        break
                return
            # 递归求所有拆牌可能性
            for k,v in last_close.items():
                # 以k成刻子
                if v>=3:
                    new_close = last_close.copy()
                    new_close[k] -= 3
                    dfs(last_close=new_close, temp_tiles=temp_tiles+[(k)*3])
                # 以k为中心的顺子
                if v and last_close[get_last_tile(k)] and last_close[get_next_tile(k)]:
                    new_close = last_close.copy()
                    new_close[k] -= 1
                    new_close[get_last_tile(k)] -= 1
                    new_close[get_next_tile(k)] -= 1
                    dfs(last_close=new_close, temp_tiles=temp_tiles+[(get_last_tile(k), k, get_next_tile(k))])
            return
        dfs(all_close, [])
        win_result = []
        # 清一色最后统一检查
        # 七对子检查
        if not self.open:
            flag = 1
            for k,v in all_close.items():
                if v%2:
                    flag = 0
                    break
            if flag:
                win_result.append([12,["七对子"]])
        # 常规和牌番数计算
        def check_win(tiles:list[tuple[str]]) -> list:
            res = [3, ["素和"]]
            # 基本和检查（全是顺子）
            flag = 1
            for tile in tiles:
                if len(tile)!=2 and len(set(tile)) == 1:
                    flag = 0
                    break
            if flag:
                res[0] += 3
                res[1].append("基本和")
            # 对对和检查（全是顺子）
            flag = 1
            for tile in tiles:
                if len(tile)!=2 and len(set(tile)) != 1:
                    flag = 0
                    break
            if flag:
                res[0] += 5
                res[1].append("对对和")
            return res
        for tiles in posible:
            all_tile = tiles+self.open
            res = check_win(all_tile)
            win_result.append(res)
        # 清一色检查
        all_tiles = self.close+[new]
        for open_tiles in self.open:
            all_tiles.extend(open_tiles)
        color_cnt = Counter(tile[1] for tile in all_tiles)
        if len(color_cnt) == 1:
            for win in win_result:
                win[0] += 9
                win[1].append("清一色")
        # 最终选择
        win_result.sort(reverse=True)
        if win_result:
            return [{
                "action": "win",
                "tile_type": new,
                "player_index": self.player_index,
                "target_player_index": target_player_index
            }]
        else:
            return []
    
    def to_dict(self):
        return {
            "name":self.name,
            "user_id":self.user_id,
            "close":self.close,
            "open":self.open,
            "draw":self.draw,
            "discard":self.discard,
            "score":self.score
        }
    
    def to_public_dict(self):
        return {
            "name":self.name,
            "user_id":self.user_id,
            "open":self.open,
            "draw":self.draw,
            "discard":self.discard,
            "score":self.score
        }



class Match:
    '''单场牌局类，不控制牌局进程，只对牌局本身状态进行控制'''
    
    player:list[PlayerInMatch]
    '''游戏玩家，首位为庄家'''
    initial_deck:list[str]
    '''对局牌堆'''
    hash:str
    '''牌堆哈希'''
    rand_seed:Optional[int]=None
    '''给定的随机种子'''

    deck:Deque[str]
    '''牌堆，会时刻变化'''
    turn:int = 0
    '''摸牌次序'''
    result:dict={}
    '''牌局结果，可以用以判断牌局是否结束'''

    def __init__(self, players:list[Player], rand_seed:Optional[int]=None):
        self.player = [PlayerInMatch.construct(player, i) for i, player in enumerate(players)]
        self._shuffle_deck(rand_seed)
        self._initial_hand()
    
    def draw(self, player_index:int=None, turn_change:bool=True, wall_end:bool=False) -> tuple[int, str]:
        '''
        玩家摸牌
        :param player_index: 摸牌玩家的序号，默认为self.turn值
        :param turn_change: self.turn是否变化，默认为True
        :param wall_end: 是否从牌堆末摸牌，默认为False
        :rtype: 返回(摸牌玩家序号, 摸牌牌面)
        '''
        if player_index==None:
            player_index = self.turn
        self._draw_to_close(player_index)
        player = self.player[player_index]
        if not self.deck:
            self.result = {
                "end_type":"draw_end",
            }
            raise MatchEndedException("牌堆为空，牌局结束。")
        if wall_end:
            player.draw = self.deck.pop()
        else:
            player.draw = self.deck.popleft()
        if turn_change:
            self._turn_change()
        return player_index, player.draw

    def discard(self, player_index:int, tile_type:str='', discard_draw:bool=True) -> str:
        '''玩家切牌'''
        player = self.player[player_index]
        if not tile_type and not discard_draw:
            raise DiscardException(f"切牌信息不足，切牌失败。")
        elif (discard_draw and player.draw==tile_type) or (discard_draw and not tile_type and player.draw):
            player.discard.append((player.draw, False))
            tile_type = player.draw
        elif discard_draw and not tile_type and player.draw:
            tile_type = player.close.pop()
            player.discard.append((tile_type, True))
            logger.debug("玩家默认切牌且draw区为空，已自动切手牌。")
        else:
            flag = False
            for i, tile in enumerate(player.close):
                if tile==tile_type:
                    flag = True
                    player.discard.append((tile_type, True))
                    if player.draw: # 摸了牌的情况
                        player.close[i] = player.draw
                    else: # 没摸牌的情况
                        player.close.pop(i)
                    break
            if not flag:
                tile_type = player.close.pop()
                player.discard.append((tile_type, True))
                logger.error("玩家选择切牌错误，已自动切手牌。")
        player.draw = None
        return tile_type

    def chi(self, player_index:int, target_player_index:int, tile_type:str, tiles:tuple[str,str]):
        '''吃'''
        player = self.player[player_index]
        target_player_index = player_index-1 if player_index else MATCH_PLAYER_COUNT-1
        if len(tiles) != 2:
            raise ChiException(f"指定吃牌数量错误，长度应为2，而现在为{len(tiles)}。")
        for tile in tiles:
            if tile not in player.close:
                raise ChiException(f"所指定吃牌在手牌中不存在，出错吃牌：{tiles}，手牌：{player.close}。")
        if self.player[target_player_index].discard[-1][0] != tile_type:
            raise ChiException(f"所吃牌不同于指定吃牌，将吃的牌为{self.player[target_player_index].discard[-1][0]}，而指定的牌为{tile_type}。")
        temp_tiles = sorted([*tiles, tile_type])
        if len(set([tile[1] for tile in temp_tiles]))!=1 or int(temp_tiles[0][0])+1!=int(temp_tiles[1][0]) or int(temp_tiles[1][0])+1!=int(temp_tiles[2][0]):
            raise ChiException(f"所指定吃牌条件不成立，出错吃牌面子：{temp_tiles}。")
        self.player[target_player_index].discard.pop()
        for tile in tiles:
            player.close.remove(tile)
        player.open.append(("chi", *temp_tiles))
        self._turn_change(cur_turn=player_index)

    def pon(self, player_index:int, target_player_index:int, tile_type:str):
        '''碰'''
        player = self.player[player_index]
        if self.player[target_player_index].discard[-1][0] != tile_type:
            raise PonException(f"所碰牌不同于指定吃牌，将碰的牌为{self.player[target_player_index].discard[-1][0]}，而指定的牌为{tile_type}。")
        if player.close.count(tile_type) < 2:
            raise PonException(f"所指定碰牌条件不成立，出错碰牌：{tile_type}，手牌：{player.close}。")
        self.player[target_player_index].discard.pop()[0]
        player.close.remove(tile_type)
        player.close.remove(tile_type)
        player.open.append(("pon", *[tile_type for _ in range(3)]))
        self._turn_change(cur_turn=player_index)

    def kan(self, player_index:int, tile_type:str, kan_type:Literal["concealed","exposed","extended"], target_player_index:Optional[int]=None):
        '''杠'''
        player = self.player[player_index]
        if kan_type=='concealed':
            if player.draw == tile_type and player.close.count(tile_type) == 3:
                player.draw = None
                for _ in range(3):
                    player.close.remove(tile_type)
                player.open.append(("con_kan", *[tile_type for _ in range(4)]))
            elif player.draw != tile_type and player.close.count(tile_type) == 4:
                for _ in range(4):
                    player.close.remove(tile_type)
                self._draw_to_close(player_index)
                player.open.append(("con_kan", *[tile_type for _ in range(4)]))
            else:
                raise KanException("暗杠条件不成立，请检查杠牌模式是否选择错误。")
        elif kan_type=='exposed' and target_player_index!=None:
            if self.player[target_player_index].discard[-1][0] != tile_type:
                raise KanException(f"明杠条件不成立，所杠牌不同于指定的牌。将杠的牌为{self.player[target_player_index].discard[-1][0]}，而指定的牌为{tile_type}。")
            if player.close.count(tile_type) != 3:
                raise KanException(f"手牌中将要杠的牌不为3张，将杠的牌为{tile_type}，而手牌为{player.close}。")
            self.player[target_player_index].discard.pop()
            for _ in range(3):
                player.close.remove(tile_type)
            player.open.append(("exp_kan", *[tile_type for _ in range(4)]))
        elif kan_type=='extended':
            temp_close = player.close + [player.draw]
            if tile_type not in temp_close:
                raise KanException("加杠缺少所指定的牌。")
            flag = False
            for open in player.open:
                if open[0]=='pon' and open[1]==tile_type:
                    if player.draw == tile_type:
                        player.draw = None
                    else:
                        player.close.remove(tile_type)
                    open = ["exp_kan", *[tile_type for _ in range(4)]]
                    flag = True
                    break
            if not flag:
                raise KanException("未找到可加杠的副露碰牌。")
        else:
            raise KanException(f"所指定杠牌类型错误，类型应为concealed, exposed, extended其一，而非{kan_type}。")
        self.turn = player_index
        
    def win(self, player_index:int, tile_type:str, target_player_index:Optional[int]=None):
        '''玩家和牌'''
        player = self.player[player_index]
        from collections import Counter
        all_close = Counter(player.close+[tile_type])
        posible = []
        def get_next_tile(tile:str)->str:
            num = int(tile[0])
            if num==9:
                return ''
            else:
                return str(num+1)+tile[1]
        def get_last_tile(tile:str)->str:
            num = int(tile[0])
            if num==1:
                return ''
            else:
                return str(num-1)+tile[1]
        def dfs(last_close:Counter[str], temp_tiles:list[tuple[str]]):
            nonlocal posible
            # 边界条件，只剩雀头或不合法
            if sum(last_close.values()) <= 2:
                for k,v in last_close.items():
                    if v==2:
                        posible.append(temp_tiles+[[k]*2])
                        break
                return
            # 递归求所有拆牌可能性
            for k,v in last_close.items():
                # 以k成刻子
                if v>=3:
                    new_close = last_close.copy()
                    new_close[k] -= 3
                    dfs(last_close=new_close, temp_tiles=temp_tiles+[(k)*3])
                # 以k为中心的顺子
                if v and last_close[get_last_tile(k)] and last_close[get_next_tile(k)]:
                    new_close = last_close.copy()
                    new_close[k] -= 1
                    new_close[get_last_tile(k)] -= 1
                    new_close[get_next_tile(k)] -= 1
                    dfs(last_close=new_close, temp_tiles=temp_tiles+[(get_last_tile(k), k, get_next_tile(k))])
            return
        dfs(all_close, [])
        win_result = []
        # 清一色最后统一检查
        # 七对子检查
        if not player.open:
            flag = 1
            for k,v in all_close.items():
                if v%2:
                    flag = 0
                    break
            if flag:
                win_result.append([12,["七对子"]])
        # 常规和牌番数计算
        def check_win(tiles:list[tuple[str]]) -> list:
            res = [3, ["素和"]]
            # 基本和检查（全是顺子）
            flag = 1
            for tile in tiles:
                if len(tile)!=2 and len(set(tile)) == 1:
                    flag = 0
                    break
            if flag:
                res[0] += 3
                res[1].append("基本和")
            # 对对和检查（全是顺子）
            flag = 1
            for tile in tiles:
                if len(tile)!=2 and len(set(tile)) != 1:
                    flag = 0
                    break
            if flag:
                res[0] += 5
                res[1].append("对对和")
            return res
        for tiles in posible:
            all_tile = tiles+player.open
            res = check_win(all_tile)
            win_result.append(res)
        # 清一色检查
        all_tiles = player.close+[tile_type]
        for open_tiles in player.open:
            all_tiles.extend(open_tiles)
        color_cnt = Counter(tile[1] for tile in all_tiles)
        if len(color_cnt) == 1:
            for win in win_result:
                win[0] += 9
                win[1].append("清一色")
        # 最终选择
        win_result.sort(reverse=True)
        if not win_result:
            raise WinException("牌型未构成和牌")
        self.result = {
            "end_type": "ron" if target_player_index!=None else "zimo",
            "winner": self.player[player_index].to_dict().get("name", ""),
            "loser": [self.player[target_player_index].to_dict().get("name", "")] if target_player_index!=None else [self.player[i].to_dict().get("name", "") for i in range(MATCH_PLAYER_COUNT) if i!=player_index],
            "attribute": win_result[0][1],
            "score": win_result[0][0]
        }
        raise MatchEndedException("玩家和牌，牌局结束")


    def _turn_change(self, cur_turn:int=None, next_turn:int=None):
        '''将turn转到下一位玩家，如果提供了cur_turn则为其下一位，如果提供了next_turn则为其'''
        if cur_turn!=None:
            self.turn = (cur_turn+1)%MATCH_PLAYER_COUNT
        elif next_turn!=None:
            self.turn = next_turn
        else:
            self.turn = (self.turn+1)%MATCH_PLAYER_COUNT

    def _draw_to_close(self, player_index:int):
        '''将摸牌放入手牌中'''
        player = self.player[player_index]
        if player.draw:
            player.close.append(self.player[player_index].draw)
            player.draw = None

    def _shuffle_deck(self, rand_seed:Optional[int]=None):
        self.rand_seed = rand_seed
        random.seed(rand_seed)
        temp_deck = [f"{num}{color}" for _ in range(4) for num in range(1,10) for color in "msp"]
        random.shuffle(temp_deck)
        temp_deck = ["1m", "1m", "2m", "2m", "3m", "4m", "5s", "5s", "3m", "3p", "3p", "4p", "5m", "3p", "7s", "8s", "4p", "5s", "5s", "6s", "9s", "6s", "5s", "4s", "6s", "3s", "5m", "9s", "3m", "4s", "9s", "9s"]
        self.hash = md5(''.join(temp_deck).encode()).hexdigest()
        self.initial_deck = temp_deck
        self.deck = deque(temp_deck)

    def _initial_hand(self):
        for turn in range(3):
            for player_index in range(MATCH_PLAYER_COUNT):
                for _ in range(4):
                    self.draw(player_index, False)
        for player_index in range(MATCH_PLAYER_COUNT):
            self.draw(player_index, False)
            self._draw_to_close(player_index)



@dataclass(unsafe_hash=False)
class Table:
    '''牌桌类，控制牌局开始和进行节奏，与用户交流'''
    static_code:int = 1
    table_code:str = field(default_factory=lambda:f"{Table.static_code:04}")
    player:list[Player] = field(default_factory=list)
    match:Match=None
    player_in_match:list[PlayerInMatch] = field(default_factory=list)
    player_request:list[Optional[dict]] = field(default_factory=lambda:[{} for _ in range(MATCH_PLAYER_COUNT)])

    def __post_init__(self):
        Table.static_code += 1
        asyncio.create_task(self.main())

    async def main(self):
        # 每秒检查人数
        time_limit = TABLE_WAIT_TIME # 等待时间限制
        while time_limit>0:
            await asyncio.sleep(1)
            time_limit -= 1
            if len(self.player) == MATCH_PLAYER_COUNT:
                break
        if not time_limit:
            await self.dismiss("在限制时间内人数不足，牌桌被解散。")
            return
        logger.debug(f"牌桌【{self.table_code}】检查到人数已达目标，发送准备请求。")
        # 准备阶段
        await self.ready()
        if not (len(self.player) == MATCH_PLAYER_COUNT and all(req and req.get("type")=="ready" for req in self.player_request)):
            await self.dismiss("有玩家没有准备，牌桌被解散。")
            return
        logger.debug(f"牌桌【{self.table_code}】准备完毕。")
        self.player_request = [{} for _ in range(MATCH_PLAYER_COUNT)]
        res = await self.run()
        await self.send_public_message({
            "type": "end",
            "data": res
        })
        # 用户成绩变更
        logger.debug(f"牌桌【{self.table_code}】牌局结束，准备更新玩家分数。")
        logger.debug(f"牌桌【{self.table_code}】牌局结果如下\n{res}")
        if res.get("end_type") == "zimo":
            score = res.get("score", 0)
            winner_index = res.get("winner")
            for i in range(MATCH_PLAYER_COUNT):
                if i == winner_index:
                    self.player_in_match[i].score += 3*score
                    logger.debug(f"序号【{i}】的玩家【{self.player_in_match[i].user_id}】分数 +3*{score}.")
                else:
                    self.player_in_match[i].score -= score
                    logger.debug(f"序号【{i}】的玩家【{self.player_in_match[i].user_id}】分数 -{score}.")
            logger.debug(f"牌局结束，序号【{winner_index}】的玩家【{self.player_in_match[i].user_id}】{'自摸' if res.get('end_type') == 'zimo' else '荣和'}获胜【{score}*3】点数。")
        elif res.get("end_type") == "ron":
            score:int = res.get("score", 0)
            winner_index:int = res.get("winner")
            loser_index:int = res.get("loser")
            self.player_in_match[winner_index].score += score
            logger.debug(f"序号【{winner_index}】的玩家【{self.player_in_match[winner_index].user_id}】分数 +{score}.")
            self.player_in_match[loser_index].score -= score
            logger.debug(f"序号【{loser_index}】的玩家【{self.player_in_match[loser_index].user_id}】分数 -{score}.")
            logger.debug(f"牌局结束，序号【{winner_index}】的玩家【{self.player_in_match[winner_index].user_id}】{'自摸' if res.get('end_type') == 'zimo' else '荣和'}获胜【{score}*3】点数。")
        else:
            logger.debug(f"牌局结束，荒牌流局。")
        for i in range(MATCH_PLAYER_COUNT):
            await self.player[i].update_score(self.player_in_match[i].score)
        logger.info(f"牌桌【{self.table_code}】牌局结束，桌内玩家分数已更新。")
        # 牌桌解散
        await self.dismiss("牌局结束，牌桌解散。", False)
        return


    async def dismiss(self, reason:str="", send_msg:bool=True):
        if send_msg:
            await self.send_public_message(
                {
                "type": "dismiss",
                "data": reason
                })
        tasks = [asyncio.create_task(table_manager.exit_table(self.table_code, player.user_id, True)) for player in self.player]
        await asyncio.gather(*tasks)
        logger.debug(f"牌桌【{self.table_code}】被解散，原因是【{reason}】。")
        table_manager._remove_table(self)


    def to_dict(self):
        return {
            "table_code":self.table_code,
            "players":[player.to_dict() for player in self.player],
            "if_start":bool(self.match)
        }
    
    async def join(self, user_id:str):
        if len(self.player) >= MATCH_PLAYER_COUNT:
            raise PlayerJoinException(403, "牌桌人数已达到上限")
        player = player_manager.get_online_player(user_id)
        if player.if_in_table() and player.in_table != self.table_code:
            raise PlayerJoinException(403, "用户已在其他牌局中")
        if not player.if_in_table():
            player.join_table(self.table_code)
            self.player.append(player_manager.get_online_player(user_id))
            await self.send_public_message({
                "type":"join",
                "data":self.player[-1].to_dict()
            }, len(self.player)-1)
            logger.debug(f"玩家【{user_id}】加入房间【{self.table_code}】。")
        else:
            # 发送牌局当前信息
            if self.match:
                tasks = [asyncio.create_task(self.send_private_message({
                        "type": "update_info",
                        "data": {
                            "self":self.player_in_match[i].to_dict(), 
                            "table":[player.to_public_dict() for player in self.player_in_match]},
                            "rest_tile":len(self.match.deck)
                    }, i)) for i in range(MATCH_PLAYER_COUNT)]
                await asyncio.gather(*tasks)
            logger.debug(f"玩家【{user_id}】重连房间【{self.table_code}】。")
    
    async def ready(self):
        await asyncio.sleep(3) # 等待最后一名玩家的WebSocket连接
        await self.send_public_message({
            "type":"can_ready"
        })
        logger.debug("等待玩家准备中...")
        tasks = [asyncio.create_task(self.wait_for_player(i, READY_TIMEOUT)) for i in range(MATCH_PLAYER_COUNT)]
        await asyncio.gather(*tasks)

    async def exit(self, user_id:str):
        player = player_manager.get_online_player(user_id)
        if player.in_table != self.table_code:
            raise PlayerExitException(401, f"玩家不在目标牌桌中，玩家所在牌桌【{player.in_table}】，目标牌桌【{self.table_code}】")
        if self.match and not self.match.result:
            raise PlayerExitException(401, "牌局未结束，无法正常退出")
        await player.exit_table()
        self.player.remove(player)
        if self.player:
            await self.send_public_message({
                "type":"exit",
                "data":self.player[-1].to_dict()
            })
        logger.info(f"玩家【{user_id}】退出房间【{self.table_code}】。")


    def _init_match(self, rand_seed:int=None):
        '''初始化牌桌'''
        random.shuffle(self.player)
        self.match=Match(self.player, rand_seed)
        self.player_in_match=self.match.player
        logger.info(f"牌桌【{self.table_code}】初始化完成，哈希值为【{self.match.hash}】。")
    
    async def run(self) -> dict:
        '''牌局进行'''
        # 初始化牌桌
        self._init_match()
        # 发送初始牌桌信息
        tasks = [asyncio.create_task(self.send_private_message({
                "type": "init_info",
                "data": {
                    "self":self.player_in_match[i].to_dict(), 
                    "table":[player.to_public_dict() for player in self.player_in_match]},
                    "rest_tile":len(self.match.deck)
            }, i)) for i in range(MATCH_PLAYER_COUNT)]
        await asyncio.gather(*tasks)
        logger.debug(f"牌桌【{self.table_code}】初始化完成，已向玩家发送初始信息。")
        # 牌局正常进行
        while not self.match.result:
            tasks = [asyncio.create_task(self.send_private_message({
                    "type": "update_info",
                    "data": {
                        "self":self.player_in_match[i].to_dict(), 
                        "table":[player.to_public_dict() for player in self.player_in_match]},
                        "rest_tile":len(self.match.deck)
                }, i)) for i in range(MATCH_PLAYER_COUNT)]
            await asyncio.gather(*tasks)
            # 摸牌
            try:
                draw_player_index, draw_tile = self.match.draw()
            except MatchEndedException:
                logger.debug(f"牌桌【{self.table_code}】在摸牌时检测到牌局结束。")
                break
            await self.send_private_message({
                "type":"draw_self",
                "data":{"tile":draw_tile}
            }, draw_player_index)
            await self.send_public_message({
                "type":"draw_other",
                "data":{"player_index":draw_player_index}
            }, draw_player_index)
            # 摸牌玩家检测，进行操作。操作所引发的其他操作均在对应函数中进行
            await self.check_player_action_option(draw_player_index, new=draw_tile, need_discard=True)
            try:
                await self.handle_player_request(draw_player_index, "discard")
            except MatchEndedException:
                logger.debug(f"牌桌【{self.table_code}】在玩家操作时检测到牌局结束。")
                break
            except:
                logger.error(f"牌桌【{self.table_code}】在处理玩家操作时出错，可能是操作不合法，已忽略。")
                continue
        return self.match.result

    async def check_player_action_option(self, player_index:int, target_player_index:int=None, new:str=None, need_discard=False, only_discard=False):
        logger.debug(f"牌桌【{self.table_code}】开始检查玩家序号【{player_index}】可选操作，参数为player_index={player_index}, target_player_index={target_player_index}, new={new}, need_discard={need_discard}, only_discard={only_discard}...")
        option = self.match.player[player_index].action_check(new=new, target_player_index=target_player_index, need_discard=need_discard, only_discard=only_discard)
        logger.debug(f"牌桌【{self.table_code}】检查到玩家序号【{player_index}】可选操作如下：{option}")
        if option:
            await self.send_private_message({
                "type":"action_choose",
                "data":{"action":option}
            }, player_index)
            await self.wait_for_player(player_index, THINKING_TIME_LIMIT)

    async def wait_for_player(self, player_index:int, timeout:int):
        '''等待用户发来请求'''
        logger.debug(f"牌桌【{self.table_code}】开始等待玩家序号【{player_index}】的响应。")
        try:
            countdown_task = asyncio.create_task(self._wait_countdown(player_index, timeout-1))
            self.player_request[player_index] = await asyncio.wait_for(self.player[player_index].ws.receive_json(), timeout)
            logger.debug(f"收到序号【{player_index}】玩家的请求如下\n{self.player_request[player_index]}")
        except asyncio.TimeoutError:
            logger.debug(f"牌桌【{self.table_code}】等待玩家序号【{player_index}】超时。")
        except Exception as e:
            logger.error(f"牌桌【{self.table_code}】有牌桌成员断线，为其采用默认行为托管...错误类型为{e}。")
        countdown_task.cancel()
        
    async def _wait_countdown(self, player_index:int, timeout:int):
        '''进行倒计时'''
        for time in range(timeout, -1, -1):
            if self.player_request[player_index]:
                return
            else:
                await self.send_private_message({
                    "type":"countdown",
                    "data":{"count":time}
                }, player_index)
                await asyncio.sleep(1)

    def compare_player_requests(self) -> Optional[int]:
        '''比较不同玩家请求优先级，返回应处理玩家下标，None则为无操作'''
        logger.debug(f"牌桌【{self.table_code}】开始比较不同玩家的请求优先级...")
        if not any(self.player_request):
            logger.debug(f"牌桌【{self.table_code}】玩家请求均为空，已取消比较。")
            return
        por = {"win":10, "discard":9, "kan":8, "pon":7, "chi":6, "cancel":0}
        index, max_por = None, 0
        for i, request in enumerate(self.player_request):
            if request:
                if por[request.get("type", "cancel")] > max_por:
                    index = i
                    max_por = por[request.get("type", "cancel")]
        for i in range(MATCH_PLAYER_COUNT):
            if i==index:
                continue
            self.player_request[i] = {}
        if index!= None:
            logger.debug(f"牌桌【{self.table_code}】比较得最高优先级的请求为序号【{index}】请求：{self.player_request[index]}")
        else:
            logger.debug(f"牌桌【{self.table_code}】比较可知没有应处理的请求，已返回 None.")
        return index

    async def handle_player_request(self, player_index:int, default_type:str="cancel"):
        '''对不同类型请求调用不同的处理函数'''
        method_name = f'_{self.player_request[player_index].get("type", default_type)}_handler'
        if hasattr(self, method_name):
            logger.debug(f"牌桌【{self.table_code}】请求处理，为玩家使用【{method_name}】操作。")
            try:
                await self.__getattribute__(method_name)(player_index=player_index)
            except MatchEndedException as e:
                raise e
            except Exception as e:
                logger.error(f"用户调用【{method_name}】操作时出错，错误类型为{e}。")
        else:
            logger.error(f"未找到指定的type方法，所指定method_name为【{method_name}】，已忽略操作。")
        self.player_request[player_index] = {}

    async def _cancel_handler(self, player_index:int):
        self.player_request[player_index] = {}
    
    async def _discard_handler(self, player_index:int):
        request = self.player_request[player_index]
        if not request or not request.get("type"):
            request = {
                "type": "discard",
                "player_index": player_index,
                "tile_type": "",
                "discard_draw": True
            }
        tile = self.match.discard(player_index, request.get("tile_type", ""), request.get("discard_draw", True))
        self.player_request[player_index] = {}
        await self.send_public_message({
            "type": "discard",
            "tile_type": tile,
            "player_index": player_index,
        })
        logger.debug(f"牌桌【{self.table_code}】中玩家序号【{player_index}】的【切牌】操作完成，进行后续操作。")
        tasks = [asyncio.create_task(self.check_player_action_option(index, player_index, tile, False)) for index in range(MATCH_PLAYER_COUNT) if index!=player_index]
        await asyncio.gather(*tasks)
        action_index = self.compare_player_requests()
        if action_index!=None:
            try:
                await self.handle_player_request(action_index, "cancel")
            except:
                logger.error(f"牌桌【{self.table_code}】在处理玩家操作时出错，可能是操作不合法，已忽略。")

    async def _chi_handler(self, player_index:int):
        request = self.player_request[player_index]
        if not request:
            return
        self.match.chi(player_index, request.get("target_player_index"), request.get("tile_type"), request.get("tiles"))
        self.player_request[player_index] = {}
        await self.send_public_message({
            "type": "chi",
            "tiles": sorted([request.get("tile_type")]+request.get("tiles")),
            "player_index": player_index,
            "target_player_index": request.get("target_player_index")
        })
        logger.debug(f"牌桌【{self.table_code}】中玩家序号【{player_index}】的【吃】操作完成，进行后续操作。")
        await self.check_player_action_option(player_index, only_discard=True)
        try:
            await self.handle_player_request(player_index, "discard")
        except:
            logger.error(f"牌桌【{self.table_code}】在处理玩家操作时出错，可能是操作不合法，已忽略。")


    async def _pon_handler(self, player_index:int):
        request = self.player_request[player_index]
        if not request:
            return
        self.match.pon(player_index, request.get("target_player_index"), request.get("tile_type"))
        self.player_request[player_index] = {}
        await self.send_public_message({
            "type": "pon",
            "tiles": [request.get("tile_type")]*3,
            "player_index": player_index,
            "target_player_index": request.get("target_player_index")
        })
        logger.debug(f"牌桌【{self.table_code}】中玩家序号【{player_index}】的【碰】操作完成，进行后续操作。")
        await self.check_player_action_option(player_index, only_discard=True)
        try:
            await self.handle_player_request(player_index, "discard")
        except:
            logger.error(f"牌桌【{self.table_code}】在处理玩家操作时出错，可能是操作不合法，已忽略。")

    async def _kan_handler(self, player_index:int):
        request = self.player_request[player_index]
        if not request:
            return
        self.match.kan(player_index, request.get("tile_type"), request.get("kan_type"), request.get("target_player_index"))
        self.player_request[player_index] = {}
        await self.send_public_message({
            "type": "kan",
            "kan_type": request.get("kan_type"),
            "tiles": [request.get("tile_type")]*4,
            "player_index": player_index,
            "target_player_index": request.get("target_player_index")
        })
        logger.debug(f"牌桌【{self.table_code}】中玩家序号【{player_index}】的【杠】操作完成，进行后续操作。")

    async def _win_handler(self, player_index:int):
        request = self.player_request[player_index]
        if not request:
            return
        self.match.win(player_index, request.get("tile_type"), request.get("target_player_index"))
        self.player_request[player_index] = {}
        logger.debug(f"牌桌【{self.table_code}】中玩家序号【{player_index}】的【和牌】操作完成，进行后续操作。")

    async def send_public_message(self, msg:dict, ignore_player_index:int=None):
        logger.debug(f"牌桌【{self.table_code}】广播信息中{'，忽略玩家序号【'+str(ignore_player_index)+'】' if ignore_player_index!=None else ''}。")
        tasks = []
        for i, player in enumerate(self.player):
            if ignore_player_index!=None and ignore_player_index==i:
                continue
            tasks.append(asyncio.create_task(self.send_private_message(msg, i)))
        await asyncio.gather(*tasks)

    async def send_private_message(self, msg:dict, player_index:int):
        try:
            ws = self.player[player_index].ws
        except Exception as e:
            logger.error(f"牌桌【{self.table_code}】获取玩家序号【{player_index}】的WebSocket连接时失败。错误类型为{e}。")
            return
        try:
            await ws.send_json(msg)
            logger.debug(f"牌桌【{self.table_code}】向玩家序号【{player_index}】发送消息：{msg}")
        except Exception as e:
            logger.error(f"牌桌【{self.table_code}】向玩家序号【{player_index}】发送消息时出错，已忽略。错误类型为{e}。")



@dataclass
class TableManager:
    tables:list[Table] = field(default_factory=list)

    def list_all_table(self) -> list[dict]:
        '''获取所以牌桌信息'''
        return [table.to_dict() for table in self.tables]
    
    def create_new_table(self) -> Table:
        '''创建新牌桌'''
        new_table = Table()
        self.tables.append(new_table)
        return new_table

    def get_table(self, table_code:str) -> Table:
        '''用牌桌code获取牌桌'''
        for table in self.tables:
            if table.table_code == table_code:
                return table
        raise HTTPException(401, "指定牌桌不存在")

    async def join_table(self, table_code:str, user_id:str) -> dict:
        '''用户加入牌桌'''
        table = self.get_table(table_code)
        await table.join(user_id)
        return table.to_dict()

    async def exit_table(self, table_code:str, user_id:str, from_dismiss:bool=False) -> dict:
        '''退出牌桌'''
        table = self.get_table(table_code)
        await table.exit(user_id)
        if not from_dismiss and len(table.player) <= 0:
            await table.dismiss("房间内已无玩家。")
    
    def _remove_table(self, table:Table):
        try:
            if table in self.tables:
                self.tables.remove(table)
                logger.info(f"牌桌管理器已删除牌桌【{table.table_code}】。")
            else:
                logger.debug(f"牌桌管理器删除牌桌时发现牌桌【{table.table_code}】不存在，已忽略删除操作。")
        except Exception as e:
            logger.info(f"牌桌管理器删除牌桌【{table.table_code}】时出错，错误原因是{e}。")
        


def init_table_manager():
    '''初始化牌桌管理器'''
    global table_manager
    table_manager = TableManager()
    logger.info("牌桌管理器初始化初始化完成")

init_table_manager()