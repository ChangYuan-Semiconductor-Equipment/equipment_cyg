from sqlalchemy import Integer, Column, String, DateTime, func, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship

from equipment_cyg.utils.database.database_config import ENGINE, get_declarative_base

DECLARATIVE_BASE = get_declarative_base()


class CygStatusVariable(DECLARATIVE_BASE):
    __tablename__ = "cyg_status_variable"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sv_id = Column(Integer, nullable=False, unique=True)
    sv_name = Column(String(255), nullable=False, unique=True)
    sv_unit = Column(String(255), nullable=True)
    sv_value_type = Column(String(255), nullable=False)
    callback = Column(Boolean, nullable=False, default=0)
    description = Column(String(255), nullable=True)
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class CygReport(DECLARATIVE_BASE):
    __tablename__ = "cyg_report"
    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, nullable=False, unique=True)
    description = Column(String(255), nullable=True)
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class CygVariableLinkReport(DECLARATIVE_BASE):
    __tablename__ = "cyg_variable_link_report"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sv_id = Column(Integer, ForeignKey("cyg_status_variable.sv_id"), nullable=False)
    sv_info = relationship("CygStatusVariable")
    report_id = Column(Integer, ForeignKey("cyg_report.report_id"), nullable=False)
    report = relationship("CygReport")
    link_status = Column(Boolean, default=0)
    description = Column(String(255), nullable=True)
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class CygReportLinkEvent(DECLARATIVE_BASE):
    __tablename__ = "cyg_report_link_event"
    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("cyg_report.report_id"), nullable=False)
    report = relationship("CygReport")
    event_id = Column(Integer, ForeignKey("cyg_event.event_id"), nullable=False)
    event = relationship("CygEvent")
    link_status = Column(Boolean, default=0)
    description = Column(String(255), nullable=True)
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class CygEvent(DECLARATIVE_BASE):
    __tablename__ = "cyg_event"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, nullable=False, unique=True)
    event_name = Column(String(255), nullable=False, unique=True)
    description = Column(String(255), nullable=True)
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class CygLog(DECLARATIVE_BASE):
    __tablename__ = "cyg_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(Integer, nullable=True)
    data = Column(Text, nullable=True)
    create_time = Column(DateTime, default=func.now())


class CygEquipmentConstant(DECLARATIVE_BASE):
    __tablename__ = "cyg_equipment_constant"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ec_id = Column(Integer, nullable=False, unique=True)
    ec_name = Column(String(255), nullable=True, unique=True)
    min_value = Column(Integer, nullable=True)
    max_value = Column(Integer, nullable=True)
    default_value = Column(String(255), nullable=True)
    value_type = Column(String(255), nullable=False)
    ec_unit = Column(String(255), nullable=True)
    callback = Column(Boolean, nullable=False, default=0)
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class CygRemoteCommand(DECLARATIVE_BASE):
    __tablename__ = "cyg_remote_command"
    id = Column(Integer, primary_key=True, autoincrement=True)
    rc_code = Column(String(255), nullable=False, unique=True)
    rc_name = Column(String(255), nullable=False, unique=True)
    ce_id = Column(Integer, ForeignKey("cyg_event.event_id"), nullable=True)
    event = relationship("CygEvent")
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class CygRemoteCommandParam(DECLARATIVE_BASE):
    __tablename__ = "cyg_remote_command_param"
    id = Column(Integer, primary_key=True, autoincrement=True)
    rc_code = Column(String(255), ForeignKey("cyg_remote_command.rc_code"), nullable=False)
    rc = relationship("CygRemoteCommand")
    sv_id = Column(Integer, ForeignKey("cyg_status_variable.sv_id"), nullable=False)
    sv = relationship("CygStatusVariable")
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class CygAlarm(DECLARATIVE_BASE):
    __tablename__ = "cyg_alarm"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alarm_id = Column(Integer, nullable=False, unique=True)
    alarm_name = Column(String(255), nullable=True)
    alarm_text = Column(String(255), nullable=False)
    alarm_code = Column(Integer, nullable=True)
    ce_on = Column(Integer, ForeignKey("cyg_event.event_id"), nullable=True)
    on_event = relationship("CygEvent", foreign_keys=[ce_on])
    ce_off = Column(Integer, ForeignKey("cyg_event.event_id"), nullable=True)
    off_event = relationship("CygEvent", foreign_keys=[ce_off])
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


if __name__ == '__main__':
    # 创建数据表
    DECLARATIVE_BASE.metadata.create_all(ENGINE)
