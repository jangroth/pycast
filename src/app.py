import json
import logging
import os
import tempfile
import time
from collections import namedtuple
from datetime import datetime
from pathlib import Path

import boto3
import requests
from boto3.dynamodb.conditions import Key
from jinja2 import Environment, select_autoescape, FileSystemLoader
from pytube import YouTube

log_level = os.environ.get('Logging', logging.DEBUG)

logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger('PyCastApplication')
logger.setLevel(os.environ.get('LOGGING', logging.DEBUG))

VideoInformation = namedtuple('VideoInformation', ['video_id', 'title', 'views', 'rating', 'description'])
UploadInformation = namedtuple('DownloadInformation', ['bucket_path', 'timestamp_utc', 'file_size'])


class TelegramNotifier:
    TELEGRAM_URL = 'https://api.telegram.org/bot{api_token}/sendMessage?chat_id={chat_id}&parse_mode=HTML&text={message}'

    def __init__(self):
        ssm_client = boto3.client('ssm')
        self.api_token = ssm_client.get_parameter(Name='/pycast/telegram/api-token', WithDecryption=True)['Parameter']['Value']
        self.chat_id = ssm_client.get_parameter(Name='/pycast/telegram/chat-id')['Parameter']['Value']

    def send(self, message):
        response = requests.get(self.TELEGRAM_URL.format(api_token=self.api_token, chat_id=self.chat_id, message=message))
        if response.status_code != 200:
            raise ValueError(
                f'Request to Telegram returned an error {response.status_code}, the response is:\n{response.text}'
            )

    def notify_entry(self, context=None):
        self.send(f"<b>ENTRY</b> <i>{context.function_name}</i>")

    def notify_exit(self, context=None, status='NOT SUBMITTED'):
        self.send(f"<b>EXIT</b> - <i>{context.function_name}</i>\n\n<pre>Status: '{status}'</pre>")


def notify_telegram(function):
    def wrapper(*args, **kwargs):
        if os.environ.get('TELEGRAM_NOTIFICATION', 'False').lower() == 'true':
            telegram = TelegramNotifier()
            if log_level == 'DEBUG':
                telegram.notify_entry(context=args[1])
            result = function(*args, **kwargs)
            if log_level == 'DEBUG':
                telegram.notify_exit(context=args[1], status=result.get('Status', 'NOT SUBMITTED'))
        else:
            result = function(*args, **kwargs)
        return result

    return wrapper


def notify_cloudwatch(function):
    def wrapper(*args, **kwargs):
        incoming_event = args[0]  # ...event
        function_name = args[1].function_name  # ...context
        logger.info(f"'{function_name}' - entry.\nIncoming event: '{incoming_event}'")
        result = function(*args, **kwargs)
        logger.info(f"'{function_name}' - exit.\n\nResult: '{result}'")
        return result

    return wrapper


