"""枚举 secs 数据类型."""
from enum import Enum

from secsgem.secs.variables import Array, List
from secsgem.secs.variables.f4 import F4
from secsgem.secs.variables.string import String
from secsgem.secs.variables.boolean import Boolean
from secsgem.secs.variables.u1 import U1
from secsgem.secs.variables.u4 import U4
from secsgem.secs.variables.i4 import I4
from secsgem.secs.variables.binary import Binary


class EnumSecsDataType(Enum):
    """Secs 数据类型枚举类."""
    F4 = F4
    ASCII = String
    BOOL = Boolean
    UINT_1 = U1
    UINT_4 = U4
    I4 = I4
    BINARY = Binary
    ARRAY = Array
    LIST = List
