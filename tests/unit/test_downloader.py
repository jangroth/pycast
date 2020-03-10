import json
from unittest.mock import MagicMock

import pytest

from src.app import Downloader, VideoInformation, UploadInformation

GOOD_EVENT = '''
{
    "url":"https://www.youtube.com/watch?v=1234567"
}
'''

VIDEO_INFORMATION = VideoInformation(video_id='video_id', title='title', views='views', rating='rating', description='description', source_url='source_url')
UPLOAD_INFORMATION = UploadInformation(bucket_path='bucket_path', timestamp_utc='timestamp_utc', file_size=1024)


@pytest.fixture
def good_event():
    event = json.loads(GOOD_EVENT)
    event['body'] = '{\"url\":\"https://www.ccc.de\"}'
    return event


@pytest.fixture()
def dld():
    the_object = Downloader.__new__(Downloader)
    the_object.logger = MagicMock()
    the_object.telegram = MagicMock()
    return the_object


def test_should_download_video_and_upload_ddb_if_video_is_new(dld, good_event):
    dld._populate_video_information = MagicMock(return_value=VIDEO_INFORMATION)
    dld._is_new_video = MagicMock(return_value=True)
    dld._download_to_tmp = MagicMock(return_value='/tmp/abc')
    dld._upload_to_s3 = MagicMock(return_value=UPLOAD_INFORMATION)
    dld._store_metadata = MagicMock()

    result = dld.handle_event(good_event)

    assert result['status'] == 'SUCCESS'
    dld._download_to_tmp.assert_called_once_with(VIDEO_INFORMATION)
    dld._upload_to_s3.assert_called_once_with('/tmp/abc', VIDEO_INFORMATION)
    dld._store_metadata.assert_called_once_with(UPLOAD_INFORMATION, VIDEO_INFORMATION)


def test_should_return_no_action_if_video_already_exists(dld, good_event):
    dld._populate_video_information = MagicMock(return_value=VIDEO_INFORMATION)
    dld._is_new_video = MagicMock(return_value=False)

    result = dld.handle_event(good_event)

    assert result['status'] == 'NO_ACTION'


def test_should_return_failure_if_bad_event(dld):
    result = dld.handle_event({'foo': 'bar'})
    assert result['status'] == 'FAILURE'
