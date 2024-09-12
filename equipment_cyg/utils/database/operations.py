import functools
import importlib
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from equipment_cyg.utils.database.database_config import SESSION_CLASS
from equipment_cyg.controller.enum_sece_data_type import EnumSecsDataType
from equipment_cyg.utils.database.models import CygEvent, CygEquipmentConstant, CygStatusVariable, CygRemoteCommand, \
    CygRemoteCommandParam, CygAlarm, CygVariableLinkReport, CygLog


def get_session_close(func: Callable) -> Callable:
    """装饰器函数, 传入增删改查函数, 生成session使用, 使用完关闭session."""
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        session = SESSION_CLASS()
        result = func(session, *args, **kwargs)
        session.close()
        return result
    return wrapped


@get_session_close
def get_all_event(session: Session) -> List[Optional[list]]:
    events = session.query(CygEvent).all()
    return [[event.event_id, event.event_name] for event in events]


@get_session_close
def get_all_equipment_constant(session: Session) -> List[Optional[list]]:
    ecs = session.query(CygEquipmentConstant).all()
    return [[ec.ec_id, ec.ec_name, ec.min_value, ec.max_value, eval(ec.value_type)(ec.default_value),
             getattr(EnumSecsDataType, ec.value_type.upper()).value, ec.ec_unit, ec.callback] for ec in ecs]


@get_session_close
def get_all_status_variable(session: Session) -> List[Optional[list]]:
    svs = session.query(CygStatusVariable).all()
    return [[sv.sv_id, sv.sv_name, sv.sv_unit,
             getattr(EnumSecsDataType, sv.sv_value_type.upper()).value, sv.callback] for sv in svs]


@get_session_close
def get_all_remote_command(session: Session) -> List[Optional[list]]:
    rc_params = session.query(CygRemoteCommand, CygRemoteCommandParam).join(CygRemoteCommandParam).all()
    temp_dict = {}
    for rc, param in rc_params:
        key = (rc.rc_code, rc.rc_name, rc.ce_id)
        if key in temp_dict:
            temp_dict[key].append(param.sv.sv_name)
            continue
        temp_dict[key] = [param.sv.sv_name]
    return [[*_, param_list] for _, param_list in temp_dict.items()]


@get_session_close
def get_all_alarm(session: Session) -> List[Optional[list]]:
    alarms = session.query(CygAlarm).all()
    return [[alarm.alarm_id, alarm.alarm_name, alarm.alarm_text,
             alarm.alarm_code, alarm.ce_on, alarm.ce_off] for alarm in alarms]


@get_session_close
def get_all_monitor_alarm(session: Session, model: str) -> dict:
    module = importlib.import_module(".database.models", package="utils")
    model = getattr(module, model)
    monitor_alarms = session.query(model).all()
    monitor_alarm_dict = {}
    for monitor_alarm in monitor_alarms:
        field_name = monitor_alarm.field_info.field_name
        data_type = eval(monitor_alarm.field_info.data_type)
        start_byte = monitor_alarm.field_info.start_byte
        monitor_value = monitor_alarm.monitor_value if isinstance(data_type, str) else int(monitor_alarm.monitor_value)
        alarm_id = monitor_alarm.alarm_id
        if field_name in monitor_alarm_dict:
            monitor_alarm_dict[field_name]["monitor_value"].update({data_type(monitor_value): alarm_id})
            continue
        monitor_alarm_dict[field_name] = {
            "monitor_value": {data_type(monitor_value): alarm_id},
            "data_type": data_type,
            "start_byte": start_byte,
            "end_byte": start_byte + monitor_alarm.field_info.size,
            "bool_index": monitor_alarm.field_info.bool_bit_index
        }
    return monitor_alarm_dict


@get_session_close
def get_monitor_event(session: Session, product_name: str, prefix: str) -> dict:
    module = importlib.import_module(f".{product_name}.models_{product_name}", package="product")
    model = getattr(module, f"{prefix}{''.join(map(lambda x: x.capitalize(),product_name.split('_')))}")
    results = session.query(model).all()
    results = {result.event.event_name: result.__dict__ for result in results}
    for field_name, value in results.items():
        value.pop("_sa_instance_state")
    return results


@get_session_close
def get_report_link_variable(session: Session, report_ids) -> dict:
    result = {}
    for report_id in report_ids:
        sv_ids = session.query(CygVariableLinkReport).filter_by(report_id=report_id).with_entities(
            CygVariableLinkReport.sv_id).all()
        sv_id_list = [_[0] for _ in sv_ids]

        # 从cyg_status_variable表里查询sv_id_list下的sv数据
        svs = session.query(CygStatusVariable).filter(CygStatusVariable.sv_id.in_(sv_id_list)).all()
        result[report_id] = {sv.sv_id: sv.sv_name for sv in svs}
    return result


@get_session_close
def insert_data(session: Session, level, data):
    new_log = CygLog(level=level, data=data)
    session.add(new_log)
    session.commit()
