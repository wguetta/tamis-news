from botocore.exceptions import ClientError


class FakeBody:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def iter_lines(self):
        for line in self.data.splitlines():
            yield line


class FakePaginator:
    def __init__(self, s3: "FakeS3"):
        self.s3 = s3

    def paginate(self, *, Bucket, Prefix=""):
        contents = [
            {"Key": key}
            for (bucket, key) in self.s3.objects
            if bucket == Bucket and key.startswith(Prefix)
        ]
        yield {"Contents": contents}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, ContentType=None):
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        self.objects[(Bucket, Key)] = {"Body": Body, "ContentType": ContentType}

    def get_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": FakeBody(self.objects[(Bucket, Key)]["Body"])}

    def get_paginator(self, name):
        if name != "list_objects_v2":
            raise ValueError(name)
        return FakePaginator(self)
