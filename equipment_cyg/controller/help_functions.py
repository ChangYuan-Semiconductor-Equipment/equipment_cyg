import collections
import json
import os
import pathlib

import pandas as pd

log_format = "%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s"


def create_log_dir():
    """判断log目录是否存在, 不存在就创建."""
    log_dir = pathlib.Path(f"{os.getcwd()}/log")
    if not log_dir.exists():
        os.mkdir(log_dir)


def get_status_variables(manual_path: str) -> dict:
    """获取手册里定义的变量.

    Args:
        manual_path: 手册路径.

    Returns:
        dict: 手册里定义的变量信息.
    """
    data_frame = pd.read_excel(manual_path, sheet_name="sv_ids")  # 使用工作表名称
    data_dict = data_frame.set_index("name").T.to_dict(orient="dict")
    for _, sv_info in data_dict.items():
        sv_info.pop("values")
        if isinstance(sv_info["unit"], float):
            sv_info["unit"] = ""
    return data_dict


def get_collection_events(manual_path: str) -> dict:
    """获取手册里定义的事件.

    Args:
        manual_path: 手册路径.

    Returns:
        dict: 手册里定义的事件信息.
    """
    collection_events = collections.defaultdict(dict)
    data_frame = pd.read_excel(manual_path, sheet_name="collection_events", engine="openpyxl")
    data_frame.ffill(inplace=True)
    data_list = data_frame.to_dict(orient="records")
    for data in data_list:
        data.pop("sv_value_type")  # 删除不需要的元素
        data.pop("sv_description")  # 删除不需要的元素
        data.pop("sv_name")  # 删除不需要的元素

        ce_name = data.pop("ce_name")
        ce_id = int(data.pop("ce_id"))
        report_id = int(data.pop("report_id"))
        sv_id = data.pop("sv_id")
        if ce_name in collection_events:
            if report_id in collection_events[ce_name]["link_reports"]:
                collection_events[ce_name]["link_reports"][report_id].append(sv_id)
            else:
                collection_events[ce_name]["link_reports"].update({report_id: [sv_id]})
        else:
            link_reports = {report_id: [sv_id]}
            collection_events[ce_name] = {"ceid": ce_id, "link_reports": link_reports, **data}
    return collection_events


def get_remote_commands(manual_path: str) -> dict:
    """获取手册里定义的远程命令.

    Args:
        manual_path: 手册路径.

    Returns:
        dict: 手册里定义的远程命令信息.
    """
    data_frame = pd.read_excel(manual_path, sheet_name="remote_commands")  # 使用工作表名称
    data_dict = data_frame.set_index("remote_command").T.to_dict(orient="dict")
    for remote_command, remote_command_info, in data_dict.items():
        params = data_dict[remote_command]["params"]
        data_dict[remote_command]["rcmd"] = remote_command
        data_dict[remote_command]["params"] = [] if isinstance(params, float) else params.split(",")
    return data_dict


def generate_secs_conf(manual_path: str):
    """根据手册创建保存变量、事件、远程命令的配置文件.

    Args:
        manual_path: 手册路径.
    """
    secs_info = {}
    secs_info.update({"status_variable": get_status_variables(manual_path)})
    secs_info.update({"collection_events": get_collection_events(manual_path)})
    secs_info.update({"remote_commands": get_remote_commands(manual_path)})
    with pathlib.Path("secs_gem.conf").open(mode="w", encoding="utf-8") as f:
        json.dump(secs_info, f, indent=4, ensure_ascii=False)


if __name__ == '__main__':
    path = r"D:\python_workspace\equipment_cyg\equipment_cyg\product\zhong_che_yi_xing\zhong_che_yi_xing_manual.xlsx"
    generate_secs_conf(path)
