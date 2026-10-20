"""出力先。ローカルフォルダとCloudflare R2(S3互換API)の2種類。"""
import json
import os
from pathlib import Path


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)

    def put(self, key, data, content_type, cache_control=None):
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_json(self, key):
        p = self.root / key
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def delete_prefix(self, prefix):
        import shutil
        p = self.root / prefix
        if p.exists():
            shutil.rmtree(p)


class R2Store:
    """環境変数 R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET を使う。"""

    def __init__(self):
        import boto3
        self.bucket = os.environ["R2_BUCKET"]
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )

    def put(self, key, data, content_type, cache_control=None):
        kw = {"Bucket": self.bucket, "Key": key, "Body": data, "ContentType": content_type}
        if cache_control:
            kw["CacheControl"] = cache_control
        self.s3.put_object(**kw)

    def get_json(self, key):
        try:
            o = self.s3.get_object(Bucket=self.bucket, Key=key)
        except self.s3.exceptions.NoSuchKey:
            return None
        return json.loads(o["Body"].read())

    def delete_prefix(self, prefix):
        pag = self.s3.get_paginator("list_objects_v2")
        for page in pag.paginate(Bucket=self.bucket, Prefix=prefix):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": objs})