class Observer:

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get('LOGGING', logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.sfn_client = boto3.client('stepfunctions')

    def _extract_incoming_message(self, event):
        return json.loads(event['body'])

    def _start_state_machine(self, message):
        response = self.sfn_client.start_execution(
            stateMachineArn=os.environ.get('STATE_MACHINE', None),
            input=json.dumps(message)
        )
        logging.info(f"Starting state machine: '{response['executionArn']}'")

    def _get_return_message(self, status_code=200, message='Event received, state machine started.'):
        return {
            "statusCode": status_code,
            "body": json.dumps({
                "message": message
            }),
        }

    def handle_event(self, event):
        try:
            event_body = self._extract_incoming_message(event)
            self._start_state_machine(event_body)
            result = self._get_return_message(status_code=200,
                                              message='Event received, state machine started.')
            self.telegram.send('Event received, starting processing.')
        except Exception as e:
            logging.exception(e)
            result = self._get_return_message(status_code=500,
                                              message=f'Error processing incoming event {event}\n\n{e}')
        return result


class Downloader:

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get('LOGGING', logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.bucket_name = os.environ['BUCKET_NAME']
        self.table_name = os.environ['TABLE_NAME']
        self.s3_bucket = boto3.resource('s3').Bucket(self.bucket_name)
        self.ddb_table = boto3.resource('dynamodb').Table(self.table_name)

    def _download(self, youtube):
        file_size = 0
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_name = f'{youtube.video_id}.mp4'
            bucket_path = f"audio/default/{file_name}"
            logger.info(f'Starting download into {tmp_dir}...')
            download_file_path = youtube.streams.filter(only_audio=True).filter(subtype='mp4').order_by('abr').desc().first().download(output_path=tmp_dir, filename=youtube.video_id)
            file_size = Path(download_file_path).stat().st_size
            logger.info(f'Finished download ({download_file_path}, now uploading to S3 ({self.bucket_name}:{bucket_path})')
            self.s3_bucket.upload_file(download_file_path, bucket_path)
            logger.info('Finished upload.')

        return UploadInformation(bucket_path=bucket_path, timestamp_utc=int(datetime.utcnow().timestamp()), file_size=file_size)

    def _store_metadata(self, download_information, video_information):
        metadata = dict([
            ('CastId', 'default'),
            ('EpisodeId', video_information.video_id),
            ('Title', video_information.title),
            ('Views', video_information.views),
            ('Rating', str(video_information.rating)),
            ('Description', video_information.description),
            ('BucketPath', download_information.bucket_path),
            ('TimestampUtc', str(download_information.timestamp_utc))
        ])
        self.ddb_table.put_item(Item=metadata)
        logger.info(f'Storing metadata: {metadata}')

    def _build_response(self, status, data=None):
        result = {'Status': status}
        if data:
            result = {**data, **result}
        return result

    def _extract_url_from_event(self, event):
        return event['url']

    def _download_video(self, url):
        yt = YouTube(url)
        video_information = VideoInformation(video_id=yt.video_id, title=yt.title, views=yt.views, rating=yt.rating, description=yt.description)
        download_information = self._download(yt)
        return video_information, download_information

    def _populate_video_information(self, url):
        yt = YouTube(url)
        return VideoInformation(video_id=yt.video_id, title=yt.title, views=yt.views, rating=yt.rating, description=yt.description)

    def _is_new_video(self, video_information):
        return self.ddb_table.query(
            KeyConditionExpression=Key('EpisodeId').eq(video_information.video_id)
        )['Items']

    def handle_event(self, event):
        try:
            url = self._extract_url_from_event(event)
            video_information = self._populate_video_information(url)
            if self._is_new_video(video_information):
                start_time = time.time()
                download_information = self._download_video(url)
                self._store_metadata(download_information, video_information)
                total_time = int(time.time() - start_time)
                self.telegram.send(f'Download finished, database updated.\n\n<code>Title:{video_information.title}\nFile Size: {download_information.file_size >> 20}MB\nTransfer time: {total_time}s</code>')
                status = 'SUCCESS'
            else:
                self.telegram.send(f'Video {video_information.title} already in the cast. Skipping download.')
                status = 'DUPLICATE'
            data = dict([('url', url), ('video_information', video_information), ('download_information', download_information)])
        except Exception as e:
            logger.exception(e)
            status = 'FAILED'
        return self._build_response(status, data)


class UpdatePodcastFeed:
    BUCKET_URL = "https://{bucket_name}.s3.amazonaws.com"

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get('LOGGING', logging.DEBUG))
        self.bucket_name = os.environ['BUCKET_NAME']
        self.bucket_url = self.BUCKET_URL.format(bucket_name=self.bucket_name)
        self.table_name = os.environ['TABLE_NAME']
        self.s3_bucket = boto3.resource('s3').Bucket(self.bucket_name)
        self.ddb_table = boto3.resource('dynamodb').Table(self.table_name)
        self.jinja_env = Environment(
            loader=FileSystemLoader(searchpath="./templates"),
            autoescape=select_autoescape(['html', 'xml'])
        )

    def _render_template(self, metadata):
        template = self.jinja_env.get_template('podcast.xml.j2')
        output = template.render(dict(podcast=dict(
            bucket=f'{self.bucket_url}',
            url=f'{self.bucket_url}/rss',
            episodes=metadata)))
        with tempfile.NamedTemporaryFile(mode='w') as tmp_file:
            tmp_file.write(output)
            tmp_file.flush()
            self.s3_bucket.upload_file(
                tmp_file.name,
                'rss',
                ExtraArgs={'ACL': 'public-read', 'ContentType': 'application/xml'})

    def _retrieve_metadata(self):
        items = self.ddb_table.scan()['Items']
        return items

    def _build_response(self, status, data=None):
        result = {'Status': status}
        if data:
            result = {**data, **result}
        return result

    def handle_event(self, event):
        try:
            metadata = self._retrieve_metadata()
            self._render_template(metadata)
            TelegramNotifier().send(f'Podcast updated.\n\n<code>URL:<a href="{self.bucket_url}/rss">{self.bucket_url}/rss</a></code>')
            status = 'SUCCESS'
        except Exception as e:
            logger.exception(e)
            status = 'FAILED'
        return self._build_response(status)


@notify_telegram
@notify_cloudwatch
def observer_handler(event, context):
    return Observer().handle_event(event)


@notify_telegram
@notify_cloudwatch
def download_cast_handler(event, context):
    return Downloader().handle_event(event)


@notify_telegram
@notify_cloudwatch
def update_podcast__data_handler(event, context):
    return UpdatePodcastFeed().handle_event(event)


if __name__ == '__main__':
    stack_outputs = cfn_client = boto3.client('cloudformation').describe_stacks(StackName='pycast')['Stacks'][0]['Outputs']
    bucket_name = [output['OutputValue'] for output in stack_outputs if output['OutputKey'] == 'PyCastBucketName'][0]
    table_name = [output['OutputValue'] for output in stack_outputs if output['OutputKey'] == 'PyCastTable'][0]
    print(f'Bucket:{bucket_name} Table:{table_name}')
    os.environ['TABLE_NAME'] = table_name
    os.environ['BUCKET_NAME'] = bucket_name
    Downloader()._is_new_video(VideoInformation(video_id='RjEdmrxjIHQ', title='title', views='views', rating='rating', description='description'))
