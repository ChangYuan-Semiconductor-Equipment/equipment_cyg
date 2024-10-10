"""Airtable 封装."""
import base64
import io
import logging
import requests
from pyairtable import Api
from PIL import Image


# pylint: disable=W1203
class Airtable:
    """Airtable class."""
    def __init__(self, access_token):
        self._access_token = access_token
        self._api = Api(access_token)
        self._logger = logging.getLogger(f"{self.__module__}.{self.__class__.__name__}")

    @property
    def logger(self):
        """日志实例."""
        return self._logger

    @property
    def api(self):
        """api实例."""
        return self._api

    def create_one_record(self, base_id: str, table_name: str, field_value: dict, typecast=False) -> str:
        """上传一条记录, 上传成功返回record_id."""
        table = self.api.table(base_id, table_name)
        response = table.create(field_value, typecast)
        return response.get("id")

    def create_multiple_record(self, base_id: str, table_name: str, field_value: list, typecast=False):
        """上传多条记录."""
        table = self.api.table(base_id, table_name)
        return table.batch_create(field_value, typecast)

    def upload_photo_with_record_id(self, base_id: str, record_id: str, field_name, photo_path):
        """将图片上传到指定记录的列下."""
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "contentType": "image/jpeg",
            "filename": photo_path,
            "file": self.get_photo_base64(photo_path)
        }
        url = f"https://content.airtable.com/v0/{base_id}/{record_id}/{field_name}/uploadAttachment"
        response = requests.post(url=url, headers=headers, json=data, timeout=5)
        if response.status_code == 200:
            self.logger.info(f"*** 上传成功 *** -> 图片已上传到 {record_id}")
        else:
            self.logger.warning(f"*** 上传失败 *** -> 图片未上传到 {record_id}")

    @staticmethod
    def get_photo_base64(photo_path) -> str:
        """获取图片的base64数据."""
        with Image.open(photo_path) as image:
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format="JPEG")
            img_byte_arr = img_byte_arr.getvalue()
            base64_str = base64.b64encode(img_byte_arr).decode("UTF-8")
            return base64_str
