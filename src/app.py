import json
import logging
import os
import tempfile
from collections import namedtuple
from datetime import datetime

import boto3
import requests
from pytube import YouTube

logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger('PyCastFunction')
logger.setLevel(os.environ.get('Logging', logging.DEBUG))

AudioInformation = namedtuple('AudioInformation', ['title', 'video_id', 'views', 'rating', 'description'])
UploadInformation = namedtuple('DownloadInformation', ['bucket_path', 'timestamp_utc'])


class TelegramNotifier:

    def __init__(self):
        self.api_token = boto3.client('ssm').get_parameter(Name='/pycast/telegram/api-token', WithDecryption=True)['Parameter']['Value']
        self.chat_id = boto3.client('ssm').get_parameter(Name='/pycast/telegram/chat-id')['Parameter']['Value']

    def _send(self, message):
        telegram_url = f'https://api.telegram.org/bot{self.api_token}/sendMessage?chat_id={self.chat_id}&parse_mode=Markdown&text={message}'
        print(telegram_url)
        response = requests.get(telegram_url)
        if response.status_code != 200:
            raise ValueError(
                f'Request to Telegram returned an error {response.status_code}, the response is:\n{response.text}'
            )

    def notify_entry(self, context=None):
        self._send(f"'{context.function_name}' - entry.")

    def notify_exit(self, context=None, status=None):
        self._send(f"'{context.function_name}' - exit.")


def notify_telegram(function):
    def wrapper(*args, **kwargs):
        if os.environ.get('TelegramNotification', 'False').lower() == 'true':
            telegram = TelegramNotifier()
            telegram.notify_entry(context=args[1])
            result = function(*args, **kwargs)
            telegram.notify_exit(context=args[1], status=result.get('Status', 'NOT SUBMITTED'))
        else:
            result = function(*args, **kwargs)
        return result

    return wrapper


def notify_cloudwatch(function):
    def wrapper(*args, **kwargs):
        incoming_event = args[0]
        function_name = args[1].function_name
        logger.info(f"'{function_name}' - entry.\nIncoming event: '{incoming_event}'")
        result = function(*args, **kwargs)
        logger.info(f"'{function_name}' - exit.\nResult: '{result}'")
        return result

    return wrapper


class Downloader:
    def __init__(self, bucket_name, table_name):
        self.bucket_name = bucket_name
        self.table_name = table_name
        self.s3_bucket = boto3.resource('s3').Bucket(bucket_name)
        self.ddb_table = boto3.resource('dynamodb').Table(table_name)

    def _download(self, youtube):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_name = f'{youtube.video_id}.mp4'
            bucket_path = f"audio/default/{file_name}"
            logger.info(f'Starting download into {tmp_dir}...')
            download_file_path = youtube.streams.filter(only_audio=True).filter(subtype='mp4').order_by('bitrate').desc().first().download(output_path=tmp_dir, filename=youtube.video_id)
            logger.info(f'Finished download ({download_file_path}, now uploading to S3 ({self.bucket_name}:{bucket_path})')
            self.s3_bucket.upload_file(download_file_path, bucket_path)
            logger.info('Finished upload.')

        return UploadInformation(bucket_path=bucket_path, timestamp_utc=int(datetime.utcnow().timestamp()))

    def handle_event(self, url):
        yt = YouTube(url)
        audio_information = AudioInformation(title=yt.title, video_id=yt.video_id, views=yt.views, rating=yt.rating, description=yt.description)
        download_information = self._download(yt)
        self._store_metadata(download_information, audio_information)
        return download_information

    def _store_metadata(self, download_information, audio_information):
        metadata = dict([
            ('CastId', 'default'),
            ('EpisodeId', audio_information.video_id),
            ('Title', audio_information.title),
            ('Views', audio_information.views),
            ('Rating', str(audio_information.rating)),
            ('Description', audio_information.description),
            ('BucketPath', download_information.bucket_path),
            ('TimestampUtc', download_information.timestamp_utc)
        ])
        self.ddb_table.put_item(Item=metadata)
        logger.info(f'Storing metadata: {metadata}')


@notify_telegram
@notify_cloudwatch
def observer_handler(event, context):
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": 'I\'m happy'
        }),
    }


def download_handler(event, context):
    bucket = os.environ['BUCKET_NAME']
    table = os.environ['TABLE_NAME']
    event_body = json.loads(event['body'])
    try:
        download_information = Downloader(bucket_name=bucket, table_name=table).handle_event(url=event_body['url'])
        status_code = 200
        message = f'Added video ({download_information})'
    except Exception as e:
        logging.error(e)
        status_code = 500
        message = f'Problem: {e}'

    return {
        "statusCode": status_code,
        "body": json.dumps({
            "message": message
        }),
    }
