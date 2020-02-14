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
from jinja2 import Environment, select_autoescape, FileSystemLoader
from pytube import YouTube

logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger('PyCast')
logger.setLevel(os.environ.get('Logging', logging.DEBUG))

AudioInformation = namedtuple('AudioInformation', ['title', 'video_id', 'views', 'rating', 'description'])
UploadInformation = namedtuple('DownloadInformation', ['bucket_path', 'timestamp_utc', 'file_size'])


class TelegramNotifier:

    def __init__(self):
        self.api_token = boto3.client('ssm').get_parameter(Name='/pycast/telegram/api-token', WithDecryption=True)['Parameter']['Value']
        self.chat_id = boto3.client('ssm').get_parameter(Name='/pycast/telegram/chat-id')['Parameter']['Value']

    def send(self, message):
        telegram_url = f'https://api.telegram.org/bot{self.api_token}/sendMessage?chat_id={self.chat_id}&parse_mode=HTML&text={message}'
        response = requests.get(telegram_url)
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
        logger.info(f"'{function_name}' - exit.\n\nResult: '{result}'")
        return result

    return wrapper


class Observer:

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get('Logging', logging.DEBUG))
        self.sfn_client = boto3.client('stepfunctions')

    def _start_state_machine(self, message):
        response = self.sfn_client.start_execution(
            stateMachineArn=os.environ.get('STATE_MACHINE', None),
            input=json.dumps(message)
        )
        logging.info(f"Starting state machine: '{response['executionArn']}'")

    def handle_event(self, event):
        try:
            event_body = json.loads(event['body'])
            url = event_body['url']
            self._start_state_machine(event_body)
            status_code = 200
            message = f"Received '{url}'..."
        except KeyError as e:
            status_code = 400
            message = "Expecting 'url' in request body...\n{e}"
        except Exception as e:
            logging.exception(e)
            status_code = 500
            message = f"Error '{e}'"
        return {
            "statusCode": status_code,
            "body": json.dumps({
                "message": message
            }),
        }


class Downloader:

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get('Logging', logging.DEBUG))
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

    def _store_metadata(self, download_information, audio_information):
        metadata = dict([
            ('CastId', 'default'),
            ('EpisodeId', audio_information.video_id),
            ('Title', audio_information.title),
            ('Views', audio_information.views),
            ('Rating', str(audio_information.rating)),
            ('Description', audio_information.description),
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

    def handle_event(self, event):
        try:
            url = event['url']
            yt = YouTube(url)
            start_time = time.time()
            audio_information = AudioInformation(title=yt.title, video_id=yt.video_id, views=yt.views, rating=yt.rating, description=yt.description)
            download_information = self._download(yt)
            self._store_metadata(download_information, audio_information)
            total_time = int(time.time() - start_time)
            TelegramNotifier().send(f'Download finished, database updated.\n\n<code>Title:{yt.title}\nFile Size: {download_information.file_size >> 20}MB\nTransfer time: {total_time}s</code>')
            status = 'SUCCESS'
            data = dict([('url', url), ('audio_information', audio_information), ('download_information', download_information)])
        except Exception as e:
            logger.exception(e)
            status = 'FAILED'
        return self._build_response(status, data)


class UpdatePodcastFeed:
    BUCKET_URL = "https://{bucket_name}.s3.amazonaws.com"

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get('Logging', logging.DEBUG))
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
    UpdatePodcastFeed().handle_event({})
