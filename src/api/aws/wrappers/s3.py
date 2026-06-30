import boto3
import os
from commons.globals import CURRENT_REGION, BUCKET_NAME
from aws.wrappers.awsbase import AWSBase
    
class S3Wrapper(AWSBase):
    def __init__(self):
        super().__init__('s3')
        self.s3_resource = boto3.resource('s3', region_name=CURRENT_REGION)
        self.bucket = self.s3_resource.Bucket(BUCKET_NAME)

    def generate_presigned_url(self, key, expiration=3600):
        return self.s3_resource.meta.client.generate_presigned_url('get_object', Params={'Bucket': self.bucket.name, 'Key': key}, ExpiresIn=expiration)

    async def upload_file(self, file_path, key):
        self.bucket.upload_file(file_path, key)
        
    
    async def download_file(self, key, file_path):
        self.bucket.download_file(key, file_path)

    def empty_bucket(self):
        try:
            self.bucket.objects.all().delete()
            versions = list(self.bucket.object_versions.all())
            if versions:
                self.bucket.object_versions.all().delete()
            return True
        except Exception:
            return False