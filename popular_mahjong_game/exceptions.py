from fastapi import HTTPException

class DeclaringException(Exception):
    '''鸣牌错误'''

class ChiException(DeclaringException):
    '''吃牌错误'''

class PonException(DeclaringException):
    '''碰牌错误'''

class KanException(DeclaringException):
    '''杠牌错误'''

class WinException(DeclaringException):
    '''和牌错误'''

class MatchEndedException(Exception):
    '''牌局结束错误'''

class DiscardException(Exception):
    '''切牌错误'''


class UserInvalidException(HTTPException):
    '''用户验证错误'''

class PlayerJoinException(HTTPException):
    '''用户加入牌桌错误'''

class PlayerExitException(HTTPException):
    '''用户退出牌桌错误'''